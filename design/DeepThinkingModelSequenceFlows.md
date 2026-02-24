# Deep-Thinking Model - Sequence Flows

This document captures all current application interactions that configure, invoke, persist, and surface deep-thinking model work.

## 1) User Configures Deep-Thinking Model (Settings)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Settings.tsx
    participant API as PUT /api/settings/models or /api/settings/api-key
    participant S as api/settings.py
    participant N as _normalize_models_for_provider
    participant DB as DB(UserSettings)

    U->>UI: Select provider + deep-thinking model
    UI->>API: Save model configuration
    API->>S: Validate provider + payload
    S->>N: Normalize reasoning/utility/deep model IDs
    N-->>S: Validated model IDs (fallback to provider defaults if invalid)
    S->>DB: Persist user_settings.deep_thinking_model
    DB-->>S: Commit
    S-->>UI: Saved model config
```

## 2) Admin Configures Deep-Thinking Model for a User

```mermaid
sequenceDiagram
    autonumber
    actor A as Admin
    participant UI as AdminUsers.tsx
    participant API as PUT /api/admin/users/{id}/ai-config
    participant AD as api/admin.py
    participant N as _normalize_models_for_provider
    participant DB as DB(UserSettings)

    A->>UI: Choose provider/preset/deep-thinking model for target user
    UI->>API: Save AI config for target user
    API->>AD: Validate admin auth + target user
    AD->>N: Normalize model set for provider
    N-->>AD: Normalized reasoning/utility/deep IDs
    AD->>DB: Update target_user.settings.deep_thinking_model
    DB-->>AD: Commit
    AD-->>UI: Updated user AI config
```

## 3) Chat-Triggered Due Analysis -> Monthly Deep Synthesis

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant C as Chat API
    participant O as ai/orchestrator.py
    participant D as run_due_analyses_for_user_id
    participant AS as run_due_analyses
    participant RL as run_longitudinal_analysis
    participant P as Provider
    participant M as Deep-thinking model
    participant DB as DB(AnalysisRun, AnalysisProposal, ModelUsageEvent)

    U->>C: Send chat message
    C->>O: process_chat(...)
    O->>D: _dispatch_due_analysis_if_allowed(user_id)
    D->>AS: run_due_analyses(trigger="chat")
    AS->>RL: run_longitudinal_analysis(run_type=daily)
    RL-->>AS: completed without deep call
    AS->>RL: run_longitudinal_analysis(run_type=weekly)
    RL-->>AS: completed without deep call
    AS->>RL: run_longitudinal_analysis(run_type=monthly)
    RL->>P: provider.chat(reasoning_model, REASONING_SYNTHESIS_PROMPT)
    P-->>RL: reasoning synthesis JSON
    RL->>P: provider.chat(deep_thinking_model, DEEP_SYNTHESIS_PROMPT)
    P->>M: Invoke deep-thinking model
    M-->>P: root causes + prompt adjustment proposals
    P-->>RL: deep payload
    RL->>DB: track_usage_from_result(... usage_type="deep_thinking")
    RL->>DB: Save AnalysisRun.used_deep_model + synthesis_json + proposals
    DB-->>RL: Commit
```

## 4) Manual Monthly Analysis Run -> Deep Synthesis

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Settings/Analysis UI
    participant API as POST /api/analysis/runs
    participant AAPI as api/analysis.py
    participant RL as run_longitudinal_analysis
    participant P as Provider
    participant M as Deep-thinking model
    participant DB as DB

    U->>UI: Trigger analysis run (run_type="monthly")
    UI->>API: POST /api/analysis/runs
    API->>AAPI: create_run(...)
    AAPI->>RL: run_longitudinal_analysis(monthly, trigger="manual")
    RL->>P: provider.chat(reasoning model)
    RL->>P: provider.chat(deep-thinking model)
    P->>M: Deep synthesis call
    M-->>P: Deep output
    RL->>DB: Persist run/proposals/usage
    AAPI-->>UI: Serialized analysis run (includes used_deep_model)
```

## 5) Deep Proposal Lifecycle (Store -> Apply -> Undo)

```mermaid
sequenceDiagram
    autonumber
    participant RL as run_longitudinal_analysis
    participant DB as AnalysisProposal
    participant COMB as combine_similar_pending_proposals
    participant REV as review_proposal
    actor U as User
    participant API as POST /api/analysis/proposals/{id}/review

    RL->>DB: Insert prompt_adjustment proposals from deep payload
    RL->>COMB: Merge repetitive pending proposals
    COMB->>DB: Update merge_count/merged_run_ids

    opt ANALYSIS_AUTO_APPLY_PROPOSALS=true
        RL->>REV: review_proposal(action="apply")
        REV->>DB: Mark applied + write adaptation changes
    end

    U->>API: Undo applied proposal
    API->>REV: review_proposal(action="undo")
    REV->>DB: Revert applied change (where supported)
```

## 6) Deep Usage Visibility (Cost/Token Reporting)

```mermaid
sequenceDiagram
    autonumber
    participant RL as run_longitudinal_analysis
    participant UT as ai/usage_tracker.py
    participant DB as ModelUsageEvent
    participant SU as GET /api/settings/usage
    participant AU as GET /api/admin/stats
    actor U as User/Admin

    RL->>UT: track_usage_from_result(... usage_type="deep_thinking")
    UT->>DB: Insert ModelUsageEvent(model_used, tokens_in, tokens_out, usage_type)
    U->>SU: Request personal usage/cost view
    SU->>DB: Aggregate Message + ModelUsageEvent rows
    SU-->>U: Per-model requests/tokens/estimated cost
    U->>AU: Request global admin stats
    AU->>DB: Aggregate usage across users/models
    AU-->>U: Global usage summary
```

## 7) Failure Path for Deep-Thinking Calls

```mermaid
sequenceDiagram
    autonumber
    participant RL as run_longitudinal_analysis
    participant P as Provider
    participant M as Deep-thinking model
    participant DB as AnalysisRun
    participant LOG as logger

    RL->>P: provider.chat(deep-thinking model)
    P->>M: API call
    M--xP: HTTP/API error (model unavailable, invalid params, etc.)
    P--xRL: Exception
    RL->>LOG: logger.exception("Longitudinal analysis failed")
    RL->>DB: status=failed, error_message, used_deep_model, completed_at
    DB-->>RL: Commit failure run
```

## Code Anchors

- Orchestrator dispatch: `backend/ai/orchestrator.py`
- Due-run scheduling and deep invocation: `backend/services/analysis_service.py`
- Provider deep model fallback: `backend/ai/providers/base.py`
- Provider model safety/normalization: `backend/ai/providers/__init__.py`
- User model config APIs: `backend/api/settings.py`
- Admin user model config API: `backend/api/admin.py`
- Analysis run/proposal APIs: `backend/api/analysis.py`
- Usage tracking and reporting: `backend/ai/usage_tracker.py`, `backend/api/settings.py`, `backend/api/admin.py`
