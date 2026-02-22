from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import AITurnTelemetry, AnalysisRun, RequestTelemetryEvent
from services.telemetry_context import consume_request_scope

REQUEST_HISTOGRAM_BUCKETS_MS = [100, 250, 500, 1000, 2000, 5000, 10000]

_DASHBOARD_PATHS = {
    "/api/settings/profile",
    "/api/logs/daily-totals",
    "/api/logs/vitals",
    "/api/logs/fasting/active",
    "/api/logs/exercise-plan",
    "/api/logs/checklist",
}


def classify_request_group(path: str) -> str | None:
    route = str(path or "").strip()
    if not route.startswith("/api/"):
        return None
    if route.startswith("/api/chat"):
        return "chat"
    if route.startswith("/api/analysis"):
        return "analysis"
    if route in _DASHBOARD_PATHS:
        return "dashboard"
    if route.startswith("/api/logs"):
        return "logs"
    return None


def persist_request_event(
    *,
    path: str,
    method: str,
    request_group: str,
    status_code: int,
    duration_ms: float,
    user_id: int | None,
    db_query_count: int,
    db_query_time_ms: float,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            RequestTelemetryEvent(
                user_id=user_id,
                request_group=request_group,
                path=path,
                method=method,
                status_code=int(status_code),
                duration_ms=max(float(duration_ms), 0.0),
                db_query_count=max(int(db_query_count), 0),
                db_query_time_ms=max(float(db_query_time_ms), 0.0),
            )
        )
        db.commit()
    finally:
        db.close()


def flush_request_scope(status_code: int, duration_ms: float, user_id: int | None = None) -> None:
    scope = consume_request_scope()
    if not scope:
        return
    persist_request_event(
        path=scope.path,
        method=scope.method,
        request_group=scope.request_group,
        status_code=status_code,
        duration_ms=duration_ms,
        user_id=user_id,
        db_query_count=scope.db_query_count,
        db_query_time_ms=scope.db_query_time_ms,
    )


def persist_ai_turn_event(payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.add(
            AITurnTelemetry(
                user_id=int(payload.get("user_id") or 0),
                message_id=payload.get("message_id"),
                specialist_id=str(payload.get("specialist_id") or "orchestrator"),
                intent_category=str(payload.get("intent_category") or "general_chat"),
                first_token_latency_ms=payload.get("first_token_latency_ms"),
                total_latency_ms=float(payload.get("total_latency_ms") or 0.0),
                utility_calls=int(payload.get("utility_calls") or 0),
                reasoning_calls=int(payload.get("reasoning_calls") or 0),
                deep_calls=int(payload.get("deep_calls") or 0),
                utility_tokens_in=int(payload.get("utility_tokens_in") or 0),
                utility_tokens_out=int(payload.get("utility_tokens_out") or 0),
                reasoning_tokens_in=int(payload.get("reasoning_tokens_in") or 0),
                reasoning_tokens_out=int(payload.get("reasoning_tokens_out") or 0),
                deep_tokens_in=int(payload.get("deep_tokens_in") or 0),
                deep_tokens_out=int(payload.get("deep_tokens_out") or 0),
                failure_count=int(payload.get("failure_count") or 0),
                failures_json=payload.get("failures_json"),
            )
        )
        db.commit()
    finally:
        db.close()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * weight)


def _histogram(values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return [{"bucket": f"<= {b}ms", "count": 0} for b in REQUEST_HISTOGRAM_BUCKETS_MS] + [
            {"bucket": f"> {REQUEST_HISTOGRAM_BUCKETS_MS[-1]}ms", "count": 0}
        ]

    counts = [0 for _ in REQUEST_HISTOGRAM_BUCKETS_MS]
    overflow = 0
    for value in values:
        assigned = False
        for i, boundary in enumerate(REQUEST_HISTOGRAM_BUCKETS_MS):
            if value <= boundary:
                counts[i] += 1
                assigned = True
                break
        if not assigned:
            overflow += 1

    rows = []
    for i, boundary in enumerate(REQUEST_HISTOGRAM_BUCKETS_MS):
        rows.append({"bucket": f"<= {boundary}ms", "count": counts[i]})
    rows.append({"bucket": f"> {REQUEST_HISTOGRAM_BUCKETS_MS[-1]}ms", "count": overflow})
    return rows


def summarize_request_group(db: Session, group: str, since: datetime) -> dict[str, Any]:
    try:
        rows = (
            db.query(
                RequestTelemetryEvent.duration_ms,
                RequestTelemetryEvent.db_query_count,
                RequestTelemetryEvent.db_query_time_ms,
            )
            .filter(
                RequestTelemetryEvent.request_group == group,
                RequestTelemetryEvent.created_at >= since,
            )
            .all()
        )
    except OperationalError:
        rows = []
    durations = [float(r.duration_ms or 0.0) for r in rows]
    db_counts = [int(r.db_query_count or 0) for r in rows]
    db_times = [float(r.db_query_time_ms or 0.0) for r in rows]
    count = len(durations)
    if count == 0:
        return {
            "count": 0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "db_query_count_avg": 0.0,
            "db_query_time_ms_avg": 0.0,
            "histogram": _histogram([]),
        }
    return {
        "count": count,
        "avg_ms": round(sum(durations) / count, 2),
        "p50_ms": round(_percentile(durations, 50), 2),
        "p95_ms": round(_percentile(durations, 95), 2),
        "p99_ms": round(_percentile(durations, 99), 2),
        "db_query_count_avg": round(sum(db_counts) / count, 2),
        "db_query_time_ms_avg": round(sum(db_times) / count, 2),
        "histogram": _histogram(durations),
    }


def summarize_ai_turns(db: Session, since: datetime) -> dict[str, Any]:
    try:
        rows = (
            db.query(AITurnTelemetry)
            .filter(AITurnTelemetry.created_at >= since)
            .order_by(AITurnTelemetry.created_at.desc())
            .all()
        )
    except OperationalError:
        rows = []
    if not rows:
        return {
            "count": 0,
            "first_token_p95_ms": 0.0,
            "total_turn_p95_ms": 0.0,
            "utility_calls_total": 0,
            "reasoning_calls_total": 0,
            "deep_calls_total": 0,
            "failures_total": 0,
            "top_failure_reasons": [],
        }

    first_token_values = [float(r.first_token_latency_ms) for r in rows if r.first_token_latency_ms is not None]
    total_turn_values = [float(r.total_latency_ms or 0.0) for r in rows]
    utility_calls_total = int(sum(int(r.utility_calls or 0) for r in rows))
    reasoning_calls_total = int(sum(int(r.reasoning_calls or 0) for r in rows))
    deep_calls_total = int(sum(int(r.deep_calls or 0) for r in rows))
    failures_total = int(sum(int(r.failure_count or 0) for r in rows))

    failure_counter: dict[str, int] = {}
    for row in rows:
        if not row.failures_json:
            continue
        try:
            import json

            failures = json.loads(row.failures_json)
        except Exception:
            continue
        if not isinstance(failures, list):
            continue
        for entry in failures:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("operation") or "unknown")
            failure_counter[key] = failure_counter.get(key, 0) + 1

    top_failure_reasons = [
        {"operation": op, "count": count}
        for op, count in sorted(failure_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    return {
        "count": len(rows),
        "first_token_p95_ms": round(_percentile(first_token_values, 95), 2) if first_token_values else 0.0,
        "total_turn_p95_ms": round(_percentile(total_turn_values, 95), 2),
        "utility_calls_total": utility_calls_total,
        "reasoning_calls_total": reasoning_calls_total,
        "deep_calls_total": deep_calls_total,
        "failures_total": failures_total,
        "top_failure_reasons": top_failure_reasons,
    }


def summarize_analysis_sla(db: Session, since: datetime) -> dict[str, Any]:
    try:
        rows = (
            db.query(AnalysisRun.created_at, AnalysisRun.completed_at)
            .filter(
                and_(
                    AnalysisRun.status == "completed",
                    AnalysisRun.created_at.isnot(None),
                    AnalysisRun.completed_at.isnot(None),
                    AnalysisRun.created_at >= since,
                )
            )
            .all()
        )
    except OperationalError:
        rows = []
    durations_s = [
        max((r.completed_at - r.created_at).total_seconds(), 0.0)
        for r in rows
        if r.completed_at and r.created_at
    ]
    if not durations_s:
        return {"count": 0, "p95_seconds": 0.0, "avg_seconds": 0.0}
    return {
        "count": len(durations_s),
        "p95_seconds": round(_percentile(durations_s, 95), 2),
        "avg_seconds": round(sum(durations_s) / len(durations_s), 2),
    }


def build_performance_snapshot(db: Session, since_hours: int = 24) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=max(int(since_hours), 1))
    return {
        "window_hours": max(int(since_hours), 1),
        "request_groups": {
            "chat": summarize_request_group(db, "chat", since),
            "logs": summarize_request_group(db, "logs", since),
            "dashboard": summarize_request_group(db, "dashboard", since),
            "analysis": summarize_request_group(db, "analysis", since),
        },
        "ai_turns": summarize_ai_turns(db, since),
        "analysis_sla": summarize_analysis_sla(db, since),
    }


def count_request_events(db: Session) -> int:
    try:
        return int(db.query(func.count(RequestTelemetryEvent.id)).scalar() or 0)
    except OperationalError:
        return 0
