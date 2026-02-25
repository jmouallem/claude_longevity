# FIXME - Architecture and Behavior Deep Dive

## Scope Reviewed
- Backend orchestration, intent parsing, structured extraction, tool execution, and persistence paths.
- API behavior for chat/logs/settings/menu/analysis/admin/feedback/intake.
- Data model constraints and migration behavior.
- Frontend data synchronization for Chat, Dashboard, Settings, Menu.
- Time handling, timezone behavior, checklist synchronization, and adaptation loop behavior.

## Execution Plan
1. Stabilize correctness in chat->log->dashboard synchronization and time semantics (P0).
2. Remove hidden side effects and redundant writes in read paths and orchestration (P0/P1).
3. Align tooling architecture with prompt contract and harden provider/model validation (P1).
4. Improve adaptation engine dedupe/determinism and reduce runtime contention (P1).
5. Normalize UX and naming consistency, then add regression tests for critical user journeys (P2).

## Findings and Task List

## Items Addressed

### Core Correctness and Data Integrity
1. Deprecated/unsafe user load in chat SSE stream.
2. Intent classifier fallback dropping log workflows.
3. Missing deterministic parser fallback on utility parse failure.
4. Silent write failures with success-sounding responses.
5. Duplicate checklist marking in a single turn.
6. Dashboard day basis misaligned with user timezone.
7. Sleep logs `target_date` not respected.
8. Side-effecting mutations inside `GET /api/logs/checklist`.
9. Missing uniqueness enforcement for daily checklist entries.
10. Clock token parsing gaps for common time formats.
11. Low-confidence inferred time confirmation persistence/enforcement.

### Architecture, Reliability, and Cohesion
12. Prompt/tool contract vs runtime execution alignment.
13. Blocking web search calls on async chat path.
14. Unsupported provider values accepted in settings API.
15. Comma-split fallback corrupting med/supp structured entries.
16. Proposal-list `GET` mutating proposal state.
17. Potential duplicate analysis runs under concurrency.
18. Oversized/competing context assembly each turn.
19. Mixed date semantics across domains/services.
20. Branding/name inconsistencies.
21. Missing automated cross-component regression coverage.

### Performance / AI Performance / Security
22. High per-turn backend read fan-out baseline and instrumentation.
23. Excessive sequential LLM utility-call fan-out.
24. Due-analysis dispatch on every chat message (debounce/lock added).
25. Dashboard request waterfall/duplication risk.
26. Blocking web-search path and resilience controls.
27. Missing explicit context-budget controls.
28. Production-unsafe default secret/credential guardrails.
29. `localStorage` token/session exposure risk.
30. Missing auth/chat endpoint rate limiting.
31. Upload content-type/signature hardening gaps.
32. Missing app-layer security header enforcement.

### Meal Logging Hardening Already Applied
45. Stronger meal-evidence detection in orchestration.
46. Context carry-over handling for short meal follow-up replies.
47. Multi-log attempt path for mixed-turn write opportunities.
48. Heuristic routing preference for mixed "log + question" meal turns.
49. Focused meal logging regression tests added.
50. False-positive safeguards for planning questions (no unintended meal write).

### Meal Recording Focus - Status Updates (33-44)
33. Workflow A resilience (explicit meal logs): **Partially addressed** with forced food logging gates; edge cases remain.
34. Workflow B resilience (short contextual follow-ups): **Partially addressed** via carry-over detection.
35. Workflow C resilience (mixed log + nutrition question): **Mostly addressed** for food-first handling.
38. Workflow F resilience (timezone/day-bucket perception): **Partially addressed** with server-driven dashboard day key.
40. Phase M2 secondary food-intent override/carry-over: **Partially addressed**.
41. Phase M3 deterministic parse/write fallback + failure surfacing: **Partially addressed**.
43. Phase M5 server day-key consistency: **Partially addressed** in dashboard path.

## Items Outstanding

### Meal Recording Focus - Deferred Work
33. Workflow A resilience: close remaining edge cases where explicit meal content bypasses write path.
34. Workflow B resilience: increase confidence/coverage for terse follow-up meal replies.
35. Workflow C resilience: enforce consistent “log first + coach” behavior for all mixed meal-question forms.
36. Workflow D resilience: one-message multi-domain logging completeness is still unresolved.
37. Workflow E resilience: menu save/update still depends on latest persisted meal and can drift.
38. Workflow F resilience: remaining UX mismatch outside dashboard aggregation path.

### Deferred Execution Plan (Not Fully Closed)
39. Phase M1 reproduction matrix + decision-trace telemetry for meal-write path.
40. Phase M2 hard guarantees (not heuristics) for secondary food-intent override/carry-over.
41. Phase M3 completion: deterministic parse/write guarantees across all food message patterns.
42. Phase M4 multi-intent segmentation and idempotent multi-write execution.
43. Phase M5 completion: server day-key consistency across all goal/chat/menu surfaces + write receipt UX.
44. End-state validation criteria for zero silent meal drops across message patterns.

### P0 - Correctness and Data Integrity

1. Deprecated and unsafe user load in chat SSE stream
- Evidence: `backend/api/chat.py:50`
- Evidence: `backend/api/chat.py:51`
- Problem: Uses `query(...).get(...)` and does not handle missing user before entering `process_chat`.
- Impact: Runtime failures or undefined behavior if user/session state becomes invalid mid-stream.
- Fix: Replace with `stream_db.get(User, user_id)` and explicit `None` guard that yields a terminal SSE error.
- Validate: Add API test for deleted/invalid user during `/api/chat` stream start.

2. Intent classifier failure collapses to `general_chat`, dropping logging workflows
- Evidence: `backend/ai/specialist_router.py:111`
- Evidence: `backend/ai/specialist_router.py:116`
- Evidence: `backend/ai/orchestrator.py:1825`
- Problem: On classifier failure, category becomes `general_chat`; structured log parsing/saving path is skipped.
- Impact: User says "I took meds" or "I ate lunch", assistant responds, but durable state may not update.
- Fix: Add deterministic intent fallback heuristics before defaulting to `general_chat`.
- Validate: Tests for classifier failure path still producing correct `log_*` categories for known intents.

3. No deterministic fallback when utility parser fails
- Evidence: `backend/ai/log_parser.py:121`
- Evidence: `backend/ai/log_parser.py:166`
- Problem: `parse_log_data` returns `None` on any extraction error; no rule-based fallback parser.
- Impact: Intermittent model/provider errors silently lose user logs.
- Fix: Add per-domain fallback extraction (regex/rules) for minimal viable writes.
- Validate: Simulate provider error and verify food/sleep/med logs still persist from deterministic parser.

4. Silent write failures can still lead to success-sounding assistant responses
- Evidence: `backend/ai/orchestrator.py:1850`
- Evidence: `backend/ai/orchestrator.py:1861`
- Evidence: `backend/ai/orchestrator.py:1590`
- Problem: Write/extraction exceptions are logged and suppressed; assistant generation proceeds without explicit failure context.
- Impact: Trust breach: user believes action was logged/updated when it was not.
- Fix: Propagate structured write status into generation context and require explicit "not saved" acknowledgement on failure.
- Validate: Force `ToolExecutionError` in write tools and assert assistant response states failure clearly.

5. Checklist marking runs multiple times in one chat turn
- Evidence: `backend/ai/orchestrator.py:1533`
- Evidence: `backend/ai/orchestrator.py:1581`
- Evidence: `backend/ai/orchestrator.py:1592`
- Evidence: `backend/ai/orchestrator.py:1788`
- Problem: Checklist completion is invoked in global pass + profile-sync path + exception fallback.
- Impact: Redundant model/tool calls, noisy writes, harder reasoning about source of checkbox state.
- Fix: Centralize checklist marking into a single post-parse phase with idempotent semantics.
- Validate: Instrument call counts; one user message should execute one checklist-mark workflow.

6. Dashboard date basis is browser-local, not user profile timezone
- Evidence: `frontend/src/pages/Dashboard.tsx:68`
- Evidence: `frontend/src/pages/Dashboard.tsx:399`
- Evidence: `frontend/src/pages/Dashboard.tsx:412`
- Problem: `today()` derives from local browser date, while backend calculations use user timezone.
- Impact: Dashboard can show previous/next-day data relative to what chat just logged.
- Fix: Fetch server/profile timezone day key from backend and use it for all `target_date` calls.
- Validate: Cross-timezone test (user TZ != device TZ) keeps chat logs and dashboard in same day bucket.

7. Sleep logs endpoint ignores `target_date`
- Evidence: `backend/api/logs.py:825`
- Evidence: `backend/api/logs.py:833`
- Problem: Both branches execute the same query; `target_date` has no effect.
- Impact: Sleep history filtering is misleading and incorrect for daily views.
- Fix: Use timezone-aware day window filtering when `target_date` is provided.
- Validate: API test confirms distinct results for different `target_date` values.

8. Read endpoint performs cleanup mutations and commits
- Evidence: `backend/api/logs.py:611`
- Evidence: `backend/api/logs.py:614`
- Evidence: `backend/api/logs.py:635`
- Problem: `GET /api/logs/checklist` repairs dates, edits profile fields, deletes rows, and commits.
- Impact: Non-idempotent read behavior, surprising state mutation, race risk under concurrent reads.
- Fix: Move repairs/cleanup to explicit migration/maintenance jobs; keep GET side-effect free.
- Validate: Repeated GET returns identical response and no row-count changes.

9. Missing uniqueness guarantee for daily checklist entries
- Evidence: `backend/db/models.py:359`
- Evidence: `backend/db/models.py:557`
- Problem: Index exists but is not unique for `(user_id, target_date, item_type, item_name)`.
- Impact: Duplicate rows possible; toggles/readbacks may use stale or ambiguous records.
- Fix: Add unique composite constraint/index and migration dedupe script.
- Validate: Concurrent writes for same key yield single row with deterministic final state.

10. Clock token extractor misses common explicit forms
- Evidence: `backend/ai/orchestrator.py:483`
- Evidence: `backend/ai/orchestrator.py:487`
- Problem: Extractor requires `HH:MM`; misses `11am`, `6 pm`, etc.
- Impact: Explicit user times degrade to inferred "now" behavior in some paths.
- Fix: Expand extractor to support hour-only meridiem formats and normalize.
- Validate: Unit tests for `11am`, `6 pm`, `06:20`, `18:20`.

11. Low-confidence inferred time only prompts for confirmation; no enforced correction loop
- Evidence: `backend/ai/orchestrator.py:562`
- Evidence: `backend/ai/orchestrator.py:573`
- Problem: Confirmation is prompt-only guidance; backend does not track unresolved low-confidence events.
- Impact: Incorrect event times can persist if assistant omits/softens follow-up.
- Fix: Persist inference confidence on writes and require explicit confirmation or correction for low-confidence events.
- Validate: Low-confidence logs surface pending-confirmation status until user confirms/corrects.

### P1 - Architecture Alignment and Reliability

12. Tool Usage Contract and runtime tool architecture are misaligned
- Evidence: `backend/context/system_prompt.md:59`
- Evidence: `backend/ai/orchestrator.py:1990`
- Evidence: `backend/services/summary_service.py:195`
- Problem: Prompt contract implies tool-aware behavior, but model calls are plain chat without runtime tool-call protocol.
- Impact: Contract cannot be enforced end-to-end; assistant wording can drift from actual write outcomes.
- Fix: Introduce explicit server-side action plan protocol (intent -> tool plan -> execute -> response) or true model tool-calling interface.
- Validate: For each stateful message type, response is generated from verified tool results, not assumptions.

13. Blocking web search in async chat path
- Evidence: `backend/tools/web_tools.py:72`
- Evidence: `backend/tools/web_tools.py:134`
- Evidence: `backend/tools/web_tools.py:167`
- Problem: Sync `httpx.Client` calls are used in tool handlers invoked from async orchestration.
- Impact: Event loop blocking, slower stream startup, poor concurrency.
- Fix: Convert web tools to async I/O or run blocking calls via thread executor.
- Validate: Load test with concurrent chats shows no event-loop starvation.

14. API key settings allow unsupported provider values
- Evidence: `backend/api/settings.py:686`
- Evidence: `backend/ai/providers/__init__.py:30`
- Problem: `set_api_key` writes `ai_provider` directly without validating allowed providers.
- Impact: Invalid provider persists and later fails at runtime provider resolution.
- Fix: Validate provider in settings API and reject unknown values with 400.
- Validate: `PUT /api/settings/api-key` rejects unsupported provider strings deterministically.

15. Legacy comma-split fallback can corrupt structured medication/supplement entries
- Evidence: `backend/utils/med_utils.py:254`
- Evidence: `backend/utils/med_utils.py:255`
- Problem: Non-JSON fallback splits by commas; values like `1,200 mcg` can fragment into multiple entries.
- Impact: Profile data quality degradation and downstream checklist mismatch.
- Fix: Remove comma-split fallback for structured fields or make parser number-aware.
- Validate: Parse tests for `1,200 mcg` and branded strings with commas.

16. Proposal list endpoint mutates proposal state during GET
- Evidence: `backend/api/analysis.py:121`
- Evidence: `backend/api/analysis.py:123`
- Problem: Listing proposals triggers dedupe+commit.
- Impact: Read operation changes state; hard to audit exactly when merges occurred.
- Fix: Move combine operation to write path (run creation/manual combine) and make GET read-only.
- Validate: GET proposals is idempotent with no DB writes.

17. Potential duplicate analysis runs under concurrency
- Evidence: `backend/services/analysis_service.py:699`
- Evidence: `backend/services/analysis_service.py:713`
- Problem: Check-then-create without uniqueness lock can race under concurrent triggers.
- Impact: Duplicate runs/proposals for same window and noisy adaptation output.
- Fix: Add DB uniqueness key for `(user_id, run_type, period_start, period_end)` and upsert semantics.
- Validate: Concurrent trigger test yields one run per window.

### P2 - Cohesion, Maintainability, and UX Consistency

18. Context assembly is large and can contain conflicting directives
- Evidence: `backend/ai/context_builder.py:294`
- Evidence: `backend/ai/orchestrator.py:1946`
- Problem: Base prompt + specialist prompt + identity + profile + frameworks + daily snapshot + summaries + adaptive guidance + runtime overlays are appended each turn.
- Impact: Token overhead, instruction collisions, less deterministic outputs.
- Fix: Use structured context blocks with budget limits and prioritization by intent category.
- Validate: Token budget telemetry and response consistency checks across categories.

19. Date semantics are mixed across services (event time vs created time vs target_date)
- Evidence: `backend/services/summary_service.py:81`
- Evidence: `backend/services/summary_service.py:92`
- Evidence: `backend/ai/context_builder.py:230`
- Problem: Some queries use `logged_at`, some `created_at`, some `target_date`, not always aligned by timezone rules.
- Impact: Daily summaries/dashboard/context can disagree on "today."
- Fix: Define canonical date dimension per domain and standardize all aggregations.
- Validate: One reference day should produce matching totals across dashboard, context snapshot, and summary service.

20. Branding/name inconsistencies remain across backend and frontend
- Evidence: `backend/main.py:28`
- Evidence: `backend/context/system_prompt.md:1`
- Evidence: `frontend/src/pages/Chat.tsx:150`
- Problem: Mixed "Longevity Alchemist" vs "Longevity Coach" labels.
- Impact: Product identity inconsistency and user confusion.
- Fix: Centralize app name constants and replace hardcoded strings.
- Validate: Smoke test for UI title/nav/auth pages + `/api/health` branding.

21. Missing automated regression coverage for critical cross-component flows
- Evidence: No backend test suite discovered for these flows.
- Problem: High-risk paths (intent->parse->write->dashboard sync->analysis) lack automated guardrails.
- Impact: Regressions reappear in time inference, checklist sync, menu save/update, and adaptation proposal logic.
- Fix: Add integration tests for priority user journeys.
- Validate: CI includes at least:
- Validate: chat intake/update sync tests.
- Validate: timezone day-boundary tests.
- Validate: checklist and dashboard consistency tests.
- Validate: adaptation dedupe/idempotency tests.

## Implementation Phasing

### Phase A - Data and Time Correctness
1. Fix items 1, 2, 3, 6, 7, 9, 10, 11.
2. Add deterministic intent/parser fallback and day-key normalization.
3. Add checklist unique constraint + dedupe migration.

### Phase B - Tool and Orchestration Reliability
1. Fix items 4, 5, 8, 12, 13, 14, 15.
2. Remove read-path mutations; centralize write outcomes and error propagation.
3. Move web tools off blocking sync calls.

### Phase C - Adaptation and System Cohesion
1. Fix items 16, 17, 18, 19, 20, 21.
2. Stabilize adaptation idempotency and unify date semantics.
3. Add regression suite and finalize naming consistency.

## Done Criteria (Global)
1. A log entered in chat is visible in dashboard and summaries for the same user-day in user timezone.
2. Stateful assistant confirmations are only emitted after successful writes.
3. GET endpoints are side-effect free.
4. Adaptation runs/proposals are idempotent under repeated/concurrent triggers.
5. Critical journeys are covered by automated tests in CI.

## Appendix - Performance, AI Performance, and Security Plan

### Additional Findings (Performance / AI Performance / Security)

22. Chat turn executes a high number of backend reads before generation
- Evidence: `backend/ai/context_builder.py:143`
- Evidence: `backend/ai/context_builder.py:294`
- Evidence: `backend/ai/orchestrator.py:1946`
- Problem: Each turn rebuilds large context and queries multiple tables (food/hydration/vitals/exercise/sleep/fasting/summaries/messages/frameworks).
- Impact: Higher p95 latency, higher DB load, and token bloat.
- Fix: Cache stable context slices per user (profile/frameworks/summaries) and compute only delta data per turn.
- Validate: Measure context-build latency and DB query count reduction by >=40% at p95.

23. Chat turn can fan out into many sequential LLM calls
- Evidence: `backend/ai/orchestrator.py:1765`
- Evidence: `backend/ai/orchestrator.py:1832`
- Evidence: `backend/ai/orchestrator.py:1463`
- Evidence: `backend/ai/orchestrator.py:1206`
- Evidence: `backend/ai/orchestrator.py:1333`
- Problem: Intent classify, parse, profile extract, med match, supplement match, then final generation can all run in one turn.
- Impact: Latency and cost amplification; failure probability increases with call count.
- Fix: Introduce per-turn AI call budget and merge utility tasks into a single extraction contract where possible.
- Validate: Track mean utility calls/turn and reduce to target envelope by intent type.

24. Due-analysis trigger runs on every chat message
- Evidence: `backend/ai/orchestrator.py:1939`
- Evidence: `backend/ai/orchestrator.py:1941`
- Evidence: `backend/services/analysis_service.py:896`
- Problem: Every chat message can spawn due-window scanning and potential run creation work.
- Impact: Unnecessary background load and contention under active chat usage.
- Fix: Add per-user debounce window and distributed/in-process lock for due-analysis dispatch.
- Validate: At most one due-analysis scheduler dispatch per user per configured interval.

25. Dashboard has avoidable request waterfall and likely duplicate dev fetches
- Evidence: `frontend/src/pages/Dashboard.tsx:395`
- Evidence: `frontend/src/pages/Dashboard.tsx:408`
- Evidence: `frontend/src/pages/Dashboard.tsx:411`
- Problem: Some dashboard calls are sequential after initial fetch, and the page has no strict-mode guard.
- Impact: Slower first render and repeated network load in development.
- Fix: Move to a single aggregate dashboard endpoint or fully parallelize calls with client cache and strict-mode-safe load guard.
- Validate: Dashboard first meaningful paint and API call count reduced in local and production profiles.

26. Blocking web search I/O in request path increases tail latency
- Evidence: `backend/tools/web_tools.py:72`
- Evidence: `backend/tools/web_tools.py:134`
- Evidence: `backend/tools/web_tools.py:167`
- Problem: Sync HTTP client calls are used in a chat request lifecycle.
- Impact: Event loop stalls and degraded concurrent chat throughput.
- Fix: Convert to async HTTP calls or offload to worker pool with timeout/circuit breaker.
- Validate: No blocking call sites on async path; improved concurrent throughput benchmark.

27. No explicit prompt/context size budgeting by specialist or intent
- Evidence: `backend/ai/orchestrator.py:1946`
- Evidence: `backend/ai/context_builder.py:300`
- Problem: Context concatenation grows with history/summaries/framework data without strict truncation policy.
- Impact: Token inflation, slower model responses, and unstable instruction adherence.
- Fix: Add context budget allocator (hard token caps per section) with deterministic truncation.
- Validate: Prompt token distribution dashboards show bounded section sizes.

28. Security defaults include production-unsafe fallback secrets/credentials
- Evidence: `backend/config.py:6`
- Evidence: `backend/config.py:7`
- Evidence: `backend/config.py:20`
- Evidence: `backend/config.py:21`
- Problem: Defaults include placeholder secret/encryption keys and a known admin username/password.
- Impact: High risk if defaults are deployed unchanged.
- Fix: Startup hard-fail in non-dev env when defaults remain; rotate and validate secrets.
- Validate: Boot-time config validation blocks unsafe secrets in staging/production.

29. Access token stored in `localStorage`
- Evidence: `frontend/src/api/client.ts:1`
- Evidence: `frontend/src/api/client.ts:4`
- Evidence: `frontend/src/stores/authStore.ts:29`
- Problem: Bearer token in localStorage is accessible to XSS payloads.
- Impact: Account/session takeover if frontend XSS occurs.
- Fix: Migrate to httpOnly secure same-site cookie session (or hardened token storage strategy with strict CSP/Trusted Types).
- Validate: Auth flow works without localStorage token persistence.

30. No explicit rate limiting for auth and chat endpoints
- Evidence: `backend/auth/routes.py:74`
- Evidence: `backend/api/chat.py:16`
- Problem: Login and chat endpoints do not show request throttling controls.
- Impact: Brute-force risk and AI-cost abuse risk.
- Fix: Add IP+user sliding-window rate limits and abuse telemetry for auth/chat/image upload.
- Validate: Automated tests verify throttling behavior and response codes.

31. Image upload path lacks content-type/signature validation beyond size
- Evidence: `backend/api/images.py:19`
- Evidence: `backend/api/images.py:27`
- Evidence: `backend/utils/image_utils.py:11`
- Problem: Size is enforced, but file type/content signature validation is minimal.
- Impact: Non-image payloads can enter upload pipeline; downstream processing risk.
- Fix: Validate mime + magic bytes, restrict extensions, and sanitize upload metadata.
- Validate: Reject disguised/non-image binaries; accept supported image types only.

32. Security headers are not enforced at app layer
- Evidence: `backend/main.py:31`
- Evidence: `backend/main.py:37`
- Problem: App sets CORS but no explicit security header middleware in code path.
- Impact: Reliance on external edge config; frontend protections may be inconsistent by environment.
- Fix: Add configurable middleware for CSP (or nonce-compatible policy), frame-ancestors/XFO, nosniff, referrer policy, and permissions policy.
- Validate: Security header checks pass in integration tests and runtime probes.

### Performance and Security Execution Plan

#### Phase D - Measurement Baseline (Required First)
1. Add request timing middleware and per-route latency histograms (chat, logs, dashboard, analysis).
2. Add DB query count/time instrumentation for chat and dashboard requests.
3. Add AI telemetry per turn: utility/reasoning/deep call counts, prompt tokens, completion tokens, and failure reasons.
4. Define SLO targets:
- Chat p95 first-token latency.
- Dashboard p95 load latency.
- Analysis run completion SLA.

#### Phase E - Backend and AI Performance
1. Implement per-user context cache for stable sections in `build_context`.
2. Introduce AI call budget policy per intent:
- `log_*` turns: max N utility calls.
- Non-logging turns: skip parser/profile extract unless intent confidence threshold triggers.
3. Merge profile extract + med/supplement semantic matching into one utility extraction response schema.
4. Debounce/lock due-analysis dispatcher on chat.
5. Convert blocking web-search tools to async/circuit-breaker pattern.
6. Add dashboard aggregate endpoint returning all card payloads in one response.

#### Phase F - Security Hardening
1. Enforce secure configuration gates:
- Reject default `SECRET_KEY`, `ENCRYPTION_KEY`, and default admin password outside dev.
2. Add auth and chat rate limiting with structured audit metrics.
3. Move user session token from localStorage to cookie-based session tokens (httpOnly, secure, same-site policy per environment).
4. Harden file upload validation (mime/magic bytes/allowlist).
5. Add security headers middleware with environment-specific CSP strategy.
6. Add dependency/vulnerability checks in CI and scheduled update policy.

#### Phase G - Verification and Rollout
1. Run load tests on chat and dashboard before/after each phase.
2. Add regression tests for:
- chat->log->dashboard synchronization.
- timezone day-boundary behavior.
- rate limit and auth/session behavior.
- upload validation rejection cases.
3. Add security verification checklist in CI:
- Header assertions.
- secret/config validation.
- token storage migration checks.
4. Roll out behind feature flags where behavior changes affect auth/session.

### Acceptance Criteria (Performance / AI / Security)
1. Chat p95 first-token latency improved against baseline target.
2. Average AI calls per chat turn reduced by intent class without loss of logging correctness.
3. Dashboard call count reduced and load latency improved.
4. Auth/chat abuse protections enforce configured rate limits.
5. No production startup with unsafe default secrets/credentials.
6. Session tokens are not readable via JavaScript in production mode.

## Progress Log

### Phase D Baseline Instrumentation (Implemented)
1. Added request telemetry middleware with route grouping (`chat`, `logs`, `dashboard`, `analysis`), duration capture, and DB query count/time capture.
2. Added SQLAlchemy query timing hooks (`before_cursor_execute`/`after_cursor_execute`) wired to per-request DB metrics.
3. Added persistent telemetry tables:
- `request_telemetry_events`
- `ai_turn_telemetry`
4. Added AI turn telemetry capture for chat turns:
- utility/reasoning/deep call counts
- token in/out totals by model tier
- first-token latency and total turn latency
- failure operation/reason capture
5. Added admin telemetry endpoint:
- `GET /api/admin/stats/performance?since_hours=24`
- Returns histograms, p50/p95/p99, DB metrics, AI turn stats, analysis completion timing, SLO targets, and current SLO pass/fail status.
6. Added SLO target config keys:
- `SLO_CHAT_P95_FIRST_TOKEN_MS`
- `SLO_DASHBOARD_P95_LOAD_MS`
- `SLO_ANALYSIS_RUN_COMPLETION_SLA_SECONDS`
7. Added Phase D tests in `backend/tests/test_phase_d_telemetry.py`.

### Phase E Performance Work (Implemented)
1. Added utility-call budget controls per turn category:
- `UTILITY_CALL_BUDGET_LOG_TURN`
- `UTILITY_CALL_BUDGET_NONLOG_TURN`
2. Added intent-call fallback to heuristic routing when utility budget is exhausted for classification.
3. Added parse fallback to deterministic parser when utility budget blocks model extraction.
4. Merged profile extraction + med/supp intake matching into one utility extraction contract (`matched_medications`, `matched_supplements`) and reused that output for checklist marking.
5. Removed extra med/supp AI matcher calls from checklist marking path to reduce per-turn utility fan-out.
6. Added debounced + in-flight-locked due-analysis dispatch on chat (`ANALYSIS_AUTORUN_DEBOUNCE_SECONDS`).
7. Added stable context caching in context builder for prompt/profile/framework/med-supp sections (TTL + bounded cache).
8. Added web-search circuit breaker controls:
- `WEB_SEARCH_CIRCUIT_FAIL_THRESHOLD`
- `WEB_SEARCH_CIRCUIT_OPEN_SECONDS`
9. Added aggregate dashboard API endpoint `GET /api/logs/dashboard` and switched frontend dashboard load to a single initial request.
10. Validation completed for Phase E changes:
- `python -m compileall backend` (pass)
- `python -m pytest -q backend/tests` (pass, 6 tests)
- `npm run build` in `frontend/` (pass)

### Phase F Security Hardening (Implemented)
1. Added production security startup gates in `backend/config.py`:
- blocks default `SECRET_KEY`, `ENCRYPTION_KEY`, and `ADMIN_PASSWORD` in production/staging.
- enforces secure cookie requirements in production-like environments.
2. Migrated auth session transport to cookie-backed auth:
- login/register/passkey login set HttpOnly session cookie.
- added `/api/auth/logout` cookie clear endpoint.
- backend auth now supports cookie token resolution (with bearer fallback).
- frontend removed `localStorage` token usage and sends `credentials: include`.
3. Added auth/chat rate limiting:
- `/api/auth/login`, `/api/auth/register`, `/api/auth/passkey/login/options`, `/api/auth/passkey/login/verify`, and `/api/chat`.
- returns HTTP `429` with `Retry-After` on limit breach.
4. Added structured rate-limit audit metrics:
- new table `rate_limit_audit_events`.
- integrated into admin performance payload as `rate_limit_blocks_last_window`.
5. Hardened upload validation:
- enforce image mime + magic-byte signature checks.
- allowlist formats: `jpg/jpeg`, `png`, `webp`, `gif`.
6. Added app-layer security headers middleware:
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Permissions-Policy`
7. Added dependency security automation:
- CI workflow `.github/workflows/security-dependency-checks.yml` (`pip-audit` + `npm audit`).
- scheduled update policy via `.github/dependabot.yml`.
8. Validation completed for Phase F changes:
- `python -m compileall backend` (pass)
- `python -m pytest -q backend/tests` (pass, 6 tests)
- `npm run build` in `frontend/` (pass)

### Phase G Verification and Rollout (In Progress)
1. Added CI quality gate workflow:
- `.github/workflows/quality-gates.yml`
- Runs backend dependency install, compile check, test suite, and frontend production build on push/PR to `main`.
2. Added verification tests in `backend/tests/test_phase_g_verification.py`:
- Security header assertions on `/api/health`.
- Cookie-session register/login/logout flow assertions.
- Rate limiter block behavior assertions.
- Upload signature/content-type mismatch rejection assertion.
3. Validation completed for new Phase G checks:
- `python -m compileall backend` (pass)
- `python -m pytest -q backend/tests` (pass, 13 tests)
- `npm run build` in `frontend/` (pass)
4. Added end-to-end onboarding regression in `backend/tests/test_phase_g_onboarding_e2e.py` covering:
- register -> API key/models setup -> intake completion -> framework selection -> plan snapshot -> task completion -> guided chat stream smoke check.
5. Re-validated backend suite after onboarding regression addition:
- `python -m pytest -q backend/tests` (pass, 18 tests)
6. Added cross-sync regression coverage in `backend/tests/test_phase_g_chat_dashboard_sync.py`:
- Chat-driven logging sync to dashboard totals and plan task progress.
- Time inference/day-bucket consistency for user timezone boundaries (today vs previous local day).
7. Re-validated backend suite after cross-sync regression addition:
- `python -m pytest -q backend/tests` (pass, 20 tests)
8. Added Phase G load-probe regression in `backend/tests/test_phase_g_load_probe.py`:
- Generates repeated chat and dashboard traffic.
- Verifies telemetry/performance snapshot captures route-group counts and p95 values.
9. Re-validated backend suite after load-probe regression addition:
- `python -m pytest -q backend/tests` (pass, 21 tests)
10. Added proactive low-signal check-in coaching path:
- `hello`/`check in` now returns active execution guidance (top priorities + immediate next action), not passive open-ended prompt.
- Implemented in `backend/ai/orchestrator.py` with regression coverage in `backend/tests/test_phase_g_chat_dashboard_sync.py`.
11. Re-validated backend suite after proactive check-in addition:
- `python -m pytest -q backend/tests` (pass, 22 tests)

## Fixed Items Register

### P0 Fixed
1. `backend/api/chat.py` now uses safe user loading in stream scope and handles missing user guard before streaming.
2. Deterministic intent fallback added so classifier failure does not collapse all actionable logs into `general_chat`.
3. Deterministic parse fallback added when utility extraction is unavailable/budget blocked.
4. Write outcome context is injected so assistant does not silently imply successful persistence after failed writes.
5. Checklist marking centralized/idempotent in one turn flow with merged extraction output reuse.
6. Dashboard unified to aggregate endpoint/day basis aligned to user timezone (`/api/logs/dashboard`).
7. Sleep/day filtering corrected for `target_date` semantics in logs endpoints.
8. `GET /api/logs/checklist` made read-only; cleanup mutations removed from read path.
9. Unique checklist item enforcement implemented (`idx_daily_checklist_unique_item`).
10. Time parsing and inference handling expanded/normalized for common user time forms.
11. Low-confidence time-inference confirmation flow persisted and enforced in orchestration context.

### P1 Fixed
12. Tool usage contract aligned with runtime orchestration/write-path confirmation semantics.
13. Web search moved off event-loop blocking path (`asyncio.to_thread`) and circuit-breaker controls added.
14. Provider/model validation hardened in settings APIs and model normalization flows.
15. Structured med/supp parsing strengthened to prevent comma-dose fragmentation regressions.
16. Proposal list GET path made side-effect free; combine moved to explicit write operation.
17. Analysis run dedupe hardening added with unique window index and race-safe creation behavior.

### P2 Fixed
18. Context builder now uses bounded section budgets and cached stable blocks to reduce collision/token bloat.
19. Date semantics consolidated across logs/dashboard/context/summary paths with timezone-aware helpers.
20. Product naming and UI behavior converged on `Longevity Coach` identity.
21. Cross-component regression suite now covers onboarding, sync, timezone boundary, security, and telemetry paths.

### Additional Post-Review Fixes Completed
22. Added Phase G load probe regression (`backend/tests/test_phase_g_load_probe.py`) validating telemetry snapshot population for chat/dashboard request groups.
23. Added proactive coaching fast-path for low-signal check-ins in orchestrator (execution-oriented response with next action).
24. Framework allocation UX standardized to 0-100 percent totals per framework type with normalize-to-100 support (`frontend/src/pages/Settings.tsx`).
25. Added strategy insight popout: click framework strategy (for example HIIT) to see summary, goal-fit mapping, benefits, and tradeoffs.
26. Seed framework metadata enhanced with explainability payloads (`summary`, `supports`, `watch_out_for`) and backfill for existing seed rows (`backend/services/health_framework_service.py`).

## Focused Review - Meal Recording From Chat (Deferred Work Plan)

### Review Scope
- Entry point: `POST /api/chat` streaming flow (`backend/api/chat.py`).
- Orchestration gates for `log_food` parse/write (`backend/ai/orchestrator.py`).
- Intent routing heuristics and model fallback (`backend/ai/specialist_router.py`).
- Parser and write tools (`backend/ai/log_parser.py`, `backend/tools/write_tools.py`).
- Readback path used by dashboard totals (`/api/logs/dashboard`).

### Perspectives and Workflow Lenses

33. Workflow A - Explicit meal logs ("I had X for lunch") **PARTIALLY ADDRESSED**
- Evidence: Parse/write path is gated by `if category.startswith("log_")` (`backend/ai/orchestrator.py`).
- Risk: Any misclassification bypasses parse + write entirely.

34. Workflow B - Contextual follow-up replies are fragile ("banana and bagel") **PARTIALLY ADDRESSED**
- Evidence: Intent classifier is message-only (no conversational turn context) and can fallback to deterministic heuristics (`backend/ai/orchestrator.py`, `backend/ai/specialist_router.py`).
- Risk: Short follow-up meal answers without strong cues can classify as `general_chat`, so no meal is written.

35. Workflow C - Mixed log + question messages can be routed as Q&A and skip persistence **MOSTLY ADDRESSED (food path)**
- Evidence: Food heuristic routes question-shaped meal messages to `ask_nutrition` (`backend/ai/specialist_router.py`).
- Example failure: "I had a bagel and coffee, is that okay?" can be coached but not persisted.

36. Workflow D - Multi-domain messages lose one side of the update **OUTSTANDING**
- Evidence: Router chooses one category only (`ROUTING_PROMPT_TEMPLATE` one-category contract in `backend/ai/specialist_router.py`).
- Example failure: "I ate lunch and took my meds" persists only one domain depending on category chosen.

37. Workflow E - Menu save/update confirmation and meal logging are separate paths **OUTSTANDING**
- Evidence: Menu actions use intent helpers and recent food log lookup (`backend/ai/orchestrator.py`).
- Risk: If the meal itself did not persist first, follow-up "yes save to menu" succeeds/fails against stale or missing latest food log.

38. Workflow F - "Not recorded" perception can be day-bucket mismatch, not write failure **PARTIALLY ADDRESSED**
- Evidence: Meal writes use inferred/explicit `logged_at`; dashboard reads by `target_date`.
- Risk: Meals inferred near day boundary/timezone edges appear under adjacent day and look missing in "today" view.

### Targeted Questions Before Fixing
1. Should any message that appears to contain food entities be dual-handled as `log_food + ask_nutrition` when both are present (log first, then coach)?
2. For short follow-ups after a food prompt ("banana and bagel"), should we force `log_food` for one turn based on prior assistant question context?
3. When multi-domain logs are in one message ("ate lunch and took meds"), should we support multi-write in one turn now, or split with explicit follow-up prompts?
4. If parse confidence is low, should we save a minimal meal item anyway (with `notes=low_confidence`) or ask for confirmation before writing?
5. Should dashboard default to user timezone "today" from server only (no client-derived date fallbacks) for meal totals everywhere?

### Deferred Implementation Plan

39. Phase M1 - Reproduction Matrix and Telemetry Hardening **OUTSTANDING**
- Add a meal-log diagnostic matrix in tests for 6 message shapes:
  - explicit statement
  - short follow-up
  - log+question
  - mixed meal+medication
  - image-assisted meal text
  - day-boundary meal time
- Persist per-turn `log_food` decision trace:
  - classified category
  - parser called yes/no
  - write success/failure reason
  - resulting food_log_id(s)

40. Phase M2 - Intent and Routing Reliability **PARTIALLY ADDRESSED**
- Add a secondary food-intent detector in orchestrator that can override category to `log_food` when strong meal evidence exists, even if classifier returns `ask_nutrition`/`general_chat`.
- Introduce "context carryover intent" for one turn after assistant asks meal-detail follow-up, so short answers are treated as food logs.
- Support `log_food + coaching` behavior for mixed meal/question messages.

41. Phase M3 - Parse/Write Safety Guarantees **PARTIALLY ADDRESSED**
- Ensure meal logging path always attempts deterministic parse fallback before giving up when category indicates food-like content.
- On write failure, enforce explicit assistant disclosure ("not saved") and actionable retry guidance.
- Add optional minimal-write mode for low-confidence meal extraction with a pending-confirmation tag.

42. Phase M4 - Multi-Intent Handling **OUTSTANDING**
- Add orchestrator split-pass for compound user messages:
  - identify meal segment and medication/supplement segment in same turn,
  - execute multiple write tools idempotently,
  - return one unified coaching response summarizing all successful writes.

43. Phase M5 - UX/Readback Consistency **PARTIALLY ADDRESSED**
- Standardize server-driven day keys for meal totals in all goal/dashboard/chat follow-up cards.
- Add a visible "Logged just now" confirmation snippet in chat sourced from actual write output (`food_log_id`, meal label, timestamp) to reduce ambiguity.

44. Validation and Done Criteria (Meal Logging) **OUTSTANDING**
- 0% silent meal-drop for tested patterns: if user message contains meal content, system either writes a food log or explicitly asks clarifying follow-up before claiming success.
- Mixed meal+question and mixed meal+med turns persist expected writes in one turn.
- Dashboard "today" meal counts match newly logged meals for user timezone within one refresh cycle.
- Regression tests cover classifier fallback and context-follow-up meal capture.

### Meal Logging Focus - Initial Hardening Applied
45. Added stronger meal-evidence detection in chat orchestration (`backend/ai/orchestrator.py`) and deterministic food fallback payloads for sparse follow-up turns.
46. Added contextual carry-over guard: if coach recently asked for meal details, short non-question follow-ups can still be persisted as meal logs (low-confidence tagged).
47. Added multi-log attempt path per turn so a food log can be persisted even when classifier selects a different `log_*` intent.
48. Updated heuristic routing so mixed "I had X ... ?" messages prefer `log_food` over pure Q&A (`backend/ai/specialist_router.py`).
49. Added focused regression tests (`backend/tests/test_meal_logging_focus.py`) and revalidated full backend test suite.
50. Added false-positive safeguards so planning questions (for example, "Can I have a banana for lunch?") route to `ask_nutrition` and do not auto-log meals.
