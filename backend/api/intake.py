from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
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

router = APIRouter(prefix="/intake", tags=["intake"], dependencies=[Depends(require_non_admin)])


class IntakeStartRequest(BaseModel):
    restart: bool = False


class IntakeAnswerRequest(BaseModel):
    answer: str = Field(min_length=1)
    field_id: Optional[str] = None


class IntakeSkipRequest(BaseModel):
    skip_all: bool = False


class IntakePromptStatusResponse(BaseModel):
    should_prompt: bool
    recommended_action: str
    intake_status: str
    has_api_key: bool
    models_ready: bool
    reason: str
    message: str


@router.get("/prompt-status", response_model=IntakePromptStatusResponse)
def get_intake_prompt_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings:
        raise HTTPException(status_code=404, detail="User settings not found")

    has_api_key = bool(settings.api_key_encrypted)
    models_ready = all(
        [
            bool((settings.reasoning_model or "").strip()),
            bool((settings.utility_model or "").strip()),
            bool((settings.deep_thinking_model or settings.reasoning_model or "").strip()),
        ]
    )
    active_session = get_active_session(db, user.id)

    intake_status = "not_started"
    if settings.intake_completed_at:
        intake_status = "completed"
    elif active_session:
        intake_status = "in_progress"
    elif settings.intake_skipped_at:
        intake_status = "skipped"

    should_prompt = has_api_key and models_ready and intake_status in {"not_started", "in_progress"}
    recommended_action = "continue" if intake_status == "in_progress" else ("start" if should_prompt else "none")

    if not has_api_key:
        reason = "missing_api_key"
        message = "Set your API key first."
    elif not models_ready:
        reason = "missing_models"
        message = "Set your models first."
    elif intake_status == "completed":
        reason = "intake_completed"
        message = "Intake is already completed."
    elif intake_status == "skipped":
        reason = "intake_skipped"
        message = "Intake was skipped."
    elif intake_status == "in_progress":
        reason = "intake_in_progress"
        message = "Resume your intake to finish profile setup."
    else:
        reason = "intake_not_started"
        message = "Start intake to complete your profile setup."

    return IntakePromptStatusResponse(
        should_prompt=should_prompt,
        recommended_action=recommended_action,
        intake_status=intake_status,
        has_api_key=has_api_key,
        models_ready=models_ready,
        reason=reason,
        message=message,
    )


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

    patch = finalize_session(session, settings, db=db)
    state = session_state(session, settings)
    db.commit()
    return {"status": "completed", "applied_patch": patch, **state}
