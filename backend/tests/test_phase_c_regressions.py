from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.analysis import list_proposals  # noqa: E402
from db.database import Base  # noqa: E402
from db.models import AnalysisProposal, AnalysisRun, SleepLog, User, UserSettings  # noqa: E402
from ai.log_parser import _deterministic_sleep_parse  # noqa: E402
from services.analysis_service import run_longitudinal_analysis  # noqa: E402
from utils.datetime_utils import end_of_day, sleep_log_overlaps_window, start_of_day  # noqa: E402


def _new_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _new_user(db, username: str = "tester") -> User:
    user = User(
        username=username,
        username_normalized=username.lower(),
        password_hash="hash",
        display_name="Tester",
    )
    user.settings = UserSettings(
        ai_provider="openai",
        reasoning_model="gpt-4o",
        utility_model="gpt-4o",
        deep_thinking_model="gpt-4o",
        timezone="UTC",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_analysis_window_is_single_row_without_force():
    db = _new_db()
    user = _new_user(db, "analysis_u")

    run1 = asyncio.run(
        run_longitudinal_analysis(
            db=db,
            user=user,
            run_type="daily",
            target_date=date(2026, 2, 21),
            trigger="test",
            force=False,
        )
    )
    run2 = asyncio.run(
        run_longitudinal_analysis(
            db=db,
            user=user,
            run_type="daily",
            target_date=date(2026, 2, 21),
            trigger="test",
            force=False,
        )
    )

    assert run1.id == run2.id
    count = (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.user_id == user.id,
            AnalysisRun.run_type == "daily",
            AnalysisRun.period_start == "2026-02-21",
            AnalysisRun.period_end == "2026-02-21",
        )
        .count()
    )
    assert count == 1


def test_proposals_get_is_read_only_no_auto_merge():
    db = _new_db()
    user = _new_user(db, "proposal_u")

    run = AnalysisRun(
        user_id=user.id,
        run_type="daily",
        period_start="2026-02-21",
        period_end="2026-02-21",
        status="completed",
        summary_markdown="ok",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    p1 = AnalysisProposal(
        user_id=user.id,
        analysis_run_id=run.id,
        proposal_kind="prompt_adjustment",
        status="pending",
        title="Add daily quick log prompt",
        rationale="Improve adherence",
        requires_approval=True,
        proposal_json="{}",
    )
    p2 = AnalysisProposal(
        user_id=user.id,
        analysis_run_id=run.id,
        proposal_kind="prompt_adjustment",
        status="pending",
        title="Add daily quick logging prompt",
        rationale="Improve adherence",
        requires_approval=True,
        proposal_json="{}",
    )
    db.add(p1)
    db.add(p2)
    db.commit()

    before_ids = sorted(r.id for r in db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id).all())
    rows = list_proposals(status=None, run_id=None, limit=50, user=user, db=db)
    after_ids = sorted(r.id for r in db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id).all())

    assert len(rows) == 2
    assert before_ids == after_ids


def test_sleep_window_uses_event_overlap_not_created_at_only():
    db = _new_db()
    user = _new_user(db, "sleep_u")

    # Overnight sleep crossing into target day should count.
    db.add(
        SleepLog(
            user_id=user.id,
            sleep_start=datetime(2026, 2, 20, 23, 0, tzinfo=timezone.utc),
            sleep_end=datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc),
            duration_minutes=420,
            created_at=datetime(2026, 2, 20, 23, 0, tzinfo=timezone.utc),
        )
    )
    # Outside day window should not count.
    db.add(
        SleepLog(
            user_id=user.id,
            sleep_start=datetime(2026, 2, 18, 23, 0, tzinfo=timezone.utc),
            sleep_end=datetime(2026, 2, 19, 6, 0, tzinfo=timezone.utc),
            duration_minutes=420,
            created_at=datetime(2026, 2, 18, 23, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()

    day = date(2026, 2, 21)
    start = start_of_day(day, "UTC")
    end = end_of_day(day, "UTC")
    rows = (
        db.query(SleepLog)
        .filter(
            SleepLog.user_id == user.id,
            sleep_log_overlaps_window(SleepLog, start, end),
        )
        .all()
    )

    assert len(rows) == 1
    assert rows[0].duration_minutes == 420


def test_deterministic_sleep_parse_extracts_start_end_and_duration():
    payload = _deterministic_sleep_parse("I went to bed at 10:30pm and woke up at 6:00 am")
    assert payload["action"] == "end"
    assert str(payload.get("sleep_start") or "").lower().startswith("10:30")
    assert str(payload.get("sleep_end") or "").lower().startswith("6:00")
    assert int(payload.get("duration_minutes") or 0) >= 450
