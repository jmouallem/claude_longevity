from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.models import (
    DailyChecklistItem,
    ExercisePlan,
    ExerciseLog,
    FastingLog,
    FoodLog,
    HydrationLog,
    MealTemplate,
    MealTemplateVersion,
    MealResponseSignal,
    Notification,
    SleepLog,
    SupplementLog,
    VitalsLog,
)
from services.coaching_plan_service import refresh_task_statuses, set_task_status
from services.health_framework_service import (
    delete_framework,
    serialize_framework,
    sync_frameworks_from_settings,
    update_framework,
    upsert_framework,
)
from tools.base import ToolContext, ToolExecutionError, ToolSpec, ensure_string
from tools.health_tools import _normalize_meal_name, _resolve_structured_reference
from tools.registry import ToolRegistry
from utils.med_utils import (
    StructuredItem,
    cleanup_structured_list,
    merge_structured_items,
    parse_structured_list,
    to_structured,
)


VALID_NOTIFICATION_CATEGORIES = {"info", "reminder", "warning", "system"}
VALID_CHECKLIST_TYPES = {"medication", "supplement"}
VALID_SEX = {"male", "female", "other"}
VALID_UNITS_HEIGHT = {"cm", "ft"}
VALID_UNITS_WEIGHT = {"kg", "lb"}
VALID_UNITS_HYDRATION = {"ml", "oz"}
VALID_FITNESS = {"sedentary", "lightly_active", "moderately_active", "very_active", "extremely_active"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out = [str(v).strip() for v in value if str(v).strip()]
        return list(dict.fromkeys(out))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                arr = json.loads(text)
                if isinstance(arr, list):
                    out = [str(v).strip() for v in arr if str(v).strip()]
                    return list(dict.fromkeys(out))
            except json.JSONDecodeError:
                pass
        out = [s.strip() for s in text.split(",") if s.strip()]
        return list(dict.fromkeys(out))
    raise ToolExecutionError("Expected list of strings")


def _normalize_structured_item(value: Any) -> StructuredItem:
    item = to_structured(value)
    name = str(item.get("name", "")).strip()
    if not name:
        raise ToolExecutionError("Structured item requires `name`")
    return {
        "name": name,
        "dose": str(item.get("dose", "")).strip(),
        "timing": str(item.get("timing", "")).strip(),
    }


def _parse_structured_items_input(value: Any) -> list[StructuredItem]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_normalize_structured_item(v) for v in value if v is not None]
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        if txt.startswith("["):
            try:
                parsed = json.loads(txt)
                if isinstance(parsed, list):
                    return [_normalize_structured_item(v) for v in parsed if v is not None]
            except json.JSONDecodeError:
                pass
        # Fallback: avoid comma splitting (e.g., "1,200 mcg"); support semicolon/newline separators.
        if ";" in txt or "\n" in txt:
            return [_normalize_structured_item(part.strip()) for part in re.split(r"[;\n]+", txt) if part.strip()]
        return [_normalize_structured_item(txt)]
    raise ToolExecutionError("Structured items must be a JSON array, list, string, semicolon, or newline-separated input")


def _ensure_timezone(tz_name: str) -> str:
    try:
        ZoneInfo(tz_name)
        return tz_name
    except ZoneInfoNotFoundError as exc:
        raise ToolExecutionError("Invalid timezone name") from exc


def _merge_list_field(existing_raw: str | None, values: list[str]) -> str | None:
    existing = _parse_string_list(existing_raw or "")
    merged = list(dict.fromkeys([*existing, *values]))
    return _json_dumps(merged) if merged else None


def _to_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError(f"`{field}` must be a number") from exc


def _to_float_relaxed(value: Any, field: str) -> float | None:
    """
    Lenient numeric parser used for AI-extracted nutrition fields.
    Accepts values like "<1g", "220 kcal", "~30", "1,200 mg".
    Returns None for empty/unknown values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower().strip()
    if lowered in {"none", "null", "n/a", "na", "unknown", "unsure", "?"}:
        return None

    # Normalize common textual prefixes and separators.
    lowered = lowered.replace(",", "")
    lowered = re.sub(r"^(about|approx(?:imately)?|around|~)\s*", "", lowered)

    less_than = lowered.startswith("<")
    if less_than:
        lowered = lowered[1:].strip()

    match = re.search(r"[-+]?\d*\.?\d+", lowered)
    if not match:
        raise ToolExecutionError(f"`{field}` must be a number")

    parsed = float(match.group(0))
    if less_than and parsed > 0:
        # Preserve the "less than" meaning without failing the full write.
        parsed = parsed * 0.5
    return parsed


def _to_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError(f"`{field}` must be an integer") from exc


def _get_user_timezone(ctx: ToolContext) -> ZoneInfo:
    tz_name = str(getattr(getattr(ctx.user, "settings", None), "timezone", "") or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _refresh_tasks_after_write(ctx: ToolContext) -> None:
    """Refresh plan task statuses after a health-data write so metric-based goals auto-complete."""
    now = _context_now_utc(ctx)
    user_tz = _get_user_timezone(ctx)
    local_day = now.astimezone(user_tz).date()
    refresh_task_statuses(ctx.db, ctx.user, reference_day=local_day, create_notifications=False)


def _context_now_utc(ctx: ToolContext) -> datetime:
    reference = getattr(ctx, "reference_utc", None)
    if isinstance(reference, datetime):
        if reference.tzinfo is None:
            return reference.replace(tzinfo=timezone.utc)
        return reference.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _resolve_logged_at(args: dict[str, Any], ctx: ToolContext) -> datetime:
    default_dt = _context_now_utc(ctx)
    raw_value = args.get("logged_at")
    if raw_value is None:
        raw_value = args.get("event_time")
    return _resolve_local_datetime(ctx, raw_value, default_dt)


def _default_target_date(ctx: ToolContext) -> str:
    user_tz = _get_user_timezone(ctx)
    return _context_now_utc(ctx).astimezone(user_tz).date().isoformat()


def _parse_clock_time(value: Any) -> time | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None

    patterns = ("%H:%M", "%H:%M:%S", "%I:%M%p", "%I:%M %p", "%I%p", "%I %p")
    normalized = text.replace(".", "").upper()
    for fmt in patterns:
        try:
            return datetime.strptime(normalized, fmt).time()
        except ValueError:
            continue
    return None


def _resolve_local_datetime(ctx: ToolContext, value: Any, default_dt_utc: datetime) -> datetime:
    if value is None:
        return default_dt_utc
    text = str(value).strip()
    if not text:
        return default_dt_utc

    # First try full datetime input.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=_get_user_timezone(ctx)).astimezone(timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    clock = _parse_clock_time(text)
    if clock is None:
        return default_dt_utc

    user_tz = _get_user_timezone(ctx)
    local_now = default_dt_utc.astimezone(user_tz)
    candidate_local = datetime.combine(local_now.date(), clock, user_tz)
    # If parsed time appears too far in the future, assume it referred to the previous day.
    if candidate_local > local_now + timedelta(hours=2):
        candidate_local = candidate_local - timedelta(days=1)
    return candidate_local.astimezone(timezone.utc)


def _tool_profile_patch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")

    patch = args.get("patch")
    if not isinstance(patch, dict) or not patch:
        raise ToolExecutionError("`patch` must be a non-empty object")

    allowed = {
        "age",
        "sex",
        "height_cm",
        "current_weight_kg",
        "goal_weight_kg",
        "height_unit",
        "weight_unit",
        "hydration_unit",
        "fitness_level",
        "timezone",
        "medical_conditions",
        "dietary_preferences",
        "health_goals",
        "family_history",
        "coaching_why",
        "plan_visibility_mode",
        "plan_max_visible_tasks",
    }
    unknown = set(patch.keys()) - allowed
    if unknown:
        raise ToolExecutionError(f"Unsupported fields in patch: {', '.join(sorted(unknown))}")

    changed: list[str] = []
    for key, value in patch.items():
        if key == "age":
            if value is None:
                s.age = None
            else:
                age = _to_int(value, "age")
                if age is None or age < 1 or age > 120:
                    raise ToolExecutionError("`age` must be between 1 and 120")
                s.age = age
            changed.append(key)
            continue

        if key == "sex":
            if value is None or str(value).strip() == "":
                s.sex = None
            else:
                sex = str(value).strip().lower()
                if sex not in VALID_SEX:
                    raise ToolExecutionError("`sex` must be one of male, female, other")
                s.sex = sex
            changed.append(key)
            continue

        if key in {"height_cm", "current_weight_kg", "goal_weight_kg"}:
            numeric = _to_float(value, key)
            setattr(s, key, numeric)
            changed.append(key)
            continue

        if key == "height_unit":
            if value is None:
                continue
            v = str(value).strip().lower()
            if v not in VALID_UNITS_HEIGHT:
                raise ToolExecutionError("`height_unit` must be cm or ft")
            s.height_unit = v
            changed.append(key)
            continue

        if key == "weight_unit":
            if value is None:
                continue
            v = str(value).strip().lower()
            if v not in VALID_UNITS_WEIGHT:
                raise ToolExecutionError("`weight_unit` must be kg or lb")
            s.weight_unit = v
            changed.append(key)
            continue

        if key == "hydration_unit":
            if value is None:
                continue
            v = str(value).strip().lower()
            if v not in VALID_UNITS_HYDRATION:
                raise ToolExecutionError("`hydration_unit` must be ml or oz")
            s.hydration_unit = v
            changed.append(key)
            continue

        if key == "fitness_level":
            if value is None or str(value).strip() == "":
                s.fitness_level = None
            else:
                v = str(value).strip().lower()
                if v not in VALID_FITNESS:
                    raise ToolExecutionError("Invalid `fitness_level`")
                s.fitness_level = v
            changed.append(key)
            continue

        if key == "coaching_why":
            text = " ".join(str(value or "").split()).strip()
            s.coaching_why = text or None
            changed.append(key)
            continue

        if key == "plan_visibility_mode":
            if value is None:
                continue
            mode = str(value).strip().lower()
            if mode not in {"top3", "all"}:
                raise ToolExecutionError("`plan_visibility_mode` must be top3 or all")
            s.plan_visibility_mode = mode
            changed.append(key)
            continue

        if key == "plan_max_visible_tasks":
            if value is None:
                continue
            count = _to_int(value, key)
            if count is None:
                raise ToolExecutionError("`plan_max_visible_tasks` must be an integer")
            s.plan_max_visible_tasks = max(1, min(int(count), 10))
            changed.append(key)
            continue

        if key == "timezone":
            if value is None or str(value).strip() == "":
                s.timezone = None
            else:
                s.timezone = _ensure_timezone(str(value).strip())
            changed.append(key)
            continue

        if key in {"medical_conditions", "dietary_preferences", "health_goals", "family_history"}:
            if value is None:
                setattr(s, key, None)
            else:
                values = _parse_string_list(value)
                setattr(s, key, _json_dumps(values) if values else None)
            changed.append(key)

    return {"changed_fields": changed}


def _tool_medication_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    item = _normalize_structured_item(args.get("item"))
    merged = merge_structured_items(s.medications, [item])
    s.medications = cleanup_structured_list(merged)
    return {"medications": parse_structured_list(s.medications)}


def _tool_supplement_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    item = _normalize_structured_item(args.get("item"))
    merged = merge_structured_items(s.supplements, [item])
    s.supplements = cleanup_structured_list(merged)
    return {"supplements": parse_structured_list(s.supplements)}


def _tool_medication_set(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    items = _parse_structured_items_input(args.get("items"))
    if not items:
        s.medications = None
    else:
        s.medications = cleanup_structured_list(_json_dumps(items))
    return {"medications": parse_structured_list(s.medications)}


def _tool_supplement_set(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    items = _parse_structured_items_input(args.get("items"))
    if not items:
        s.supplements = None
    else:
        s.supplements = cleanup_structured_list(_json_dumps(items))
    return {"supplements": parse_structured_list(s.supplements)}


def _tool_goal_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    goals = args.get("goals")
    if goals is None and "goal" in args:
        goals = [args["goal"]]
    values = _parse_string_list(goals)
    s.health_goals = _merge_list_field(s.health_goals, values)
    return {"health_goals": _parse_string_list(s.health_goals or "")}


def _resolve_checklist_targets(
    ctx: ToolContext,
    item_type: str,
    names: list[str] | None,
    reference_query: str | None,
) -> list[str]:
    resolved: list[str] = []
    if names:
        resolved.extend([str(n).strip() for n in names if str(n).strip()])

    if reference_query:
        if item_type == "medication":
            source = parse_structured_list(ctx.user.settings.medications if ctx.user.settings else None)
            matches = _resolve_structured_reference(reference_query, source, "medication")
        else:
            source = parse_structured_list(ctx.user.settings.supplements if ctx.user.settings else None)
            matches = _resolve_structured_reference(reference_query, source, "supplement")
        resolved.extend([str(m.get("name", "")).strip() for m in matches if str(m.get("name", "")).strip()])

    # Deduplicate while preserving order
    unique: list[str] = []
    seen: set[str] = set()
    for name in resolved:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _tool_checklist_mark_taken(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    item_type = str(args.get("item_type", "")).strip().lower()
    if item_type not in VALID_CHECKLIST_TYPES:
        raise ToolExecutionError("`item_type` must be medication or supplement")

    names = args.get("names")
    if names is not None and not isinstance(names, list):
        raise ToolExecutionError("`names` must be a list of strings")
    reference_query = args.get("reference_query")
    if reference_query is not None and not isinstance(reference_query, str):
        raise ToolExecutionError("`reference_query` must be a string")

    targets = _resolve_checklist_targets(ctx, item_type, names, reference_query)
    if not targets:
        raise ToolExecutionError("No checklist targets resolved")

    target_date = args.get("target_date")
    if target_date is None:
        target_date = _default_target_date(ctx)
    else:
        target_date = str(target_date).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
            raise ToolExecutionError("`target_date` must be YYYY-MM-DD")

    completed = bool(args.get("completed", True))
    updated: list[str] = []
    for name in targets:
        stmt = sqlite_insert(DailyChecklistItem).values(
            user_id=ctx.user.id,
            target_date=target_date,
            item_type=item_type,
            item_name=name,
            completed=completed,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                DailyChecklistItem.user_id,
                DailyChecklistItem.target_date,
                DailyChecklistItem.item_type,
                DailyChecklistItem.item_name,
            ],
            set_={
                "completed": completed,
                "updated_at": datetime.utcnow(),
            },
        )
        ctx.db.execute(stmt)
        updated.append(name)

    _refresh_tasks_after_write(ctx)
    return {"item_type": item_type, "target_date": target_date, "updated_items": updated, "completed": completed}


def _tool_vitals_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    payload = {
        "weight_kg": _to_float(args.get("weight_kg"), "weight_kg"),
        "bp_systolic": _to_int(args.get("bp_systolic"), "bp_systolic"),
        "bp_diastolic": _to_int(args.get("bp_diastolic"), "bp_diastolic"),
        "heart_rate": _to_int(args.get("heart_rate"), "heart_rate"),
        "blood_glucose": _to_float(args.get("blood_glucose"), "blood_glucose"),
        "temperature_c": _to_float(args.get("temperature_c"), "temperature_c"),
        "spo2": _to_float(args.get("spo2"), "spo2"),
        "notes": str(args.get("notes", "")).strip() or None,
    }
    if not any(v is not None for k, v in payload.items() if k != "notes"):
        raise ToolExecutionError("At least one vitals metric is required")

    row = VitalsLog(
        user_id=ctx.user.id,
        logged_at=_resolve_logged_at(args, ctx),
        source_message_id=ctx.message_id,
        **payload,
    )
    ctx.db.add(row)

    if payload["weight_kg"] is not None and ctx.user.settings:
        ctx.user.settings.current_weight_kg = payload["weight_kg"]

    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {"vitals_log_id": row.id}


def _tool_exercise_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    exercise_type = ensure_string(args, "exercise_type")
    row = ExerciseLog(
        user_id=ctx.user.id,
        logged_at=_resolve_logged_at(args, ctx),
        exercise_type=exercise_type,
        duration_minutes=_to_int(args.get("duration_minutes"), "duration_minutes"),
        details=_json_dumps(args["details"]) if isinstance(args.get("details"), (dict, list)) else args.get("details"),
        max_hr=_to_int(args.get("max_hr"), "max_hr"),
        avg_hr=_to_int(args.get("avg_hr"), "avg_hr"),
        calories_burned=_to_float(args.get("calories_burned"), "calories_burned"),
        notes=str(args.get("notes", "")).strip() or None,
        source_message_id=ctx.message_id,
    )
    ctx.db.add(row)
    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {"exercise_log_id": row.id}


def _tool_food_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    meal_label = str(args.get("meal_label", "")).strip() or None
    items_val = args.get("items", [])
    if isinstance(items_val, str):
        try:
            items = json.loads(items_val)
        except json.JSONDecodeError:
            items = [{"name": items_val}]
    elif isinstance(items_val, dict):
        items = [items_val]
    elif isinstance(items_val, list):
        items = items_val
    else:
        items = []

    if not isinstance(items, list):
        items = []

    normalized_items: list[dict[str, str]] = []
    for raw_item in items:
        if isinstance(raw_item, dict):
            name = str(raw_item.get("name") or raw_item.get("item") or "").strip()
            if not name:
                continue
            normalized_items.append(
                {
                    "name": name,
                    "quantity": str(raw_item.get("quantity", "") or "").strip(),
                    "unit": str(raw_item.get("unit", "") or "").strip(),
                }
            )
            continue
        text_item = str(raw_item or "").strip()
        if text_item:
            normalized_items.append({"name": text_item, "quantity": "", "unit": ""})

    if not normalized_items:
        fallback_name = meal_label or str(args.get("template_name", "")).strip() or "Meal entry"
        normalized_items = [{"name": fallback_name, "quantity": "", "unit": ""}]

    query_name = str(args.get("template_name", "")).strip() or meal_label or ""
    if not query_name and normalized_items:
        first = normalized_items[0]
        if isinstance(first, dict):
            query_name = str(first.get("name", "")).strip()
        else:
            query_name = str(first).strip()

    resolved_template = None
    if query_name:
        norm_query = _normalize_meal_name(query_name)
        templates = (
            ctx.db.query(MealTemplate)
            .filter(MealTemplate.user_id == ctx.user.id, MealTemplate.is_archived.is_(False))
            .order_by(MealTemplate.updated_at.desc(), MealTemplate.created_at.desc())
            .all()
        )
        for row in templates:
            if row.normalized_name == norm_query:
                resolved_template = row
                break
            aliases = _parse_string_list(row.aliases or "")
            if any(_normalize_meal_name(alias) == norm_query for alias in aliases):
                resolved_template = row
                break

    if resolved_template is not None and bool(args.get("use_template_if_found", True)):
        logged_at = _resolve_logged_at(args, ctx)
        servings = _to_float(args.get("servings", 1.0), "servings") or 1.0
        if servings <= 0:
            raise ToolExecutionError("`servings` must be > 0")
        base_servings = resolved_template.servings or 1.0
        mult = servings / base_servings
        ing = _parse_string_list(resolved_template.ingredients or "")
        template_items = [{"name": x} for x in ing] if ing else [{"name": resolved_template.name}]
        row = FoodLog(
            user_id=ctx.user.id,
            meal_template_id=resolved_template.id,
            logged_at=logged_at,
            meal_label=meal_label or resolved_template.name,
            items=_json_dumps(template_items),
            calories=(resolved_template.calories * mult) if resolved_template.calories is not None else None,
            protein_g=(resolved_template.protein_g * mult) if resolved_template.protein_g is not None else None,
            carbs_g=(resolved_template.carbs_g * mult) if resolved_template.carbs_g is not None else None,
            fat_g=(resolved_template.fat_g * mult) if resolved_template.fat_g is not None else None,
            fiber_g=(resolved_template.fiber_g * mult) if resolved_template.fiber_g is not None else None,
            sodium_mg=(resolved_template.sodium_mg * mult) if resolved_template.sodium_mg is not None else None,
            notes=str(args.get("notes", "")).strip() or None,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {"food_log_id": row.id, "used_template": True, "meal_template_id": resolved_template.id}

    row = FoodLog(
        user_id=ctx.user.id,
        logged_at=_resolve_logged_at(args, ctx),
        meal_label=meal_label,
        items=_json_dumps(normalized_items),
        calories=_coerce_float_field(args, "calories", strict=False),
        protein_g=_coerce_float_field(args, "protein_g", strict=False),
        carbs_g=_coerce_float_field(args, "carbs_g", strict=False),
        fat_g=_coerce_float_field(args, "fat_g", strict=False),
        fiber_g=_coerce_float_field(args, "fiber_g", strict=False),
        sodium_mg=_coerce_float_field(args, "sodium_mg", strict=False),
        notes=str(args.get("notes", "")).strip() or None,
        source_message_id=ctx.message_id,
    )
    ctx.db.add(row)
    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {"food_log_id": row.id, "used_template": False}


def _tool_hydration_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    amount_ml = _to_float(args.get("amount_ml"), "amount_ml")
    if amount_ml is None or amount_ml <= 0:
        raise ToolExecutionError("`amount_ml` must be > 0")
    row = HydrationLog(
        user_id=ctx.user.id,
        logged_at=_resolve_logged_at(args, ctx),
        amount_ml=amount_ml,
        source=str(args.get("source", "water")).strip() or "water",
        notes=str(args.get("notes", "")).strip() or None,
        source_message_id=ctx.message_id,
    )
    ctx.db.add(row)
    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {"hydration_log_id": row.id}


def _tool_supplement_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    supplements_val = args.get("supplements", [])
    if isinstance(supplements_val, str):
        try:
            supplements = json.loads(supplements_val)
        except json.JSONDecodeError:
            supplements = [supplements_val]
    elif isinstance(supplements_val, list):
        supplements = supplements_val
    else:
        raise ToolExecutionError("`supplements` must be a list or JSON string")
    if not isinstance(supplements, list):
        raise ToolExecutionError("`supplements` must resolve to a list")
    row = SupplementLog(
        user_id=ctx.user.id,
        logged_at=_resolve_logged_at(args, ctx),
        supplements=_json_dumps(supplements),
        timing=str(args.get("timing", "")).strip() or None,
        notes=str(args.get("notes", "")).strip() or None,
        source_message_id=ctx.message_id,
    )
    ctx.db.add(row)
    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {"supplement_log_id": row.id}


def _tool_sleep_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    now = _context_now_utc(ctx)
    action = str(args.get("action", "auto")).strip().lower() or "auto"
    duration = _to_int(args.get("duration_minutes"), "duration_minutes")
    quality = str(args.get("quality", "")).strip() or None
    notes = str(args.get("notes", "")).strip() or None

    if action not in {"auto", "start", "end"}:
        raise ToolExecutionError("`action` must be auto, start, or end")

    raw_sleep_start = str(args.get("sleep_start") or "").strip()
    raw_sleep_end = str(args.get("sleep_end") or "").strip()
    has_explicit_pair = bool(raw_sleep_start and raw_sleep_end)

    start_dt = _resolve_local_datetime(ctx, args.get("sleep_start"), now)
    end_dt = _resolve_local_datetime(ctx, args.get("sleep_end"), now)

    # Defensive canonicalization: if both start/end are supplied in one turn,
    # persist a complete sleep interval (end flow), even if action was "start".
    if has_explicit_pair and action in {"auto", "start", "end"}:
        action = "end"

    if action == "auto":
        if args.get("sleep_start") and not args.get("sleep_end"):
            action = "start"
        elif args.get("sleep_end"):
            action = "end"
        elif duration is not None:
            action = "duration_only"
        else:
            active = (
                ctx.db.query(SleepLog)
                .filter(
                    SleepLog.user_id == ctx.user.id,
                    SleepLog.sleep_start.isnot(None),
                    SleepLog.sleep_end.is_(None),
                )
                .order_by(SleepLog.created_at.desc())
                .first()
            )
            action = "end" if active else "start"

    if action == "start":
        row = SleepLog(
            user_id=ctx.user.id,
            sleep_start=start_dt,
            sleep_end=None,
            duration_minutes=None,
            quality=quality,
            notes=notes,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        return {"status": "started", "sleep_log_id": row.id, "sleep_start": row.sleep_start.isoformat()}

    if action == "duration_only":
        row = SleepLog(
            user_id=ctx.user.id,
            sleep_start=None,
            sleep_end=None,
            duration_minutes=duration,
            quality=quality,
            notes=notes,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {"status": "created", "sleep_log_id": row.id, "duration_minutes": row.duration_minutes}

    # action == "end"
    active = (
        ctx.db.query(SleepLog)
        .filter(
            SleepLog.user_id == ctx.user.id,
            SleepLog.sleep_start.isnot(None),
            SleepLog.sleep_end.is_(None),
        )
        .order_by(SleepLog.created_at.desc())
        .first()
    )

    # If no active session exists but both start/end are provided in one turn,
    # persist a complete sleep event so downstream plan progress can update.
    if not active and has_explicit_pair:
        if end_dt < start_dt:
            end_dt = end_dt + timedelta(days=1)
        computed_minutes = int((end_dt - start_dt).total_seconds() / 60)
        resolved_minutes = duration if duration is not None else max(0, computed_minutes)
        row = SleepLog(
            user_id=ctx.user.id,
            sleep_start=start_dt,
            sleep_end=end_dt,
            duration_minutes=resolved_minutes,
            quality=quality,
            notes=notes,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {
            "status": "created",
            "sleep_log_id": row.id,
            "sleep_start": row.sleep_start.isoformat() if row.sleep_start else None,
            "sleep_end": row.sleep_end.isoformat() if row.sleep_end else None,
            "duration_minutes": row.duration_minutes,
        }

    if not active:
        row = SleepLog(
            user_id=ctx.user.id,
            sleep_start=None,
            sleep_end=end_dt,
            duration_minutes=duration,
            quality=quality,
            notes=notes,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {"status": "created", "sleep_log_id": row.id, "sleep_end": row.sleep_end.isoformat() if row.sleep_end else None}

    if end_dt < active.sleep_start:
        end_dt = end_dt + timedelta(days=1)
    computed_minutes = int((end_dt - active.sleep_start).total_seconds() / 60)
    active.sleep_end = end_dt
    active.duration_minutes = computed_minutes if computed_minutes >= 0 else duration
    if quality:
        active.quality = quality
    if notes:
        active.notes = notes
    if ctx.message_id and not active.source_message_id:
        active.source_message_id = ctx.message_id
    ctx.db.flush()
    _refresh_tasks_after_write(ctx)
    return {
        "status": "ended",
        "sleep_log_id": active.id,
        "sleep_start": active.sleep_start.isoformat() if active.sleep_start else None,
        "sleep_end": active.sleep_end.isoformat() if active.sleep_end else None,
        "duration_minutes": active.duration_minutes,
    }


def _tool_fasting_manage(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action = str(args.get("action", "")).strip().lower()
    now = _context_now_utc(ctx)
    if action not in {"start", "end"}:
        raise ToolExecutionError("`action` must be `start` or `end`")

    if action == "start":
        fast_start = _resolve_local_datetime(ctx, args.get("fast_start"), now)
        row = FastingLog(
            user_id=ctx.user.id,
            fast_start=fast_start,
            fast_type=str(args.get("fast_type", "")).strip() or None,
            notes=str(args.get("notes", "")).strip() or None,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        return {"status": "started", "fasting_log_id": row.id, "fast_start": row.fast_start.isoformat()}

    explicit_start = args.get("fast_start") is not None and str(args.get("fast_start")).strip() != ""
    explicit_end = args.get("fast_end") is not None and str(args.get("fast_end")).strip() != ""
    start_dt = _resolve_local_datetime(ctx, args.get("fast_start"), now) if explicit_start else None
    end_dt = _resolve_local_datetime(ctx, args.get("fast_end"), now) if explicit_end else now

    active = (
        ctx.db.query(FastingLog)
        .filter(FastingLog.user_id == ctx.user.id, FastingLog.fast_end.is_(None))
        .order_by(FastingLog.fast_start.desc())
        .first()
    )
    if active:
        if start_dt is not None:
            active.fast_start = start_dt
        active.fast_end = end_dt
        start = active.fast_start if active.fast_start.tzinfo else active.fast_start.replace(tzinfo=timezone.utc)
        if active.fast_end < start:
            active.fast_end = active.fast_end + timedelta(days=1)
        active.duration_minutes = int((active.fast_end - start).total_seconds() / 60)
        if ctx.message_id and not active.source_message_id:
            active.source_message_id = ctx.message_id
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {"status": "ended", "fasting_log_id": active.id, "duration_minutes": active.duration_minutes}

    # Support direct fasting interval logs (e.g., "last meal 8pm, first meal 10am")
    # even when no active fast is open.
    if explicit_start and explicit_end and start_dt is not None:
        if end_dt < start_dt:
            end_dt = end_dt + timedelta(days=1)
        row = FastingLog(
            user_id=ctx.user.id,
            fast_start=start_dt,
            fast_end=end_dt,
            duration_minutes=int((end_dt - start_dt).total_seconds() / 60),
            fast_type=str(args.get("fast_type", "")).strip() or None,
            notes=str(args.get("notes", "")).strip() or None,
            source_message_id=ctx.message_id,
        )
        ctx.db.add(row)
        ctx.db.flush()
        _refresh_tasks_after_write(ctx)
        return {"status": "created", "fasting_log_id": row.id, "duration_minutes": row.duration_minutes}

    return {"status": "no_active_fast"}


def _tool_exercise_plan_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    target_date = ensure_string(args, "target_date")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise ToolExecutionError("`target_date` must be YYYY-MM-DD")

    plan_type = str(args.get("plan_type", "mixed")).strip().lower() or "mixed"
    if plan_type not in {"rest_day", "hiit", "strength", "zone2", "mobility", "mixed"}:
        plan_type = "mixed"
    title = str(args.get("title", "Today's Exercise Plan")).strip() or "Today's Exercise Plan"
    description = str(args.get("description", "")).strip() or None
    target_minutes = _to_int(args.get("target_minutes"), "target_minutes")
    source = str(args.get("source", "ai")).strip() or "ai"

    row = (
        ctx.db.query(ExercisePlan)
        .filter(ExercisePlan.user_id == ctx.user.id, ExercisePlan.target_date == target_date)
        .first()
    )
    created = False
    if not row:
        row = ExercisePlan(user_id=ctx.user.id, target_date=target_date, source=source)
        ctx.db.add(row)
        created = True

    row.plan_type = plan_type
    row.title = title
    row.description = description
    row.target_minutes = target_minutes
    row.source = source
    ctx.db.flush()
    return {"exercise_plan_id": row.id, "created": created}


def _coerce_float_field(args: dict[str, Any], field: str, *, strict: bool = True) -> float | None:
    if field not in args:
        return None
    value = args.get(field)
    try:
        if strict:
            return _to_float(value, field)
        return _to_float_relaxed(value, field)
    except ToolExecutionError:
        if strict:
            raise
        return None


def _meal_template_snapshot(row: MealTemplate) -> dict[str, Any]:
    return {
        "name": row.name,
        "normalized_name": row.normalized_name,
        "aliases": _parse_string_list(row.aliases or ""),
        "ingredients": _parse_string_list(row.ingredients or ""),
        "servings": row.servings,
        "calories": row.calories,
        "protein_g": row.protein_g,
        "carbs_g": row.carbs_g,
        "fat_g": row.fat_g,
        "fiber_g": row.fiber_g,
        "sodium_mg": row.sodium_mg,
        "notes": row.notes,
        "is_archived": bool(row.is_archived),
    }


def _create_template_version(
    ctx: ToolContext,
    row: MealTemplate,
    change_note: str | None = None,
) -> int:
    latest = (
        ctx.db.query(MealTemplateVersion)
        .filter(MealTemplateVersion.meal_template_id == row.id)
        .order_by(MealTemplateVersion.version_number.desc())
        .first()
    )
    next_version = 1 if not latest else int(latest.version_number) + 1
    version = MealTemplateVersion(
        user_id=ctx.user.id,
        meal_template_id=row.id,
        version_number=next_version,
        snapshot_json=_json_dumps(_meal_template_snapshot(row)),
        change_note=(change_note or "").strip() or None,
    )
    ctx.db.add(version)
    return next_version


def _tool_meal_template_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = ensure_string(args, "name")
    normalized_name = _normalize_meal_name(name)
    if not normalized_name:
        raise ToolExecutionError("Invalid `name`")

    aliases = _parse_string_list(args.get("aliases", []))
    ingredients = _parse_string_list(args.get("ingredients", []))
    servings = _to_float(args.get("servings", 1.0), "servings") or 1.0
    if servings <= 0:
        raise ToolExecutionError("`servings` must be > 0")

    row = (
        ctx.db.query(MealTemplate)
        .filter(MealTemplate.user_id == ctx.user.id, MealTemplate.normalized_name == normalized_name)
        .first()
    )
    created = False
    before_snapshot: dict[str, Any] | None = None
    if not row:
        row = MealTemplate(
            user_id=ctx.user.id,
            name=name,
            normalized_name=normalized_name,
        )
        ctx.db.add(row)
        created = True
    else:
        before_snapshot = _meal_template_snapshot(row)

    row.name = name
    row.normalized_name = normalized_name
    row.aliases = _json_dumps(aliases) if aliases else None
    row.ingredients = _json_dumps(ingredients) if ingredients else None
    row.servings = servings
    row.calories = _coerce_float_field(args, "calories")
    row.protein_g = _coerce_float_field(args, "protein_g")
    row.carbs_g = _coerce_float_field(args, "carbs_g")
    row.fat_g = _coerce_float_field(args, "fat_g")
    row.fiber_g = _coerce_float_field(args, "fiber_g")
    row.sodium_mg = _coerce_float_field(args, "sodium_mg")
    row.notes = str(args.get("notes", "")).strip() or None
    row.is_archived = False
    row.archived_at = None

    ctx.db.flush()

    after_snapshot = _meal_template_snapshot(row)
    change_note = str(args.get("change_note", "")).strip() or ("Created template" if created else "Updated template")
    version_number = None
    if created or before_snapshot != after_snapshot:
        version_number = _create_template_version(ctx, row, change_note=change_note)

    return {
        "meal_template_id": row.id,
        "created": created,
        "name": row.name,
        "version_number": version_number,
    }


def _tool_meal_log_from_template(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    template_id = args.get("template_id")
    template_name = args.get("template_name")
    row = None
    if template_id is not None:
        try:
            tid = int(template_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`template_id` must be an integer") from exc
        row = ctx.db.query(MealTemplate).filter(MealTemplate.user_id == ctx.user.id, MealTemplate.id == tid).first()
    elif template_name:
        norm = _normalize_meal_name(str(template_name))
        row = (
            ctx.db.query(MealTemplate)
            .filter(MealTemplate.user_id == ctx.user.id, MealTemplate.normalized_name == norm)
            .first()
        )
    else:
        raise ToolExecutionError("Provide `template_id` or `template_name`")

    if not row:
        raise ToolExecutionError("Meal template not found")

    servings = _to_float(args.get("servings", 1.0), "servings") or 1.0
    if servings <= 0:
        raise ToolExecutionError("`servings` must be > 0")

    base_servings = row.servings or 1.0
    mult = servings / base_servings

    ingredients = _parse_string_list(row.ingredients or "")
    meal_items = [{"name": item} for item in ingredients] if ingredients else [{"name": row.name}]
    log = FoodLog(
        user_id=ctx.user.id,
        meal_template_id=row.id,
        logged_at=_resolve_logged_at(args, ctx),
        meal_label=str(args.get("meal_label", row.name)).strip() or row.name,
        items=_json_dumps(meal_items),
        calories=(row.calories * mult) if row.calories is not None else None,
        protein_g=(row.protein_g * mult) if row.protein_g is not None else None,
        carbs_g=(row.carbs_g * mult) if row.carbs_g is not None else None,
        fat_g=(row.fat_g * mult) if row.fat_g is not None else None,
        fiber_g=(row.fiber_g * mult) if row.fiber_g is not None else None,
        sodium_mg=(row.sodium_mg * mult) if row.sodium_mg is not None else None,
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(log)
    ctx.db.flush()
    return {"food_log_id": log.id, "meal_template_id": row.id, "servings": servings}


def _resolve_meal_template_row(ctx: ToolContext, args: dict[str, Any], include_archived: bool = True) -> MealTemplate:
    template_id = args.get("template_id")
    template_name = args.get("template_name")
    query = ctx.db.query(MealTemplate).filter(MealTemplate.user_id == ctx.user.id)
    if not include_archived:
        query = query.filter(MealTemplate.is_archived.is_(False))
    row = None
    if template_id is not None:
        try:
            tid = int(template_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`template_id` must be an integer") from exc
        row = query.filter(MealTemplate.id == tid).first()
    elif template_name:
        norm = _normalize_meal_name(str(template_name))
        row = query.filter(MealTemplate.normalized_name == norm).first()
    else:
        raise ToolExecutionError("Provide `template_id` or `template_name`")

    if not row:
        raise ToolExecutionError("Meal template not found")
    return row


def _tool_meal_template_archive(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    row = _resolve_meal_template_row(ctx, args, include_archived=True)
    archive = bool(args.get("archive", True))
    if archive:
        if not row.is_archived:
            _create_template_version(ctx, row, change_note="Archived template")
        row.is_archived = True
        row.archived_at = datetime.now(timezone.utc)
    else:
        if row.is_archived:
            _create_template_version(ctx, row, change_note="Restored template")
        row.is_archived = False
        row.archived_at = None
    ctx.db.flush()
    return {"meal_template_id": row.id, "archived": bool(row.is_archived)}


def _tool_meal_template_delete(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    row = _resolve_meal_template_row(ctx, args, include_archived=True)
    template_id = row.id
    name = row.name
    ctx.db.query(MealTemplateVersion).filter(MealTemplateVersion.meal_template_id == template_id).delete()
    ctx.db.query(MealResponseSignal).filter(MealResponseSignal.meal_template_id == template_id).update(
        {"meal_template_id": None}
    )
    ctx.db.query(FoodLog).filter(FoodLog.meal_template_id == template_id).update({"meal_template_id": None})
    ctx.db.delete(row)
    return {"deleted": True, "meal_template_id": template_id, "name": name}


def _tool_meal_response_signal_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    meal_template_id = args.get("meal_template_id")
    food_log_id = args.get("food_log_id")
    source_message_id = args.get("source_message_id")
    energy_level = args.get("energy_level")
    gi_severity = args.get("gi_severity")
    notes = str(args.get("notes", "")).strip() or None
    tags = _parse_string_list(args.get("gi_symptom_tags", []))

    if meal_template_id is not None:
        try:
            meal_template_id = int(meal_template_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`meal_template_id` must be an integer") from exc
    if food_log_id is not None:
        try:
            food_log_id = int(food_log_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`food_log_id` must be an integer") from exc
    if source_message_id is not None:
        try:
            source_message_id = int(source_message_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`source_message_id` must be an integer") from exc

    template_row = None
    if meal_template_id is not None:
        template_row = (
            ctx.db.query(MealTemplate)
            .filter(MealTemplate.user_id == ctx.user.id, MealTemplate.id == meal_template_id)
            .first()
        )
        if not template_row:
            raise ToolExecutionError("Meal template not found for this user")

    food_log_row = None
    if food_log_id is not None:
        food_log_row = (
            ctx.db.query(FoodLog)
            .filter(FoodLog.user_id == ctx.user.id, FoodLog.id == food_log_id)
            .first()
        )
        if not food_log_row:
            raise ToolExecutionError("Food log not found for this user")

    if food_log_row and food_log_row.meal_template_id is not None:
        linked_template_id = int(food_log_row.meal_template_id)
        if meal_template_id is None:
            meal_template_id = linked_template_id
        elif int(meal_template_id) != linked_template_id:
            raise ToolExecutionError("`meal_template_id` does not match the provided `food_log_id`")

    if energy_level is not None:
        try:
            energy_level = int(energy_level)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`energy_level` must be an integer") from exc
        if energy_level < -2 or energy_level > 2:
            raise ToolExecutionError("`energy_level` must be between -2 and 2")

    if gi_severity is not None:
        try:
            gi_severity = int(gi_severity)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`gi_severity` must be an integer") from exc
        if gi_severity < 1 or gi_severity > 5:
            raise ToolExecutionError("`gi_severity` must be between 1 and 5")

    row = MealResponseSignal(
        user_id=ctx.user.id,
        meal_template_id=meal_template_id,
        food_log_id=food_log_id,
        source_message_id=source_message_id,
        energy_level=energy_level,
        gi_symptom_tags=_json_dumps(tags) if tags else None,
        gi_severity=gi_severity,
        notes=notes,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"meal_response_signal_id": row.id}


def _tool_notification_create(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    title = ensure_string(args, "title")
    message = ensure_string(args, "message")
    category = str(args.get("category", "info")).strip().lower()
    if category not in VALID_NOTIFICATION_CATEGORIES:
        raise ToolExecutionError(f"`category` must be one of {', '.join(sorted(VALID_NOTIFICATION_CATEGORIES))}")
    payload = args.get("payload")
    if payload is not None and not isinstance(payload, (dict, list, str, int, float, bool)):
        raise ToolExecutionError("`payload` must be JSON-serializable")

    row = Notification(
        user_id=ctx.user.id,
        category=category,
        title=title,
        message=message,
        payload=_json_dumps(payload) if payload is not None else None,
        is_read=False,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"notification_id": row.id}


def _tool_notification_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    unread_only = bool(args.get("unread_only", False))
    limit = args.get("limit", 30)
    if not isinstance(limit, int):
        raise ToolExecutionError("`limit` must be an integer")
    limit = max(1, min(limit, 200))

    q = ctx.db.query(Notification).filter(Notification.user_id == ctx.user.id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()

    out = []
    for row in rows:
        payload = None
        if row.payload:
            try:
                payload = json.loads(row.payload)
            except json.JSONDecodeError:
                payload = row.payload
        out.append(
            {
                "id": row.id,
                "category": row.category,
                "title": row.title,
                "message": row.message,
                "payload": payload,
                "is_read": bool(row.is_read),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "read_at": row.read_at.isoformat() if row.read_at else None,
            }
        )
    return {"notifications": out}


def _tool_notification_mark_read(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    notification_id = args.get("notification_id")
    try:
        nid = int(notification_id)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("`notification_id` must be an integer") from exc

    row = (
        ctx.db.query(Notification)
        .filter(Notification.user_id == ctx.user.id, Notification.id == nid)
        .first()
    )
    if not row:
        raise ToolExecutionError("Notification not found")

    row.is_read = True
    row.read_at = datetime.now(timezone.utc)
    return {"notification_id": row.id, "is_read": True}


def _tool_framework_upsert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    framework_type = ensure_string(args, "framework_type")
    name = ensure_string(args, "name")
    try:
        row, demoted_ids = upsert_framework(
            db=ctx.db,
            user_id=ctx.user.id,
            framework_type=framework_type,
            name=name,
            priority_score=args.get("priority_score"),
            is_active=args.get("is_active"),
            source=str(args.get("source", "user")),
            rationale=str(args.get("rationale", "") or ""),
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
            commit=False,
        )
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"item": serialize_framework(row), "demoted_ids": demoted_ids}


def _tool_framework_update(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    framework_id = args.get("framework_id")
    try:
        fid = int(framework_id)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("`framework_id` must be an integer") from exc
    if fid <= 0:
        raise ToolExecutionError("`framework_id` must be positive")

    try:
        row, demoted_ids = update_framework(
            db=ctx.db,
            user_id=ctx.user.id,
            framework_id=fid,
            framework_type=args.get("framework_type"),
            name=args.get("name"),
            priority_score=args.get("priority_score"),
            is_active=args.get("is_active"),
            source=args.get("source"),
            rationale=args.get("rationale"),
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
            commit=False,
        )
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"item": serialize_framework(row), "demoted_ids": demoted_ids}


def _tool_framework_delete(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    framework_id = args.get("framework_id")
    source = str(args.get("source", "user") or "user").strip().lower()
    if source == "adaptive":
        raise ToolExecutionError("Adaptive updates cannot delete framework items; only deactivate or reprioritize.")
    try:
        fid = int(framework_id)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("`framework_id` must be an integer") from exc
    if fid <= 0:
        raise ToolExecutionError("`framework_id` must be positive")
    try:
        row = delete_framework(
            db=ctx.db,
            user_id=ctx.user.id,
            framework_id=fid,
            allow_seed_delete=True,
            commit=False,
        )
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"deleted_id": row.id}


def _tool_framework_sync_from_profile(_: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    rows = sync_frameworks_from_settings(ctx.db, ctx.user, source="user", commit=False)
    return {"count": len(rows), "items": [serialize_framework(row) for row in rows]}


def _tool_plan_task_update_status(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    task_id = int(args["task_id"])
    status = str(args.get("status", "")).strip().lower()
    if status not in {"completed", "skipped", "pending"}:
        raise ToolExecutionError("`status` must be completed, skipped, or pending")
    row = set_task_status(ctx.db, ctx.user, task_id=task_id, status=status)
    return {"task_id": row.id, "status": row.status}


def register_write_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="profile_patch",
            description="Patch selected profile fields with validation and normalized storage.",
            required_fields=("patch",),
            read_only=False,
            tags=("profile", "write"),
        ),
        _tool_profile_patch,
    )
    registry.register(
        ToolSpec(
            name="medication_upsert",
            description="Upsert a medication entry into the user's structured medication list.",
            required_fields=("item",),
            read_only=False,
            tags=("medication", "write"),
        ),
        _tool_medication_upsert,
    )
    registry.register(
        ToolSpec(
            name="medication_set",
            description="Replace the full medication list using structured storage.",
            required_fields=("items",),
            read_only=False,
            tags=("medication", "write"),
        ),
        _tool_medication_set,
    )
    registry.register(
        ToolSpec(
            name="supplement_upsert",
            description="Upsert a supplement entry into the user's structured supplement list.",
            required_fields=("item",),
            read_only=False,
            tags=("supplement", "write"),
        ),
        _tool_supplement_upsert,
    )
    registry.register(
        ToolSpec(
            name="supplement_set",
            description="Replace the full supplement list using structured storage.",
            required_fields=("items",),
            read_only=False,
            tags=("supplement", "write"),
        ),
        _tool_supplement_set,
    )
    registry.register(
        ToolSpec(
            name="goal_upsert",
            description="Add one or more health goals into the user's profile goals.",
            read_only=False,
            tags=("goals", "write"),
        ),
        _tool_goal_upsert,
    )
    registry.register(
        ToolSpec(
            name="framework_upsert",
            description="Create or upsert a health optimization framework strategy item.",
            required_fields=("framework_type", "name"),
            read_only=False,
            tags=("framework", "write"),
        ),
        _tool_framework_upsert,
    )
    registry.register(
        ToolSpec(
            name="framework_update",
            description="Update priority/activation/details of a framework item by id.",
            required_fields=("framework_id",),
            read_only=False,
            tags=("framework", "write"),
        ),
        _tool_framework_update,
    )
    registry.register(
        ToolSpec(
            name="framework_delete",
            description="Delete a framework item by id (adaptive sources cannot delete).",
            required_fields=("framework_id",),
            read_only=False,
            tags=("framework", "write"),
        ),
        _tool_framework_delete,
    )
    registry.register(
        ToolSpec(
            name="framework_sync_from_profile",
            description="Infer and upsert framework items from current user profile fields.",
            read_only=False,
            tags=("framework", "write"),
        ),
        _tool_framework_sync_from_profile,
    )
    registry.register(
        ToolSpec(
            name="checklist_mark_taken",
            description="Mark medication/supplement checklist entries completed for a date by names or reference query.",
            required_fields=("item_type",),
            read_only=False,
            tags=("checklist", "write"),
        ),
        _tool_checklist_mark_taken,
    )
    registry.register(
        ToolSpec(
            name="food_log_write",
            description="Write a food log entry (can auto-resolve to named meal template).",
            required_fields=("items",),
            read_only=False,
            tags=("food", "write"),
        ),
        _tool_food_log_write,
    )
    registry.register(
        ToolSpec(
            name="vitals_log_write",
            description="Write a vitals log entry (weight, BP, HR, glucose, temperature, SpO2).",
            read_only=False,
            tags=("vitals", "write"),
        ),
        _tool_vitals_log_write,
    )
    registry.register(
        ToolSpec(
            name="exercise_log_write",
            description="Write an exercise log entry.",
            required_fields=("exercise_type",),
            read_only=False,
            tags=("exercise", "write"),
        ),
        _tool_exercise_log_write,
    )
    registry.register(
        ToolSpec(
            name="hydration_log_write",
            description="Write a hydration log entry.",
            required_fields=("amount_ml",),
            read_only=False,
            tags=("hydration", "write"),
        ),
        _tool_hydration_log_write,
    )
    registry.register(
        ToolSpec(
            name="supplement_log_write",
            description="Write a supplement intake log entry.",
            required_fields=("supplements",),
            read_only=False,
            tags=("supplement", "write"),
        ),
        _tool_supplement_log_write,
    )
    registry.register(
        ToolSpec(
            name="sleep_log_write",
            description="Write a sleep log entry.",
            read_only=False,
            tags=("sleep", "write"),
        ),
        _tool_sleep_log_write,
    )
    registry.register(
        ToolSpec(
            name="fasting_manage",
            description="Start or end fasting log.",
            required_fields=("action",),
            read_only=False,
            tags=("fasting", "write"),
        ),
        _tool_fasting_manage,
    )
    registry.register(
        ToolSpec(
            name="exercise_plan_upsert",
            description="Create or update daily exercise plan.",
            required_fields=("target_date", "plan_type", "title"),
            read_only=False,
            tags=("exercise_plan", "write"),
        ),
        _tool_exercise_plan_upsert,
    )
    registry.register(
        ToolSpec(
            name="meal_template_upsert",
            description="Create or update a named meal template with ingredients and macros.",
            required_fields=("name",),
            read_only=False,
            tags=("meal_template", "write"),
        ),
        _tool_meal_template_upsert,
    )
    registry.register(
        ToolSpec(
            name="meal_template_archive",
            description="Archive or restore a meal template by id or name.",
            read_only=False,
            tags=("meal_template", "write"),
        ),
        _tool_meal_template_archive,
    )
    registry.register(
        ToolSpec(
            name="meal_template_delete",
            description="Delete a meal template by id or name.",
            read_only=False,
            tags=("meal_template", "write"),
        ),
        _tool_meal_template_delete,
    )
    registry.register(
        ToolSpec(
            name="meal_log_from_template",
            description="Create a food log entry from a saved meal template by template id or name.",
            read_only=False,
            tags=("meal_template", "write"),
        ),
        _tool_meal_log_from_template,
    )
    registry.register(
        ToolSpec(
            name="meal_response_signal_write",
            description="Write a meal response signal (energy/GI outcomes) for user-level meal analysis.",
            read_only=False,
            tags=("meal_response", "write"),
        ),
        _tool_meal_response_signal_write,
    )
    registry.register(
        ToolSpec(
            name="notification_create",
            description="Create a user notification/reminder entry.",
            required_fields=("title", "message"),
            read_only=False,
            tags=("notification", "write"),
        ),
        _tool_notification_create,
    )
    registry.register(
        ToolSpec(
            name="notification_list",
            description="List user notifications.",
            read_only=True,
            tags=("notification", "read"),
        ),
        _tool_notification_list,
    )
    registry.register(
        ToolSpec(
            name="notification_mark_read",
            description="Mark a notification as read.",
            required_fields=("notification_id",),
            read_only=False,
            tags=("notification", "write"),
        ),
        _tool_notification_mark_read,
    )
    registry.register(
        ToolSpec(
            name="plan_task_update_status",
            description="Mark a plan task as completed, skipped, or pending by task_id.",
            required_fields=("task_id", "status"),
            read_only=False,
            tags=("plan", "write"),
        ),
        _tool_plan_task_update_status,
    )
