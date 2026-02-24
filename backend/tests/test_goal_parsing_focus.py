from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from ai.orchestrator import _apply_goal_updates, _extract_json_payload  # noqa: E402
from db.database import SessionLocal  # noqa: E402
from db.models import User, UserGoal  # noqa: E402


class _FakeProvider:
    def __init__(self, content: str):
        self._content = content
        self.chat_calls = 0

    def get_utility_model(self) -> str:
        return "gpt-4o-mini"

    async def chat(self, *, messages, model, system, stream):  # noqa: ANN001
        _ = messages
        _ = model
        _ = system
        _ = stream
        self.chat_calls += 1
        return {"content": self._content, "tokens_in": 25, "tokens_out": 10}


def _create_test_user(db) -> User:
    suffix = uuid.uuid4().hex[:10]
    username = f"goal_parse_{suffix}"
    user = User(
        username=username,
        username_normalized=username.lower(),
        password_hash="x",
        display_name="Goal Parse Test",
    )
    db.add(user)
    db.flush()
    return user


def test_apply_goal_updates_creates_goals_from_user_goal_turn():
    db = SessionLocal()
    try:
        user = _create_test_user(db)
        provider = _FakeProvider(
            json.dumps(
                {
                    "action": "create",
                    "create_goals": [
                        {
                            "title": "Weight loss",
                            "goal_type": "weight_loss",
                            "target_value": 230,
                            "target_unit": "lb",
                            "baseline_value": 270,
                            "target_date": "2026-08-01",
                            "priority": 2,
                            "why": "Improve blood pressure",
                        }
                    ],
                    "update_goals": [],
                }
            )
        )
        summary = asyncio.run(
            _apply_goal_updates(
                db=db,
                provider=provider,
                user=user,
                message_text="Goal-setting kickoff: I want to lose weight by Aug 1.",
                reference_utc=datetime.now(timezone.utc),
            )
        )
        db.commit()

        assert summary["goal_context"] is True
        assert summary["attempted"] is True
        assert int(summary["created"]) == 1
        assert provider.chat_calls == 1

        row = db.query(UserGoal).filter(UserGoal.user_id == user.id, UserGoal.title == "Weight loss").first()
        assert row is not None
        assert row.goal_type == "weight_loss"
        assert float(row.target_value or 0) == 230.0
        assert row.target_unit == "lb"
        assert row.target_date == "2026-08-01"
    finally:
        db.close()


def test_apply_goal_updates_updates_existing_goal_by_title_match():
    db = SessionLocal()
    try:
        user = _create_test_user(db)
        existing = UserGoal(
            user_id=user.id,
            title="Exercise consistency",
            goal_type="fitness",
            target_value=3.0,
            target_unit="sessions/week",
            baseline_value=0.0,
            current_value=1.0,
            status="active",
            priority=3,
            created_by="coach",
        )
        db.add(existing)
        db.flush()

        provider = _FakeProvider(
            json.dumps(
                {
                    "action": "update",
                    "create_goals": [],
                    "update_goals": [
                        {
                            "title_match": "exercise consistency",
                            "target_value": 4,
                            "current_value": 2,
                            "priority": 1,
                            "why": "User confirmed 2 HIIT + 2 strength sessions",
                        }
                    ],
                }
            )
        )

        summary = asyncio.run(
            _apply_goal_updates(
                db=db,
                provider=provider,
                user=user,
                message_text="Goal-refinement kickoff: update my workout target to 4 sessions.",
                reference_utc=datetime.now(timezone.utc),
            )
        )
        db.commit()

        assert summary["goal_context"] is True
        assert summary["attempted"] is True
        assert int(summary["updated"]) == 1
        assert provider.chat_calls == 1

        db.refresh(existing)
        assert float(existing.target_value or 0) == 4.0
        assert float(existing.current_value or 0) == 2.0
        assert int(existing.priority or 0) == 1
    finally:
        db.close()


def test_apply_goal_updates_skips_non_goal_message_without_model_call():
    db = SessionLocal()
    try:
        user = _create_test_user(db)
        provider = _FakeProvider("{}")
        summary = asyncio.run(
            _apply_goal_updates(
                db=db,
                provider=provider,
                user=user,
                message_text="hello there",
                reference_utc=datetime.now(timezone.utc),
            )
        )

        assert summary["goal_context"] is False
        assert summary["attempted"] is False
        assert int(summary["created"]) == 0
        assert int(summary["updated"]) == 0
        assert provider.chat_calls == 0
    finally:
        db.close()


def test_apply_goal_updates_handles_invalid_json_without_creating_rows():
    db = SessionLocal()
    try:
        user = _create_test_user(db)
        provider = _FakeProvider("not-json")
        summary = asyncio.run(
            _apply_goal_updates(
                db=db,
                provider=provider,
                user=user,
                message_text="I want to refine my goals",
                reference_utc=datetime.now(timezone.utc),
            )
        )

        assert summary["goal_context"] is True
        assert summary["attempted"] is False
        assert int(summary["created"]) == 0
        assert int(summary["updated"]) == 0
        assert provider.chat_calls == 1

        count = db.query(UserGoal).filter(UserGoal.user_id == user.id).count()
        assert int(count) == 0
    finally:
        db.close()


def test_extract_json_payload_supports_markdown_code_fence():
    payload = _extract_json_payload('```json\n{"action":"create","create_goals":[],"update_goals":[]}\n```')
    assert payload.get("action") == "create"
