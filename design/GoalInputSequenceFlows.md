# Goal Input Parsing - Key Sequence Flows

This document captures the main runtime sequences for parsing user goal input and persisting structured goals.

## 1) Goals Page Kickoff -> Chat -> Goal Sync

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant G as Goals.tsx
    participant C as Chat.tsx
    participant API as POST /api/chat
    participant O as ai/orchestrator.py
    participant R as specialist_router.classify_intent
    participant P as Provider(utility model)
    participant GS as _apply_goal_updates
    participant T as ToolRegistry
    participant DB as DB(UserGoal, Message)

    U->>G: Click "Set goals with coach" / "Refine with coach"
    G->>C: navigate('/chat', state={chatFill, autoSend:true})
    C->>API: send chatFill as first user message
    API->>O: process_chat(user, message)
    O->>R: classify_intent(message)
    R-->>O: {category, specialist}
    O->>DB: Save user Message
    O->>GS: _apply_goal_updates(message, recent context, current goals)
    GS->>P: goal_sync_extract (GOAL_SYNC_EXTRACT_PROMPT)
    P-->>GS: JSON {action, create_goals[], update_goals[]}
    GS->>T: create_goal / update_goal (per extracted rows)
    T->>DB: INSERT/UPDATE UserGoal
    DB-->>T: saved rows
    T-->>GS: goal payload(s)
    GS-->>O: summary {created, updated, titles}
    O->>P: Generate assistant response
    P-->>O: final coaching text
    O-->>API: stream chunks + done
    API-->>C: assistant response + goal sync follow-up line
```

## 2) Goal Extraction + Persistence (Detailed)

```mermaid
sequenceDiagram
    autonumber
    participant O as process_chat
    participant GS as _apply_goal_updates
    participant DB as DB
    participant P as Utility Model
    participant T as Goal Tools

    O->>GS: call with message_text + reference_utc
    GS->>GS: _looks_like_goal_turn?
    alt not goal context
        GS-->>O: {goal_context:false, created:0, updated:0}
    else goal context
        GS->>GS: _goal_save_intent(message)
        GS->>DB: Load active UserGoal rows
        GS->>DB: Load last ~6 messages (assistant+user)
        GS->>P: Extract JSON action/create/update
        alt extraction fails / invalid JSON
            GS-->>O: attempted=true, created=0, updated=0
        else parsed JSON
            GS->>GS: Validate action in {create, update, create_or_update}
            loop each create_goals item (max 3)
                GS->>GS: dedupe by title/goal_id
                GS->>T: create_goal(payload)
                T->>DB: INSERT UserGoal
                DB-->>T: saved goal
            end
            loop each update_goals item (max 5)
                GS->>DB: refresh active goals
                GS->>GS: resolve by goal_id or title_match
                GS->>T: update_goal(payload)
                T->>DB: UPDATE UserGoal
                DB-->>T: updated goal
            end
            GS-->>O: created/updated counts + titles
        end
    end
```

## 3) Create vs Refine Intents from Goals UI

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant G as Goals.tsx
    participant O as Orchestrator
    participant GS as _apply_goal_updates
    participant DB as UserGoal

    U->>G: Open goals
    alt no active goals
        G->>O: "Goal-setting kickoff: define 1-3 measurable goals..."
        O->>GS: parse kickoff + user confirmation turns
        GS->>DB: create_goal rows
    else active goals exist
        G->>O: "Goal-refinement kickoff: review/refine existing goals..."
        O->>GS: parse refine/update turns
        GS->>DB: update_goal rows (targets/timeline/priority/status)
    end
    DB-->>G: goals available via /api/goals and /api/plan snapshots
```

## 4) Guardrails / Non-Persistence Paths

```mermaid
sequenceDiagram
    autonumber
    participant U as User Message
    participant GS as _apply_goal_updates
    participant P as Utility Model
    participant DB as UserGoal

    U->>GS: "goal conversation" turn
    GS->>P: extract action/create/update
    P-->>GS: JSON payload
    alt action == "none" OR invalid action
        GS-->>U: no goal persistence
    else create/update present
        GS->>GS: validate numeric/status/goal_type fields
        alt row unresolved (no matching goal_id/title)
            GS-->>U: skip unresolved update
        else valid resolved row
            GS->>DB: persist create/update
            DB-->>GS: committed goal state
        end
    end
```

## Code Anchors

- Goal kickoff prompt composition: `frontend/src/pages/Goals.tsx`
- Goal extraction prompt and sync logic: `backend/ai/orchestrator.py`
- Goal persistence tool handlers: `backend/tools/goal_tools.py`
- CRUD API for goals page: `backend/api/goals.py`
