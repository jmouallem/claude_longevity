from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from tools.base import ToolContext, ToolExecutionError, ToolSpec, ensure_string
from tools.health_tools import _normalize_meal_name, _resolve_structured_reference
from tools.registry import ToolRegistry
from utils.datetime_utils import today_utc
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
        # Fallback: comma-separated strings
        return [_normalize_structured_item(part.strip()) for part in txt.split(",") if part.strip()]
    raise ToolExecutionError("Structured items must be a JSON array, list, or comma-separated string")


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


def _to_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError(f"`{field}` must be an integer") from exc


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
        target_date = today_utc().isoformat()
    else:
        target_date = str(target_date).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
            raise ToolExecutionError("`target_date` must be YYYY-MM-DD")

    completed = bool(args.get("completed", True))
    updated: list[str] = []
    for name in targets:
        row = (
            ctx.db.query(DailyChecklistItem)
            .filter(
                DailyChecklistItem.user_id == ctx.user.id,
                DailyChecklistItem.target_date == target_date,
                DailyChecklistItem.item_type == item_type,
                DailyChecklistItem.item_name == name,
            )
            .first()
        )
        if not row:
            row = DailyChecklistItem(
                user_id=ctx.user.id,
                target_date=target_date,
                item_type=item_type,
                item_name=name,
                completed=completed,
            )
            ctx.db.add(row)
        else:
            row.completed = completed
        updated.append(name)

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
        logged_at=datetime.now(timezone.utc),
        **payload,
    )
    ctx.db.add(row)

    if payload["weight_kg"] is not None and ctx.user.settings:
        ctx.user.settings.current_weight_kg = payload["weight_kg"]

    ctx.db.flush()
    return {"vitals_log_id": row.id}


def _tool_exercise_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    exercise_type = ensure_string(args, "exercise_type")
    row = ExerciseLog(
        user_id=ctx.user.id,
        logged_at=datetime.now(timezone.utc),
        exercise_type=exercise_type,
        duration_minutes=_to_int(args.get("duration_minutes"), "duration_minutes"),
        details=_json_dumps(args["details"]) if isinstance(args.get("details"), (dict, list)) else args.get("details"),
        max_hr=_to_int(args.get("max_hr"), "max_hr"),
        avg_hr=_to_int(args.get("avg_hr"), "avg_hr"),
        calories_burned=_to_float(args.get("calories_burned"), "calories_burned"),
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"exercise_log_id": row.id}


def _tool_food_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    meal_label = str(args.get("meal_label", "")).strip() or None
    items_val = args.get("items", [])
    if isinstance(items_val, str):
        try:
            items = json.loads(items_val)
        except json.JSONDecodeError:
            items = [{"name": items_val}]
    elif isinstance(items_val, list):
        items = items_val
    else:
        raise ToolExecutionError("`items` must be a list or JSON string")

    if not isinstance(items, list):
        raise ToolExecutionError("`items` must resolve to a list")

    query_name = str(args.get("template_name", "")).strip() or meal_label or ""
    if not query_name and items:
        first = items[0]
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
            logged_at=datetime.now(timezone.utc),
            meal_label=meal_label or resolved_template.name,
            items=_json_dumps(template_items),
            calories=(resolved_template.calories * mult) if resolved_template.calories is not None else None,
            protein_g=(resolved_template.protein_g * mult) if resolved_template.protein_g is not None else None,
            carbs_g=(resolved_template.carbs_g * mult) if resolved_template.carbs_g is not None else None,
            fat_g=(resolved_template.fat_g * mult) if resolved_template.fat_g is not None else None,
            fiber_g=(resolved_template.fiber_g * mult) if resolved_template.fiber_g is not None else None,
            sodium_mg=(resolved_template.sodium_mg * mult) if resolved_template.sodium_mg is not None else None,
            notes=str(args.get("notes", "")).strip() or None,
        )
        ctx.db.add(row)
        ctx.db.flush()
        return {"food_log_id": row.id, "used_template": True, "meal_template_id": resolved_template.id}

    row = FoodLog(
        user_id=ctx.user.id,
        logged_at=datetime.now(timezone.utc),
        meal_label=meal_label,
        items=_json_dumps(items),
        calories=_coerce_float_field(args, "calories"),
        protein_g=_coerce_float_field(args, "protein_g"),
        carbs_g=_coerce_float_field(args, "carbs_g"),
        fat_g=_coerce_float_field(args, "fat_g"),
        fiber_g=_coerce_float_field(args, "fiber_g"),
        sodium_mg=_coerce_float_field(args, "sodium_mg"),
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"food_log_id": row.id, "used_template": False}


def _tool_hydration_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    amount_ml = _to_float(args.get("amount_ml"), "amount_ml")
    if amount_ml is None or amount_ml <= 0:
        raise ToolExecutionError("`amount_ml` must be > 0")
    row = HydrationLog(
        user_id=ctx.user.id,
        logged_at=datetime.now(timezone.utc),
        amount_ml=amount_ml,
        source=str(args.get("source", "water")).strip() or "water",
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(row)
    ctx.db.flush()
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
        logged_at=datetime.now(timezone.utc),
        supplements=_json_dumps(supplements),
        timing=str(args.get("timing", "")).strip() or None,
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"supplement_log_id": row.id}


def _tool_sleep_log_write(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    row = SleepLog(
        user_id=ctx.user.id,
        sleep_start=None,
        sleep_end=None,
        duration_minutes=_to_int(args.get("duration_minutes"), "duration_minutes"),
        quality=str(args.get("quality", "")).strip() or None,
        notes=str(args.get("notes", "")).strip() or None,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"sleep_log_id": row.id}


def _tool_fasting_manage(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action = str(args.get("action", "")).strip().lower()
    now = datetime.now(timezone.utc)
    if action not in {"start", "end"}:
        raise ToolExecutionError("`action` must be `start` or `end`")

    if action == "start":
        row = FastingLog(
            user_id=ctx.user.id,
            fast_start=now,
            fast_type=str(args.get("fast_type", "")).strip() or None,
            notes=str(args.get("notes", "")).strip() or None,
        )
        ctx.db.add(row)
        ctx.db.flush()
        return {"status": "started", "fasting_log_id": row.id, "fast_start": row.fast_start.isoformat()}

    active = (
        ctx.db.query(FastingLog)
        .filter(FastingLog.user_id == ctx.user.id, FastingLog.fast_end.is_(None))
        .order_by(FastingLog.fast_start.desc())
        .first()
    )
    if not active:
        return {"status": "no_active_fast"}
    active.fast_end = now
    start = active.fast_start if active.fast_start.tzinfo else active.fast_start.replace(tzinfo=timezone.utc)
    active.duration_minutes = int((now - start).total_seconds() / 60)
    return {"status": "ended", "fasting_log_id": active.id, "duration_minutes": active.duration_minutes}


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


def _coerce_float_field(args: dict[str, Any], field: str) -> float | None:
    if field not in args:
        return None
    return _to_float(args.get(field), field)


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
        logged_at=datetime.now(timezone.utc),
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
