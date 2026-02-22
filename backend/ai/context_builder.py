import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import (
    User, FoodLog, HydrationLog, VitalsLog, ExerciseLog,
    SupplementLog, FastingLog, SleepLog, Summary, Message, HealthOptimizationFramework,
)
from services.health_framework_service import FRAMEWORK_TYPES, active_frameworks_for_context, ensure_default_frameworks
from services.specialists_config import get_specialist_prompt, get_system_prompt, parse_overrides
from utils.datetime_utils import start_of_day, end_of_day, today_for_tz, sleep_log_overlaps_window
from utils.units import cm_to_ft_in, kg_to_lb, ml_to_oz

CONTEXT_DIR = Path(__file__).parent.parent / "context"
_DEFAULT_CONTEXT_MAX_CHARS = 18000
_STABLE_CONTEXT_CACHE_TTL_S = 300
_STABLE_CONTEXT_CACHE_MAX = 256
_stable_context_cache: dict[tuple, tuple[float, str]] = {}


def _context_budget(intent_category: str | None) -> dict[str, int]:
    category = str(intent_category or "").strip().lower()
    is_log = category.startswith("log_")
    return {
        "max_total": 13000 if is_log else _DEFAULT_CONTEXT_MAX_CHARS,
        "max_profile": 1500,
        "max_framework": 1400,
        "max_meds_supps": 1800,
        "max_snapshot": 2200 if is_log else 3200,
        "max_daily_summary": 1200 if is_log else 1800,
        "max_weekly_summary": 900 if is_log else 1500,
        "max_guidance": 1600,
        "min_section_chars": 220,
    }


def _clip_block(text: str, max_chars: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    keep = max(80, max_chars - 24)
    return f"{raw[:keep].rstrip()}\n...[truncated]"


def _format_height(cm_value: float, unit: str) -> str:
    if unit == "ft":
        ft, inches = cm_to_ft_in(cm_value)
        return f"{ft} ft {inches} in"
    return f"{cm_value:.1f} cm"


def _format_weight(kg_value: float, unit: str) -> str:
    if unit == "lb":
        return f"{kg_to_lb(kg_value):.1f} lb"
    return f"{kg_value:.1f} kg"


def _format_hydration(ml_value: float, unit: str) -> str:
    if unit == "oz":
        return f"{ml_to_oz(ml_value):.1f} oz"
    return f"{ml_value:.0f} ml"


def format_user_profile(settings) -> str:
    """Format user settings into a readable profile section."""
    if not settings:
        return "No profile configured yet."

    lines = []
    height_unit = settings.height_unit or "cm"
    weight_unit = settings.weight_unit or "kg"
    hydration_unit = settings.hydration_unit or "ml"
    lines.append(
        f"- Preferred units: height={height_unit}, weight={weight_unit}, hydration={hydration_unit}"
    )
    if settings.age:
        lines.append(f"- Age: {settings.age}")
    if settings.sex:
        lines.append(f"- Sex: {settings.sex}")
    if settings.height_cm:
        lines.append(f"- Height: {_format_height(settings.height_cm, height_unit)}")
    if settings.current_weight_kg:
        lines.append(f"- Current weight: {_format_weight(settings.current_weight_kg, weight_unit)}")
    if settings.goal_weight_kg:
        lines.append(f"- Goal weight: {_format_weight(settings.goal_weight_kg, weight_unit)}")
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


def _format_item_list(raw: str | None, label: str = "items") -> str:
    """Format a stored list (JSON array of strings/dicts, or comma-separated) into bullet points."""
    if not raw:
        return "None reported."
    txt = raw.strip()
    items: list[str] = []
    if txt.startswith("["):
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, str):
                        items.append(entry.strip())
                    elif isinstance(entry, dict):
                        name = entry.get("name", str(entry))
                        dose = entry.get("dose", "")
                        timing = entry.get("timing", "")
                        parts = [str(name)]
                        if dose:
                            parts[0] += f" ({dose})"
                        if timing:
                            parts[0] += f" — {timing}"
                        items.append(parts[0])
                    else:
                        items.append(str(entry))
        except (json.JSONDecodeError, TypeError):
            items = [s.strip() for s in txt.split(",") if s.strip()]
    else:
        items = [s.strip() for s in txt.split(",") if s.strip()]
    if not items:
        return "None reported."
    return "\n".join(f"- {item}" for item in items)


def format_medications(medications_json: str | None) -> str:
    return _format_item_list(medications_json, "medications")


def format_supplements(supplements_json: str | None) -> str:
    return _format_item_list(supplements_json, "supplements")


def format_active_frameworks(db: Session, user: User) -> str:
    ensure_default_frameworks(db, user.id)
    rows = active_frameworks_for_context(db, user.id)
    if not rows:
        return "No active frameworks yet. Use Settings > Framework to activate prioritized strategies."

    by_type_totals: dict[str, int] = {}
    for row in rows:
        key = str(row.framework_type)
        by_type_totals[key] = by_type_totals.get(key, 0) + max(int(row.priority_score or 0), 0)

    lines: list[str] = []
    for row in rows:
        label = FRAMEWORK_TYPES.get(row.framework_type, {}).get("classifier_label", row.framework_type)
        source = f" [{row.source}]" if row.source else ""
        score = int(row.priority_score or 0)
        total = by_type_totals.get(str(row.framework_type), 0)
        weight_pct = int(round((score / total) * 100)) if total > 0 else 0
        lines.append(f"- ({score}, {weight_pct}% allocation) {row.name} - {label}{source}")
        if row.rationale:
            lines.append(f"  - Rationale: {row.rationale}")
    return "\n".join(lines)


def _cache_prune() -> None:
    if len(_stable_context_cache) <= _STABLE_CONTEXT_CACHE_MAX:
        return
    oldest = sorted(_stable_context_cache.items(), key=lambda kv: kv[1][0])[: max(len(_stable_context_cache) - _STABLE_CONTEXT_CACHE_MAX, 1)]
    for key, _ in oldest:
        _stable_context_cache.pop(key, None)


def _stable_cache_key(db: Session, user: User, specialist: str) -> tuple:
    settings_stamp = (
        getattr(getattr(user, "settings", None), "updated_at", None).isoformat()
        if getattr(getattr(user, "settings", None), "updated_at", None)
        else "none"
    )
    specialist_stamp = (
        getattr(getattr(user, "specialist_config", None), "updated_at", None).isoformat()
        if getattr(getattr(user, "specialist_config", None), "updated_at", None)
        else "none"
    )
    framework_stamp_row = (
        db.query(func.max(HealthOptimizationFramework.updated_at))
        .filter(HealthOptimizationFramework.user_id == user.id)
        .scalar()
    )
    framework_stamp = framework_stamp_row.isoformat() if framework_stamp_row else "none"
    return (user.id, specialist, settings_stamp, specialist_stamp, framework_stamp)


def _build_stable_context_block(db: Session, user: User, specialist: str, overrides: dict, budget: dict[str, int]) -> str:
    blocks: list[str] = []
    blocks.append(get_system_prompt(overrides).strip())
    if specialist and specialist != "orchestrator":
        specialist_prompt = get_specialist_prompt(specialist, overrides)
        if specialist_prompt:
            blocks.append(specialist_prompt.strip())

    display_name = (user.display_name or "").strip()
    username = (user.username or "").strip()
    if display_name or username:
        identity_lines = []
        if display_name:
            identity_lines.append(f"- Name: {display_name}")
        if username and username != display_name:
            identity_lines.append(f"- Username: {username}")
        blocks.append("## User Identity\n" + "\n".join(identity_lines))

    profile = format_user_profile(user.settings)
    blocks.append(_clip_block(f"## Current User Profile\n{profile}", budget["max_profile"]))

    framework_text = format_active_frameworks(db, user)
    blocks.append(
        _clip_block(
            f"## Prioritized Health Optimization Framework\n{framework_text}",
            budget["max_framework"],
        )
    )

    if user.settings:
        meds = format_medications(user.settings.medications)
        supps = format_supplements(user.settings.supplements)
        blocks.append(
            _clip_block(
                f"## Medications\n{meds}\n\n## Supplements\n{supps}",
                budget["max_meds_supps"],
            )
        )

    return "\n\n".join([b for b in blocks if b.strip()]).strip()


def _get_stable_context_block_cached(db: Session, user: User, specialist: str, overrides: dict, budget: dict[str, int]) -> str:
    key = _stable_cache_key(db, user, specialist)
    now_ts = time.monotonic()
    cached = _stable_context_cache.get(key)
    if cached and (now_ts - cached[0]) <= _STABLE_CONTEXT_CACHE_TTL_S:
        return cached[1]

    block = _build_stable_context_block(db, user, specialist, overrides, budget)
    _stable_context_cache[key] = (now_ts, block)
    _cache_prune()
    return block


def compute_today_snapshot(db: Session, user: User, target_date: date | None = None) -> str:
    """Compute a snapshot of today's health data."""
    settings = user.settings
    tz_name = (settings.timezone if settings else None) or None
    d = target_date or today_for_tz(tz_name)
    day_start = start_of_day(d, tz_name)
    day_end = end_of_day(d, tz_name)
    weight_unit = (settings.weight_unit if settings else None) or "kg"
    hydration_unit = (settings.hydration_unit if settings else None) or "ml"

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
        sections.append(f"Hydration: {_format_hydration(total_ml, hydration_unit)}")
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
            parts.append(f"Weight: {_format_weight(vitals.weight_kg, weight_unit)}")
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

    # Sleep (latest entry for the same local day window)
    sleep_logs = (
        db.query(SleepLog)
        .filter(
            SleepLog.user_id == user.id,
            sleep_log_overlaps_window(SleepLog, day_start, day_end),
        )
        .order_by(SleepLog.created_at.desc())
        .limit(15)
        .all()
    )
    if sleep_logs:
        latest_sleep = next(
            (s for s in sleep_logs if s.duration_minutes is not None or s.sleep_end is not None or s.sleep_start is not None),
            None,
        )
        if latest_sleep:
            sleep_parts = []
            if latest_sleep.duration_minutes is not None:
                hours = int(latest_sleep.duration_minutes // 60)
                minutes = int(latest_sleep.duration_minutes % 60)
                sleep_parts.append(f"Duration: {hours}h {minutes}m")
            if latest_sleep.quality:
                sleep_parts.append(f"Quality: {latest_sleep.quality}")
            if latest_sleep.sleep_start:
                sleep_parts.append(f"Start: {latest_sleep.sleep_start.isoformat()}")
            if latest_sleep.sleep_end:
                sleep_parts.append(f"End: {latest_sleep.sleep_end.isoformat()}")
            if sleep_parts:
                sections.append("Latest sleep: " + " | ".join(sleep_parts))

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


def build_context(
    db: Session,
    user: User,
    specialist: str = "orchestrator",
    intent_category: str | None = None,
) -> str:
    """Build context with bounded section budgets and prioritized inclusion."""
    budget = _context_budget(intent_category)
    sections: list[dict[str, object]] = []
    overrides = parse_overrides(user.specialist_config)

    def _add_section(
        text: str,
        *,
        max_chars: int | None = None,
        required: bool = False,
    ) -> None:
        payload = (text or "").strip()
        if not payload:
            return
        if max_chars and max_chars > 0:
            payload = _clip_block(payload, max_chars)
        sections.append({"text": payload, "required": required})

    # 1. Stable context block (cached): prompts, identity, profile, frameworks, meds/supps.
    stable_block = _get_stable_context_block_cached(db, user, specialist, overrides, budget)
    _add_section(stable_block, required=True)

    # 7. Today snapshot
    snapshot = compute_today_snapshot(db, user)
    _add_section(
        f"## Today's Status\n{snapshot}",
        max_chars=budget["max_snapshot"],
        required=True,
    )

    # 8. Approved adaptive guidance (user-approved proposals only)
    from services.analysis_service import get_approved_guidance_for_context
    approved_guidance = get_approved_guidance_for_context(db, user)
    if approved_guidance:
        _add_section(approved_guidance, max_chars=budget["max_guidance"])

    # 9. Recent summaries (lowest priority, clipped first)
    daily = get_latest_summary(db, user, "daily")
    weekly = get_latest_summary(db, user, "weekly")
    if daily:
        _add_section(f"## Yesterday's Summary\n{daily}", max_chars=budget["max_daily_summary"])
    if weekly:
        _add_section(f"## Last Week's Summary\n{weekly}", max_chars=budget["max_weekly_summary"])

    max_total = int(budget["max_total"])
    min_required = int(budget["min_section_chars"])
    selected: list[str] = []
    used = 0
    for section in sections:
        text = str(section.get("text", "")).strip()
        if not text:
            continue
        required = bool(section.get("required", False))
        section_len = len(text)
        join_cost = 2 if selected else 0
        if used + join_cost + section_len <= max_total:
            selected.append(text)
            used += join_cost + section_len
            continue
        if not required:
            continue
        remaining = max_total - used - join_cost
        if remaining < min_required:
            continue
        trimmed = _clip_block(text, remaining)
        if trimmed:
            selected.append(trimmed)
            used += join_cost + len(trimmed)

    return "\n\n".join(selected)
