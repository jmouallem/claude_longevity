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
from db.models import CoachingPlanAdjustment, CoachingPlanTask, User, UserSettings  # noqa: E402
from services.coaching_plan_service import get_plan_snapshot, set_task_status, undo_adjustment  # noqa: E402


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
