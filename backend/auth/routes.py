from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.models import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from auth.utils import hash_password, verify_password, create_token, get_current_user, normalize_username
from db.database import get_db
from db.models import User, UserSettings, SpecialistConfig

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
