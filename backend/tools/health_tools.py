from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import func

from db.models import FoodLog, MealResponseSignal, MealTemplate, MealTemplateVersion, Message, VitalsLog
from tools.base import ToolContext, ToolExecutionError, ToolSpec, ensure_string
from tools.registry import ToolRegistry
from utils.med_utils import parse_structured_list


BP_MED_HINTS = {
    "candesartan",
    "lisinopril",
    "losartan",
    "amlodipine",
    "hydrochlorothiazide",
    "hctz",
    "metoprolol",
    "atenolol",
    "valsartan",
}

VITAMIN_HINTS = {
    "vitamin",
    "multi",
    "multivitamin",
    "b12",
    "d3",
    "omega",
    "coq10",
}

TIMING_HINTS = {
    "morning": {"morning", "with breakfast"},
    "evening": {"evening", "with dinner", "bedtime"},
    "lunch": {"with lunch"},
    "breakfast": {"with breakfast"},
    "dinner": {"with dinner"},
    "bedtime": {"bedtime"},
}


def _json_or_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    txt = raw.strip()
    if not txt:
        return []
    if txt.startswith("["):
        try:
            arr = json.loads(txt)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in txt.split(",") if x.strip()]


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_text(text)))


def _extract_query_timing(query: str) -> set[str]:
    q = _normalize_text(query)
    out: set[str] = set()
    for q_hint, timing_values in TIMING_HINTS.items():
        if q_hint in q:
            out.update(timing_values)
    return out


def _item_matches_timing(item: dict[str, str], timing_targets: set[str]) -> bool:
    if not timing_targets:
        return False
    t = _normalize_text(str(item.get("timing", "")))
    if not t:
        return False
    return t in timing_targets


def _resolve_structured_reference(
    query: str,
    items: list[dict[str, str]],
    domain: str,
) -> list[dict[str, Any]]:
    if not items:
        return []

    q_norm = _normalize_text(query)
    q_tokens = _tokens(query)
    q_timing = _extract_query_timing(query)
    matches: list[dict[str, Any]] = []

    if domain == "medication":
        if "blood pressure" in q_norm or "bp med" in q_norm:
            for item in items:
                name = _normalize_text(item.get("name", ""))
                if any(k in name for k in BP_MED_HINTS):
                    matches.append({**item, "score": 0.95, "reason": "bp_keyword"})

    if domain == "supplement":
        if "vitamin" in q_norm or "vitamins" in q_norm:
            for item in items:
                name = _normalize_text(item.get("name", ""))
                if any(k in name for k in VITAMIN_HINTS):
                    matches.append({**item, "score": 0.9, "reason": "vitamin_keyword"})

    for item in items:
        name = item.get("name", "")
        if not name:
            continue
        n_norm = _normalize_text(name)

        # Direct mention by text
        if n_norm and n_norm in q_norm:
            matches.append({**item, "score": 1.0, "reason": "direct_name_match"})
            continue

        # Timing phrase like "morning meds" / "evening vitamins"
        if _item_matches_timing(item, q_timing):
            if (domain == "medication" and ("med" in q_norm or "medication" in q_norm)) or (
                domain == "supplement" and ("supplement" in q_norm or "vitamin" in q_norm)
            ):
                matches.append({**item, "score": 0.85, "reason": "timing_group_match"})
                continue

        # Token overlap fallback
        n_tokens = _tokens(name)
        if not n_tokens:
            continue
        overlap = len(q_tokens & n_tokens)
        if overlap == 0:
            continue
        score = overlap / max(len(n_tokens), 1)
        if score >= 0.34:
            matches.append({**item, "score": round(score, 3), "reason": "token_overlap"})

    # Generic phrases: "my meds", "my vitamins", "my supplements"
    if not matches:
        if domain == "medication" and ("my meds" in q_norm or "my medication" in q_norm):
            for item in items:
                if q_timing and not _item_matches_timing(item, q_timing):
                    continue
                matches.append({**item, "score": 0.6, "reason": "generic_med_group"})
        if domain == "supplement" and (
            "my supplements" in q_norm or "my vitamin" in q_norm or "my vitamins" in q_norm
        ):
            for item in items:
                if q_timing and not _item_matches_timing(item, q_timing):
                    continue
                matches.append({**item, "score": 0.6, "reason": "generic_supp_group"})

    # De-duplicate by canonical name, keep highest score
    best_by_name: dict[str, dict[str, Any]] = {}
    for m in matches:
        name = str(m.get("name", "")).strip()
        if not name:
            continue
        existing = best_by_name.get(name)
        if not existing or float(m.get("score", 0)) > float(existing.get("score", 0)):
            best_by_name[name] = m

    ordered = sorted(best_by_name.values(), key=lambda m: float(m.get("score", 0)), reverse=True)
    return ordered


def _normalize_meal_name(text: str) -> str:
    t = _normalize_text(text)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = " ".join(t.split())
    return t


def _meal_templates_for_user(ctx: ToolContext, include_archived: bool = False) -> list[MealTemplate]:
    query = ctx.db.query(MealTemplate).filter(MealTemplate.user_id == ctx.user.id)
    if not include_archived:
        query = query.filter(MealTemplate.is_archived.is_(False))
    return query.order_by(MealTemplate.updated_at.desc(), MealTemplate.created_at.desc()).all()


def _serialize_template(row: MealTemplate) -> dict[str, Any]:
    version_count = len(row.versions) if row.versions is not None else 0
    return {
        "id": row.id,
        "name": row.name,
        "normalized_name": row.normalized_name,
        "aliases": _json_or_csv_list(row.aliases),
        "ingredients": _json_or_csv_list(row.ingredients),
        "servings": row.servings,
        "macros_per_serving": {
            "calories": row.calories,
            "protein_g": row.protein_g,
            "carbs_g": row.carbs_g,
            "fat_g": row.fat_g,
            "fiber_g": row.fiber_g,
            "sodium_mg": row.sodium_mg,
        },
        "notes": row.notes,
        "is_archived": bool(row.is_archived),
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "version_count": version_count,
    }


def _resolve_template_from_args(
    args: dict[str, Any],
    ctx: ToolContext,
    include_archived: bool = True,
) -> MealTemplate:
    template_id = args.get("template_id")
    template_name = args.get("template_name")
    query = ctx.db.query(MealTemplate).filter(MealTemplate.user_id == ctx.user.id)
    if not include_archived:
        query = query.filter(MealTemplate.is_archived.is_(False))

    if template_id is not None:
        try:
            tid = int(template_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`template_id` must be an integer") from exc
        row = query.filter(MealTemplate.id == tid).first()
    elif template_name:
        row = query.filter(MealTemplate.normalized_name == _normalize_meal_name(str(template_name))).first()
    else:
        raise ToolExecutionError("Provide `template_id` or `template_name`")

    if not row:
        raise ToolExecutionError("Meal template not found")
    return row


def _template_usage_stats(ctx: ToolContext, template_id: int) -> dict[str, Any]:
    usage_count = (
        ctx.db.query(func.count(FoodLog.id))
        .filter(FoodLog.user_id == ctx.user.id, FoodLog.meal_template_id == template_id)
        .scalar()
    ) or 0
    last_logged_at = (
        ctx.db.query(FoodLog.logged_at)
        .filter(FoodLog.user_id == ctx.user.id, FoodLog.meal_template_id == template_id)
        .order_by(FoodLog.logged_at.desc())
        .scalar()
    )
    return {
        "usage_count": int(usage_count),
        "last_logged_at": last_logged_at.isoformat() if last_logged_at else None,
    }


def _batch_template_usage_stats(ctx: ToolContext, template_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not template_ids:
        return {}
    rows = (
        ctx.db.query(
            FoodLog.meal_template_id,
            func.count(FoodLog.id),
            func.max(FoodLog.logged_at),
        )
        .filter(
            FoodLog.user_id == ctx.user.id,
            FoodLog.meal_template_id.in_(template_ids),
        )
        .group_by(FoodLog.meal_template_id)
        .all()
    )
    out: dict[int, dict[str, Any]] = {}
    for template_id, count_val, last_logged in rows:
        if template_id is None:
            continue
        out[int(template_id)] = {
            "usage_count": int(count_val or 0),
            "last_logged_at": last_logged.isoformat() if last_logged else None,
        }
    return out


def _tool_meal_template_get(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    row = _resolve_template_from_args(args, ctx, include_archived=True)
    payload = _serialize_template(row)
    payload.update(_template_usage_stats(ctx, row.id))
    return {"template": payload}


def _tool_meal_template_versions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    row = _resolve_template_from_args(args, ctx, include_archived=True)
    versions = (
        ctx.db.query(MealTemplateVersion)
        .filter(MealTemplateVersion.user_id == ctx.user.id, MealTemplateVersion.meal_template_id == row.id)
        .order_by(MealTemplateVersion.version_number.desc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for version in versions:
        try:
            snapshot = json.loads(version.snapshot_json) if version.snapshot_json else {}
        except json.JSONDecodeError:
            snapshot = {}
        items.append(
            {
                "id": version.id,
                "version_number": version.version_number,
                "change_note": version.change_note,
                "snapshot": snapshot,
                "created_at": version.created_at.isoformat() if version.created_at else None,
            }
        )
    return {"template_id": row.id, "name": row.name, "versions": items}


def _weight_daily_map(ctx: ToolContext, since: datetime) -> dict[str, float]:
    vitals_rows = (
        ctx.db.query(VitalsLog)
        .filter(
            VitalsLog.user_id == ctx.user.id,
            VitalsLog.logged_at >= since,
            VitalsLog.weight_kg.isnot(None),
        )
        .order_by(VitalsLog.logged_at.asc())
        .all()
    )
    bucket: dict[str, list[float]] = {}
    for row in vitals_rows:
        if row.weight_kg is None or not row.logged_at:
            continue
        key = row.logged_at.date().isoformat()
        bucket.setdefault(key, []).append(float(row.weight_kg))
    out: dict[str, float] = {}
    for key, vals in bucket.items():
        if vals:
            out[key] = sum(vals) / len(vals)
    return out


def _find_weight_delta(weight_map: dict[str, float], day: datetime) -> float | None:
    today_key = day.date().isoformat()
    next_key = (day + timedelta(days=1)).date().isoformat()
    if today_key not in weight_map or next_key not in weight_map:
        return None
    return weight_map[next_key] - weight_map[today_key]


def _tool_meal_response_insights(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    since_days = args.get("since_days", 90)
    if not isinstance(since_days, int) or since_days < 7 or since_days > 365:
        since_days = 90

    only_template_id = args.get("template_id")
    if only_template_id is not None:
        try:
            only_template_id = int(only_template_id)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("`template_id` must be an integer") from exc

    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    templates = _meal_templates_for_user(ctx, include_archived=True)
    template_by_id = {t.id: t for t in templates}
    if only_template_id is not None:
        template_by_id = {tid: t for tid, t in template_by_id.items() if tid == only_template_id}
        if not template_by_id:
            raise ToolExecutionError("Meal template not found")

    usage_rows = (
        ctx.db.query(FoodLog)
        .filter(
            FoodLog.user_id == ctx.user.id,
            FoodLog.meal_template_id.isnot(None),
            FoodLog.logged_at >= since,
        )
        .order_by(FoodLog.logged_at.asc())
        .all()
    )
    if only_template_id is not None:
        usage_rows = [r for r in usage_rows if r.meal_template_id == only_template_id]

    signals_rows = (
        ctx.db.query(MealResponseSignal)
        .filter(
            MealResponseSignal.user_id == ctx.user.id,
            MealResponseSignal.created_at >= since,
            MealResponseSignal.meal_template_id.isnot(None),
        )
        .order_by(MealResponseSignal.created_at.asc())
        .all()
    )
    if only_template_id is not None:
        signals_rows = [r for r in signals_rows if r.meal_template_id == only_template_id]

    weight_map = _weight_daily_map(ctx, since)

    by_template: dict[int, dict[str, Any]] = {}
    for row in usage_rows:
        tid = int(row.meal_template_id or 0)
        if tid == 0:
            continue
        entry = by_template.setdefault(
            tid,
            {
                "usage_count": 0,
                "weight_deltas_kg": [],
            },
        )
        entry["usage_count"] += 1
        delta = _find_weight_delta(weight_map, row.logged_at if row.logged_at else datetime.now(timezone.utc))
        if delta is not None:
            entry["weight_deltas_kg"].append(delta)

    for row in signals_rows:
        tid = int(row.meal_template_id or 0)
        if tid == 0:
            continue
        entry = by_template.setdefault(
            tid,
            {
                "usage_count": 0,
                "weight_deltas_kg": [],
            },
        )
        entry.setdefault("signal_count", 0)
        entry.setdefault("energy_values", [])
        entry.setdefault("gi_events", 0)
        entry.setdefault("gi_severity_values", [])
        entry.setdefault("gi_tag_counts", {})
        entry["signal_count"] += 1
        if row.energy_level is not None:
            entry["energy_values"].append(int(row.energy_level))
        tag_list = _json_or_csv_list(row.gi_symptom_tags)
        if tag_list or row.gi_severity is not None:
            entry["gi_events"] += 1
        for tag in tag_list:
            key = tag.lower()
            entry["gi_tag_counts"][key] = int(entry["gi_tag_counts"].get(key, 0)) + 1
        if row.gi_severity is not None:
            entry["gi_severity_values"].append(int(row.gi_severity))

    results: list[dict[str, Any]] = []
    for tid, agg in by_template.items():
        template = template_by_id.get(tid)
        if not template:
            continue
        usage_count = int(agg.get("usage_count", 0))
        signal_count = int(agg.get("signal_count", 0))
        energy_values = list(agg.get("energy_values", []))
        gi_events = int(agg.get("gi_events", 0))
        gi_severity_values = list(agg.get("gi_severity_values", []))
        gi_tag_counts = dict(agg.get("gi_tag_counts", {}))
        weight_deltas = list(agg.get("weight_deltas_kg", []))

        avg_energy = (sum(energy_values) / len(energy_values)) if energy_values else None
        gi_event_rate = (gi_events / signal_count) if signal_count else None
        avg_gi_severity = (sum(gi_severity_values) / len(gi_severity_values)) if gi_severity_values else None
        avg_weight_delta = (sum(weight_deltas) / len(weight_deltas)) if weight_deltas else None

        top_gi_tags = sorted(gi_tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

        results.append(
            {
                "template_id": template.id,
                "template_name": template.name,
                "is_archived": bool(template.is_archived),
                "usage_count": usage_count,
                "signal_count": signal_count,
                "energy_avg": round(avg_energy, 3) if avg_energy is not None else None,
                "gi_event_rate": round(gi_event_rate, 3) if gi_event_rate is not None else None,
                "gi_severity_avg": round(avg_gi_severity, 3) if avg_gi_severity is not None else None,
                "weight_delta_next_day_kg_avg": round(avg_weight_delta, 4) if avg_weight_delta is not None else None,
                "weight_delta_sample_size": len(weight_deltas),
                "top_gi_tags": [{"tag": tag, "count": count} for tag, count in top_gi_tags],
            }
        )

    results.sort(key=lambda x: (x["usage_count"], x["signal_count"]), reverse=True)
    return {"since_days": since_days, "items": results}


def _tool_profile_read(_: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    s = ctx.user.settings
    if not s:
        raise ToolExecutionError("User settings are missing")
    return {
        "profile": {
            "age": s.age,
            "sex": s.sex,
            "height_cm": s.height_cm,
            "current_weight_kg": s.current_weight_kg,
            "goal_weight_kg": s.goal_weight_kg,
            "height_unit": s.height_unit or "cm",
            "weight_unit": s.weight_unit or "kg",
            "hydration_unit": s.hydration_unit or "ml",
            "fitness_level": s.fitness_level,
            "timezone": s.timezone,
            "medical_conditions": _json_or_csv_list(s.medical_conditions),
            "dietary_preferences": _json_or_csv_list(s.dietary_preferences),
            "health_goals": _json_or_csv_list(s.health_goals),
            "family_history": _json_or_csv_list(s.family_history),
            "medications": parse_structured_list(s.medications),
            "supplements": parse_structured_list(s.supplements),
        }
    }


def _tool_medication_resolve_reference(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = ensure_string(args, "query")
    items = parse_structured_list(ctx.user.settings.medications if ctx.user.settings else None)
    matches = _resolve_structured_reference(query, items, "medication")
    return {"query": query, "matches": matches}


def _tool_supplement_resolve_reference(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = ensure_string(args, "query")
    items = parse_structured_list(ctx.user.settings.supplements if ctx.user.settings else None)
    matches = _resolve_structured_reference(query, items, "supplement")
    return {"query": query, "matches": matches}


def _tool_meal_template_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    include_archived = bool(args.get("include_archived", False))
    rows = _meal_templates_for_user(ctx, include_archived=include_archived)
    usage_map = _batch_template_usage_stats(ctx, [int(r.id) for r in rows])
    templates: list[dict[str, Any]] = []
    for row in rows:
        payload = _serialize_template(row)
        payload.update(usage_map.get(int(row.id), {"usage_count": 0, "last_logged_at": None}))
        templates.append(payload)
    return {"templates": templates}


def _tool_meal_template_resolve_name(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = ensure_string(args, "query")
    rows = _meal_templates_for_user(ctx)
    if not rows:
        return {"query": query, "matches": []}

    norm_query = _normalize_meal_name(query)
    q_tokens = _tokens(norm_query)
    matches: list[dict[str, Any]] = []

    for row in rows:
        names = [row.name, *(_json_or_csv_list(row.aliases))]
        best_score = 0.0
        best_reason = "token_overlap"
        for candidate in names:
            norm_name = _normalize_meal_name(candidate)
            if not norm_name:
                continue
            if norm_name == norm_query:
                best_score = 1.0
                best_reason = "exact_name_match"
                break
            if norm_name in norm_query or norm_query in norm_name:
                best_score = max(best_score, 0.92)
                best_reason = "contains_match"
                continue
            c_tokens = _tokens(norm_name)
            if not c_tokens:
                continue
            overlap = len(q_tokens & c_tokens)
            if overlap > 0:
                score = overlap / max(len(c_tokens), 1)
                if score > best_score:
                    best_score = score
                    best_reason = "token_overlap"

        if best_score >= 0.34:
            matches.append(
                {
                    "template": _serialize_template(row),
                    "score": round(best_score, 3),
                    "reason": best_reason,
                }
            )

    matches.sort(key=lambda m: float(m["score"]), reverse=True)
    return {"query": query, "matches": matches}


def _tool_health_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = ensure_string(args, "query")
    q = _normalize_text(query)
    since_days = args.get("since_days", 30)
    if not isinstance(since_days, int) or since_days < 1 or since_days > 365:
        since_days = 30

    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    messages = (
        ctx.db.query(Message)
        .filter(
            Message.user_id == ctx.user.id,
            Message.created_at >= since,
            Message.content.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(150)
        .all()
    )

    hits: list[dict[str, Any]] = []
    for m in messages:
        content = m.content or ""
        if q in _normalize_text(content):
            hits.append(
                {
                    "message_id": m.id,
                    "role": m.role,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "content": content[:500],
                }
            )

    return {"query": query, "since_days": since_days, "hits": hits[:50]}


def register_health_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="profile_read",
            description="Read normalized user profile, goals, meds, supplements, and preferences.",
            read_only=True,
            tags=("profile", "read"),
        ),
        _tool_profile_read,
    )
    registry.register(
        ToolSpec(
            name="medication_resolve_reference",
            description="Resolve phrases like `morning meds` or `blood pressure meds` to profile medications.",
            required_fields=("query",),
            read_only=True,
            tags=("medication", "resolve"),
        ),
        _tool_medication_resolve_reference,
    )
    registry.register(
        ToolSpec(
            name="supplement_resolve_reference",
            description="Resolve supplement phrases like `my vitamins` to profile supplements.",
            required_fields=("query",),
            read_only=True,
            tags=("supplement", "resolve"),
        ),
        _tool_supplement_resolve_reference,
    )
    registry.register(
        ToolSpec(
            name="meal_template_list",
            description="List user-defined named meals (meal templates).",
            read_only=True,
            tags=("meal_template", "read"),
        ),
        _tool_meal_template_list,
    )
    registry.register(
        ToolSpec(
            name="meal_template_get",
            description="Get one meal template by template id or name, with usage stats.",
            read_only=True,
            tags=("meal_template", "read"),
        ),
        _tool_meal_template_get,
    )
    registry.register(
        ToolSpec(
            name="meal_template_versions",
            description="List saved version snapshots for a meal template.",
            read_only=True,
            tags=("meal_template", "read"),
        ),
        _tool_meal_template_versions,
    )
    registry.register(
        ToolSpec(
            name="meal_template_resolve_name",
            description="Resolve a named meal phrase like `power pancakes` to known meal templates.",
            required_fields=("query",),
            read_only=True,
            tags=("meal_template", "resolve"),
        ),
        _tool_meal_template_resolve_name,
    )
    registry.register(
        ToolSpec(
            name="meal_response_insights",
            description="Analyze meal response trends (weight, GI symptoms, energy) per meal template.",
            read_only=True,
            tags=("meal_response", "read"),
        ),
        _tool_meal_response_insights,
    )
    registry.register(
        ToolSpec(
            name="health_search",
            description="Search recent health conversation history for a text query.",
            required_fields=("query",),
            read_only=True,
            tags=("search",),
        ),
        _tool_health_search,
    )
