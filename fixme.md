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
