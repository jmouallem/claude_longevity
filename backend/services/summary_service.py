import json
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ai.context_builder import format_user_profile
from ai.providers import get_provider
from ai.usage_tracker import track_usage_from_result
from db.models import (
    User, Summary, FoodLog, VitalsLog, ExerciseLog,
    HydrationLog, SupplementLog, FastingLog, SleepLog, DailyChecklistItem,
)
from utils.datetime_utils import start_of_day, end_of_day, today_for_tz
from utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)

DAILY_SUMMARY_PROMPT = """Summarize this day's health data into a concise daily summary.
Date: {date}
User timezone: {timezone}

Include: total calories/macros, protein goal status, hydration total,
fasting duration, exercise done, vitals trends, sleep quality,
what went well, what needs improvement, and any recommendations.
Keep it under 400 words.

User profile: {profile}
Day's data: {data}

Return a structured summary with sections for:
- Nutrition overview
- Exercise
- Vitals
- Sleep
- Fasting
- Wins (what went well)
- Concerns (what needs attention)
- Recommendations"""

WEEKLY_SUMMARY_PROMPT = """Synthesize these daily summaries into a weekly overview.
Identify trends, patterns, and areas of improvement.
Keep it under 500 words.

User profile: {profile}
Daily summaries: {data}"""

MONTHLY_SUMMARY_PROMPT = """Synthesize these weekly summaries into a monthly overview.
Highlight progress toward goals, key trends, and strategic recommendations.
Keep it under 600 words.

User profile: {profile}
Weekly summaries: {data}"""


def gather_daily_data(db: Session, user: User, d: date, tz_name: str | None = None) -> dict:
    """Gather all health data for a specific day in the user's timezone."""
    day_start = start_of_day(d, tz_name)
    day_end = end_of_day(d, tz_name)

    foods = db.query(FoodLog).filter(
        FoodLog.user_id == user.id, FoodLog.logged_at >= day_start, FoodLog.logged_at <= day_end
    ).all()

    vitals = db.query(VitalsLog).filter(
        VitalsLog.user_id == user.id, VitalsLog.logged_at >= day_start, VitalsLog.logged_at <= day_end
    ).all()

    exercises = db.query(ExerciseLog).filter(
        ExerciseLog.user_id == user.id, ExerciseLog.logged_at >= day_start, ExerciseLog.logged_at <= day_end
    ).all()

    hydrations = db.query(HydrationLog).filter(
        HydrationLog.user_id == user.id, HydrationLog.logged_at >= day_start, HydrationLog.logged_at <= day_end
    ).all()

    supplements = db.query(SupplementLog).filter(
        SupplementLog.user_id == user.id, SupplementLog.logged_at >= day_start, SupplementLog.logged_at <= day_end
    ).all()

    checklist_supp_count = db.query(DailyChecklistItem).filter(
        DailyChecklistItem.user_id == user.id,
        DailyChecklistItem.target_date == d.isoformat(),
        DailyChecklistItem.item_type == "supplement",
        DailyChecklistItem.completed.is_(True),
    ).count()

    fasting = db.query(FastingLog).filter(
        FastingLog.user_id == user.id, FastingLog.fast_start >= day_start, FastingLog.fast_start <= day_end
    ).all()

    sleep = db.query(SleepLog).filter(
        SleepLog.user_id == user.id, SleepLog.created_at >= day_start, SleepLog.created_at <= day_end
    ).all()

    return {
        "food": {
            "meals": len(foods),
            "total_calories": sum(f.calories or 0 for f in foods),
            "total_protein": sum(f.protein_g or 0 for f in foods),
            "total_carbs": sum(f.carbs_g or 0 for f in foods),
            "total_fat": sum(f.fat_g or 0 for f in foods),
            "total_fiber": sum(f.fiber_g or 0 for f in foods),
            "total_sodium": sum(f.sodium_mg or 0 for f in foods),
        },
        "vitals": [
            {
                "weight_kg": v.weight_kg,
                "bp": f"{v.bp_systolic}/{v.bp_diastolic}" if v.bp_systolic else None,
                "hr": v.heart_rate,
            }
            for v in vitals
        ],
        "exercise": [
            {"type": e.exercise_type, "duration": e.duration_minutes, "calories": e.calories_burned}
            for e in exercises
        ],
        "hydration_ml": sum(h.amount_ml for h in hydrations),
        # Include checklist-completed supplements so "I took X" messages are reflected
        # even when no explicit supplement log row was created.
        "supplements_taken": max(len(supplements), checklist_supp_count),
        "fasting": [
            {"duration_min": f.duration_minutes, "type": f.fast_type}
            for f in fasting if f.duration_minutes
        ],
        "sleep": [
            {"duration_min": s.duration_minutes, "quality": s.quality}
            for s in sleep
        ],
    }


async def generate_summary(db: Session, user: User, summary_type: str, target_date: date | None = None) -> int:
    """Generate a summary using the utility model."""
    settings = user.settings
    if not settings or not settings.api_key_encrypted:
        raise ValueError("API key not configured")

    tz_name = settings.timezone or "UTC"
    if target_date is None:
        target_date = today_for_tz(tz_name)

    api_key = decrypt_api_key(settings.api_key_encrypted)
    provider = get_provider(
        settings.ai_provider,
        api_key,
        reasoning_model=settings.reasoning_model,
        utility_model=settings.utility_model,
    )
    profile = format_user_profile(settings)

    if summary_type == "daily":
        data = gather_daily_data(db, user, target_date, tz_name)
        prompt = DAILY_SUMMARY_PROMPT.format(
            date=target_date.isoformat(),
            timezone=tz_name,
            profile=profile,
            data=json.dumps(data),
        )
        period_start = target_date
        period_end = target_date

    elif summary_type == "weekly":
        # Get daily summaries for the past 7 days
        week_start = target_date - timedelta(days=6)
        dailies = db.query(Summary).filter(
            Summary.user_id == user.id,
            Summary.summary_type == "daily",
            Summary.period_start >= week_start.isoformat(),
            Summary.period_end <= target_date.isoformat(),
        ).all()
        data = [s.full_narrative for s in dailies if s.full_narrative]
        prompt = WEEKLY_SUMMARY_PROMPT.format(profile=profile, data="\n\n".join(data))
        period_start = week_start
        period_end = target_date

    elif summary_type == "monthly":
        # Get weekly summaries for the past 30 days
        month_start = target_date - timedelta(days=29)
        weeklies = db.query(Summary).filter(
            Summary.user_id == user.id,
            Summary.summary_type == "weekly",
            Summary.period_start >= month_start.isoformat(),
            Summary.period_end <= target_date.isoformat(),
        ).all()
        data = [s.full_narrative for s in weeklies if s.full_narrative]
        prompt = MONTHLY_SUMMARY_PROMPT.format(profile=profile, data="\n\n".join(data))
        period_start = month_start
        period_end = target_date
    else:
        raise ValueError(f"Unknown summary type: {summary_type}")

    # Generate with utility model
    result = await provider.chat(
        messages=[{"role": "user", "content": prompt}],
        model=provider.get_utility_model(),
        system="You are a health data summarization assistant. Provide clear, structured summaries.",
        stream=False,
    )
    track_usage_from_result(
        db=db,
        user_id=user.id,
        result=result,
        model_used=provider.get_utility_model(),
        operation=f"summary_generate:{summary_type}",
        usage_type="utility",
    )

    narrative = result["content"]

    # Save summary
    summary = Summary(
        user_id=user.id,
        summary_type=summary_type,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        full_narrative=narrative,
    )
    db.add(summary)
    db.commit()

    return summary.id
