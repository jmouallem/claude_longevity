from __future__ import annotations

import sys
import uuid
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402
from tools import tool_registry  # noqa: E402
from tools.base import ToolContext  # noqa: E402


def _register_and_configure_user(client: TestClient, *, timezone_name: str = "America/Edmonton") -> None:
    username = f"sync_{uuid.uuid4().hex[:8]}"
    password = "Sync!Pass123"

    register = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": "Sync User"},
    )
    assert register.status_code == 201

    set_key = client.put(
        "/api/settings/api-key",
        json={
            "ai_provider": "openai",
            "api_key": "sk-test-dummy-key",
            "reasoning_model": "gpt-4o",
            "utility_model": "gpt-4o-mini",
            "deep_thinking_model": "gpt-4.1",
        },
    )
    assert set_key.status_code == 200

    profile = client.put(
        "/api/settings/profile",
        json={
            "timezone": timezone_name,
            "medications": '[{"name":"Candesartan","dose":"4mg","timing":"morning"}]',
            "supplements": '[{"name":"Omega 3","dose":"1000mg","timing":"with lunch"}]',
        },
    )
    assert profile.status_code == 200


def test_chat_logged_items_sync_to_dashboard_and_plan(monkeypatch):
    client = TestClient(app)
    _register_and_configure_user(client, timezone_name="America/Edmonton")

    import api.chat as chat_api

    async def _fake_process_chat(db, user, message, image_bytes, verbosity=None):
        _ = image_bytes
        _ = verbosity
        assert "sync-daily" in message
        reference = datetime.now(timezone.utc)
        ctx = ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference)
        tool_registry.execute(
            "food_log_write",
            {
                "meal_label": "breakfast",
                "items": [{"name": "coffee with cream"}],
                "calories": 70,
                "protein_g": 2,
                "carbs_g": 5,
                "fat_g": 7,
                "fiber_g": 0,
                "sodium_mg": 15,
                "logged_at": "08:00",
            },
            ctx,
        )
        tool_registry.execute(
            "hydration_log_write",
            {"amount_ml": 500, "source": "water", "logged_at": "08:10"},
            ctx,
        )
        tool_registry.execute(
            "checklist_mark_taken",
            {"item_type": "medication", "names": ["Candesartan"], "completed": True},
            ctx,
        )
        db.commit()
        yield {"type": "content", "text": "Logged today's breakfast, hydration, and medication."}
        yield {"type": "done", "text": ""}

    monkeypatch.setattr(chat_api, "process_chat", _fake_process_chat)

    chat = client.post("/api/chat", data={"message": "sync-daily"})
    assert chat.status_code == 200

    dashboard = client.get("/api/logs/dashboard")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert float(payload["daily_totals"]["food"]["calories"]) == 70.0
    assert int(payload["daily_totals"]["food"]["meal_count"]) == 1
    assert float(payload["daily_totals"]["hydration_ml"]) == 500.0

    meds = payload["checklist"]["medications"]
    candesartan = next((m for m in meds if str(m.get("name", "")).lower() == "candesartan"), None)
    assert candesartan is not None
    assert bool(candesartan.get("completed")) is True

    plan = client.get("/api/plan/snapshot?cycle_type=daily")
    assert plan.status_code == 200
    plan_payload = plan.json()
    meal_task = next((t for t in plan_payload["tasks"] if t.get("target_metric") == "meals_logged"), None)
    hydration_task = next((t for t in plan_payload["tasks"] if t.get("target_metric") == "hydration_ml"), None)
    assert meal_task is not None
    assert hydration_task is not None
    assert float(meal_task["progress_pct"]) > 0
    assert float(hydration_task["progress_pct"]) > 0


def test_chat_time_inference_respects_user_timezone_day_buckets(monkeypatch):
    client = TestClient(app)
    timezone_name = "America/Edmonton"
    user_tz = ZoneInfo(timezone_name)
    _register_and_configure_user(client, timezone_name=timezone_name)

    import api.chat as chat_api

    base_utc = datetime.combine(datetime.now(timezone.utc).date(), time(12, 0), tzinfo=timezone.utc)
    local_today = base_utc.astimezone(user_tz).date()
    local_yesterday = local_today - timedelta(days=1)

    async def _fake_process_chat(db, user, message, image_bytes, verbosity=None):
        _ = image_bytes
        _ = verbosity
        assert "sync-boundary" in message
        # At local ~05:00, "23:30" should resolve to the previous local day.
        ctx = ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=base_utc)
        tool_registry.execute(
            "food_log_write",
            {
                "meal_label": "late snack",
                "items": [{"name": "banana"}],
                "calories": 105,
                "protein_g": 1,
                "carbs_g": 27,
                "fat_g": 0,
                "fiber_g": 3,
                "sodium_mg": 1,
                "logged_at": "23:30",
            },
            ctx,
        )
        db.commit()
        yield {"type": "content", "text": "Logged late snack."}
        yield {"type": "done", "text": ""}

    monkeypatch.setattr(chat_api, "process_chat", _fake_process_chat)

    chat = client.post("/api/chat", data={"message": "sync-boundary"})
    assert chat.status_code == 200

    today_resp = client.get(f"/api/logs/dashboard?target_date={local_today.isoformat()}")
    assert today_resp.status_code == 200
    today_payload = today_resp.json()
    assert int(today_payload["daily_totals"]["food"]["meal_count"]) == 0

    yesterday_resp = client.get(f"/api/logs/dashboard?target_date={local_yesterday.isoformat()}")
    assert yesterday_resp.status_code == 200
    yesterday_payload = yesterday_resp.json()
    assert int(yesterday_payload["daily_totals"]["food"]["meal_count"]) == 1
    assert float(yesterday_payload["daily_totals"]["food"]["calories"]) == 105.0
