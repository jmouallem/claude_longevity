from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import User
from services.coaching_plan_service import (
    clear_plan_data,
    ensure_plan_seeded,
    get_plan_snapshot,
    mark_notification_read,
    set_plan_preferences,
    set_task_status,
    undo_adjustment,
)
from services.health_framework_service import FRAMEWORK_TYPES, grouped_frameworks_for_user


router = APIRouter(prefix="/plan", tags=["plan"], dependencies=[Depends(require_non_admin)])


class PlanPreferenceUpdate(BaseModel):
    visibility_mode: Optional[str] = None  # top3 | all
    max_visible_tasks: Optional[int] = None
    coaching_why: Optional[str] = None


class TaskStatusUpdate(BaseModel):
    status: str  # pending | completed | skipped


@router.get("/snapshot")
def plan_snapshot(
    cycle_type: str = "daily",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = get_plan_snapshot(db, user, cycle_type=cycle_type)
    db.commit()
    return payload


@router.get("/preferences")
def get_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    if not s:
        raise HTTPException(status_code=404, detail="User settings not found")
    return {
        "visibility_mode": (s.plan_visibility_mode or "top3"),
        "max_visible_tasks": int(s.plan_max_visible_tasks or 3),
        "coaching_why": s.coaching_why,
    }


@router.put("/preferences")
def update_preferences(
    payload: PlanPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        s = set_plan_preferences(
            db,
            user,
            visibility_mode=payload.visibility_mode,
            max_visible_tasks=payload.max_visible_tasks,
            coaching_why=payload.coaching_why,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        "status": "ok",
        "visibility_mode": s.plan_visibility_mode,
        "max_visible_tasks": int(s.plan_max_visible_tasks or 3),
        "coaching_why": s.coaching_why,
    }


@router.post("/seed")
def seed_plan(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = ensure_plan_seeded(db, user)
    db.commit()
    return {"status": "ok", **result}


@router.post("/tasks/{task_id}/status")
def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = set_task_status(db, user, task_id=task_id, status=payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        "status": "ok",
        "task_id": row.id,
        "task_status": row.status,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = mark_notification_read(db, user, notification_id=notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.commit()
    return {"status": "ok", "notification_id": row.id, "is_read": True}


@router.post("/adjustments/{adjustment_id}/undo")
def undo_plan_adjustment(
    adjustment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = undo_adjustment(db, user, adjustment_id=adjustment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        "status": "ok",
        "adjustment_id": row.id,
        "adjustment_status": row.status,
        "undone_at": row.undone_at.isoformat() if row.undone_at else None,
    }


@router.get("/framework-education")
def framework_education(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    grouped = grouped_frameworks_for_user(db, user.id)
    return {
        "framework_types": FRAMEWORK_TYPES,
        "grouped": grouped,
    }


@router.delete("/tasks")
def clear_all_plan_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = clear_plan_data(db, user.id)
    db.commit()
    return {"status": "ok", **result}
