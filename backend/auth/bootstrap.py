from sqlalchemy.orm import Session

from auth.utils import hash_password, normalize_username
from config import settings
from db.database import SessionLocal
from db.models import SpecialistConfig, User, UserSettings


def ensure_admin_account() -> None:
    admin_username_raw = " ".join((settings.ADMIN_USERNAME or "").strip().split()) or "longadmin"
    admin_username_normalized = normalize_username(admin_username_raw)
    admin_display_name = (settings.ADMIN_DISPLAY_NAME or "Long Admin").strip() or "Long Admin"

    db: Session = SessionLocal()
    try:
        admin_user = (
            db.query(User)
            .filter(User.username_normalized == admin_username_normalized, User.role == "admin")
            .order_by(User.created_at, User.id)
            .first()
        )

        if not admin_user:
            # If the username is already taken by a non-admin account, create a suffixed admin username.
            final_username = admin_username_raw
            final_normalized = admin_username_normalized
            username_taken = db.query(User).filter(User.username_normalized == final_normalized).first()
            if username_taken:
                suffix = 2
                while True:
                    candidate = f"{admin_username_raw}_{suffix}"
                    candidate_norm = normalize_username(candidate)
                    if not db.query(User).filter(User.username_normalized == candidate_norm).first():
                        final_username = candidate
                        final_normalized = candidate_norm
                        break
                    suffix += 1

            admin_user = User(
                username=final_username,
                username_normalized=final_normalized,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                display_name=admin_display_name,
                role="admin",
                token_version=0,
                force_password_change=bool(settings.ADMIN_FORCE_PASSWORD_CHANGE),
            )
            db.add(admin_user)
            db.flush()
            db.add(UserSettings(user_id=admin_user.id))
            db.add(SpecialistConfig(user_id=admin_user.id))
            db.commit()
            return

        if settings.ADMIN_RESET_PASSWORD_ON_STARTUP:
            admin_user.password_hash = hash_password(settings.ADMIN_PASSWORD)
            admin_user.force_password_change = True
            admin_user.token_version = int(admin_user.token_version or 0) + 1
        if not admin_user.settings:
            db.add(UserSettings(user_id=admin_user.id))
        if not admin_user.specialist_config:
            db.add(SpecialistConfig(user_id=admin_user.id))
        db.commit()
    finally:
        db.close()
