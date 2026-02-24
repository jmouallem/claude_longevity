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
