from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import Base  # noqa: E402
from db.models import CoachingPlanAdjustment, CoachingPlanTask, HealthOptimizationFramework, SleepLog, User, UserSettings  # noqa: E402
from services.coaching_plan_service import (  # noqa: E402
    apply_framework_selection,
    get_daily_rolling_snapshot,
    get_plan_snapshot,
    refresh_task_statuses,
    set_task_status,
    undo_adjustment,
)
from tools import tool_registry  # noqa: E402
from tools.base import ToolContext  # noqa: E402


def _new_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _new_user(db, username: str = "plan_tester") -> User:
    user = User(
        username=username,
        username_normalized=username.lower(),
        password_hash="hash",
        display_name="Plan Tester",
    )
    user.settings = UserSettings(
        ai_provider="openai",
        reasoning_model="gpt-4o",
        utility_model="gpt-4o-mini",
        deep_thinking_model="gpt-4.1",
        timezone="UTC",
        plan_visibility_mode="top3",
        plan_max_visible_tasks=3,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_plan_snapshot_auto_seeds_tasks_and_defaults():
    db = _new_db()
    user = _new_user(db, "plan_seed_user")

    snapshot = get_plan_snapshot(db, user, cycle_type="daily")
    db.commit()

    assert snapshot["cycle"]["cycle_type"] == "daily"
    assert len(snapshot["tasks"]) >= 4
    assert snapshot["preferences"]["visibility_mode"] == "top3"
    assert len(snapshot["upcoming_tasks"]) <= 3


def test_task_status_update_roundtrip():
    db = _new_db()
    user = _new_user(db, "plan_task_user")
    snapshot = get_plan_snapshot(db, user, cycle_type="daily")
    db.commit()
    pending = [row for row in snapshot["tasks"] if row["status"] == "pending"]
    assert pending, "expected at least one pending task"

    task_id = int(pending[0]["id"])
    set_task_status(db, user, task_id=task_id, status="completed")
    db.commit()

    row = db.query(CoachingPlanTask).filter(CoachingPlanTask.id == task_id).first()
    assert row is not None
    assert row.status == "completed"
    assert row.completed_at is not None


def test_undo_adjustment_restores_targets():
    db = _new_db()
    user = _new_user(db, "plan_undo_user")
    snapshot = get_plan_snapshot(db, user, cycle_type="daily")
    db.commit()

    task = db.query(CoachingPlanTask).filter(CoachingPlanTask.user_id == user.id).first()
    assert task is not None
    task.target_value = 55.0
    db.flush()

    change_payload = {
        "changes": [
            {
                "task_id": int(task.id),
                "old_target_value": 40.0,
                "new_target_value": 55.0,
            }
        ]
    }
    adj = CoachingPlanAdjustment(
        user_id=user.id,
        cycle_anchor=snapshot["cycle"]["end"],
        title="Test adjustment",
        rationale="test",
        change_json=json.dumps(change_payload),
        status="applied",
        applied_at=datetime.now(timezone.utc),
        undo_expires_at=datetime.now(timezone.utc) + timedelta(days=29),
        source="plan_engine_weekly",
    )
    db.add(adj)
    db.commit()
    db.refresh(adj)

    undo_adjustment(db, user, adjustment_id=int(adj.id))
    db.commit()

    db.refresh(task)
    db.refresh(adj)
    assert task.target_value == 40.0
    assert adj.status == "undone"
    assert adj.undone_at is not None


def test_framework_selection_updates_active_flags_and_plan_tasks():
    db = _new_db()
    user = _new_user(db, "plan_framework_user")
    get_plan_snapshot(db, user, cycle_type="daily")
    db.commit()

    frameworks = (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user.id, HealthOptimizationFramework.framework_type == "dietary")
        .order_by(HealthOptimizationFramework.id.asc())
        .all()
    )
    assert len(frameworks) >= 2
    selected_id = int(frameworks[1].id)

    result = apply_framework_selection(db, user, selected_framework_ids=[selected_id])
    db.commit()

    assert result["selected_count"] == 1
    assert result["changed"] >= 1
    selected_row = db.query(HealthOptimizationFramework).filter(HealthOptimizationFramework.id == selected_id).first()
    assert selected_row is not None
    assert bool(selected_row.is_active) is True

    snapshot = get_plan_snapshot(db, user, cycle_type="daily")
    db.commit()
    framework_tasks = [row for row in snapshot["tasks"] if row["domain"] == "framework"]
    assert framework_tasks
    assert all("Follow " in row["title"] for row in framework_tasks)


def test_repeated_rolling_snapshots_do_not_leave_future_days_missed():
    db = _new_db()
    user = _new_user(db, "plan_rolling_missed_guard")

    first = get_daily_rolling_snapshot(db, user, days=5)
    db.commit()
    second = get_daily_rolling_snapshot(db, user, days=5)
    db.commit()

    for payload in (first, second):
        days = payload.get("days", [])
        assert days, "expected rolling day snapshots"
        for day_snapshot in days:
            statuses = [str(task.get("status", "")) for task in day_snapshot.get("tasks", [])]
            assert all(status != "missed" for status in statuses), (
                f"unexpected missed status in rolling preview for {day_snapshot.get('cycle', {}).get('today')}"
            )


def test_sleep_window_task_completes_when_start_and_end_logged_together():
    db = _new_db()
    user = _new_user(db, "plan_sleep_pair_user")

    reference = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    get_plan_snapshot(db, user, cycle_type="daily", reference_day=reference.date())
    db.commit()

    ctx = ToolContext(
        db=db,
        user=user,
        specialist_id="sleep_expert",
        reference_utc=reference,
    )
    out = tool_registry.execute(
        "sleep_log_write",
        {
            "action": "auto",
            "sleep_start": "10:30 pm",
            "sleep_end": "6:00 am",
        },
        ctx,
    )
    assert int(out.get("duration_minutes") or 0) >= 450

    refresh_task_statuses(db, user, reference_day=reference.date(), create_notifications=False)
    db.commit()

    task = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_start == reference.date().isoformat(),
            CoachingPlanTask.target_metric == "sleep_minutes",
        )
        .first()
    )
    assert task is not None
    assert task.status == "completed"
    assert float(task.progress_pct or 0.0) >= 100.0


def test_sleep_window_task_completes_when_action_is_start_but_interval_present():
    db = _new_db()
    user = _new_user(db, "plan_sleep_start_with_interval_user")

    reference = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    get_plan_snapshot(db, user, cycle_type="daily", reference_day=reference.date())
    db.commit()

    ctx = ToolContext(
        db=db,
        user=user,
        specialist_id="sleep_expert",
        reference_utc=reference,
    )
    out = tool_registry.execute(
        "sleep_log_write",
        {
            "action": "start",
            "sleep_start": "10:30 pm",
            "sleep_end": "6:00 am",
        },
        ctx,
    )
    assert int(out.get("duration_minutes") or 0) >= 450

    refresh_task_statuses(db, user, reference_day=reference.date(), create_notifications=False)
    db.commit()

    task = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_start == reference.date().isoformat(),
            CoachingPlanTask.target_metric == "sleep_minutes",
        )
        .first()
    )
    assert task is not None
    assert task.status == "completed"
    assert float(task.progress_pct or 0.0) >= 100.0


def test_daily_sleep_progress_uses_best_session_not_average():
    db = _new_db()
    user = _new_user(db, "plan_sleep_best_session_user")

    reference = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    get_plan_snapshot(db, user, cycle_type="daily", reference_day=reference.date())
    db.commit()

    db.add(
        SleepLog(
            user_id=user.id,
            sleep_start=datetime(2026, 2, 23, 0, 0, tzinfo=timezone.utc),
            sleep_end=datetime(2026, 2, 23, 7, 30, tzinfo=timezone.utc),
            duration_minutes=450,
        )
    )
    # Duplicate/partial row should not drag daily completion below target.
    db.add(
        SleepLog(
            user_id=user.id,
            sleep_start=datetime(2026, 2, 23, 6, 0, tzinfo=timezone.utc),
            sleep_end=datetime(2026, 2, 23, 6, 5, tzinfo=timezone.utc),
            duration_minutes=5,
        )
    )
    db.commit()

    refresh_task_statuses(db, user, reference_day=reference.date(), create_notifications=False)
    db.commit()

    task = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_start == reference.date().isoformat(),
            CoachingPlanTask.target_metric == "sleep_minutes",
        )
        .first()
    )
    assert task is not None
    assert task.status == "completed"
    assert float(task.progress_pct or 0.0) >= 100.0


def test_daily_sleep_target_is_normalized_to_7_hours():
    db = _new_db()
    user = _new_user(db, "plan_sleep_target_normalize_user")

    reference = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    get_plan_snapshot(db, user, cycle_type="daily", reference_day=reference.date())
    db.commit()

    task = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_start == reference.date().isoformat(),
            CoachingPlanTask.target_metric == "sleep_minutes",
        )
        .first()
    )
    assert task is not None
    task.target_value = 7.7  # Simulate drift from auto-adjustment

    db.add(
        SleepLog(
            user_id=user.id,
            sleep_start=datetime(2026, 2, 23, 0, 0, tzinfo=timezone.utc),
            sleep_end=datetime(2026, 2, 23, 7, 30, tzinfo=timezone.utc),
            duration_minutes=450,
        )
    )
    db.commit()

    refresh_task_statuses(db, user, reference_day=reference.date(), create_notifications=False)
    db.commit()
    db.refresh(task)

    assert float(task.target_value or 0.0) == 7.0
    assert task.status == "completed"
