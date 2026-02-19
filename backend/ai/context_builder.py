import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import (
    User, FoodLog, HydrationLog, VitalsLog, ExerciseLog,
    SupplementLog, FastingLog, SleepLog, Summary, Message,
)
from utils.datetime_utils import start_of_day, end_of_day, today_utc

CONTEXT_DIR = Path(__file__).parent.parent / "context"


def load_system_prompt() -> str:
    return (CONTEXT_DIR / "system_prompt.md").read_text(encoding="utf-8")


def load_specialist_prompt(specialist: str) -> str:
    path = CONTEXT_DIR / "specialists" / f"{specialist}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def format_user_profile(settings) -> str:
    """Format user settings into a readable profile section."""
    if not settings:
        return "No profile configured yet."

    lines = []
    if settings.age:
        lines.append(f"- Age: {settings.age}")
    if settings.sex:
        lines.append(f"- Sex: {settings.sex}")
    if settings.height_cm:
        lines.append(f"- Height: {settings.height_cm} cm")
    if settings.current_weight_kg:
        lines.append(f"- Current weight: {settings.current_weight_kg} kg")
    if settings.goal_weight_kg:
        lines.append(f"- Goal weight: {settings.goal_weight_kg} kg")
    if settings.fitness_level:
        lines.append(f"- Fitness level: {settings.fitness_level}")
    if settings.medical_conditions:
        try:
            conditions = json.loads(settings.medical_conditions)
            lines.append(f"- Medical conditions: {', '.join(conditions)}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- Medical conditions: {settings.medical_conditions}")
    if settings.health_goals:
        try:
            goals = json.loads(settings.health_goals)
            lines.append(f"- Health goals: {', '.join(goals)}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- Health goals: {settings.health_goals}")
    if settings.dietary_preferences:
        try:
            prefs = json.loads(settings.dietary_preferences)
            lines.append(f"- Dietary preferences: {', '.join(prefs)}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- Dietary preferences: {settings.dietary_preferences}")

    return "\n".join(lines) if lines else "Profile not yet configured."


def format_medications(medications_json: str | None) -> str:
    if not medications_json:
        return "None reported."
    try:
        meds = json.loads(medications_json)
        lines = []
        for m in meds:
            line = f"- {m.get('name', 'Unknown')}"
            if m.get('dose'):
                line += f" ({m['dose']})"
            if m.get('timing'):
                line += f" — {m['timing']}"
            if m.get('purpose'):
                line += f" — for {m['purpose']}"
            lines.append(line)
        return "\n".join(lines) if lines else "None reported."
    except (json.JSONDecodeError, TypeError):
        return medications_json or "None reported."


def format_supplements(supplements_json: str | None) -> str:
    if not supplements_json:
        return "None reported."
    try:
        supps = json.loads(supplements_json)
        lines = []
        for s in supps:
            line = f"- {s.get('name', 'Unknown')}"
            if s.get('dose'):
                line += f" ({s['dose']})"
            if s.get('timing'):
                line += f" — {s['timing']}"
            lines.append(line)
        return "\n".join(lines) if lines else "None reported."
    except (json.JSONDecodeError, TypeError):
        return supplements_json or "None reported."


def compute_today_snapshot(db: Session, user: User, target_date: date | None = None) -> str:
    """Compute a snapshot of today's health data."""
    d = target_date or today_utc()
    day_start = start_of_day(d)
    day_end = end_of_day(d)

    sections = [f"Date: {d.isoformat()}"]

    # Food totals
    foods = db.query(FoodLog).filter(
        FoodLog.user_id == user.id,
        FoodLog.logged_at >= day_start,
        FoodLog.logged_at <= day_end,
    ).all()

    if foods:
        total_cal = sum(f.calories or 0 for f in foods)
        total_protein = sum(f.protein_g or 0 for f in foods)
        total_carbs = sum(f.carbs_g or 0 for f in foods)
        total_fat = sum(f.fat_g or 0 for f in foods)
        total_fiber = sum(f.fiber_g or 0 for f in foods)
        total_sodium = sum(f.sodium_mg or 0 for f in foods)

        meals = []
        for f in foods:
            try:
                items = json.loads(f.items) if isinstance(f.items, str) else f.items
                item_names = [i.get("name", str(i)) for i in items] if isinstance(items, list) else [str(items)]
            except (json.JSONDecodeError, TypeError):
                item_names = [f.items]
            meals.append(f"  - {f.meal_label or 'Meal'}: {', '.join(item_names)} ({f.calories or '?'} cal)")

        sections.append(f"Meals today ({len(foods)}):\n" + "\n".join(meals))
        sections.append(
            f"Running totals: {total_cal:.0f} cal | {total_protein:.0f}g protein | "
            f"{total_carbs:.0f}g carbs | {total_fat:.0f}g fat | {total_fiber:.0f}g fiber | "
            f"{total_sodium:.0f}mg sodium"
        )
    else:
        sections.append("No meals logged today.")

    # Hydration
    hydration = db.query(HydrationLog).filter(
        HydrationLog.user_id == user.id,
        HydrationLog.logged_at >= day_start,
        HydrationLog.logged_at <= day_end,
    ).all()
    if hydration:
        total_ml = sum(h.amount_ml for h in hydration)
        sections.append(f"Hydration: {total_ml:.0f} ml ({total_ml/250:.1f} cups)")
    else:
        sections.append("No hydration logged today.")

    # Vitals
    vitals = db.query(VitalsLog).filter(
        VitalsLog.user_id == user.id,
        VitalsLog.logged_at >= day_start,
        VitalsLog.logged_at <= day_end,
    ).order_by(VitalsLog.logged_at.desc()).first()
    if vitals:
        parts = []
        if vitals.weight_kg:
            parts.append(f"Weight: {vitals.weight_kg} kg")
        if vitals.bp_systolic and vitals.bp_diastolic:
            parts.append(f"BP: {vitals.bp_systolic}/{vitals.bp_diastolic}")
        if vitals.heart_rate:
            parts.append(f"HR: {vitals.heart_rate}")
        if parts:
            sections.append("Latest vitals: " + " | ".join(parts))

    # Exercise
    exercises = db.query(ExerciseLog).filter(
        ExerciseLog.user_id == user.id,
        ExerciseLog.logged_at >= day_start,
        ExerciseLog.logged_at <= day_end,
    ).all()
    if exercises:
        ex_lines = []
        for e in exercises:
            ex_lines.append(f"  - {e.exercise_type}: {e.duration_minutes or '?'} min")
        sections.append(f"Exercise today:\n" + "\n".join(ex_lines))

    # Active fasting
    active_fast = db.query(FastingLog).filter(
        FastingLog.user_id == user.id,
        FastingLog.fast_end.is_(None),
    ).order_by(FastingLog.fast_start.desc()).first()
    if active_fast:
        fast_start = active_fast.fast_start if active_fast.fast_start.tzinfo else active_fast.fast_start.replace(tzinfo=timezone.utc)
        duration = (datetime.now(timezone.utc) - fast_start).total_seconds() / 3600
        sections.append(f"Active fast: Started at {active_fast.fast_start.isoformat()}, duration: {duration:.1f} hours")

    return "\n".join(sections)


def get_recent_messages(db: Session, user: User, limit: int = 20) -> list[dict]:
    """Get recent messages for conversational context."""
    messages = db.query(Message).filter(
        Message.user_id == user.id,
    ).order_by(Message.created_at.desc()).limit(limit).all()

    result = []
    for m in reversed(messages):
        result.append({"role": m.role, "content": m.content})
    return result


def get_latest_summary(db: Session, user: User, summary_type: str) -> str | None:
    """Get the most recent summary of a given type."""
    summary = db.query(Summary).filter(
        Summary.user_id == user.id,
        Summary.summary_type == summary_type,
    ).order_by(Summary.period_end.desc()).first()

    if summary and summary.full_narrative:
        return summary.full_narrative
    return None


def build_context(db: Session, user: User, specialist: str = "orchestrator") -> str:
    """Build the full context string for an AI call."""
    sections = []

    # 1. Base system prompt
    sections.append(load_system_prompt())

    # 2. Specialist instructions
    if specialist and specialist != "orchestrator":
        specialist_prompt = load_specialist_prompt(specialist)
        if specialist_prompt:
            sections.append(specialist_prompt)

    # 3. User profile
    profile = format_user_profile(user.settings)
    sections.append(f"## Current User Profile\n{profile}")

    # 4. Medications & supplements
    if user.settings:
        meds = format_medications(user.settings.medications)
        supps = format_supplements(user.settings.supplements)
        sections.append(f"## Medications\n{meds}\n\n## Supplements\n{supps}")

    # 5. Today's snapshot
    snapshot = compute_today_snapshot(db, user)
    sections.append(f"## Today's Status\n{snapshot}")

    # 6. Recent summaries
    daily = get_latest_summary(db, user, "daily")
    weekly = get_latest_summary(db, user, "weekly")
    if daily:
        sections.append(f"## Yesterday's Summary\n{daily}")
    if weekly:
        sections.append(f"## Last Week's Summary\n{weekly}")

    return "\n\n".join(sections)
