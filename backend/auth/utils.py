from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import settings
from db.database import get_db
from db.models import User

security = HTTPBearer(auto_error=False)


def normalize_username(username: str) -> str:
    return " ".join((username or "").strip().split()).lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(
    user_id: int,
    role: str = "user",
    token_version: int = 0,
    expiry_hours_override: int | None = None,
) -> str:
    expiry_hours = (
        int(expiry_hours_override)
        if expiry_hours_override is not None
        else (settings.ADMIN_JWT_EXPIRY_HOURS if role == "admin" else settings.JWT_EXPIRY_HOURS)
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": int(token_version or 0),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_name = (settings.AUTH_COOKIE_NAME or "").strip() or "longevity_session"
    cookie_token = request.cookies.get(cookie_name)
    if cookie_token:
        return cookie_token
    return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token_payload = decode_token(token)
    user_id = int(token_payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    token_version = int(token_payload.get("tv", 0))
    if token_version != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalidated. Please sign in again.")
    request.state.user_id = user.id
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if (user.role or "").lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if bool(user.force_password_change):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin password change required before accessing admin functions",
        )
    return user


def require_non_admin(user: User = Depends(get_current_user)) -> User:
    if (user.role or "").lower() == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts cannot access user-only endpoints",
        )
    return user
