from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import FeedbackEntry, User

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[Depends(require_non_admin)])

ALLOWED_TYPES = {"bug", "enhancement", "missing", "other"}


class FeedbackCreateRequest(BaseModel):
    feedback_type: str
    title: str
    details: Optional[str] = None
    specialist_id: Optional[str] = None
    specialist_name: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: int
    feedback_type: str
    title: str
    details: Optional[str] = None
    source: str
    specialist_id: Optional[str] = None
    specialist_name: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: str


def _to_response(entry: FeedbackEntry, username_by_id: dict[int, str]) -> FeedbackResponse:
    return FeedbackResponse(
        id=entry.id,
        feedback_type=entry.feedback_type,
        title=entry.title,
        details=entry.details,
        source=entry.source,
        specialist_id=entry.specialist_id,
        specialist_name=entry.specialist_name,
        created_by_user_id=entry.created_by_user_id,
        created_by_username=username_by_id.get(entry.created_by_user_id or -1),
        created_at=entry.created_at.isoformat() if isinstance(entry.created_at, datetime) else str(entry.created_at),
    )


@router.get("", response_model=list[FeedbackResponse])
def list_feedback(
    feedback_type: Optional[str] = Query(default=None),
    specialist_id: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(FeedbackEntry).filter(
        FeedbackEntry.created_by_user_id == user.id,
        FeedbackEntry.source == "user",
    )
    if feedback_type:
        q = q.filter(FeedbackEntry.feedback_type == feedback_type.strip().lower())
    if specialist_id:
        q = q.filter(FeedbackEntry.specialist_id == specialist_id.strip().lower())

    rows = q.order_by(FeedbackEntry.created_at.desc()).limit(limit).all()

    user_ids = {r.created_by_user_id for r in rows if r.created_by_user_id}
    username_by_id: dict[int, str] = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        username_by_id = {u.id: u.username for u in users}

    return [_to_response(r, username_by_id) for r in rows]


@router.post("", response_model=FeedbackResponse)
def create_feedback(
    req: FeedbackCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f_type = req.feedback_type.strip().lower()
    if f_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"feedback_type must be one of: {', '.join(sorted(ALLOWED_TYPES))}")

    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    row = FeedbackEntry(
        feedback_type=f_type,
        title=title,
        details=(req.details or "").strip() or None,
        source="user",
        specialist_id=(req.specialist_id or "").strip().lower() or None,
        specialist_name=(req.specialist_name or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return _to_response(row, {user.id: user.username})


@router.delete("/{feedback_id}")
def delete_feedback(
    feedback_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(FeedbackEntry)
        .filter(
            FeedbackEntry.id == feedback_id,
            FeedbackEntry.created_by_user_id == user.id,
            FeedbackEntry.source == "user",
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Feedback entry not found")
    db.delete(row)
    db.commit()
    return {"status": "ok"}
