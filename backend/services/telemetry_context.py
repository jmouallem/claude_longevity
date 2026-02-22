from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _bucket_for_usage_type(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"utility"}:
        return "utility"
    if value in {"reasoning"}:
        return "reasoning"
    if value in {"deep", "deep_thinking", "deep-thinking"}:
        return "deep"
    return "utility"


@dataclass
class RequestTelemetryScope:
    path: str
    method: str
    request_group: str
    started_at: datetime = field(default_factory=_now_utc)
    db_query_count: int = 0
    db_query_time_ms: float = 0.0


@dataclass
class AITurnTelemetryScope:
    user_id: int
    specialist_id: str = "orchestrator"
    intent_category: str = "general_chat"
    started_at: datetime = field(default_factory=_now_utc)
    first_token_latency_ms: float | None = None
    utility_calls: int = 0
    reasoning_calls: int = 0
    deep_calls: int = 0
    utility_tokens_in: int = 0
    utility_tokens_out: int = 0
    reasoning_tokens_in: int = 0
    reasoning_tokens_out: int = 0
    deep_tokens_in: int = 0
    deep_tokens_out: int = 0
    failure_count: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


_request_scope_var: contextvars.ContextVar[RequestTelemetryScope | None] = contextvars.ContextVar(
    "request_telemetry_scope",
    default=None,
)
_ai_turn_scope_var: contextvars.ContextVar[AITurnTelemetryScope | None] = contextvars.ContextVar(
    "ai_turn_telemetry_scope",
    default=None,
)


def start_request_scope(path: str, method: str, request_group: str) -> RequestTelemetryScope:
    scope = RequestTelemetryScope(path=path, method=method, request_group=request_group)
    _request_scope_var.set(scope)
    return scope


def get_request_scope() -> RequestTelemetryScope | None:
    return _request_scope_var.get()


def consume_request_scope() -> RequestTelemetryScope | None:
    scope = _request_scope_var.get()
    _request_scope_var.set(None)
    return scope


def clear_request_scope() -> None:
    _request_scope_var.set(None)


def add_request_db_query(duration_ms: float) -> None:
    scope = _request_scope_var.get()
    if not scope:
        return
    scope.db_query_count += 1
    scope.db_query_time_ms += max(float(duration_ms), 0.0)


def start_ai_turn_scope(user_id: int, specialist_id: str = "orchestrator", intent_category: str = "general_chat") -> AITurnTelemetryScope:
    scope = AITurnTelemetryScope(
        user_id=int(user_id),
        specialist_id=str(specialist_id or "orchestrator"),
        intent_category=str(intent_category or "general_chat"),
    )
    _ai_turn_scope_var.set(scope)
    return scope


def get_ai_turn_scope() -> AITurnTelemetryScope | None:
    return _ai_turn_scope_var.get()


def update_ai_turn_scope(specialist_id: str | None = None, intent_category: str | None = None) -> None:
    scope = _ai_turn_scope_var.get()
    if not scope:
        return
    if specialist_id:
        scope.specialist_id = str(specialist_id)
    if intent_category:
        scope.intent_category = str(intent_category)


def record_ai_call(
    usage_type: str,
    model_used: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    operation: str | None,
) -> None:
    _ = model_used
    _ = operation
    scope = _ai_turn_scope_var.get()
    if not scope:
        return

    bucket = _bucket_for_usage_type(usage_type)
    in_count = _safe_int(tokens_in)
    out_count = _safe_int(tokens_out)

    if bucket == "utility":
        scope.utility_calls += 1
        scope.utility_tokens_in += in_count
        scope.utility_tokens_out += out_count
    elif bucket == "reasoning":
        scope.reasoning_calls += 1
        scope.reasoning_tokens_in += in_count
        scope.reasoning_tokens_out += out_count
    else:
        scope.deep_calls += 1
        scope.deep_tokens_in += in_count
        scope.deep_tokens_out += out_count


def record_ai_failure(usage_type: str, operation: str, error: str) -> None:
    scope = _ai_turn_scope_var.get()
    if not scope:
        return
    scope.failure_count += 1
    if len(scope.failures) < 10:
        scope.failures.append(
            {
                "usage_type": str(usage_type or "utility"),
                "operation": str(operation or "unknown"),
                "error": str(error or "")[:300],
            }
        )


def mark_ai_first_token(first_token_latency_ms: float) -> None:
    scope = _ai_turn_scope_var.get()
    if not scope:
        return
    if scope.first_token_latency_ms is None:
        scope.first_token_latency_ms = max(float(first_token_latency_ms), 0.0)


def consume_ai_turn_scope() -> AITurnTelemetryScope | None:
    scope = _ai_turn_scope_var.get()
    _ai_turn_scope_var.set(None)
    return scope


def clear_ai_turn_scope() -> None:
    _ai_turn_scope_var.set(None)

