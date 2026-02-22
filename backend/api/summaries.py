from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import User, Summary
from utils.datetime_utils import today_for_tz

router = APIRouter(prefix="/summaries", tags=["summaries"], dependencies=[Depends(require_non_admin)])


@router.get("")
def get_summaries(
    summary_type: Optional[str] = None,
    limit: int = 10,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get summaries, optionally filtered by type."""
    query = db.query(Summary).filter(Summary.user_id == user.id)
    if summary_type:
        query = query.filter(Summary.summary_type == summary_type)
    summaries = query.order_by(Summary.period_end.desc()).limit(limit).all()

    return [
        {
            "id": s.id,
            "summary_type": s.summary_type,
            "period_start": s.period_start,
            "period_end": s.period_end,
            "nutrition_summary": s.nutrition_summary,
            "exercise_summary": s.exercise_summary,
            "vitals_summary": s.vitals_summary,
            "sleep_summary": s.sleep_summary,
            "fasting_summary": s.fasting_summary,
            "supplement_summary": s.supplement_summary,
            "wins": s.wins,
            "concerns": s.concerns,
            "recommendations": s.recommendations,
            "full_narrative": s.full_narrative,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in summaries
    ]


@router.post("/generate")
async def generate_summary(
    summary_type: str = "daily",
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger summary generation."""
    if not user.settings or not user.settings.api_key_encrypted:
        raise HTTPException(status_code=400, detail="API key required for summary generation")

    from services.summary_service import generate_summary as gen_summary
    try:
        tz_name = getattr(getattr(user, "settings", None), "timezone", None)
        result = await gen_summary(db, user, summary_type, target_date or today_for_tz(tz_name))
        return {"status": "generated", "summary_id": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")
