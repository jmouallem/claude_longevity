# Application Vision - Longevity Coach

## Purpose
Longevity Coach exists to help users improve long-term health outcomes through clear goals, daily execution, active AI coaching, and adaptive plan adjustments based on real data.

## Primary Users
- Health-conscious adults who want structured coaching, not generic chat.
- Users managing weight, blood pressure, cardiometabolic risk, fitness, sleep, and adherence.
- Users who need an app that remembers context and guides the next step continuously.
- Multi-user households where each person has isolated data and coaching.

## Core User Needs
- I need a clear starting point after intake, not an open-ended blank chat.
- I need goals broken into daily, weekly, and monthly targets I can actually follow.
- I need active coaching that tells me what to do next and logs progress with me.
- I need my profile, chat logs, dashboard, and plan to stay synchronized.
- I need the system to adapt targets and prompts when I struggle or improve.
- I need coaching to align with my selected health frameworks and priorities.
- I need recommendations that are safe, practical, and personalized to my data.
- I need low-friction logging for repeated meals, meds, supplements, and routines.

## Product Principles
- Active over passive: coaching should initiate and guide execution.
- Actionable over abstract: every interaction should end with a concrete next action.
- Contextful over stateless: responses must use current profile, logs, framework weights, and plan state.
- Adaptive over static: plans should evolve with adherence, outcomes, and user feedback.
- Explainable over opaque: framework choices and adaptive changes should be understandable and reversible.
- Safe by default: medical-risk topics must include safety boundaries and escalation guidance.

## Experience Model
1. Foundation
- User sets provider/models, completes intake, selects frameworks, defines goals/why.
2. Execution
- Daily/weekly/monthly plan tasks appear with top priorities visible in chat/dashboard.
- User logs events naturally in chat; system updates records and progress immediately.
3. Reflection
- System summarizes trends, adherence, and outcomes across time windows.
4. Adaptation
- Engine proposes/applies adjustments (with undo/audit), then updates guidance and targets.
5. Repeat
- Continuous coaching loop: plan -> do -> review -> adjust.

## Key Capability Areas
- Goal Setting and Planning
- Active Coaching and Next-Step Guidance
- Framework Management and Weighted Allocation (0-100 per framework type)
- Adaptive Analysis (daily/weekly/monthly)
- Structured Logging (food, hydration, sleep, exercise, vitals, meds/supplements)
- Menu Templates and Reusable Meals
- Safety Guardrails and Specialist Routing
- Multi-model AI routing (utility/reasoning/deep-thinking)
- Admin controls and operational visibility

## What “Good” Looks Like
- New users are guided into setup/intake/plan onboarding without confusion.
- A low-signal check-in like “hello” returns execution guidance, not a generic greeting.
- Chat logging instantly updates dashboard totals and plan task progress for the same user-day.
- Framework selections measurably influence coaching recommendations.
- Adaptive changes are visible, explainable, and reversible.
- Users feel coached through the day, not left to invent the workflow.

## Non-Goals
- Replacing licensed medical care.
- Fully autonomous clinical decision-making.
- High-friction manual data entry as the primary interaction style.

## Living Document Rules
- This file is the product-level source of truth for user intent and experience direction.
- When features change, update this file in the same PR/commit as the implementation.
- Add a short entry to the change log for every material behavior change.

## Change Log
- 2026-02-23: Initial vision file created and aligned to current coaching architecture (intake -> frameworks -> plan -> active coaching -> adaptation loop).
