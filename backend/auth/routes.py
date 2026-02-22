from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.models import (
    LoginRequest,
    PasskeyBeginRequest,
    PasskeyBeginResponse,
    PasskeyCredentialResponse,
    PasskeyRegisterOptionsRequest,
    PasskeyStatusResponse,
    PasskeyVerifyAuthenticationRequest,
    PasskeyVerifyRegistrationRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from auth.passkey_service import (
    begin_passkey_authentication,
    begin_passkey_registration,
    clear_passkeys_for_user,
    delete_passkey_for_user,
    list_passkeys_for_user,
    passkey_server_available,
    verify_passkey_authentication,
    verify_passkey_registration,
)
from auth.utils import (
    create_token,
    get_current_user,
    hash_password,
    normalize_username,
    require_non_admin,
    verify_password,
)
from config import settings
from db.database import get_db
from db.models import User, UserSettings, SpecialistConfig
from services.health_framework_service import ensure_default_frameworks

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    normalized_username = normalize_username(req.username)
    if len(normalized_username) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username must be at least 3 characters")

    if db.query(User).filter(User.username_normalized == normalized_username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    canonical_username = " ".join(req.username.strip().split())
    user = User(
        username=canonical_username,
        username_normalized=normalized_username,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        role="user",
        token_version=0,
        force_password_change=False,
    )
    db.add(user)
    db.flush()

    # Create default settings and specialist config
    db.add(UserSettings(user_id=user.id))
    db.add(SpecialistConfig(user_id=user.id))
    ensure_default_frameworks(db, user.id)
    db.commit()

    return TokenResponse(access_token=create_token(user.id, role=user.role, token_version=user.token_version))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    normalized_username = normalize_username(req.username)
    user = db.query(User).filter(User.username_normalized == normalized_username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(access_token=create_token(user.id, role=user.role, token_version=user.token_version))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/passkey/status", response_model=PasskeyStatusResponse)
def passkey_status():
    return PasskeyStatusResponse(
        enabled=bool(passkey_server_available()),
        rp_id=settings.PASSKEY_RP_ID,
        rp_name=settings.PASSKEY_RP_NAME,
    )


@router.post("/passkey/register/options", response_model=PasskeyBeginResponse)
def passkey_register_options(
    req: PasskeyRegisterOptionsRequest,
    user: User = Depends(require_non_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    payload = begin_passkey_registration(db, user)
    db.commit()
    return payload


@router.post("/passkey/register/verify")
def passkey_register_verify(
    req: PasskeyVerifyRegistrationRequest,
    user: User = Depends(require_non_admin),
    db: Session = Depends(get_db),
):
    credential = verify_passkey_registration(
        db,
        user,
        request_id=req.request_id,
        credential=req.credential,
        label=req.label,
    )
    db.commit()
    return {"status": "ok", "credential": credential}


@router.post("/passkey/login/options", response_model=PasskeyBeginResponse)
def passkey_login_options(req: PasskeyBeginRequest, db: Session = Depends(get_db)):
    username_normalized = normalize_username(req.username) if req.username else None
    payload = begin_passkey_authentication(db, username_normalized=username_normalized)
    db.commit()
    return payload


@router.post("/passkey/login/verify", response_model=TokenResponse)
def passkey_login_verify(req: PasskeyVerifyAuthenticationRequest, db: Session = Depends(get_db)):
    user, _credential = verify_passkey_authentication(
        db,
        request_id=req.request_id,
        credential=req.credential,
    )
    token = create_token(
        user.id,
        role=user.role,
        token_version=user.token_version,
        expiry_hours_override=settings.PASSKEY_USER_TOKEN_HOURS,
    )
    db.commit()
    return TokenResponse(access_token=token)


@router.get("/passkey/credentials", response_model=list[PasskeyCredentialResponse])
def passkey_list_credentials(
    user: User = Depends(require_non_admin),
    db: Session = Depends(get_db),
):
    return list_passkeys_for_user(db, user.id)


@router.delete("/passkey/credentials/{passkey_id}")
def passkey_delete_credential(
    passkey_id: int,
    user: User = Depends(require_non_admin),
    db: Session = Depends(get_db),
):
    delete_passkey_for_user(db, user.id, passkey_id)
    db.commit()
    return {"status": "ok"}


@router.delete("/passkey/credentials")
def passkey_clear_credentials(
    user: User = Depends(require_non_admin),
    db: Session = Depends(get_db),
):
    deleted = clear_passkeys_for_user(db, user.id)
    db.commit()
    return {"status": "ok", "deleted": deleted}
