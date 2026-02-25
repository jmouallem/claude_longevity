# Goal Completion Bug: ALL Goals Not Closing from Chat

## Problem

When a user logs health data in chat (sleep, food, exercise, supplements, etc.), the system:
1. Correctly logs the data via the appropriate write tool
2. **Never marks the associated daily plan task as complete**
3. Forces the user to repeatedly ask "how do I close this goal?"

This affects **every goal type** — sleep, exercise, nutrition, hydration, supplement adherence, etc. The AI responds with coaching fluff ("Celebrate Success", "Optional Reflection") instead of actually completing the task, because **it has no tool to do so**.

---

## Root Cause

There are **two independent gaps** that both need fixing:

### Gap 1: No AI tool to mark plan tasks complete

The system prompt (`backend/context/system_prompt.md:114`) instructs the AI:

> **Mark the plan task.** Use the plan task tool to mark the task completed, partially progressed, or skipped based on what they report.

But **no such tool exists** in the tool registry. The service function `set_task_status()` exists in `coaching_plan_service.py:1402` and is exposed via HTTP API (`api/plan.py:187`), but there is no tool wrapper for the AI to call it.

**Existing tools for reference:**
- `checklist_mark_taken` (write_tools.py:1438) - marks meds/supplements done. **Works.**
- `sleep_log_write` (write_tools.py:1497) - logs sleep data. **Works, but doesn't touch tasks.**
- No `plan_task_status` or equivalent. **Missing.**

### Gap 2: No log-write tool triggers task refresh

**None** of the log-write tools call `refresh_task_statuses()` (defined at `coaching_plan_service.py:839`). This function calculates metric progress and auto-completes tasks that hit 100%, but it is never invoked from any tool or from the orchestrator.

Affected tools (all have the same gap):
- `sleep_log_write` (write_tools.py:1497)
- `food_log_write`
- `exercise_log_write`
- `supplement_log_write`
- `checklist_mark_taken` (marks checklist items, but doesn't refresh plan tasks)

The orchestrator (`orchestrator.py`) and the entire `backend/tools/` directory have **zero references** to `refresh_task_statuses`.

---

## Recommended Fixes

### Fix 1: Add a `plan_task_update_status` tool (Primary fix)

Create a new tool in `write_tools.py` that wraps `set_task_status()`:

```python
def _tool_plan_task_update_status(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    from backend.services.coaching_plan_service import set_task_status
    task_id = int(args["task_id"])
    status = str(args["status"]).strip().lower()
    if status not in {"completed", "skipped", "pending"}:
        raise ToolExecutionError("`status` must be completed, skipped, or pending")
    row = set_task_status(ctx.db, ctx.user, task_id=task_id, status=status)
    return {"task_id": row.id, "status": row.status}
```

Register it:
```python
registry.register(
    ToolSpec(
        name="plan_task_update_status",
        description="Mark a plan task as completed, skipped, or pending.",
        required_fields=("task_id", "status"),
        read_only=False,
        tags=("plan", "write"),
    ),
    _tool_plan_task_update_status,
)
```

This gives the AI a direct mechanism matching what the system prompt already instructs.

### Fix 2: Call `refresh_task_statuses` after health data writes (Complementary fix)

After **every** log-write tool persists data, trigger a task refresh so metric-based goals auto-complete without waiting for the next plan cycle.

Add a shared helper and call it from each write tool:
```python
def _refresh_tasks_after_write(ctx: ToolContext, now: datetime) -> None:
    from backend.services.coaching_plan_service import refresh_task_statuses
    user_tz = _get_user_tz(ctx)
    local_day = now.astimezone(user_tz).date()
    refresh_task_statuses(ctx.db, ctx.user, reference_day=local_day, create_notifications=False)
```

Call `_refresh_tasks_after_write(ctx, now)` at the end of:
- `_tool_sleep_log_write`
- `_tool_food_log_write`
- `_tool_exercise_log_write`
- `_tool_supplement_log_write`
- `_tool_checklist_mark_taken`

This makes metric-based goals (e.g., "get 7+ hours sleep", "eat 2000 cal", "exercise 30 min") auto-complete the moment the data is logged, even if the AI doesn't explicitly mark the task.

### Fix 3: Update system prompt to reference the new tool name

At `system_prompt.md:114`, update the instruction to reference the actual tool:

```markdown
5. **Mark the plan task.** Use `plan_task_update_status` with the task_id and status (completed/skipped/pending).
```

---

## Why Both Fix 1 and Fix 2 Matter

| Scenario | Fix 1 alone | Fix 2 alone | Both |
|----------|-------------|-------------|------|
| User does goal check-in, AI marks complete | Works | No | Works |
| User logs sleep casually (no check-in) | Depends on AI deciding to mark | Works (auto-complete via metrics) | Works |
| User says "mark my sleep goal done" | Works | No | Works |
| Sleep logged but AI hallucinates wrong task_id | Fails | Works (metrics are accurate) | Works (fallback) |

Fix 2 is the safety net. Fix 1 is the direct mechanism the prompt already expects.

---

## Files to Change

| File | Change |
|------|--------|
| `backend/tools/write_tools.py` | Add `_tool_plan_task_update_status` function and register it |
| `backend/tools/write_tools.py` | Add `_refresh_tasks_after_write` helper; call from all log-write tools |
| `backend/context/system_prompt.md:114` | Reference actual tool name `plan_task_update_status` |
| `backend/ai/orchestrator.py` | Ensure goal check-in context includes the pending task_id so the AI can pass it to the tool |

---

## How the Fixed Flow Should Work

```
User: "I went to bed at 10:30pm and woke up at 6:00am"
  -> AI calls sleep_log_write (sleep logged)
  -> sleep_log_write triggers refresh_task_statuses (task auto-completes if metric hits target)
  -> AI sees task completed, confirms to user

User clicks "Update with Coach" on sleep goal:
  -> "Goal check-in for Tue, Feb 24: Protect sleep window"
  -> AI asks what they did (step 2 of workflow)
  -> User provides data
  -> AI logs via sleep_log_write
  -> AI calls plan_task_update_status(task_id=X, status="completed")
  -> Task is marked done, user sees it reflected immediately
```

---

## Code Review Findings (Post-Fix)

### Issue 1: Missing `db.flush()` before `_refresh_tasks_after_write` in fasting_manage (FIXED)

**Location:** `write_tools.py` — `_tool_fasting_manage`, active-fast-ended path (~line 930-939)

The "end active fast" branch modifies the ORM object in-place (`active.fast_end = ...`, `active.duration_minutes = ...`) but did not call `ctx.db.flush()` before `_refresh_tasks_after_write(ctx)`. The refresh function queries the DB for fasting data to compute metric progress, and without a flush the dirty ORM state may not be visible, causing the fasting goal to stay incomplete.

**Fix applied:** Added `ctx.db.flush()` before `_refresh_tasks_after_write(ctx)` on that path.

The other fasting paths (start and direct interval) were already correct — start doesn't refresh, and the direct interval path already had `ctx.db.flush()`.

### Issue 2: `[task_id=N]` tag visible in chat input (FIXED)

**Location:** `ChatMessage.tsx`, `GoalChatPanel.tsx`, `ChatInput.tsx`

The `[task_id=123]` metadata tag is embedded in the message text sent to the backend (where the AI needs it), but is now stripped from all user-facing display:
- **ChatMessage.tsx** — `stripMetaTags()` removes the tag before rendering user bubbles
- **GoalChatPanel.tsx** — same `stripMetaTags()` in `MessageBubble` component
- **ChatInput.tsx** — `fillText` is split: tag stored in `hiddenMetaRef`, stripped text shown in textarea, tag reattached on send

The AI still receives the full message with `[task_id=N]`; the user never sees it.

### Issue 3: Dashboard does NOT auto-refresh after returning from Chat (FIXED)

**Location:** `Dashboard.tsx`

Added a `visibilitychange` listener that calls `fetchData()` when the page becomes visible again (tab switch). SPA navigation already triggers remount since Dashboard uses a standard `<Route>`, which causes the mount-based `useEffect` to re-run.

### Issue 4: Fasting goal closure — all paths covered

**Verification:** The linter-modified code already added `_refresh_tasks_after_write` to both fasting completion paths:
- Active fast ended (line ~938) — now with flush fix
- Direct interval created (line ~956) — already had flush

The "start" path correctly does NOT refresh (fast is still in progress, no metric to update).
The "no_active_fast" fallback return also correctly does NOT refresh (nothing was written).

**Fasting goals will now auto-close** when the logged duration hits the target metric.

---

## Outstanding Issues (Resolved)

### Issue 5: Combined hydration + supplement messages lose the hydration data (FIXED)

**Was:** "drank 24 oz with 10 mg creatine and fat burner" → only `log_supplement`, hydration lost.

**Fix:** Added `_heuristic_log_categories()` in `specialist_router.py` — a multi-intent scanner that runs independent checks for ALL log categories instead of stopping at the first match. The orchestrator now merges these secondary categories into `log_categories` after the existing force-signal block.

**Result:** "drank 24 oz with creatine and fat burner" → `[log_hydration, log_supplement]` — both get parsed and saved.

### Issue 6: Hydration heuristic cues are too narrow (FIXED)

**Was:** Hydration cues required "water" explicitly. "drank 24 oz" missed because no "water".

**Fix:** Added regex-based detection for quantity + fluid unit + drinking verb (e.g., `\b\d+\s*(oz|ml|cups?|...)\b` + "drank"/"drink") in both `_heuristic_category()` and `_heuristic_log_categories()`. Also added named supplement detection (`_SUPPLEMENT_NAMES` tuple) and broadened food cues to align with `_looks_like_food_logging_message()`.

**Files changed:**
- `backend/ai/specialist_router.py` — added `_heuristic_log_categories()`, `_SUPPLEMENT_NAMES`, broadened hydration/supplement cues
- `backend/ai/orchestrator.py` — added multi-intent merge loop after force-signal block
