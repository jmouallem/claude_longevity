from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import settings
from db.models import PasskeyChallenge, PasskeyCredential, User


def _utcnow() -> datetime:
    # Use naive UTC to match existing SQLite datetime usage across the app.
    return datetime.utcnow()


def _ensure_enabled() -> None:
    if not settings.ENABLE_PASSKEY_AUTH:
        raise HTTPException(status_code=404, detail="Passkey authentication is disabled")


def passkey_server_available() -> bool:
    if not settings.ENABLE_PASSKEY_AUTH:
        return False
    try:
        _load_webauthn()
        return True
    except HTTPException:
        return False


def _load_webauthn():
    try:
        from webauthn import (
            generate_authentication_options,
            generate_registration_options,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers import options_to_json
        from webauthn.helpers.structs import (
            AttestationConveyancePreference,
            AuthenticatorSelectionCriteria,
            AuthenticatorTransport,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        raise HTTPException(
            status_code=500,
            detail="Passkey support is unavailable on server (missing webauthn dependency)",
        ) from exc

    return {
        "generate_authentication_options": generate_authentication_options,
        "generate_registration_options": generate_registration_options,
        "verify_authentication_response": verify_authentication_response,
        "verify_registration_response": verify_registration_response,
        "options_to_json": options_to_json,
        "AttestationConveyancePreference": AttestationConveyancePreference,
        "AuthenticatorSelectionCriteria": AuthenticatorSelectionCriteria,
        "AuthenticatorTransport": AuthenticatorTransport,
        "PublicKeyCredentialDescriptor": PublicKeyCredentialDescriptor,
        "ResidentKeyRequirement": ResidentKeyRequirement,
        "UserVerificationRequirement": UserVerificationRequirement,
    }


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    txt = (value or "").strip()
    if not txt:
        return b""
    pad = "=" * ((4 - len(txt) % 4) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def _normalize_transports(values: Any) -> list[str]:
    allowed = {"usb", "nfc", "ble", "smart-card", "internal", "cable", "hybrid"}
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        name = str(value).strip().lower()
        if name in allowed and name not in out:
            out.append(name)
    return out


def _cleanup_expired_challenges(db: Session) -> None:
    now = _utcnow()
    (
        db.query(PasskeyChallenge)
        .filter(
            (PasskeyChallenge.expires_at < now)
            | (PasskeyChallenge.is_used.is_(True) & (PasskeyChallenge.created_at < now - timedelta(days=1)))
        )
        .delete(synchronize_session=False)
    )


def _create_challenge(
    db: Session,
    *,
    purpose: str,
    user_id: int | None = None,
    username_normalized: str | None = None,
) -> PasskeyChallenge:
    _cleanup_expired_challenges(db)
    challenge_bytes = os.urandom(32)
    row = PasskeyChallenge(
        user_id=user_id,
        username_normalized=username_normalized,
        purpose=purpose,
        challenge=_b64url_encode(challenge_bytes),
        expires_at=_utcnow() + timedelta(seconds=max(30, settings.PASSKEY_CHALLENGE_TTL_SECONDS)),
        is_used=False,
    )
    db.add(row)
    db.flush()
    return row


def _load_active_challenge(
    db: Session,
    *,
    request_id: int,
    purpose: str,
) -> PasskeyChallenge:
    row = db.query(PasskeyChallenge).filter(PasskeyChallenge.id == request_id, PasskeyChallenge.purpose == purpose).first()
    if not row:
        raise HTTPException(status_code=400, detail="Passkey request not found")
    if row.is_used:
        raise HTTPException(status_code=400, detail="Passkey request already used")
    if row.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="Passkey request expired")
    return row


def _descriptor_from_credential(webauthn: dict[str, Any], cred: PasskeyCredential):
    descriptor_cls = webauthn["PublicKeyCredentialDescriptor"]
    transport_enum = webauthn["AuthenticatorTransport"]
    transports_raw = _normalize_transports(json.loads(cred.transports) if cred.transports else [])
    transports = []
    for value in transports_raw:
        try:
            transports.append(transport_enum(value))
        except Exception:
            continue
    return descriptor_cls(
        id=_b64url_decode(cred.credential_id),
        transports=transports or None,
    )


def begin_passkey_registration(
    db: Session,
    user: User,
) -> dict[str, Any]:
    _ensure_enabled()
    webauthn = _load_webauthn()
    if (user.role or "").lower() == "admin":
        raise HTTPException(status_code=403, detail="Passkeys are only available for user accounts")

    challenge = _create_challenge(db, purpose="registration", user_id=user.id, username_normalized=user.username_normalized)
    existing = db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user.id).order_by(PasskeyCredential.id.asc()).all()
    exclude = [_descriptor_from_credential(webauthn, row) for row in existing]

    options = webauthn["generate_registration_options"](
        rp_id=settings.PASSKEY_RP_ID,
        rp_name=settings.PASSKEY_RP_NAME,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.username,
        user_display_name=user.display_name,
        challenge=_b64url_decode(challenge.challenge),
        timeout=60000,
        attestation=webauthn["AttestationConveyancePreference"].NONE,
        authenticator_selection=webauthn["AuthenticatorSelectionCriteria"](
            resident_key=webauthn["ResidentKeyRequirement"].PREFERRED,
            user_verification=webauthn["UserVerificationRequirement"].REQUIRED,
        ),
        exclude_credentials=exclude or None,
    )
    return {
        "request_id": challenge.id,
        "public_key": json.loads(webauthn["options_to_json"](options)),
    }


def verify_passkey_registration(
    db: Session,
    user: User,
    *,
    request_id: int,
    credential: dict[str, Any],
    label: str | None = None,
) -> dict[str, Any]:
    _ensure_enabled()
    webauthn = _load_webauthn()
    if (user.role or "").lower() == "admin":
        raise HTTPException(status_code=403, detail="Passkeys are only available for user accounts")
    challenge = _load_active_challenge(db, request_id=request_id, purpose="registration")
    if challenge.user_id != user.id:
        raise HTTPException(status_code=403, detail="Passkey request does not match current user")

    verified = webauthn["verify_registration_response"](
        credential=credential,
        expected_challenge=_b64url_decode(challenge.challenge),
        expected_rp_id=settings.PASSKEY_RP_ID,
        expected_origin=settings.PASSKEY_ALLOWED_ORIGINS,
        require_user_verification=True,
    )

    credential_id = _b64url_encode(verified.credential_id)
    public_key = _b64url_encode(verified.credential_public_key)
    transports = _normalize_transports((credential.get("response") or {}).get("transports"))
    row = db.query(PasskeyCredential).filter(PasskeyCredential.credential_id == credential_id).first()
    if row and row.user_id != user.id:
        raise HTTPException(status_code=409, detail="Credential is already registered to another account")
    if not row:
        row = PasskeyCredential(user_id=user.id, credential_id=credential_id, public_key=public_key)
        db.add(row)

    row.public_key = public_key
    row.sign_count = int(getattr(verified, "sign_count", 0) or 0)
    row.aaguid = str(getattr(verified, "aaguid", "") or "")
    device_type = getattr(getattr(verified, "credential_device_type", None), "value", None)
    row.device_type = str(device_type or "")
    row.backed_up = bool(getattr(verified, "credential_backed_up", False))
    row.transports = json.dumps(transports, ensure_ascii=True) if transports else None
    clean_label = " ".join((label or "").strip().split())
    if clean_label:
        row.label = clean_label
    elif not row.label:
        row.label = f"Device {row.id or ''}".strip()
    row.last_used_at = _utcnow()

    challenge.is_used = True
    db.flush()
    return serialize_passkey_credential(row)


def begin_passkey_authentication(
    db: Session,
    *,
    username_normalized: str | None = None,
) -> dict[str, Any]:
    _ensure_enabled()
    webauthn = _load_webauthn()

    user: User | None = None
    allow_credentials = None
    if username_normalized:
        user = db.query(User).filter(User.username_normalized == username_normalized).first()
        if not user or (user.role or "").lower() == "admin":
            raise HTTPException(status_code=404, detail="No passkeys available for this account")
        creds = db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user.id).order_by(PasskeyCredential.id.asc()).all()
        if not creds:
            raise HTTPException(status_code=404, detail="No passkeys registered for this account")
        allow_credentials = [_descriptor_from_credential(webauthn, row) for row in creds]

    challenge = _create_challenge(
        db,
        purpose="authentication",
        user_id=user.id if user else None,
        username_normalized=username_normalized,
    )
    options = webauthn["generate_authentication_options"](
        rp_id=settings.PASSKEY_RP_ID,
        challenge=_b64url_decode(challenge.challenge),
        timeout=60000,
        allow_credentials=allow_credentials,
        user_verification=webauthn["UserVerificationRequirement"].REQUIRED,
    )
    return {
        "request_id": challenge.id,
        "public_key": json.loads(webauthn["options_to_json"](options)),
    }


def verify_passkey_authentication(
    db: Session,
    *,
    request_id: int,
    credential: dict[str, Any],
) -> tuple[User, PasskeyCredential]:
    _ensure_enabled()
    webauthn = _load_webauthn()
    challenge = _load_active_challenge(db, request_id=request_id, purpose="authentication")
    credential_id = str(credential.get("id", "")).strip()
    if not credential_id:
        raise HTTPException(status_code=400, detail="Credential id is required")

    row = db.query(PasskeyCredential).filter(PasskeyCredential.credential_id == credential_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Passkey credential not found")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (user.role or "").lower() == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot sign in with passkeys")
    if challenge.user_id is not None and challenge.user_id != user.id:
        raise HTTPException(status_code=403, detail="Passkey request does not match credential owner")
    if challenge.username_normalized and challenge.username_normalized != user.username_normalized:
        raise HTTPException(status_code=403, detail="Passkey request username mismatch")

    verified = webauthn["verify_authentication_response"](
        credential=credential,
        expected_challenge=_b64url_decode(challenge.challenge),
        expected_rp_id=settings.PASSKEY_RP_ID,
        expected_origin=settings.PASSKEY_ALLOWED_ORIGINS,
        credential_public_key=_b64url_decode(row.public_key),
        credential_current_sign_count=int(row.sign_count or 0),
        require_user_verification=True,
    )
    row.sign_count = int(getattr(verified, "new_sign_count", row.sign_count or 0) or 0)
    row.last_used_at = _utcnow()
    device_type = getattr(getattr(verified, "credential_device_type", None), "value", None)
    if device_type:
        row.device_type = str(device_type)
    row.backed_up = bool(getattr(verified, "credential_backed_up", row.backed_up))
    challenge.is_used = True
    db.flush()
    return user, row


def serialize_passkey_credential(row: PasskeyCredential) -> dict[str, Any]:
    transports = []
    if row.transports:
        try:
            parsed = json.loads(row.transports)
            transports = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            transports = []
    return {
        "id": row.id,
        "label": row.label or "",
        "credential_id": row.credential_id,
        "device_type": row.device_type,
        "backed_up": bool(row.backed_up),
        "transports": transports,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


def list_passkeys_for_user(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.user_id == user_id)
        .order_by(PasskeyCredential.created_at.desc(), PasskeyCredential.id.desc())
        .all()
    )
    return [serialize_passkey_credential(row) for row in rows]


def delete_passkey_for_user(db: Session, user_id: int, passkey_id: int) -> None:
    row = db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user_id, PasskeyCredential.id == passkey_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Passkey not found")
    db.delete(row)
    db.flush()


def clear_passkeys_for_user(db: Session, user_id: int) -> int:
    count = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.user_id == user_id)
        .count()
    )
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user_id).delete(synchronize_session=False)
    db.flush()
    return int(count)
