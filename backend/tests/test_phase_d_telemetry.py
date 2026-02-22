from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.usage_tracker import track_model_usage  # noqa: E402
from db.database import Base  # noqa: E402
from db.models import AITurnTelemetry, RequestTelemetryEvent  # noqa: E402
from services.telemetry_context import (  # noqa: E402
    consume_ai_turn_scope,
    record_ai_failure,
    start_ai_turn_scope,
)
from services.telemetry_service import (  # noqa: E402
    classify_request_group,
    summarize_ai_turns,
    summarize_request_group,
)


def _new_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_classify_request_group_routes():
    assert classify_request_group("/api/chat") == "chat"
    assert classify_request_group("/api/auth/login") == "auth"
    assert classify_request_group("/api/logs/dashboard") == "dashboard"
    assert classify_request_group("/api/logs/daily-totals") == "dashboard"
    assert classify_request_group("/api/logs/hydration") == "logs"
    assert classify_request_group("/api/analysis/runs") == "analysis"
    assert classify_request_group("/assets/app.js") is None


def test_ai_turn_scope_tracks_calls_tokens_and_failures():
    class _FakeSession:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

    fake_db = _FakeSession()
    start_ai_turn_scope(user_id=1, specialist_id="nutritionist", intent_category="log_food")
    track_model_usage(
        db=fake_db,
        user_id=1,
        model_used="gpt-4o-mini",
        operation="log_parse:log_food",
        usage_type="utility",
        tokens_in=120,
        tokens_out=40,
    )
    track_model_usage(
        db=fake_db,
        user_id=1,
        model_used="gpt-4o",
        operation="chat_generate",
        usage_type="reasoning",
        tokens_in=500,
        tokens_out=260,
    )
    record_ai_failure("utility", "profile_extract", "timeout")
    scope = consume_ai_turn_scope()
    assert scope is not None
    assert scope.utility_calls == 1
    assert scope.reasoning_calls == 1
    assert scope.deep_calls == 0
    assert scope.utility_tokens_in == 120
    assert scope.utility_tokens_out == 40
    assert scope.reasoning_tokens_in == 500
    assert scope.reasoning_tokens_out == 260
    assert scope.failure_count == 1
    assert scope.failures[0]["operation"] == "profile_extract"


def test_request_and_ai_turn_summaries():
    db = _new_db()
    db.add(
        RequestTelemetryEvent(
            request_group="dashboard",
            path="/api/logs/daily-totals",
            method="GET",
            status_code=200,
            duration_ms=220.0,
            db_query_count=4,
            db_query_time_ms=19.0,
        )
    )
    db.add(
        RequestTelemetryEvent(
            request_group="dashboard",
            path="/api/logs/vitals",
            method="GET",
            status_code=200,
            duration_ms=410.0,
            db_query_count=6,
            db_query_time_ms=33.0,
        )
    )
    db.add(
        AITurnTelemetry(
            user_id=1,
            specialist_id="nutritionist",
            intent_category="log_food",
            first_token_latency_ms=1800.0,
            total_latency_ms=2600.0,
            utility_calls=2,
            reasoning_calls=1,
            deep_calls=0,
            utility_tokens_in=320,
            utility_tokens_out=140,
            reasoning_tokens_in=900,
            reasoning_tokens_out=400,
            failure_count=0,
            failures_json="[]",
        )
    )
    db.add(
        AITurnTelemetry(
            user_id=1,
            specialist_id="sleep_expert",
            intent_category="log_sleep",
            first_token_latency_ms=2300.0,
            total_latency_ms=3100.0,
            utility_calls=1,
            reasoning_calls=1,
            deep_calls=0,
            utility_tokens_in=200,
            utility_tokens_out=70,
            reasoning_tokens_in=800,
            reasoning_tokens_out=350,
            failure_count=1,
            failures_json='[{"operation":"intent_classification","usage_type":"utility","error":"timeout"}]',
        )
    )
    db.commit()

    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    dashboard_summary = summarize_request_group(db, "dashboard", since)
    ai_summary = summarize_ai_turns(db, since)

    assert dashboard_summary["count"] == 2
    assert dashboard_summary["p95_ms"] >= dashboard_summary["p50_ms"]
    assert dashboard_summary["db_query_count_avg"] == 5.0
    assert ai_summary["count"] == 2
    assert ai_summary["first_token_p95_ms"] >= 1800.0
    assert ai_summary["failures_total"] == 1
