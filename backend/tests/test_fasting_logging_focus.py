from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.log_parser import _deterministic_fasting_parse  # noqa: E402
from db.database import SessionLocal  # noqa: E402
from db.models import FastingLog, User  # noqa: E402
from main import app  # noqa: E402
from tools import tool_registry  # noqa: E402
from tools.base import ToolContext  # noqa: E402


def _register_user(client: TestClient) -> str:
    username = f"fast_{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "Fast!Pass123", "display_name": "Fast User"},
    )
    assert resp.status_code == 201
    profile = client.put("/api/settings/profile", json={"timezone": "UTC"})
    assert profile.status_code == 200
    return username


def test_deterministic_fasting_parse_handles_last_meal_first_meal_window():
    parsed = _deterministic_fasting_parse("My last meal was 8:00pm and my first meal was 10:00am.")
    assert parsed["action"] == "end"
    assert str(parsed.get("fast_start", "")).lower().startswith("8:00")
    assert str(parsed.get("fast_end", "")).lower().startswith("10:00")


def test_fasting_manage_creates_closed_interval_when_no_active_fast():
    client = TestClient(app)
    username = _register_user(client)

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None
        ctx = ToolContext(
            db=db,
            user=user,
            specialist_id="orchestrator",
            reference_utc=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
        )
        out = tool_registry.execute(
            "fasting_manage",
            {
                "action": "end",
                "fast_start": "8:00pm",
                "fast_end": "10:00am",
                "notes": "intermittent fasting window",
            },
            ctx,
        )
        db.commit()

        assert out["status"] == "created"
        row = db.get(FastingLog, int(out["fasting_log_id"]))
        assert row is not None
        assert row.fast_end is not None
        assert int(row.duration_minutes or 0) == 840


def test_fasting_manage_end_with_interval_closes_and_rewrites_active_fast():
    client = TestClient(app)
    username = _register_user(client)

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None
        active = FastingLog(
            user_id=user.id,
            fast_start=datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
            fast_end=None,
            duration_minutes=None,
            fast_type=None,
            notes="stale open fast",
        )
        db.add(active)
        db.commit()
        db.refresh(active)

        ctx = ToolContext(
            db=db,
            user=user,
            specialist_id="orchestrator",
            reference_utc=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
        )
        out = tool_registry.execute(
            "fasting_manage",
            {
                "action": "end",
                "fast_start": "8:00pm",
                "fast_end": "10:00am",
            },
            ctx,
        )
        db.commit()
        db.refresh(active)

        assert out["status"] == "ended"
        assert int(out["fasting_log_id"]) == active.id
        assert active.fast_end is not None
        assert int(active.duration_minutes or 0) == 840

