from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from db.models import (
    CoachingPlanAdjustment,
    CoachingPlanTask,
    DailyChecklistItem,
    ExerciseLog,
    FoodLog,
    HealthOptimizationFramework,
    HydrationLog,
    Notification,
    SleepLog,
    User,
    UserGoal,
    UserSettings,
)
from services.health_framework_service import FRAMEWORK_TYPES, ensure_default_frameworks
from utils.datetime_utils import end_of_day, start_of_day, start_of_week, today_for_tz, sleep_log_overlaps_window
from utils.med_utils import parse_structured_list


CYCLE_TYPES = {"daily", "weekly", "monthly"}
VISIBILITY_MODES = {"top3", "all"}
ADJUSTABLE_METRICS = {"meals_logged", "hydration_ml", "exercise_minutes"}

_TIME_OF_DAY: dict[str, str] = {
    "medication": "morning",
    "supplement": "morning",
    "sleep": "morning",
    "exercise": "afternoon",
    "vitals": "evening",
    "nutrition": "anytime",
    "hydration": "anytime",
    "general": "anytime",
    "framework": "anytime",
}


@dataclass(frozen=True)
class CycleWindow:
    cycle_type: str
    start: date
    end: date

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.cycle_type, self.start.isoformat(), self.end.isoformat())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _tz_name(user: User) -> str | None:
    return getattr(getattr(user, "settings", None), "timezone", None) or None


def _today(user: User) -> date:
    return today_for_tz(_tz_name(user))


def _window_for(cycle_type: str, anchor_day: date) -> CycleWindow:
    ct = str(cycle_type or "").strip().lower()
    if ct == "daily":
        return CycleWindow(cycle_type=ct, start=anchor_day, end=anchor_day)
    if ct == "weekly":
        start = start_of_week(anchor_day)
        return CycleWindow(cycle_type=ct, start=start, end=start + timedelta(days=6))
    if ct == "monthly":
        return CycleWindow(cycle_type=ct, start=anchor_day - timedelta(days=29), end=anchor_day)
    raise ValueError("Unsupported cycle type")


def _days_inclusive(start_day: date, end_day: date) -> int:
    return max(1, (end_day - start_day).days + 1)


def ensure_plan_preferences(settings: UserSettings) -> None:
    mode = str(getattr(settings, "plan_visibility_mode", "") or "").strip().lower()
    if mode not in VISIBILITY_MODES:
        settings.plan_visibility_mode = "top3"
    max_tasks = int(getattr(settings, "plan_max_visible_tasks", 3) or 3)
    settings.plan_max_visible_tasks = max(1, min(max_tasks, 10))


def _active_frameworks(db: Session, user_id: int) -> list[HealthOptimizationFramework]:
    return (
        db.query(HealthOptimizationFramework)
        .filter(
            HealthOptimizationFramework.user_id == user_id,
            HealthOptimizationFramework.is_active.is_(True),
        )
        .order_by(
            HealthOptimizationFramework.framework_type.asc(),
            HealthOptimizationFramework.priority_score.desc(),
            HealthOptimizationFramework.updated_at.desc(),
            HealthOptimizationFramework.id.asc(),
        )
        .all()
    )


def activate_default_frameworks_if_none(db: Session, user: User) -> list[HealthOptimizationFramework]:
    """
    If intake/framework setup was skipped, activate one safe baseline strategy from each framework type.
    """
    ensure_default_frameworks(db, user.id)
    active = _active_frameworks(db, user.id)
    if active:
        return active

    default_by_type: dict[str, str] = {}
    for framework_type, meta in FRAMEWORK_TYPES.items():
        examples = meta.get("examples", [])
        if isinstance(examples, list) and examples:
            default_by_type[framework_type] = str(examples[0]).strip()

    rows = (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user.id)
        .order_by(
            HealthOptimizationFramework.framework_type.asc(),
            HealthOptimizationFramework.priority_score.desc(),
            HealthOptimizationFramework.id.asc(),
        )
        .all()
    )
    updated = 0
    for row in rows:
        expected_name = default_by_type.get(str(row.framework_type))
        if expected_name and str(row.name).strip().lower() == expected_name.lower():
            row.is_active = True
            row.priority_score = max(int(row.priority_score or 0), 55)
            if row.source == "seed":
                row.source = "intake"
            updated += 1
    if updated <= 0:
        # Fallback: activate the highest-priority seed in each framework type.
        seen_types: set[str] = set()
        for row in rows:
            t = str(row.framework_type)
            if t in seen_types:
                continue
            row.is_active = True
            row.priority_score = max(int(row.priority_score or 0), 55)
            if row.source == "seed":
                row.source = "intake"
            seen_types.add(t)
            updated += 1
    db.flush()
    return _active_frameworks(db, user.id)


def _target_defaults(user: User) -> dict[str, float]:
    settings = user.settings
    fitness = str(getattr(settings, "fitness_level", "") or "").strip().lower()
    hydration = 2500.0
    exercise = 30.0
    if fitness in {"sedentary", "lightly_active"}:
        exercise = 20.0
    elif fitness in {"very_active", "extremely_active"}:
        exercise = 40.0
    return {
        "meals_logged": 2.0,
        "hydration_ml": hydration,
        "exercise_minutes": exercise,
        "sleep_minutes": 420.0,
        "food_log_days": 5.0,
        "exercise_sessions": 4.0,
    }


def _framework_weight_pct(frameworks: list[HealthOptimizationFramework], framework_type: str) -> dict[int, int]:
    active = [row for row in frameworks if row.framework_type == framework_type and bool(row.is_active)]
    if not active:
        return {}
    total = sum(max(int(row.priority_score or 0), 0) for row in active)
    if total <= 0:
        base = 100 // len(active)
        extra = 100 - (base * len(active))
        return {int(row.id): base + (1 if idx < extra else 0) for idx, row in enumerate(active)}

    raw = [(row, (max(int(row.priority_score or 0), 0) / total) * 100.0) for row in active]
    floors: dict[int, int] = {int(row.id): int(pct) for row, pct in raw}
    assigned = sum(floors.values())
    remainder = max(100 - assigned, 0)
    ranked = sorted(raw, key=lambda x: (x[1] - int(x[1])), reverse=True)
    for idx in range(remainder):
        row = ranked[idx % len(ranked)][0]
        floors[int(row.id)] += 1
    return floors


def _training_goal_aliases_for_strategy(name: str) -> tuple[str, ...]:
    key = str(name or "").strip().lower()
    aliases: tuple[str, ...] = (key,)
    if "hiit" in key:
        aliases = ("hiit", "high intensity", "high-intensity")
    elif "strength" in key:
        aliases = ("strength", "strength training", "weights", "weight training", "resistance")
    elif "zone" in key and "2" in key:
        aliases = ("zone 2", "zone2")
    elif "crossfit" in key:
        aliases = ("crossfit",)
    elif "5x5" in key:
        aliases = ("5x5",)
    return aliases


def _extract_training_goal_counts(
    db: Session,
    user: User,
    training_rows: list[HealthOptimizationFramework],
) -> dict[int, int]:
    if not training_rows:
        return {}
    rows = (
        db.query(UserGoal)
        .filter(UserGoal.user_id == user.id, UserGoal.status == "active")
        .order_by(UserGoal.updated_at.desc(), UserGoal.created_at.desc(), UserGoal.id.desc())
        .all()
    )
    if not rows:
        return {}

    text_parts: list[str] = []
    for goal in rows[:20]:
        for value in (goal.title, goal.description, goal.why):
            if value and str(value).strip():
                text_parts.append(str(value).strip().lower())
    corpus = " ".join(text_parts)
    if not corpus:
        return {}

    out: dict[int, int] = {}
    for row in training_rows:
        aliases = _training_goal_aliases_for_strategy(row.name)
        count = 0
        for alias in aliases:
            pattern_a = re.compile(
                rf"(\d+)\s*(?:x|times?|sessions?|workouts?)?\s*(?:of\s+)?{re.escape(alias)}",
                flags=re.IGNORECASE,
            )
            pattern_b = re.compile(
                rf"{re.escape(alias)}(?:\s+training)?[^0-9]{{0,16}}(\d+)\s*(?:x|times?|sessions?|workouts?)",
                flags=re.IGNORECASE,
            )
            matches_a = [int(m.group(1)) for m in pattern_a.finditer(corpus)]
            matches_b = [int(m.group(1)) for m in pattern_b.finditer(corpus)]
            if matches_a:
                count = max(count, max(matches_a))
            if matches_b:
                count = max(count, max(matches_b))
        if count > 0:
            out[int(row.id)] = max(0, min(count, 7))
    return out


def _distribute_training_sessions(
    training_rows: list[HealthOptimizationFramework],
    *,
    weekly_sessions_target: int,
    explicit_counts: dict[int, int],
) -> dict[int, int]:
    if not training_rows:
        return {}
    sessions = max(0, min(int(weekly_sessions_target), 7))
    if sessions == 0:
        return {}

    explicit_total = sum(max(int(v), 0) for v in explicit_counts.values())
    if explicit_total > 0:
        normalized: dict[int, int] = {}
        for row in training_rows:
            normalized[int(row.id)] = max(int(explicit_counts.get(int(row.id), 0)), 0)
        if explicit_total <= sessions:
            remaining = sessions - explicit_total
            if remaining > 0:
                weights = _framework_weight_pct(training_rows, "training")
                ranked = sorted(training_rows, key=lambda r: (weights.get(int(r.id), 0), int(r.priority_score or 0)), reverse=True)
                idx = 0
                while remaining > 0 and ranked:
                    target = ranked[idx % len(ranked)]
                    normalized[int(target.id)] += 1
                    remaining -= 1
                    idx += 1
            return normalized

        scale = sessions / float(explicit_total)
        scaled_raw = [(int(row.id), max(float(explicit_counts.get(int(row.id), 0)), 0.0) * scale) for row in training_rows]
        base = {rid: int(val) for rid, val in scaled_raw}
        assigned = sum(base.values())
        remainder = max(sessions - assigned, 0)
        ranked = sorted(scaled_raw, key=lambda x: (x[1] - int(x[1])), reverse=True)
        for idx in range(remainder):
            rid = ranked[idx % len(ranked)][0]
            base[rid] += 1
        return base

    weights = _framework_weight_pct(training_rows, "training")
    raw = [(int(row.id), (weights.get(int(row.id), 0) / 100.0) * sessions) for row in training_rows]
    base = {rid: int(val) for rid, val in raw}
    assigned = sum(base.values())
    remainder = max(sessions - assigned, 0)
    ranked = sorted(raw, key=lambda x: (x[1] - int(x[1])), reverse=True)
    for idx in range(remainder):
        rid = ranked[idx % len(ranked)][0]
        base[rid] += 1
    return base


def _weekly_training_schedule(
    training_rows: list[HealthOptimizationFramework],
    counts: dict[int, int],
) -> list[int | None]:
    schedule: list[int | None] = [None] * 7
    remaining = {int(row.id): max(int(counts.get(int(row.id), 0)), 0) for row in training_rows}
    total = min(sum(remaining.values()), 7)
    last: int | None = None
    for day_idx in range(total):
        candidates = [rid for rid, cnt in remaining.items() if cnt > 0]
        if not candidates:
            break
        candidates.sort(
            key=lambda rid: (
                remaining[rid],
                0 if rid != last else -1,
                rid,
            ),
            reverse=True,
        )
        pick = candidates[0]
        if len(candidates) > 1 and pick == last:
            pick = candidates[1]
        schedule[day_idx] = pick
        remaining[pick] -= 1
        last = pick
    return schedule


def _task_template_rows(
    db: Session,
    user: User,
    window: CycleWindow,
    frameworks: list[HealthOptimizationFramework],
) -> list[dict[str, Any]]:
    defaults = _target_defaults(user)
    due_at = end_of_day(window.end, _tz_name(user))
    meds = parse_structured_list(user.settings.medications if user.settings else None)
    supps = parse_structured_list(user.settings.supplements if user.settings else None)
    active_frameworks = [row for row in frameworks if bool(row.is_active)]
    by_type: dict[str, list[HealthOptimizationFramework]] = {}
    for row in active_frameworks:
        by_type.setdefault(str(row.framework_type), []).append(row)
    for key in by_type:
        by_type[key].sort(key=lambda r: (int(r.priority_score or 0), r.updated_at or datetime.min), reverse=True)

    rows: list[dict[str, Any]] = []
    if window.cycle_type == "daily":
        rows.extend(
            [
                {
                    "target_metric": "meals_logged",
                    "title": "Log your core meals",
                    "description": "Log at least two meals today so coaching stays calibrated.",
                    "domain": "nutrition",
                    "priority_score": 92,
                    "target_value": defaults["meals_logged"],
                    "target_unit": "count",
                },
                {
                    "target_metric": "hydration_ml",
                    "title": "Hit your hydration target",
                    "description": "Log water intake across the day.",
                    "domain": "hydration",
                    "priority_score": 88,
                    "target_value": defaults["hydration_ml"],
                    "target_unit": "ml",
                },
                {
                    "target_metric": "exercise_minutes",
                    "title": "Complete movement target",
                    "description": "Log planned movement minutes.",
                    "domain": "exercise",
                    "priority_score": 86,
                    "target_value": defaults["exercise_minutes"],
                    "target_unit": "minutes",
                },
                {
                    "target_metric": "sleep_minutes",
                    "title": "Protect sleep window",
                    "description": "Aim for at least 7 hours and log sleep start/end.",
                    "domain": "sleep",
                    "priority_score": 82,
                    "target_value": defaults["sleep_minutes"],
                    "target_unit": "minutes",
                },
            ]
        )
        if meds:
            rows.append(
                {
                    "target_metric": "medication_adherence",
                    "title": "Medication adherence check",
                    "description": "Mark medications as taken when completed.",
                    "domain": "medication",
                    "priority_score": 96,
                    "target_value": 1.0,
                    "target_unit": "ratio",
                }
            )
        if supps:
            rows.append(
                {
                    "target_metric": "supplement_adherence",
                    "title": "Supplement adherence check",
                    "description": "Mark supplements as taken when completed.",
                    "domain": "supplement",
                    "priority_score": 78,
                    "target_value": 1.0,
                    "target_unit": "ratio",
                }
            )
    elif window.cycle_type == "weekly":
        rows.extend(
            [
                {
                    "target_metric": "food_log_days",
                    "title": "Nutrition consistency",
                    "description": "Log meals on at least 5 days this week.",
                    "domain": "nutrition",
                    "priority_score": 90,
                    "target_value": defaults["food_log_days"],
                    "target_unit": "days",
                },
                {
                    "target_metric": "exercise_sessions",
                    "title": "Training consistency",
                    "description": "Complete at least 4 exercise sessions this week.",
                    "domain": "exercise",
                    "priority_score": 88,
                    "target_value": defaults["exercise_sessions"],
                    "target_unit": "sessions",
                },
                {
                    "target_metric": "hydration_ml",
                    "title": "Hydration average",
                    "description": "Maintain hydration habits all week.",
                    "domain": "hydration",
                    "priority_score": 82,
                    "target_value": defaults["hydration_ml"] * _days_inclusive(window.start, window.end),
                    "target_unit": "ml_total",
                },
            ]
        )
    else:
        rows.extend(
            [
                {
                    "target_metric": "food_log_days",
                    "title": "Rolling nutrition adherence",
                    "description": "Log meals on at least 20 of the last 30 days.",
                    "domain": "nutrition",
                    "priority_score": 88,
                    "target_value": 20.0,
                    "target_unit": "days",
                },
                {
                    "target_metric": "exercise_sessions",
                    "title": "Rolling movement adherence",
                    "description": "Complete at least 16 sessions in the last 30 days.",
                    "domain": "exercise",
                    "priority_score": 86,
                    "target_value": 16.0,
                    "target_unit": "sessions",
                },
                {
                    "target_metric": "sleep_minutes",
                    "title": "Rolling sleep quality",
                    "description": "Average at least 7 hours sleep over the last 30 days.",
                    "domain": "sleep",
                    "priority_score": 80,
                    "target_value": defaults["sleep_minutes"],
                    "target_unit": "minutes_avg",
                },
            ]
        )

    non_training_types = [t for t in FRAMEWORK_TYPES.keys() if t != "training"]
    for framework_type in non_training_types:
        selected = by_type.get(framework_type, [])
        if not selected:
            continue
        framework = selected[0]
        rows.append(
            {
                "target_metric": "manual_check",
                "title": f"Follow {framework.name} today",
                "description": f"Use your active {FRAMEWORK_TYPES.get(framework.framework_type, {}).get('label', framework.framework_type)} strategy in decisions.",
                "domain": "framework",
                "framework_type": framework.framework_type,
                "framework_name": framework.name,
                "priority_score": max(60, min(int(framework.priority_score or 60), 95)),
                "target_value": 1.0,
                "target_unit": "check",
            }
        )

    training_rows = by_type.get("training", [])
    if training_rows and window.cycle_type == "daily":
        explicit_counts = _extract_training_goal_counts(db, user, training_rows)
        session_target = int(round(defaults.get("exercise_sessions", 4.0)))
        distributed = _distribute_training_sessions(
            training_rows,
            weekly_sessions_target=session_target,
            explicit_counts=explicit_counts,
        )
        schedule = _weekly_training_schedule(training_rows, distributed)
        weekday_idx = max(0, min(window.start.weekday(), 6))
        selected_id = schedule[weekday_idx]
        if selected_id is not None:
            selected = next((row for row in training_rows if int(row.id) == int(selected_id)), None)
            if selected:
                rows.append(
                    {
                        "target_metric": "manual_check",
                        "title": f"Follow {selected.name} today",
                        "description": "Use your active Training Framework strategy in decisions.",
                        "domain": "framework",
                        "framework_type": selected.framework_type,
                        "framework_name": selected.name,
                        "priority_score": max(60, min(int(selected.priority_score or 60), 95)),
                        "target_value": 1.0,
                        "target_unit": "check",
                    }
                )
    elif training_rows:
        # Weekly/monthly views keep one representative training strategy.
        selected = training_rows[0]
        rows.append(
            {
                "target_metric": "manual_check",
                "title": f"Follow {selected.name} today",
                "description": "Use your active Training Framework strategy in decisions.",
                "domain": "framework",
                "framework_type": selected.framework_type,
                "framework_name": selected.name,
                "priority_score": max(60, min(int(selected.priority_score or 60), 95)),
                "target_value": 1.0,
                "target_unit": "check",
            }
        )

    for row in rows:
        row["cycle_type"] = window.cycle_type
        row["cycle_start"] = window.start.isoformat()
        row["cycle_end"] = window.end.isoformat()
        row["status"] = "pending"
        row["progress_pct"] = 0.0
        row["time_of_day"] = _TIME_OF_DAY.get(str(row.get("domain") or "general"), "anytime")
        row["due_at"] = due_at
        row["source"] = "system"
        row["framework_type"] = row.get("framework_type") or ""
        row["framework_name"] = row.get("framework_name") or ""
        row["metadata_json"] = _json_dump({"auto_seeded": True})
    return rows


def _ensure_window_tasks(db: Session, user: User, window: CycleWindow, frameworks: list[HealthOptimizationFramework]) -> int:
    payload_rows = _task_template_rows(db, user, window, frameworks)
    if window.cycle_type == "daily":
        desired_training_names = {
            str(row.get("framework_name") or "")
            for row in payload_rows
            if row.get("target_metric") == "manual_check" and str(row.get("framework_type") or "") == "training"
        }
        stale_training = (
            db.query(CoachingPlanTask)
            .filter(
                CoachingPlanTask.user_id == user.id,
                CoachingPlanTask.cycle_type == "daily",
                CoachingPlanTask.cycle_start == window.start.isoformat(),
                CoachingPlanTask.target_metric == "manual_check",
                CoachingPlanTask.framework_type == "training",
                CoachingPlanTask.status == "pending",
            )
            .all()
        )
        for row in stale_training:
            if str(row.framework_name or "") not in desired_training_names:
                db.delete(row)
        db.flush()

    existing = (
        db.query(CoachingPlanTask.target_metric, CoachingPlanTask.framework_name)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == window.cycle_type,
            CoachingPlanTask.cycle_start == window.start.isoformat(),
        )
        .all()
    )
    existing_keys = {(str(metric), str(name or "")) for metric, name in existing}
    created = 0
    for payload in payload_rows:
        dedupe_key = (str(payload["target_metric"]), str(payload.get("framework_name") or ""))
        if dedupe_key in existing_keys:
            continue
        row = CoachingPlanTask(user_id=user.id, **payload)
        db.add(row)
        created += 1
    if created:
        db.flush()
    return created


def ensure_plan_seeded(
    db: Session,
    user: User,
    *,
    reference_day: date | None = None,
    allow_auto_activate_defaults: bool = True,
) -> dict[str, Any]:
    settings = user.settings
    if not settings:
        return {"created": 0}
    ensure_plan_preferences(settings)
    frameworks = activate_default_frameworks_if_none(db, user) if allow_auto_activate_defaults else _active_frameworks(db, user.id)

    day = reference_day or _today(user)
    windows = [_window_for("daily", day), _window_for("weekly", day), _window_for("monthly", day)]
    created = 0
    for window in windows:
        created += _ensure_window_tasks(db, user, window, frameworks)
    return {"created": created}


def _clear_pending_framework_tasks(
    db: Session,
    user_id: int,
    *,
    reference_day: date,
) -> int:
    return int(
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user_id,
            CoachingPlanTask.domain == "framework",
            CoachingPlanTask.status == "pending",
            CoachingPlanTask.cycle_end >= reference_day.isoformat(),
        )
        .delete(synchronize_session=False)
        or 0
    )


def apply_framework_selection(
    db: Session,
    user: User,
    *,
    selected_framework_ids: list[int] | None,
) -> dict[str, Any]:
    ensure_default_frameworks(db, user.id)
    all_rows = (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user.id)
        .all()
    )
    known_ids = {int(row.id) for row in all_rows}
    selected_ids = {int(v) for v in (selected_framework_ids or []) if int(v) > 0}
    unknown = sorted(selected_ids - known_ids)
    if unknown:
        raise ValueError(f"Unknown framework ids: {', '.join(str(v) for v in unknown)}")

    changed = 0
    activated = 0
    deactivated = 0
    for row in all_rows:
        should_be_active = int(row.id) in selected_ids
        if bool(row.is_active) != should_be_active:
            row.is_active = should_be_active
            changed += 1
            if should_be_active:
                activated += 1
            else:
                deactivated += 1
        if should_be_active:
            row.priority_score = max(int(row.priority_score or 0), 60)
            if row.source == "seed":
                row.source = "user"
            if not row.rationale:
                row.rationale = "Selected during intake handoff plan setup."

    day = _today(user)
    removed_framework_tasks = _clear_pending_framework_tasks(db, user.id, reference_day=day)
    ensure_plan_seeded(db, user, reference_day=day, allow_auto_activate_defaults=False)
    refresh_task_statuses(db, user, reference_day=day, create_notifications=False)

    return {
        "changed": changed,
        "activated": activated,
        "deactivated": deactivated,
        "removed_framework_tasks": removed_framework_tasks,
        "selected_count": len(selected_ids),
    }


def _collect_metric_values(db: Session, user: User, window: CycleWindow) -> dict[str, float | None]:
    tz_name = _tz_name(user)
    start_dt = start_of_day(window.start, tz_name)
    end_dt = end_of_day(window.end, tz_name)
    days = _days_inclusive(window.start, window.end)

    foods = (
        db.query(FoodLog)
        .filter(FoodLog.user_id == user.id, FoodLog.logged_at >= start_dt, FoodLog.logged_at <= end_dt)
        .all()
    )
    hydration = (
        db.query(HydrationLog)
        .filter(HydrationLog.user_id == user.id, HydrationLog.logged_at >= start_dt, HydrationLog.logged_at <= end_dt)
        .all()
    )
    exercise = (
        db.query(ExerciseLog)
        .filter(ExerciseLog.user_id == user.id, ExerciseLog.logged_at >= start_dt, ExerciseLog.logged_at <= end_dt)
        .all()
    )
    sleep = (
        db.query(SleepLog)
        .filter(
            SleepLog.user_id == user.id,
            sleep_log_overlaps_window(SleepLog, start_dt, end_dt),
        )
        .all()
    )
    checklist = (
        db.query(DailyChecklistItem)
        .filter(
            DailyChecklistItem.user_id == user.id,
            DailyChecklistItem.target_date >= window.start.isoformat(),
            DailyChecklistItem.target_date <= window.end.isoformat(),
        )
        .all()
    )

    meal_days = {str(row.logged_at.date().isoformat()) for row in foods if row.logged_at}
    meds = parse_structured_list(user.settings.medications if user.settings else None)
    supps = parse_structured_list(user.settings.supplements if user.settings else None)
    expected_med = len(meds) * days
    expected_supp = len(supps) * days
    completed_med = sum(1 for item in checklist if item.item_type == "medication" and bool(item.completed))
    completed_supp = sum(1 for item in checklist if item.item_type == "supplement" and bool(item.completed))

    sleep_values = [float(s.duration_minutes) for s in sleep if s.duration_minutes is not None and float(s.duration_minutes) >= 0.0]
    # Daily sleep goals should credit the best complete sleep session in the day window.
    # Averaging with partial/duplicate rows can incorrectly keep daily sleep goals pending.
    if window.cycle_type == "daily":
        sleep_metric = max(sleep_values) if sleep_values else None
    else:
        sleep_metric = (sum(sleep_values) / len(sleep_values)) if sleep_values else None

    return {
        "meals_logged": float(len(foods)),
        "food_log_days": float(len(meal_days)),
        "hydration_ml": float(sum(h.amount_ml or 0 for h in hydration)),
        "exercise_minutes": float(sum(e.duration_minutes or 0 for e in exercise)),
        "exercise_sessions": float(len(exercise)),
        "sleep_minutes": sleep_metric,
        "medication_adherence": (float(completed_med) / float(expected_med)) if expected_med > 0 else None,
        "supplement_adherence": (float(completed_supp) / float(expected_supp)) if expected_supp > 0 else None,
    }


def _progress_for_task(task: CoachingPlanTask, metrics: dict[str, float | None]) -> float:
    metric = str(task.target_metric or "")
    target = float(task.target_value or 0.0)
    if metric == "manual_check":
        return 100.0 if str(task.status) == "completed" else 0.0
    value = metrics.get(metric)
    if value is None or target <= 0:
        return 0.0
    return max(0.0, (float(value) / target) * 100.0)


def _create_missed_task_notification(db: Session, user: User, task: CoachingPlanTask, today_local: date) -> None:
    dedupe_key = f"missed_task:{task.id}:{task.cycle_end}"
    recent = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.category == "reminder",
            Notification.created_at >= start_of_day(today_local - timedelta(days=31), _tz_name(user)),
        )
        .all()
    )
    for row in recent:
        payload = _safe_json_loads(row.payload, {})
        if isinstance(payload, dict) and str(payload.get("dedupe_key", "")) == dedupe_key:
            return

    why = str(getattr(getattr(user, "settings", None), "coaching_why", "") or "").strip()
    why_suffix = f" Remember why you're doing this: {why}" if why else ""
    reminder = Notification(
        user_id=user.id,
        category="reminder",
        title=f"Missed goal: {task.title}",
        message=f"You missed this objective. Re-enter today with one small action.{why_suffix}",
        payload=_json_dump(
            {
                "kind": "missed_goal",
                "task_id": task.id,
                "cycle_type": task.cycle_type,
                "cycle_start": task.cycle_start,
                "cycle_end": task.cycle_end,
                "dedupe_key": dedupe_key,
            }
        ),
    )
    db.add(reminder)


def refresh_task_statuses(
    db: Session,
    user: User,
    *,
    reference_day: date | None = None,
    create_notifications: bool = True,
) -> dict[str, Any]:
    day = reference_day or _today(user)
    ensure_plan_seeded(db, user, reference_day=day)

    windows = [_window_for("daily", day), _window_for("weekly", day), _window_for("monthly", day)]
    by_key = {w.key: w for w in windows}
    touched = 0
    completed = 0
    missed = 0

    tasks = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_end >= (day - timedelta(days=45)).isoformat(),
        )
        .all()
    )

    metric_cache: dict[tuple[str, str, str], dict[str, float | None]] = {}
    for task in tasks:
        key = (str(task.cycle_type), str(task.cycle_start), str(task.cycle_end))
        window = by_key.get(key)
        if not window:
            try:
                window = CycleWindow(
                    cycle_type=str(task.cycle_type),
                    start=date.fromisoformat(str(task.cycle_start)),
                    end=date.fromisoformat(str(task.cycle_end)),
                )
            except Exception:
                continue
        if key not in metric_cache:
            metric_cache[key] = _collect_metric_values(db, user, window)
        metrics = metric_cache[key]
        # Keep daily sleep task semantics stable at 7 hours (420 minutes).
        # Historical auto-adjustments may have raised this value and caused
        # users to appear "pending" despite meeting the documented threshold.
        if str(task.cycle_type) == "daily" and str(task.target_metric) == "sleep_minutes":
            if task.target_value is None or float(task.target_value or 0.0) != 420.0:
                task.target_value = 420.0
        progress = _progress_for_task(task, metrics)
        task.progress_pct = round(progress, 2)
        previous = str(task.status or "pending")
        new_status = previous
        if previous == "skipped":
            continue
        if previous != "completed" and progress >= 100.0:
            new_status = "completed"
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
        elif previous == "pending" and date.fromisoformat(str(task.cycle_end)) < day and progress < 100.0:
            new_status = "missed"
            if create_notifications:
                _create_missed_task_notification(db, user, task, day)
        elif previous == "missed" and date.fromisoformat(str(task.cycle_end)) >= day and progress < 100.0:
            # If status became "missed" due to a prior forward-looking evaluation,
            # restore it while the task window is still active.
            new_status = "pending"
            task.completed_at = None
        elif previous == "missed" and progress >= 100.0:
            new_status = "completed"
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
        task.status = new_status
        if new_status != previous:
            touched += 1
        if new_status == "completed":
            completed += 1
        if new_status == "missed":
            missed += 1

    return {"updated": touched, "completed": completed, "missed": missed}


def _apply_weekly_adjustment_if_due(db: Session, user: User, reference_day: date) -> CoachingPlanAdjustment | None:
    """
    Apply automatic target scaling once per completed weekly window.
    """
    this_week_start = start_of_week(reference_day)
    last_week_end = this_week_start - timedelta(days=1)
    cycle_anchor = last_week_end.isoformat()
    existing = (
        db.query(CoachingPlanAdjustment)
        .filter(
            CoachingPlanAdjustment.user_id == user.id,
            CoachingPlanAdjustment.cycle_anchor == cycle_anchor,
            CoachingPlanAdjustment.source == "plan_engine_weekly",
        )
        .first()
    )
    if existing:
        return None

    weekly_tasks = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "weekly",
            CoachingPlanTask.cycle_end == cycle_anchor,
        )
        .all()
    )
    if not weekly_tasks:
        return None

    total = len(weekly_tasks)
    done = sum(1 for row in weekly_tasks if str(row.status) == "completed")
    completion = (done / total) if total > 0 else 0.0

    if completion >= 0.85:
        factor = 1.10
        title = "Auto-adjustment: targets increased"
        rationale = "Weekly completion exceeded 85%. Targets increased 10% to keep momentum."
    elif completion < 0.50:
        factor = 0.90
        title = "Auto-adjustment: targets eased"
        rationale = "Weekly completion fell below 50%. Targets reduced 10% to improve consistency."
    else:
        return None

    now = datetime.now(timezone.utc)
    pending_tasks = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.status == "pending",
            CoachingPlanTask.target_value.isnot(None),
            CoachingPlanTask.target_metric.in_(ADJUSTABLE_METRICS),
            CoachingPlanTask.cycle_end >= reference_day.isoformat(),
        )
        .all()
    )
    changes: list[dict[str, Any]] = []
    for row in pending_tasks:
        old = float(row.target_value or 0.0)
        if old <= 0:
            continue
        new_val = round(old * factor, 2)
        if factor < 1.0:
            # Prevent easing from dropping goals too low.
            if row.target_metric == "meals_logged":
                new_val = max(new_val, 1.0)
            elif row.target_metric == "sleep_minutes":
                new_val = max(new_val, 360.0)
            elif row.target_metric == "exercise_minutes":
                new_val = max(new_val, 10.0)
            elif row.target_metric == "hydration_ml":
                new_val = max(new_val, 1200.0)
        row.target_value = new_val
        changes.append(
            {
                "task_id": int(row.id),
                "old_target_value": old,
                "new_target_value": new_val,
            }
        )

    if not changes:
        return None

    adjustment = CoachingPlanAdjustment(
        user_id=user.id,
        cycle_anchor=cycle_anchor,
        title=title,
        rationale=rationale,
        change_json=_json_dump({"factor": factor, "completion_ratio": round(completion, 4), "changes": changes}),
        status="applied",
        applied_at=now,
        undo_expires_at=now + timedelta(days=30),
        source="plan_engine_weekly",
    )
    db.add(adjustment)
    db.add(
        Notification(
            user_id=user.id,
            category="info",
            title=title,
            message=f"{rationale} You can undo this within 30 days.",
            payload=_json_dump({"kind": "plan_adjustment", "cycle_anchor": cycle_anchor}),
        )
    )
    db.flush()
    return adjustment


def maybe_apply_weekly_adjustment(db: Session, user: User, reference_day: date | None = None) -> CoachingPlanAdjustment | None:
    day = reference_day or _today(user)
    return _apply_weekly_adjustment_if_due(db, user, day)


def undo_adjustment(db: Session, user: User, adjustment_id: int) -> CoachingPlanAdjustment:
    row = (
        db.query(CoachingPlanAdjustment)
        .filter(
            CoachingPlanAdjustment.id == adjustment_id,
            CoachingPlanAdjustment.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise ValueError("Adjustment not found")
    if str(row.status) != "applied":
        raise ValueError("Adjustment cannot be undone")
    now = datetime.now(timezone.utc)
    expires_at = row.undo_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < now:
        row.status = "expired"
        db.flush()
        raise ValueError("Undo window expired")

    payload = _safe_json_loads(row.change_json, {})
    changes = payload.get("changes", []) if isinstance(payload, dict) else []
    if not isinstance(changes, list):
        changes = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        task_id = int(change.get("task_id", 0) or 0)
        old_target = change.get("old_target_value")
        task = (
            db.query(CoachingPlanTask)
            .filter(CoachingPlanTask.user_id == user.id, CoachingPlanTask.id == task_id)
            .first()
        )
        if not task:
            continue
        if old_target is not None:
            task.target_value = float(old_target)

    row.status = "undone"
    row.undone_at = now
    db.add(
        Notification(
            user_id=user.id,
            category="info",
            title="Adjustment undone",
            message=f"Reverted: {row.title}",
            payload=_json_dump({"kind": "plan_adjustment_undo", "adjustment_id": row.id}),
        )
    )
    db.flush()
    return row


def set_plan_preferences(
    db: Session,
    user: User,
    *,
    visibility_mode: str | None = None,
    max_visible_tasks: int | None = None,
    coaching_why: str | None = None,
) -> UserSettings:
    settings = user.settings
    if not settings:
        raise ValueError("User settings not found")

    if visibility_mode is not None:
        mode = str(visibility_mode).strip().lower()
        if mode not in VISIBILITY_MODES:
            raise ValueError("visibility_mode must be top3 or all")
        settings.plan_visibility_mode = mode
    if max_visible_tasks is not None:
        settings.plan_max_visible_tasks = max(1, min(int(max_visible_tasks), 10))
    if coaching_why is not None:
        clean_why = " ".join(str(coaching_why).split()).strip()
        settings.coaching_why = clean_why or None

    ensure_plan_preferences(settings)
    db.flush()
    return settings


def _task_to_dict(task: CoachingPlanTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "cycle_type": task.cycle_type,
        "cycle_start": task.cycle_start,
        "cycle_end": task.cycle_end,
        "target_metric": task.target_metric,
        "title": task.title,
        "description": task.description,
        "domain": task.domain,
        "framework_type": task.framework_type or None,
        "framework_name": task.framework_name or None,
        "priority_score": int(task.priority_score or 0),
        "target_value": task.target_value,
        "target_unit": task.target_unit,
        "status": task.status,
        "progress_pct": float(task.progress_pct or 0.0),
        "time_of_day": task.time_of_day or "anytime",
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "source": task.source,
    }


def _notification_to_dict(row: Notification) -> dict[str, Any]:
    payload = _safe_json_loads(row.payload, {})
    return {
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "message": row.message,
        "is_read": bool(row.is_read),
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _adjustment_to_dict(row: CoachingPlanAdjustment) -> dict[str, Any]:
    payload = _safe_json_loads(row.change_json, {})
    expires_at = row.undo_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return {
        "id": row.id,
        "cycle_anchor": row.cycle_anchor,
        "title": row.title,
        "rationale": row.rationale,
        "status": row.status,
        "source": row.source,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "undo_expires_at": row.undo_expires_at.isoformat() if row.undo_expires_at else None,
        "undone_at": row.undone_at.isoformat() if row.undone_at else None,
        "undo_available": bool(row.status == "applied" and expires_at and expires_at >= datetime.now(timezone.utc)),
        "change": payload if isinstance(payload, dict) else {},
    }


def _completion_stats(tasks: list[CoachingPlanTask]) -> dict[str, Any]:
    total = len(tasks)
    completed = sum(1 for row in tasks if str(row.status) == "completed")
    missed = sum(1 for row in tasks if str(row.status) == "missed")
    pending = sum(1 for row in tasks if str(row.status) == "pending")
    skipped = sum(1 for row in tasks if str(row.status) == "skipped")
    ratio = (completed / total) if total > 0 else 0.0
    return {
        "total": total,
        "completed": completed,
        "missed": missed,
        "pending": pending,
        "skipped": skipped,
        "completion_ratio": round(ratio, 4),
    }


def _daily_streaks(db: Session, user: User, today_local: date) -> dict[str, int]:
    rows = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_end >= (today_local - timedelta(days=45)).isoformat(),
        )
        .all()
    )
    by_day: dict[str, list[CoachingPlanTask]] = {}
    for row in rows:
        by_day.setdefault(str(row.cycle_start), []).append(row)

    complete_streak = 0
    miss_streak = 0
    cursor = today_local
    while True:
        key = cursor.isoformat()
        day_rows = by_day.get(key, [])
        if not day_rows:
            break
        stats = _completion_stats(day_rows)
        if stats["completion_ratio"] >= 0.7:
            complete_streak += 1
        else:
            break
        cursor = cursor - timedelta(days=1)

    cursor = today_local
    while True:
        key = cursor.isoformat()
        day_rows = by_day.get(key, [])
        if not day_rows:
            break
        stats = _completion_stats(day_rows)
        if stats["missed"] > 0 and stats["completion_ratio"] < 0.5:
            miss_streak += 1
        else:
            break
        cursor = cursor - timedelta(days=1)

    return {"completed_daily_streak": complete_streak, "missed_daily_streak": miss_streak}


def _reward_summary(db: Session, user: User, today_local: date) -> dict[str, Any]:
    rows = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.status == "completed",
            CoachingPlanTask.cycle_end >= (today_local - timedelta(days=30)).isoformat(),
        )
        .all()
    )
    points = len(rows) * 10
    streaks = _daily_streaks(db, user, today_local)
    badges: list[str] = []
    if streaks["completed_daily_streak"] >= 3:
        badges.append("3-day consistency")
    if streaks["completed_daily_streak"] >= 7:
        badges.append("7-day streak")
    if points >= 300:
        badges.append("Momentum 300")
    return {"points_30d": points, "badges": badges, **streaks}


def get_plan_snapshot(
    db: Session,
    user: User,
    *,
    cycle_type: str = "daily",
    reference_day: date | None = None,
    create_notifications: bool = True,
    allow_adjustments: bool = True,
) -> dict[str, Any]:
    ct = str(cycle_type or "daily").strip().lower()
    if ct not in CYCLE_TYPES:
        ct = "daily"

    day = reference_day or _today(user)
    ensure_plan_seeded(db, user, reference_day=day)
    refresh_task_statuses(db, user, reference_day=day, create_notifications=create_notifications)
    if allow_adjustments:
        maybe_apply_weekly_adjustment(db, user, reference_day=day)
    # Refresh once more after potential target changes.
    refresh_task_statuses(db, user, reference_day=day, create_notifications=False)

    window = _window_for(ct, day)
    tasks = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == window.cycle_type,
            CoachingPlanTask.cycle_start == window.start.isoformat(),
        )
        .order_by(CoachingPlanTask.priority_score.desc(), CoachingPlanTask.id.asc())
        .all()
    )
    stats = _completion_stats(tasks)

    settings = user.settings
    visibility = str(getattr(settings, "plan_visibility_mode", "top3") or "top3").strip().lower()
    if visibility not in VISIBILITY_MODES:
        visibility = "top3"
    max_visible = max(1, min(int(getattr(settings, "plan_max_visible_tasks", 3) or 3), 10))
    top_limit = max_visible if visibility == "top3" else len(tasks)

    pending_sorted = sorted(
        [row for row in tasks if row.status == "pending"],
        key=lambda r: (-int(r.priority_score or 0), r.id),
    )
    upcoming = pending_sorted[:top_limit]
    if visibility == "all":
        upcoming = tasks

    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(20)
        .all()
    )
    adjustments = (
        db.query(CoachingPlanAdjustment)
        .filter(CoachingPlanAdjustment.user_id == user.id)
        .order_by(CoachingPlanAdjustment.applied_at.desc())
        .limit(20)
        .all()
    )
    reward = _reward_summary(db, user, day)

    return {
        "cycle": {
            "cycle_type": window.cycle_type,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "today": day.isoformat(),
            "timezone": _tz_name(user),
        },
        "preferences": {
            "visibility_mode": visibility,
            "max_visible_tasks": max_visible,
            "coaching_why": getattr(settings, "coaching_why", None),
        },
        "stats": stats,
        "reward": reward,
        "tasks": [_task_to_dict(row) for row in tasks],
        "upcoming_tasks": [_task_to_dict(row) for row in upcoming],
        "notifications": [_notification_to_dict(row) for row in notifications],
        "adjustments": [_adjustment_to_dict(row) for row in adjustments],
    }


def get_daily_rolling_snapshot(
    db: Session,
    user: User,
    *,
    days: int = 5,
) -> dict[str, Any]:
    window_days = max(1, min(int(days or 5), 14))
    start_day = _today(user)
    day_payloads: list[dict[str, Any]] = []
    for offset in range(window_days):
        anchor = start_day + timedelta(days=offset)
        snapshot = get_plan_snapshot(
            db=db,
            user=user,
            cycle_type="daily",
            reference_day=anchor,
            create_notifications=False,
            allow_adjustments=False,
        )
        day_payloads.append(snapshot)

    weekly = get_plan_snapshot(
        db=db,
        user=user,
        cycle_type="weekly",
        reference_day=start_day,
        create_notifications=False,
        allow_adjustments=False,
    )
    monthly = get_plan_snapshot(
        db=db,
        user=user,
        cycle_type="monthly",
        reference_day=start_day,
        create_notifications=False,
        allow_adjustments=False,
    )

    return {
        "timezone": _tz_name(user),
        "start_date": start_day.isoformat(),
        "window_days": window_days,
        "days": day_payloads,
        "weekly": {
            "cycle": weekly.get("cycle", {}),
            "stats": weekly.get("stats", {}),
            "upcoming_tasks": weekly.get("upcoming_tasks", []),
        },
        "monthly": {
            "cycle": monthly.get("cycle", {}),
            "stats": monthly.get("stats", {}),
            "upcoming_tasks": monthly.get("upcoming_tasks", []),
        },
    }


def set_task_status(
    db: Session,
    user: User,
    *,
    task_id: int,
    status: str,
) -> CoachingPlanTask:
    row = (
        db.query(CoachingPlanTask)
        .filter(CoachingPlanTask.user_id == user.id, CoachingPlanTask.id == task_id)
        .first()
    )
    if not row:
        raise ValueError("Task not found")
    norm_status = str(status or "").strip().lower()
    if norm_status not in {"pending", "completed", "skipped"}:
        raise ValueError("status must be pending, completed, or skipped")
    row.status = norm_status
    row.completed_at = datetime.now(timezone.utc) if norm_status == "completed" else None
    if norm_status in {"pending", "skipped"} and row.target_metric == "manual_check":
        row.progress_pct = 0.0
    db.flush()
    return row


def mark_notification_read(db: Session, user: User, notification_id: int) -> Notification:
    row = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.id == notification_id)
        .first()
    )
    if not row:
        raise ValueError("Notification not found")
    row.is_read = True
    row.read_at = datetime.now(timezone.utc)
    db.flush()
    return row


def clear_plan_data(db: Session, user_id: int) -> dict[str, int]:
    deleted_tasks = db.query(CoachingPlanTask).filter(CoachingPlanTask.user_id == user_id).delete(synchronize_session=False)
    deleted_adjustments = (
        db.query(CoachingPlanAdjustment).filter(CoachingPlanAdjustment.user_id == user_id).delete(synchronize_session=False)
    )
    return {"tasks": int(deleted_tasks or 0), "adjustments": int(deleted_adjustments or 0)}


def get_calendar_summary(
    db: Session,
    user: User,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Compact per-day completion stats for a date range (max 42 days)."""
    max_days = 42
    delta = (end_date - start_date).days + 1
    if delta > max_days:
        end_date = start_date + timedelta(days=max_days - 1)

    tasks = (
        db.query(CoachingPlanTask)
        .filter(
            CoachingPlanTask.user_id == user.id,
            CoachingPlanTask.cycle_type == "daily",
            CoachingPlanTask.cycle_start >= start_date.isoformat(),
            CoachingPlanTask.cycle_start <= end_date.isoformat(),
        )
        .all()
    )

    by_day: dict[str, list[CoachingPlanTask]] = {}
    for t in tasks:
        by_day.setdefault(t.cycle_start, []).append(t)

    today_local = _today(user)
    result: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        iso = current.isoformat()
        day_tasks = by_day.get(iso, [])
        total = len(day_tasks)
        completed = sum(1 for t in day_tasks if t.status == "completed")
        missed = sum(1 for t in day_tasks if t.status == "missed")
        result.append({
            "date": iso,
            "total": total,
            "completed": completed,
            "missed": missed,
            "completion_ratio": round(completed / total, 2) if total else 0,
            "is_past": current < today_local,
            "is_today": current == today_local,
        })
        current += timedelta(days=1)

    return result
