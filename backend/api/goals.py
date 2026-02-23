from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import User, UserGoal

router = APIRouter(prefix="/goals", tags=["goals"], dependencies=[Depends(require_non_admin)])

VALID_STATUSES = {"active", "paused", "completed", "abandoned"}
VALID_GOAL_TYPES = {"weight_loss", "cardiovascular", "fitness", "metabolic", "energy", "sleep", "habit", "custom"}


def _goal_to_dict(goal: UserGoal) -> dict:
    progress_pct: Optional[float] = None
    if (
        goal.baseline_value is not None
        and goal.target_value is not None
        and goal.current_value is not None
        and goal.target_value != goal.baseline_value
    ):
        span = goal.target_value - goal.baseline_value
        done = goal.current_value - goal.baseline_value
        progress_pct = round(max(0.0, min(100.0, (done / span) * 100.0)), 1)

    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "goal_type": goal.goal_type,
        "target_value": goal.target_value,
        "target_unit": goal.target_unit,
        "baseline_value": goal.baseline_value,
        "current_value": goal.current_value,
        "target_date": goal.target_date,
        "status": goal.status,
        "priority": goal.priority,
        "why": goal.why,
        "created_by": goal.created_by,
        "progress_pct": progress_pct,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


class GoalCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    goal_type: str = "custom"
    target_value: Optional[float] = None
    target_unit: Optional[str] = None
    baseline_value: Optional[float] = None
    current_value: Optional[float] = None
    target_date: Optional[str] = None
    priority: int = 3
    why: Optional[str] = None
    created_by: str = "coach"


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = None
    goal_type: Optional[str] = None
    target_value: Optional[float] = None
    target_unit: Optional[str] = None
    baseline_value: Optional[float] = None
    current_value: Optional[float] = None
    target_date: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    why: Optional[str] = None


@router.get("")
def list_goals(
    status: str = "active",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(UserGoal).filter(UserGoal.user_id == user.id)
    if status and status != "all":
        query = query.filter(UserGoal.status == status)
    goals = query.order_by(UserGoal.priority.asc(), UserGoal.created_at.asc()).all()
    return [_goal_to_dict(g) for g in goals]


@router.get("/{goal_id}")
def get_goal(
    goal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(UserGoal).filter(UserGoal.id == goal_id, UserGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return _goal_to_dict(goal)


@router.post("", status_code=201)
def create_goal(
    req: GoalCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal_type = req.goal_type if req.goal_type in VALID_GOAL_TYPES else "custom"
    priority = max(1, min(5, req.priority))
    created_by = req.created_by if req.created_by in {"coach", "user"} else "coach"

    goal = UserGoal(
        user_id=user.id,
        title=req.title.strip(),
        description=req.description,
        goal_type=goal_type,
        target_value=req.target_value,
        target_unit=req.target_unit,
        baseline_value=req.baseline_value,
        current_value=req.current_value if req.current_value is not None else req.baseline_value,
        target_date=req.target_date,
        status="active",
        priority=priority,
        why=req.why,
        created_by=created_by,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _goal_to_dict(goal)


@router.put("/{goal_id}")
def update_goal(
    goal_id: int,
    req: GoalUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(UserGoal).filter(UserGoal.id == goal_id, UserGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if req.title is not None:
        goal.title = req.title.strip()
    if req.description is not None:
        goal.description = req.description
    if req.goal_type is not None:
        goal.goal_type = req.goal_type if req.goal_type in VALID_GOAL_TYPES else "custom"
    if req.target_value is not None:
        goal.target_value = req.target_value
    if req.target_unit is not None:
        goal.target_unit = req.target_unit
    if req.baseline_value is not None:
        goal.baseline_value = req.baseline_value
    if req.current_value is not None:
        goal.current_value = req.current_value
    if req.target_date is not None:
        goal.target_date = req.target_date
    if req.status is not None:
        if req.status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(VALID_STATUSES)}")
        goal.status = req.status
    if req.priority is not None:
        goal.priority = max(1, min(5, req.priority))
    if req.why is not None:
        goal.why = req.why

    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(goal)
    return _goal_to_dict(goal)


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(UserGoal).filter(UserGoal.id == goal_id, UserGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.status = "abandoned"
    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "abandoned", "id": goal_id}
