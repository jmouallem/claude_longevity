from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402


INTAKE_ANSWERS = {
    "age": "42",
    "sex": "male",
    "height_cm": "5 ft 10 in",
    "current_weight_kg": "180 lb",
    "goal_weight_kg": "170 lb",
    "timezone": "America/Edmonton",
    "fitness_level": "moderately active",
    "medical_conditions": "high blood pressure",
    "medications": "Candesartan 4mg morning",
    "supplements": "Omega 3 1000mg with lunch",
    "dietary_preferences": "no pork",
    "health_goals": "lower blood pressure, lose weight",
    "family_history": "heart disease",
}


def _complete_intake_flow(client: TestClient) -> dict:
    start = client.post("/api/intake/start", json={"restart": True})
    assert start.status_code == 200
    state = start.json()

    while not bool(state.get("ready_to_finish")):
        field_id = str(state.get("current_field_id") or "")
        answer = INTAKE_ANSWERS.get(field_id)
        if answer:
            resp = client.post("/api/intake/answer", json={"field_id": field_id, "answer": answer})
        else:
            resp = client.post("/api/intake/skip", json={"skip_all": False})
        assert resp.status_code == 200
        state = resp.json()
        if state.get("status") == "validation_error":
            raise AssertionError(f"Validation error for field {field_id}: {state.get('error')}")

    finish = client.post("/api/intake/finish", json={})
    assert finish.status_code == 200
    body = finish.json()
    assert body.get("status") == "completed"
    return body


def test_full_post_intake_onboarding_flow_with_guided_chat(monkeypatch):
    client = TestClient(app)

    username = f"onboard_{uuid.uuid4().hex[:8]}"
    password = "Onboard!Pass123"

    register = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": "Onboard User"},
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

    update_models = client.put(
        "/api/settings/models",
        json={
            "reasoning_model": "gpt-4o",
            "utility_model": "gpt-4o-mini",
            "deep_thinking_model": "gpt-4.1",
        },
    )
    assert update_models.status_code == 200

    prompt_status = client.get("/api/intake/prompt-status")
    assert prompt_status.status_code == 200
    prompt_body = prompt_status.json()
    assert bool(prompt_body.get("has_api_key")) is True
    assert bool(prompt_body.get("models_ready")) is True

    finish_body = _complete_intake_flow(client)
    next_step = finish_body.get("next_step") or {}
    assert next_step.get("route") == "/goals?onboarding=1"

    education = client.get("/api/plan/framework-education")
    assert education.status_code == 200
    grouped = (education.json() or {}).get("grouped") or {}
    assert "dietary" in grouped and "training" in grouped
    assert grouped["dietary"] and grouped["training"]

    selected_ids = [int(grouped["dietary"][0]["id"]), int(grouped["training"][0]["id"])]
    apply_selection = client.post("/api/plan/framework-selection", json={"selected_framework_ids": selected_ids})
    assert apply_selection.status_code == 200
    apply_body = apply_selection.json()
    assert apply_body.get("status") == "ok"
    assert int(apply_body.get("selected_count") or 0) == 2

    snapshot_resp = client.get("/api/plan/snapshot?cycle_type=daily")
    assert snapshot_resp.status_code == 200
    snapshot = snapshot_resp.json()
    assert snapshot.get("tasks")
    assert snapshot.get("upcoming_tasks")

    pending_task = next((t for t in snapshot["upcoming_tasks"] if t.get("status") == "pending"), None)
    assert pending_task is not None

    complete = client.post(f"/api/plan/tasks/{pending_task['id']}/status", json={"status": "completed"})
    assert complete.status_code == 200
    assert complete.json().get("task_status") == "completed"

    refreshed = client.get("/api/plan/snapshot?cycle_type=daily")
    assert refreshed.status_code == 200
    refreshed_task = next((t for t in refreshed.json()["tasks"] if int(t["id"]) == int(pending_task["id"])), None)
    assert refreshed_task is not None
    assert refreshed_task.get("status") == "completed"

    import api.chat as chat_api

    async def _fake_process_chat(_db, _user, _message, _image_bytes, _verbosity=None):
        yield {"type": "content", "text": "We will start with your next goal now."}
        yield {"type": "done", "text": ""}

    monkeypatch.setattr(chat_api, "process_chat", _fake_process_chat)

    chat = client.post("/api/chat", data={"message": "Let's begin"})
    assert chat.status_code == 200
    assert "text/event-stream" in (chat.headers.get("content-type") or "")
    assert "next goal" in chat.text.lower()

    history = client.get("/api/chat/history")
    assert history.status_code == 200
    assert isinstance(history.json(), list)
