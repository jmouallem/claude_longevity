# Longevity Coach - System Alignment Notes

This document replaces older "Longevity Alchemist" build notes and reflects the current product behavior and architecture.

## 1. Product Intent

Longevity Coach is a multi-user AI health coaching system that should behave like an active coach, not a passive chatbot.

The expected loop is:
1. Build foundation (intake + frameworks + goals)
2. Execute daily/weekly/monthly plan tasks
3. Reflect using logs, outcomes, and adaptation runs
4. Adjust guidance and continue

## 2. Core Coaching Behavior (Non-Negotiable)

1. Post-intake must not end in open-ended "How can I help?" style prompts.
2. Low-signal check-ins (for example: "hello", "check in") must produce proactive plan guidance:
- show top priorities
- show progress
- ask for the next concrete action now
3. The system should continuously log, coach, and adapt.
4. If event time is not explicitly provided, use chat/message timestamp for calculations and day-bucketing.

## 3. Framework System (Current Design)

Framework taxonomy:
- Dietary Framework (`dietary`)
- Training Framework (`training`)
- Metabolic Timing Framework (`metabolic_timing`)
- Supplement / Micronutrient Framework (`micronutrient`)
- Thought Leader / Evidence Framework (`expert_derived`)

Seed examples are pre-populated and inactive by default. Intake/profile can activate relevant strategies.

### Allocation model
- Scores are treated as allocation percentages per framework type.
- Active items in a framework type are normalized to a total of 100.
- Multiple active items are supported and weighted against each other.

### Strategy explainability
Each strategy should have metadata used by UI and coaching:
- `summary`
- `supports`
- `watch_out_for`

In Settings, clicking a strategy should show:
- what it is
- how it maps to the user goals
- tradeoffs

## 4. Plan Engine (Current Design)

Plan cycles supported:
- Daily
- Weekly (Monday-Sunday)
- Monthly (rolling 30-day perspective in coaching)

Plan capabilities:
- Seed tasks from profile + active frameworks
- Show either top-N upcoming tasks or all tasks based on user preference
- Track task status (`pending`, `completed`, `skipped`)
- Reward/streak signals
- Notify on missed goals
- Apply adaptive target changes automatically (with undo path)

## 5. Chat, Tools, and Synchronization

The chat orchestration must route through tools for state changes.

Required behavior:
1. Logging in chat updates persisted records.
2. Dashboard and plan progress reflect those updates immediately.
3. Profile updates are shared across specialists and orchestration context.
4. Medication/supplement phrase resolution should map user shorthand (for example "blood pressure meds", "morning meds") to known profile items.

Tool categories:
- Reads: profile, logs, framework list/search, plan snapshot, menu templates
- Writes: logs, checklist marks, profile patch, framework upsert/update, plan status
- Resolution: medication/supplement/menu reference matching

## 6. Menu and Reusable Meals

Menu is chat-first:
- User can log meal naturally
- User can save a logged meal as named template
- Future logs can reference template by name

Menu supports:
- active/archived/delete lifecycle
- version history per template
- insights (usage, energy/GI response hooks)

## 7. AI Model Routing

Three model roles are configurable per user:
- Utility: extraction/parsing/classification, cheaper calls
- Reasoning: primary coaching dialogue and decisions
- Deep-thinking: longitudinal synthesis and high-depth adaptation proposals

Model selection UX should include:
- role hints
- presets (budget/balanced/premium)
- provider compatibility checks and fallback notifications

## 8. Longitudinal Analysis and Adaptation

Analysis windows:
- Daily
- Weekly
- Monthly

The engine should produce:
- run artifacts
- adjustment proposals
- status transitions (`pending`, `approved/applied`, `rejected`, `undone`)

Current expectation:
- avoid excessive catch-up execution during chat (`ANALYSIS_MAX_CATCHUP_WINDOWS_CHAT`)
- avoid repetitive duplicate proposals (combine similar)
- auto-apply policy can be enabled, with undo support

## 9. Security and Session Model

Security baseline:
- Cookie-based auth session (httpOnly)
- Security headers middleware
- Rate limits on auth and chat
- Upload MIME + signature validation
- Production startup gate rejects default secrets/passwords

Admin account:
- bootstrap from env (`ADMIN_USERNAME`, `ADMIN_PASSWORD`)
- admin-only pages and actions (user management, stats, audits)

## 10. Deployment/Runtime Conventions

Local defaults:
- Backend: `8001`
- Frontend: `8050`

Render deployment notes:
- Service listens on platform-provided `PORT` (for example `10000`)
- `CORS_ORIGINS` must be JSON array string (for example `["https://your-app.onrender.com"]`)
- Do not use default admin password in production

## 11. Source-of-Truth Areas

Primary backend modules:
- `backend/ai/orchestrator.py`
- `backend/ai/context_builder.py`
- `backend/services/coaching_plan_service.py`
- `backend/services/health_framework_service.py`
- `backend/services/analysis_service.py`
- `backend/api/*`

Primary frontend modules:
- `frontend/src/pages/Chat.tsx`
- `frontend/src/pages/Plan.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/Menu.tsx`
- `frontend/src/pages/Admin.tsx`

## 12. Engineering Guardrails

When changing behavior, preserve these invariants:
1. Chat -> data write -> dashboard/plan sync regression must pass.
2. Timezone/day-boundary calculations must be stable.
3. Framework allocations must remain normalized and explainable.
4. New users should be guided to API/models + intake before normal coaching flow.
5. Adaptation changes should remain auditable and reversible.
