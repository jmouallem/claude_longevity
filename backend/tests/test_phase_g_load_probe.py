from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.database import SessionLocal  # noqa: E402
from main import app  # noqa: E402
from services.telemetry_service import build_performance_snapshot  # noqa: E402


def _register_user_for_load_probe(client: TestClient) -> None:
    username = f"load_{uuid.uuid4().hex[:8]}"
    password = "Load!Pass123"

    register = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": "Load Probe"},
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


def test_phase_g_load_probe_populates_performance_snapshot(monkeypatch):
    client = TestClient(app)
    _register_user_for_load_probe(client)

    import api.chat as chat_api

    async def _fake_process_chat(_db, _user, _message, _image_bytes, _verbosity=None):
        yield {"type": "content", "text": "ok"}
        yield {"type": "done", "text": ""}

    monkeypatch.setattr(chat_api, "process_chat", _fake_process_chat)

    for _ in range(8):
        chat = client.post("/api/chat", data={"message": "load-probe"})
        assert chat.status_code == 200

    for _ in range(12):
        dashboard = client.get("/api/logs/dashboard")
        assert dashboard.status_code == 200

    db = SessionLocal()
    try:
        snapshot = build_performance_snapshot(db, since_hours=24)
    finally:
        db.close()

    groups = snapshot.get("request_groups") or {}
    assert "chat" in groups
    assert "dashboard" in groups
    assert int(groups["chat"]["count"]) >= 8
    assert int(groups["dashboard"]["count"]) >= 12
    assert float(groups["chat"]["p95_ms"]) >= 0.0
    assert float(groups["dashboard"]["p95_ms"]) >= 0.0

