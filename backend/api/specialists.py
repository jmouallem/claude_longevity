from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User

router = APIRouter(prefix="/specialists", tags=["specialists"])

SPECIALISTS = [
    {"id": "auto", "name": "Auto (Orchestrator)", "description": "Automatically routes to the best specialist", "color": "blue"},
    {"id": "nutritionist", "name": "Nutritionist", "description": "Food, diet, macros, meal planning", "color": "green"},
    {"id": "sleep_expert", "name": "Sleep Expert", "description": "Sleep optimization, circadian rhythm", "color": "indigo"},
    {"id": "movement_coach", "name": "Movement Coach", "description": "Exercise, workouts, training", "color": "orange"},
    {"id": "supplement_auditor", "name": "Supplement Auditor", "description": "Supplements, timing, interactions", "color": "purple"},
    {"id": "safety_clinician", "name": "Safety Clinician", "description": "Medical safety, vitals concerns", "color": "red"},
]


class SpecialistUpdate(BaseModel):
    active_specialist: str
    specialist_overrides: Optional[str] = None


@router.get("")
def get_specialists(user: User = Depends(get_current_user)):
    active = "auto"
    if user.specialist_config:
        active = user.specialist_config.active_specialist or "auto"
    return {"specialists": SPECIALISTS, "active": active}


@router.put("")
def set_specialist(
    update: SpecialistUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.specialist_config:
        user.specialist_config.active_specialist = update.active_specialist
        if update.specialist_overrides is not None:
            user.specialist_config.specialist_overrides = update.specialist_overrides
        db.commit()
    return {"status": "ok", "active": update.active_specialist}
