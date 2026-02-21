from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User
from services.intake_service import (
    apply_answer_to_session,
    ensure_active_session,
    finalize_session,
    get_active_session,
    get_latest_session,
    session_state,
    skip_current_field,
    skip_session,
)

router = APIRouter(prefix="/intake", tags=["intake"])


class IntakeStartRequest(BaseModel):
    restart: bool = False


class IntakeAnswerRequest(BaseModel):
    answer: str = Field(min_length=1)
    field_id: Optional[str] = None


class IntakeSkipRequest(BaseModel):
    skip_all: bool = False


@router.post("/start")
def start_intake(
    req: IntakeStartRequest = IntakeStartRequest(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = ensure_active_session(db, settings, restart=req.restart)
    state = session_state(session, settings)
    db.commit()
    return state


@router.get("/next")
def get_next_question(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = get_active_session(db, user.id)
    if not session:
        session = ensure_active_session(db, settings, restart=False)
    state = session_state(session, settings)
    db.commit()
    return state


@router.post("/answer")
def answer_intake(
    req: IntakeAnswerRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = get_active_session(db, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active intake session. Call /api/intake/start first.")

    _, err = apply_answer_to_session(session, settings, req.answer, req.field_id)
    state = session_state(session, settings)
    db.commit()

    if err:
        return {"status": "validation_error", "error": err, **state}
    return {"status": "ok", **state}


@router.post("/skip")
def skip_intake(
    req: IntakeSkipRequest = IntakeSkipRequest(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = get_active_session(db, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active intake session.")

    if req.skip_all:
        skip_session(session, settings)
    else:
        skip_current_field(session, settings)

    state = session_state(session, settings)
    db.commit()
    return {"status": "ok", **state}


@router.get("/review")
def review_intake(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = get_active_session(db, user.id) or get_latest_session(db, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No intake session found.")

    return session_state(session, settings)


@router.post("/finish")
def finish_intake(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    session = get_active_session(db, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active intake session.")

    patch = finalize_session(session, settings)
    state = session_state(session, settings)
    db.commit()
    return {"status": "completed", "applied_patch": patch, **state}
