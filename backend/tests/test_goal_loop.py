"""Tests for the intake -> goals -> plan tasks -> goal progress loop."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import Base  # noqa: E402
from db.models import (  # noqa: E402
    CoachingPlanTask,
    ExerciseLog,
    SleepLog,
    User,
    UserGoal,
    UserSettings,
    VitalsLog,
)
from services.coaching_plan_service import (  # noqa: E402
    ensure_plan_seeded,
    link_tasks_to_goals,
    refresh_task_statuses,
    _refresh_goal_progress,
    CycleWindow,
)
from services.intake_service import create_goals_from_intake  # noqa: E402


def _new_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _new_user(db, username="loop_tester", weight_kg=90.0, goal_weight_kg=80.0) -> User:
    user = User(
        username=username,
        username_normalized=username.lower(),
        password_hash="hash",
        display_name="Loop Tester",
    )
    user.settings = UserSettings(
        ai_provider="openai",
        reasoning_model="gpt-4o",
        utility_model="gpt-4o-mini",
        deep_thinking_model="gpt-4.1",
        timezone="UTC",
        current_weight_kg=weight_kg,
        goal_weight_kg=goal_weight_kg,
        plan_visibility_mode="top3",
        plan_max_visible_tasks=3,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ─── Intake → Goals ───


def test_create_goals_from_intake_heuristic_mapping():
    db = _new_db()
    user = _new_user(db)
    goals = create_goals_from_intake(
        db, user.id,
        ["lose weight", "sleep better", "lower blood pressure"],
        user.settings,
    )
    db.commit()

    assert len(goals) == 3
    types = {g.goal_type for g in goals}
    assert "weight_loss" in types
    assert "sleep" in types
    assert "cardiovascular" in types
    assert all(g.created_by == "intake" for g in goals)


def test_create_goals_weight_loss_prefill():
    db = _new_db()
    user = _new_user(db, weight_kg=95.0, goal_weight_kg=82.0)
    goals = create_goals_from_intake(db, user.id, ["lose weight"], user.settings)
    db.commit()

    wl = [g for g in goals if g.goal_type == "weight_loss"][0]
    assert wl.baseline_value == 95.0
    assert wl.target_value == 82.0
    assert wl.current_value == 95.0
    assert wl.target_unit == "kg"


def test_create_goals_deduplication():
    db = _new_db()
    user = _new_user(db)
    first = create_goals_from_intake(db, user.id, ["lose weight"], user.settings)
    db.commit()
    assert len(first) == 1

    second = create_goals_from_intake(db, user.id, ["lose weight"], user.settings)
    db.commit()
    assert len(second) == 0

    all_goals = db.query(UserGoal).filter(UserGoal.user_id == user.id).all()
    assert len(all_goals) == 1


def test_create_goals_custom_fallback():
    db = _new_db()
    user = _new_user(db)
    goals = create_goals_from_intake(db, user.id, ["something unique and unusual"], user.settings)
    db.commit()

    assert len(goals) == 1
    assert goals[0].goal_type == "custom"
    assert goals[0].priority == 3


def test_create_goals_cap_at_five():
    db = _new_db()
    user = _new_user(db)
    many = [f"goal number {i}" for i in range(10)]
    goals = create_goals_from_intake(db, user.id, many, user.settings)
    db.commit()
    assert len(goals) == 5


# ─── Goals → Task Linking ───


def test_link_tasks_to_goals():
    db = _new_db()
    user = _new_user(db)

    # Create a weight_loss goal
    goal = UserGoal(
        user_id=user.id, title="Lose weight", goal_type="weight_loss",
        status="active", priority=1, created_by="intake",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    # Seed plan tasks
    result = ensure_plan_seeded(db, user)
    db.commit()
    assert result["created"] > 0

    # Check that some tasks got linked
    linked = (
        db.query(CoachingPlanTask)
        .filter(CoachingPlanTask.user_id == user.id, CoachingPlanTask.goal_id == goal.id)
        .all()
    )
    assert len(linked) > 0
    linked_metrics = {t.target_metric for t in linked}
    # weight_loss maps to meals_logged, food_log_days, exercise_minutes, exercise_sessions
    assert linked_metrics & {"meals_logged", "exercise_minutes"}


def test_backward_compat_null_goal_id():
    db = _new_db()
    user = _new_user(db)

    # Seed tasks with no goals — all goal_id should be None
    ensure_plan_seeded(db, user)
    db.commit()

    tasks = db.query(CoachingPlanTask).filter(CoachingPlanTask.user_id == user.id).all()
    assert len(tasks) > 0
    assert all(t.goal_id is None for t in tasks)


# ─── Task Completion → Goal Progress ───


def test_refresh_goal_progress_weight():
    db = _new_db()
    user = _new_user(db, weight_kg=90.0, goal_weight_kg=80.0)

    goal = UserGoal(
        user_id=user.id, title="Lose weight", goal_type="weight_loss",
        baseline_value=90.0, target_value=80.0, current_value=90.0,
        target_unit="kg", status="active", priority=1,
    )
    db.add(goal)
    db.commit()

    # Log a new weight
    now = datetime.now(timezone.utc)
    vitals = VitalsLog(user_id=user.id, weight_kg=87.5, logged_at=now)
    db.add(vitals)
    db.commit()

    updated = _refresh_goal_progress(db, user, now.date())
    db.commit()

    assert updated == 1
    db.refresh(goal)
    assert goal.current_value == 87.5


def test_refresh_goal_progress_sleep():
    db = _new_db()
    user = _new_user(db)

    goal = UserGoal(
        user_id=user.id, title="Improve sleep", goal_type="sleep",
        baseline_value=360.0, target_value=480.0, current_value=360.0,
        target_unit="minutes", status="active", priority=2,
    )
    db.add(goal)
    db.commit()

    now = datetime.now(timezone.utc)
    for i in range(3):
        log = SleepLog(
            user_id=user.id,
            duration_minutes=420,
            sleep_start=now - timedelta(days=i, hours=8),
            sleep_end=now - timedelta(days=i, hours=1),
        )
        db.add(log)
    db.commit()

    updated = _refresh_goal_progress(db, user, now.date())
    db.commit()

    assert updated == 1
    db.refresh(goal)
    assert goal.current_value == 420.0


def test_refresh_goal_progress_no_target_skipped():
    """Goals without target_value should not be updated."""
    db = _new_db()
    user = _new_user(db)

    goal = UserGoal(
        user_id=user.id, title="Eat better", goal_type="habit",
        status="active", priority=3,
    )
    db.add(goal)
    db.commit()

    now = datetime.now(timezone.utc)
    updated = _refresh_goal_progress(db, user, now.date())
    assert updated == 0
