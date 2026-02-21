from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from db.models import MealTemplate, Message
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


def _meal_templates_for_user(ctx: ToolContext) -> list[MealTemplate]:
    return (
        ctx.db.query(MealTemplate)
        .filter(MealTemplate.user_id == ctx.user.id)
        .order_by(MealTemplate.updated_at.desc(), MealTemplate.created_at.desc())
        .all()
    )


def _serialize_template(row: MealTemplate) -> dict[str, Any]:
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
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


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


def _tool_meal_template_list(_: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    rows = _meal_templates_for_user(ctx)
    return {"templates": [_serialize_template(r) for r in rows]}


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
            name="health_search",
            description="Search recent health conversation history for a text query.",
            required_fields=("query",),
            read_only=True,
            tags=("search",),
        ),
        _tool_health_search,
    )
