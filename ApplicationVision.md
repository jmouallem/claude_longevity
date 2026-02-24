# Application Vision - Longevity Coach

## Purpose
Longevity Coach is a goal-first AI coaching app that turns user intent into an executable health plan, then keeps the user in an active loop:
foundation -> execution -> reflection -> adaptation.

## Product Intent
- Replace passive "chat bot" behavior with proactive coaching.
- Convert broad goals into measurable targets with timelines and rationale.
- Drive daily action with clear next steps, not open-ended prompts.
- Keep profile, logs, goals, frameworks, plan tasks, and coaching responses synchronized.
- Adapt coaching and targets over time while preserving explainability and undo paths.

## Primary Users
- Adults managing weight, blood pressure, cardiometabolic risk, fitness, sleep, and adherence.
- Users who need structure and continuity across days and weeks.
- Users who repeat routines (meals, meds, supplements, training) and need low-friction logging.
- Admin operators who need secure user management and platform oversight.

## Current App Flow (Aligned to Implementation)
1. Authentication
- User registers/logs in.
- Admin users are routed to dedicated admin pages.

2. Setup Gate
- If API key/models are not configured, user is routed to Settings.
- Intake prompt is enforced until setup is complete.

3. Intake and Handoff
- Intake collects profile + framework preferences.
- Post-intake route goes to `Goals` onboarding.

4. Goals-First Home (`/goals`)
- Default authenticated landing page.
- Shows active structured goals.
- Shows plan timeline with:
  - `Today` view (time-of-day blocks).
  - `Next 5` rolling view (today + next 4 days).
- Each task is coach-driven (`Chat` action/check-in), including future-day tasks.

5. Execution in Chat (`/chat`)
- Chat is the operational surface for logging, check-ins, and coaching.
- Goal-setting/refinement kickoffs can be auto-sent from Goals page.
- Goal updates are persisted through tool-backed sync (create/update goal tools).
- Verbosity modes exist per chat turn (`normal`, `summarized`, `straight`).

6. Reflection and Adaptation
- Dashboard/History/Plan summarize progress and adherence.
- Analysis engine generates runs and adjustment proposals.
- Adjustments can be applied with auditability and undo window where supported.

## Core Capability Areas
- Structured Goals
  - Entity-backed goals with target values, units, baseline/current values, dates, priority, and why.
- Coaching Plan Engine
  - Daily/weekly/monthly tasks with completion state and progress.
  - Time-of-day task placement.
  - Rolling 5-day read model for forward visibility.
- Health Frameworks
  - Five framework types:
    - Dietary Strategy
    - Training Protocol
    - Metabolic Timing Strategy
    - Micronutrient Strategy
    - Expert-Derived Framework
  - Multiple active strategies per type with weighted allocation (0-100 scale semantics).
- Chat-First Logging + Tooling
  - Food, hydration, exercise, sleep, meds/supplements, vitals, fasting.
  - Menu templates for repeated meals.
- Adaptive Intelligence
  - Daily/weekly/monthly analysis runs.
  - Proposal generation, application, and reversibility controls.
- Security and Admin
  - Case-insensitive usernames.
  - Secure sessions/cookies and admin controls for users, feedback, and security actions.

## Decision Hierarchy
When guidance conflicts, the system should resolve in this order:
1. Safety constraints and escalation rules.
2. User-approved goals and medical context.
3. Active framework priorities and allocations.
4. Current cycle tasks (daily > weekly > monthly for immediate coaching).
5. Style preferences (verbosity, presentation).

## Training Planning Semantics
- The training framework should not collapse to one strategy every day by default.
- If user sets explicit weekly intent (for example, "2 HIIT and 2 strength"), schedule should honor that first.
- If explicit counts are missing, distribute from active training weights.
- Daily view should reflect scheduled training mix, not repeated single-strategy bias.

## Synchronization Requirements
- Same-day chat logs must update corresponding dashboard and plan signals.
- Goal updates confirmed in coaching must persist to `UserGoal` records.
- Framework changes must influence subsequent task generation and coaching context.
- Time handling should be timezone-consistent across device/browser surfaces.

## UX Principles
- Goal-first orientation over generic chat starts.
- Small visible next-action set to reduce overwhelm.
- Clear weekly/monthly context while keeping daily execution simple.
- Mobile-first behavior must remain usable in portrait and landscape.
- Markdown responses should render consistently in all chat surfaces.

## Non-Goals
- Replacing licensed medical care.
- Autonomous clinical diagnosis/treatment.
- Forcing high-friction manual workflows for routine tracking.

## Quality Bar
- New user can reach first actionable plan without dead ends.
- "Set goals with coach" always starts a guided goal conversation, not a blank chat.
- Goal persistence is verifiable in UI/API after coaching confirmation.
- Rolling timeline reflects intended training mix and future tasks are discussable.
- Adaptive behavior is observable, explainable, and reversible where applicable.

## Living Document Rules
- This file is the product-level source of truth for intent and behavioral direction.
- Any material behavior change should update this document in the same change set.
- Keep statements implementation-aligned; avoid aspirational claims without shipped behavior.

## Change Log
- 2026-02-23: Initial vision file added.
- 2026-02-24: Realigned to shipped goals-first architecture (Goals default route, goal-setting kickoff from Goals, rolling 5-day timeline, chat-driven goal updates, framework-weighted planning, adaptation loop).
