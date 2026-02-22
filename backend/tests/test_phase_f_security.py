from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from utils.image_utils import validate_image_payload  # noqa: E402


def test_validate_image_payload_accepts_png_signature():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    mime, ext = validate_image_payload(png_bytes, content_type="image/png")
    assert mime == "image/png"
    assert ext == ".png"


def test_validate_image_payload_rejects_non_image_payload():
    with pytest.raises(ValueError):
        validate_image_payload(b"not-an-image", content_type="image/png")


def test_production_security_gate_rejects_default_secret_values():
    settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="change-me-in-production",
        ENCRYPTION_KEY="change-me-in-production-32bytes!",
        ADMIN_PASSWORD="L0ngevity!123",
        AUTH_COOKIE_SECURE=False,
    )
    with pytest.raises(RuntimeError):
        settings.validate_security_configuration()

