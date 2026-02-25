# Architectural Changes Needed for Conversational Flows

## Current Architecture Summary

The orchestrator follows a **rigid, deterministic pipeline**:

```
User message
  → 1. Classify intent (single category)
  → 2. Pattern-match force signals (food/sleep/fasting only)
  → 3. Parse log data (one-shot, no clarification)
  → 4. Save via tool_registry.execute() (orchestrator calls tools, not AI)
  → 5. Build context with pass/fail status
  → 6. AI generates text response (no tool access)
```

The AI model is a **text generator** — it never receives tool specifications, never decides which tools to call, and cannot ask for clarification before committing data. All tool invocation decisions are made by the orchestrator through pattern matching and classification.

---

## Problem 1: Single-Category Intent Classification — IMPLEMENTED

**Current:** One message → one `log_*` category. The classifier (`specialist_router.py:96-190`) returns the first matching category from a priority-ordered if/elif chain.

**Breaks when:** Messages contain multiple intents.
- "drank 24 oz with 10 mg creatine and fat burner" → `log_supplement` only, hydration lost
- "took my morning meds and had a coffee with cream" → `log_supplement` only, food lost
- "30 min run, HR stayed around 140" → `log_exercise` only, vitals lost
- "broke my fast at 2pm, glucose was 95" → `log_fasting` only, vitals lost

**Partial band-aid:** Force signals exist for food, sleep, and fasting (`orchestrator.py:3393-3427`), but not for hydration, supplements, exercise, or vitals. Every new combination requires a new hardcoded signal function.

### Recommended Change: Multi-Intent Classification

Replace the single-return classifier with a multi-intent classifier:

```python
# Instead of:
async def classify_intent(...) -> dict:          # returns ONE category
    return {"category": "log_supplement", ...}

# Move to:
async def classify_intents(...) -> list[dict]:   # returns ALL categories
    return [
        {"category": "log_supplement", "confidence": 0.9},
        {"category": "log_hydration", "confidence": 0.7},
    ]
```

**Implementation approach:**

1. **Model-based multi-intent prompt** — ask the utility model to return a list of categories:
   ```
   Classify ALL intents in this message. Return a JSON array.
   Message: "drank 24 oz with creatine and fat burner"
   → [{"category": "log_hydration", ...}, {"category": "log_supplement", ...}]
   ```

2. **Heuristic multi-scan** — instead of returning on first match, collect all matches:
   ```python
   def _heuristic_categories(message: str) -> list[str]:
       categories = []
       if _contains_any(text, hydration_cues): categories.append("log_hydration")
       if _contains_any(text, supplement_cues): categories.append("log_supplement")
       if _contains_any(text, food_cues): categories.append("log_food")
       return categories or ["general_chat"]
   ```

3. **Orchestrator loop already supports it** — `log_categories` (line 3419) is already a list that gets iterated. The change is in how it's populated.

**Scope:** Medium. Classifier change + remove force-signal hacks + update orchestrator to populate `log_categories` from multi-intent results.

### Implementation (Completed)

Added `_heuristic_log_categories()` to `specialist_router.py` — a multi-intent scanner that runs independent if-checks for all 7 log categories (fasting, sleep, hydration, exercise, vitals, supplements, food) instead of the single-return if/elif chain. The orchestrator merges these into `log_categories` after existing force signals:

```python
for secondary_cat in _heuristic_log_categories(message):
    if secondary_cat not in log_categories:
        log_categories.append(secondary_cat)
```

Also broadened hydration detection (quantity + fluid unit + drinking verb regex) and added named supplement detection (`_SUPPLEMENT_NAMES` tuple with 21 common supplement names).

Existing force-signal functions for food/sleep/fasting are preserved (they provide contextual awareness via assistant-recently-asked checks that the multi-scan doesn't replicate).

---

## Problem 2: No AI Tool Access (Tools Are Orchestrator-Only) — IMPLEMENTED (Option C)

**Current:** The AI chat call (`orchestrator.py:3827`) receives NO `tools` parameter. All 40+ tool calls are `tool_registry.execute()` called directly by Python code, not by the AI model. The AI cannot decide which tools to call, cannot call tools it wasn't pre-selected for, cannot ask for clarification before acting, and cannot handle ambiguous inputs.

### Evaluated Options (Provider-Agnostic)

#### Option A: MCP (Model Context Protocol)

Wrap the tool registry as an MCP server. Any LLM client that speaks MCP can call tools.

```
AI Model (any provider)  ──MCP──▶  MCP Server (tool_registry)  ──▶  DB/Services
```

**Pros:** Full provider portability. Standard protocol. Growing ecosystem.
**Cons:** Requires MCP server infrastructure. Adds network hop for tool calls. Heavier setup for local dev. Provider must support MCP client mode (not all do yet).
**Scope:** Medium. Build MCP server wrapping ToolRegistry, update provider layer to connect as MCP client.

#### Option B: Agent-to-Agent (Delegated Executor)

The primary coaching model generates tool call requests. A secondary "executor agent" validates, refines, and executes them. The executor can be a separate model, a rule-based system, or a dedicated microservice.

```
Primary Model (coaching)  ──requests──▶  Executor Agent  ──▶  tool_registry  ──▶  DB
                          ◀──results───
```

**Pros:** Separation of concerns — coaching model focuses on conversation, executor handles state changes. Executor can add safety validation, rate limiting, and audit logging. Swappable: executor can be local (same process), remote (microservice), or model-based.
**Cons:** Extra latency per tool call round-trip. More complex orchestration flow. Needs a clear request/response protocol.
**Scope:** Medium-large. Define request/response protocol, build executor service, modify orchestrator for async handoff.

#### Option C: Structured Output + Post-Response Tool Executor (CHOSEN)

The AI emits `<tool_call>` blocks in its text response. After streaming completes, a post-processor extracts and executes them via the existing `tool_registry`. Provider-agnostic — any model that can output structured text works.

```
AI Model (any)  ──text with <tool_call> blocks──▶  Extractor  ──▶  tool_registry  ──▶  DB
```

**Pros:** Simplest to implement. Zero provider dependency. Uses existing tool_registry unchanged. Works with any model (Claude, GPT, Ollama, etc.).
**Cons:** AI doesn't see tool results in the same turn (post-response execution). Tool calls embedded in text are less reliable than native tool-use protocols. No mid-response tool loops.
**Scope:** Small. New executor module + orchestrator post-stream hook + system prompt update.

### Implementation: Option C with Migration Path to Option B

**Design:** Behind a `ToolCallExecutor` protocol so the implementation can be swapped from "inline post-response extraction" (Option C) to "delegate to agent" (Option B) without changing the orchestrator.

```python
class ToolCallExecutor(Protocol):
    async def execute(self, requests: list[ToolCallRequest], ctx: ToolContext) -> list[ToolCallResult]: ...

# Option C: DirectToolCallExecutor — extracts from text, calls tool_registry.execute()
# Option B: AgentToolCallExecutor — delegates to sub-agent/microservice (future)
```

**AI-callable tools (Phase 1):**
- `plan_task_update_status` — mark plan tasks complete/skipped/pending
- `create_goal` — create a new health goal
- `update_goal` — update an existing goal

Log-write tools stay orchestrator-controlled (the multi-intent classification pipeline handles those).

**Files:**
- `backend/ai/tool_call_executor.py` — executor protocol + Option C implementation
- `backend/ai/orchestrator.py` — post-stream tool call extraction and execution
- `backend/context/system_prompt.md` — AI tool call instructions and available tools

### Implementation (Completed — Option C)

Created `backend/ai/tool_call_executor.py` with:

- **`ToolCallRequest`** / **`ToolCallResult`** dataclasses for the request/response protocol
- **`ToolCallExecutor`** protocol (swap-point for Option B migration)
- **`DirectToolCallExecutor`** class (Option C) — calls `tool_registry.execute()` in-process
- **`extract_tool_calls()`** — regex extraction of `<tool_call>` JSON blocks from AI response text
- **`strip_tool_calls()`** — removes blocks from display/storage text
- **`AI_CALLABLE_TOOLS`** allowlist — only `plan_task_update_status`, `create_goal`, `update_goal`
- **`format_tool_results_context()`** — human-readable summary of execution results

Orchestrator wiring (`orchestrator.py`):
- After streaming + followups, extracts tool calls from `full_response`
- Executes via `DirectToolCallExecutor` with the same `ToolContext`
- Strips `<tool_call>` blocks from stored message, appends "Actions taken" summary
- Safety: tool call blocks also stripped before message persistence as a fallback

System prompt (`system_prompt.md`):
- New "AI Tool Calls" section with format, available tools, examples, and rules
- Goal workflows updated to reference `<tool_call>` format

Frontend (`ChatMessage.tsx`, `GoalChatPanel.tsx`):
- `stripMetaTags()` extended to remove `<tool_call>` blocks from both user and assistant messages

**Migration to Option B:** Replace `DirectToolCallExecutor` with `AgentToolCallExecutor` that delegates to a sub-agent/microservice. The orchestrator call-site, system prompt, and frontend remain unchanged.

---

## Problem 3: One-Shot Parse With No Clarification — IMPLEMENTED

**Current:** `parse_log_data()` (`log_parser.py:461`) makes one model call or falls back to regex. There is no mechanism to:
- Report low confidence
- Ask the user for missing details
- Defer the save pending user confirmation

When parsing fails or produces incomplete data:
- Model parse fails → silent fallback to regex (`_deterministic_parse_by_category`)
- Regex produces partial data → saved with nulls, no user notification
- Tool write fails → error stored in context as "Write Status: failed", but AI can't retry

The **only** multi-turn mechanism is `time_confirmation_gate` — a narrow pattern for confirming inferred event times. No equivalent exists for missing quantities, ambiguous meal items, or unresolved supplement names.

### Recommended Change: Confidence-Gated Parse With Deferral

Add a confidence assessment to the parse pipeline:

```python
async def parse_log_data(...) -> ParseResult:
    result = await _model_parse(...)
    confidence = assess_confidence(result, category)

    if confidence >= HIGH:
        return ParseResult(data=result, action="save")
    elif confidence >= MEDIUM:
        return ParseResult(data=result, action="save_and_confirm",
                          question="I logged X — does that look right?")
    else:
        return ParseResult(data=None, action="clarify",
                          question="Can you tell me more about X?")
```

The orchestrator would then:
- `"save"` → execute tool immediately (current behavior for high confidence)
- `"save_and_confirm"` → save but persist a pending confirmation (generalized time_confirmation pattern)
- `"clarify"` → don't save; include the question in AI context; wait for next turn

**Generalized confirmation state:**
```python
class PendingConfirmation:
    category: str          # "log_food", "log_supplement", etc.
    parsed_data: dict      # What was parsed so far
    question: str          # What to ask the user
    saved_log_id: int | None  # If save_and_confirm, the ID to update
    expires_at: datetime   # Auto-expire after N turns
```

**Scope:** Medium. Requires: ParseResult type, confidence scoring, generalized PendingConfirmation model (extending time_confirmation), orchestrator state check on each turn.

### Implementation Notes (DONE)

Lightweight enrichment approach — no new DB tables or deferral loops. Instead, the parse pipeline scores quality and the AI's Write Status context tells it to ask better follow-up questions.

- **`log_parser.py`**: Added `assess_parse_confidence(parsed, category)` returning `(confidence_level, missing_field_names)`. Defines `_CRITICAL_FIELDS` (minimum required per category) and `_NOTABLE_FIELDS` (all tracked fields). Logic: deterministic fallback or critical fields missing -> "low"; <=50% notable fields present -> "medium"; otherwise "high".
- **`orchestrator.py`**: After `_apply_inferred_event_time()`, calls `assess_parse_confidence()` and attaches `_parse_confidence` and `_parse_missing_fields` metadata to the parsed dict. These `_`-prefixed keys pass through harmlessly (write tools use explicit field extraction).
- **`orchestrator.py` `_build_single_log_context()`**: For LOW confidence, adds "**Parse confidence: LOW** -- ask user to verify recorded values and provide missing details before coaching." For MEDIUM, adds "Parse confidence: MEDIUM -- confirm values and ask about missing fields: {field_list}." HIGH/absent preserves current behavior.

---

## Problem 4: Opaque Tool Results

**Current:** After tools execute, the AI sees only a pass/fail summary (`_build_log_write_context`, line 2053):
```
## Write Status
- Structured log write: success
- You may confirm this event as saved.
```

The AI does NOT see:
- What specific data was saved (field values, IDs)
- Which fields were null/missing
- How the data was resolved (e.g., template matching, medication resolution)
- What follow-up actions might improve the record

### Recommended Change: Rich Tool Result Context

Return structured details from tool execution to inform the AI's response:

```python
def _build_log_write_context(category, parsed_log, saved_out, write_error) -> str:
    if isinstance(saved_out, dict):
        details = json.dumps(saved_out, indent=2, default=str)
        missing = [k for k, v in (parsed_log or {}).items() if v is None and k != "notes"]
        ctx = f"## Write Status\n- Structured log write: success\n- Saved data: {details}\n"
        if missing:
            ctx += f"- Missing fields that user could provide: {', '.join(missing)}\n"
        return ctx
```

This lets the AI say "Logged your 24 oz of water and creatine. I didn't capture a dose for the fat burner — what's the dosage?" instead of a generic "Logged your intake."

**Scope:** Small. Only changes the context formatting function — no architectural restructuring needed.

---

## Problem 5: No Cross-Log Correlation — IMPLEMENTED

**Current:** Each log category produces an independent record. There's no mechanism to correlate related entries from the same message:
- "Took creatine with 24 oz water" → separate SupplementLog and HydrationLog with no link
- "Had eggs and coffee for breakfast" → FoodLog for eggs, but coffee's hydration aspect isn't captured
- "Morning workout then protein shake" → ExerciseLog + FoodLog with no timing relationship

### Recommended Change: Source Message Linking

Add a `source_message_id` foreign key to all log tables:

```python
class FoodLog(Base):
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

class HydrationLog(Base):
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

# etc.
```

When `save_structured_log` is called, pass the user message ID. This enables:
- Querying all logs from a single message
- Showing correlated entries in the dashboard
- AI referencing "from your earlier message" when coaching

**Scope:** Small. DB migration + pass message ID through save flow.

### Implementation Notes (DONE)

- **`models.py`**: Added `source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)` to all 7 log models (FoodLog, HydrationLog, VitalsLog, ExerciseLog, SupplementLog, FastingLog, SleepLog).
- **`base.py`**: Extended `ToolContext` with `message_id: int | None = None`.
- **`database.py`**: Added startup migration (`ALTER TABLE ... ADD COLUMN source_message_id INTEGER`) for all 7 log tables.
- **`orchestrator.py`**: Relocated `user_msg` creation to before the log-save loop so `user_msg.id` is available. Passes `message_id=user_msg.id` to `save_structured_log()`, which sets it on `ToolContext`.
- **`write_tools.py`**: All log ORM row creation sites set `source_message_id=ctx.message_id`. End-action updates (sleep/fasting) set it if not already present.

---

## Problem 6: Specialist Prompts Promise Capabilities They Don't Have

**Current:** Every specialist prompt (`context/specialists/*.md`) includes instructions like:
- "Follow the Tool Usage Contract in the system prompt"
- "Use platform tools for reads/writes/resolution"
- "Do not claim updates unless tool execution succeeded"

But specialists are pure text generators with no tool access. This creates hallucination pressure — the AI is told to use tools it can't access, so it either:
- Generates text that sounds like it used tools (hallucinated confirmations)
- Describes what it "would do" instead of doing it
- Ignores the instructions entirely

### Recommended Change: Align Prompts With Actual Capabilities

**Short-term:** Rewrite specialist prompts to accurately describe their role:
```markdown
## Your Role
You are a text advisor. The system logs data on your behalf before you respond.
Check the "Write Status" section in your context to know what was saved.
Do NOT claim to have logged, saved, or updated data unless Write Status says success.
```

**Long-term:** When Phase 2+ tool access (Problem 2) is implemented, restore the tool-usage instructions with actual tool specs.

**Scope:** Small for prompt rewrite. Dependent on Problem 2 for full fix.

---

## Priority and Sequencing

| Change | Impact | Effort | Dependencies |
|--------|--------|--------|-------------|
| **4. Rich tool result context** | High (better AI responses immediately) | Small | None | **DONE** |
| **6. Align specialist prompts** | Medium (reduces hallucination) | Small | None | **DONE** |
| **5. Source message linking** | Medium (enables correlation) | Small | DB migration | **DONE** |
| **1. Multi-intent classification** | High (fixes lost data) | Medium | None | **DONE** |
| **3. Confidence-gated parse** | High (fixes incomplete data) | Medium | Generalized confirmation model | **DONE** |
| **2. AI tool access** | Highest (enables real conversational flows) | Large (phased) | Provider + orchestrator rework | **DONE (Option C)** |

**Recommended order:**
1. ~~Start with #4 and #6 (small wins, immediate quality improvement)~~ DONE
2. ~~Then #1 (fixes the multi-intent data loss problem from Issue 5/6 in goalfix.md)~~ DONE
3. ~~Then #2 Option C (structured output + post-response tool executor)~~ DONE
4. ~~Then #5 and #3 in parallel~~ DONE
5. Then #2 Option B migration (agent-to-agent) when needed
