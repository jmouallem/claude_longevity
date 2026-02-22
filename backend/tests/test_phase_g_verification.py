from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402
from services.rate_limit_service import InMemoryRateLimiter  # noqa: E402
from utils.image_utils import validate_image_payload  # noqa: E402


def test_health_response_includes_security_headers():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=" in (response.headers.get("permissions-policy") or "")
    assert "default-src 'self'" in (response.headers.get("content-security-policy") or "")


def test_cookie_session_login_and_logout_flow():
    client = TestClient(app)
    username = f"phaseg_{uuid.uuid4().hex[:8]}"
    password = "PhaseG!Pass123"
    display_name = "Phase G User"

    register = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": display_name},
    )
    assert register.status_code == 201
    # Cookie is set for session-based auth.
    set_cookie = register.headers.get("set-cookie", "").lower()
    assert "longevity_session=" in set_cookie
    assert "httponly" in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == username

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    me_after_logout = client.get("/api/auth/me")
    assert me_after_logout.status_code == 401


def test_rate_limiter_blocks_after_limit():
    limiter = InMemoryRateLimiter()
    allowed_1, retry_1, _remaining_1 = limiter.check(key="test-key", limit=2, window_seconds=60)
    allowed_2, retry_2, _remaining_2 = limiter.check(key="test-key", limit=2, window_seconds=60)
    allowed_3, retry_3, _remaining_3 = limiter.check(key="test-key", limit=2, window_seconds=60)

    assert allowed_1 is True and retry_1 == 0
    assert allowed_2 is True and retry_2 == 0
    assert allowed_3 is False and retry_3 >= 1


def test_image_payload_rejects_content_type_signature_mismatch():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with pytest.raises(ValueError) as excinfo:
        validate_image_payload(png_bytes, content_type="image/jpeg")
    assert "does not match" in str(excinfo.value)
