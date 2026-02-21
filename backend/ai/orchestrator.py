import json
import logging
import inspect
import re
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncGenerator

from sqlalchemy.orm import Session

from config import settings
from ai.context_builder import build_context, get_recent_messages
from ai.specialist_router import classify_intent
from ai.log_parser import parse_log_data
from ai.image_analyzer import analyze_image
from ai.providers import get_provider
from ai.usage_tracker import track_usage_from_result
from db.models import (
    User, Message, FeedbackEntry, FoodLog, MealTemplate,
)
from services.specialists_config import get_enabled_specialist_ids, get_effective_specialists, parse_overrides
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError
from utils.encryption import decrypt_api_key
from utils.datetime_utils import today_utc
from utils.units import kg_to_lb

logger = logging.getLogger(__name__)

WEB_SEARCH_CATEGORIES = {
    "ask_nutrition",
    "ask_exercise",
    "ask_sleep",
    "ask_supplement",
    "ask_medical",
}
WEB_SEARCH_TRIGGERS = (
    "search",
    "look up",
    "latest",
    "recent",
    "new",
    "today",
    "current",
    "guideline",
    "guidelines",
    "evidence",
    "study",
    "studies",
    "research",
    "news",
)
TIME_QUERY_PATTERNS = (
    r"\bwhat\s+time\s+is\s+it\b",
    r"\bwhat(?:'s| is)?\s+the\s+time\b",
    r"\bcurrent\s+time\b",
    r"\btell\s+me\s+the\s+time\b",
    r"\btime\s+now\b",
    r"\bwhat\s+day\s+is\s+it\b",
    r"\bwhat(?:'s| is)?\s+today(?:'s)?\s+date\b",
    r"\bcurrent\s+date\b",
)
MENU_SAVE_KEYWORDS = (
    "save to menu",
    "save this to menu",
    "save this meal",
    "save it as",
    "save as",
    "add to menu",
    "add this to menu",
    "make this a menu item",
    "menu item",
)
MENU_UPDATE_KEYWORDS = (
    "update base meal",
    "update the base meal",
    "update my menu",
    "save changes to",
    "save this change to",
    "update it",
    "apply this to",
    "update menu item",
)
MENU_CONFIRM_WORDS = {
    "yes",
    "y",
    "yep",
    "yeah",
    "sure",
    "ok",
    "okay",
    "do it",
    "save it",
    "add it",
}
GI_SYMPTOM_KEYWORDS = {
    "bloating": {"bloating", "bloated"},
    "gas": {"gas", "gassy", "flatulence"},
    "reflux": {"reflux", "heartburn"},
    "nausea": {"nausea", "nauseous"},
    "diarrhea": {"diarrhea", "loose stool", "loose stools"},
    "constipation": {"constipation", "constipated"},
    "cramps": {"cramps", "cramping", "stomach cramp"},
    "stomach_pain": {"stomach pain", "stomach ache", "abdominal pain"},
}
MEAL_CONTEXT_KEYWORDS = (
    "meal",
    "ate",
    "eating",
    "after eating",
    "post meal",
    "breakfast",
    "lunch",
    "dinner",
    "snack",
    "food",
)

MEDICATION_KEYWORDS = {
    "ezetimibe",
    "statin",
    "metformin",
    "lisinopril",
    "losartan",
    "candesartan",
    "amlodipine",
    "hydrochlorothiazide",
    "atorvastatin",
    "rosuvastatin",
    "simvastatin",
    "levothyroxine",
    "insulin",
    "semaglutide",
}

BP_MED_KEYWORDS = {
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

GENERIC_MEDICATION_PHRASES = {
    "blood pressure meds",
    "blood pressure medications",
    "bp meds",
    "bp medications",
    "my meds",
    "my medications",
}

MED_MATCH_PROMPT = """You map a user's medication-taking message to their listed medications.

Given:
- user message
- medication list

Return ONLY JSON:
{
  "matched_medications": ["exact medication names from list only"],
  "confidence": 0.0
}

Rules:
- Only return names that appear EXACTLY in the provided list.
- Do not invent medications.
- If message is ambiguous or no match, return empty array.
"""

SUPP_MATCH_PROMPT = """You map a user's supplement-taking message to their listed supplements.

Given:
- user message
- supplement list

Return ONLY JSON:
{
  "matched_supplements": ["exact supplement names from list only"],
  "confidence": 0.0
}

Rules:
- Only return names that appear EXACTLY in the provided list.
- Do not invent supplements.
- If message is ambiguous or no match, return empty array.
"""

FEEDBACK_EXTRACT_PROMPT = """Extract product feedback items from a user message.

Return ONLY valid JSON:
{
  "entries": [
    {
      "feedback_type": "bug|enhancement|missing|other",
      "title": "short title",
      "details": "one sentence details"
    }
  ]
}

Rules:
- Only include actionable app/product feedback.
- If there is no actionable feedback, return {"entries":[]}.
- Keep title concise (<= 90 chars).
- Never include medical advice as feedback.
"""

PROFILE_EXTRACT_PROMPT = """Extract profile updates from this health message.

Return ONLY valid JSON:
{
  "medications": [{"name": "medication name", "dose": "dose if known", "timing": "when taken if mentioned"}],
  "supplements": [{"name": "brand + product name", "dose": "dose/form if known", "timing": "when taken if mentioned"}],
  "medical_conditions": ["condition names"],
  "dietary_preferences": ["preferences/restrictions"],
  "health_goals": ["goals"],
  "family_history": ["family risk factors"]
}

Rules:
- Include only items explicitly stated by the user or clearly visible in attached image context.
- If no updates are present, return empty arrays.
- For medications/supplements: "name" is the product name without dose (e.g., "Jamieson Vitamin D3 drops"), "dose" is the amount (e.g., "1000 IU/drop, 4 drops daily"), "timing" is when taken (e.g., "morning", "with breakfast", "bedtime"). Leave dose/timing as empty string if not mentioned.
- Valid timing values: morning, evening, with breakfast, with lunch, with dinner, bedtime, twice daily, as needed, or empty string.
- If user provides a correction, return the corrected full entry.
"""

from utils.med_utils import (
    StructuredItem,
    to_structured,
    parse_structured_list,
    cleanup_structured_list,
    looks_like_medication as _looks_like_medication,
)


def _is_generic_medication_phrase(item: str) -> bool:
    t = " ".join(item.lower().split())
    return t in GENERIC_MEDICATION_PHRASES


def _normalize_alnum(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _parse_plain_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
    return [s.strip() for s in text.split(",") if s.strip()]


def _merge_plain_list(existing_raw: str | None, incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*_parse_plain_list(existing_raw), *incoming]:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


def _resolve_specialist_name(overrides: dict, specialist_id: str) -> str:
    for spec in get_effective_specialists(overrides):
        if spec.get("id") == specialist_id:
            return str(spec.get("name") or specialist_id)
    return specialist_id.replace("_", " ").title()


def _has_feedback_signal(text: str) -> bool:
    t = text.lower()
    signals = [
        "bug",
        "issue",
        "error",
        "not working",
        "doesn't work",
        "doesnt work",
        "broken",
        "improve",
        "improvement",
        "enhancement",
        "feature request",
        "missing",
        "should have",
        "add a",
        "please add",
        "would be better",
        "doesn't update",
    ]
    return any(s in t for s in signals)


def _should_use_web_search(message_text: str, category: str, specialist_id: str) -> bool:
    if not settings.ENABLE_WEB_SEARCH:
        return False
    if specialist_id not in set(settings.WEB_SEARCH_ALLOWED_SPECIALISTS):
        return False

    text = message_text.lower()
    if any(trigger in text for trigger in WEB_SEARCH_TRIGGERS):
        return True
    return category in WEB_SEARCH_CATEGORIES


def _format_web_search_context(results: list[dict]) -> str:
    if not results:
        return ""
    lines = [
        "## Live Web Search Results",
        "Use these current references when relevant. Cite URLs when making claims from these results.",
    ]
    for idx, row in enumerate(results, start=1):
        title = str(row.get("title", "")).strip() or f"Result {idx}"
        url = str(row.get("url", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        source = str(row.get("source", "")).strip()
        lines.append(f"{idx}. {title}")
        if source:
            lines.append(f"   Source: {source}")
        if url:
            lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
    return "\n".join(lines)


def _should_include_time_context(message_text: str) -> bool:
    text = message_text.lower()
    return any(re.search(pattern, text) for pattern in TIME_QUERY_PATTERNS)


def _format_time_context(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    timezone_name = str(result.get("timezone", "UTC"))
    offset = str(result.get("utc_offset", "UTC+00:00"))
    local_date = str(result.get("local_date", "")).strip()
    local_time_12h = str(result.get("local_time_12h", "")).strip()
    local_time_24h = str(result.get("local_time_24h", "")).strip()
    iso_local = str(result.get("iso_local", "")).strip()
    if not (local_date or local_time_12h or local_time_24h):
        return ""

    lines = [
        "## Current Time",
        "Use this as the authoritative current date/time for this response.",
        f"- Timezone: {timezone_name} ({offset})",
    ]
    if local_date:
        lines.append(f"- Local date: {local_date}")
    if local_time_12h:
        lines.append(f"- Local time (12h): {local_time_12h}")
    if local_time_24h:
        lines.append(f"- Local time (24h): {local_time_24h}")
    if iso_local:
        lines.append(f"- ISO local: {iso_local}")
    return "\n".join(lines)


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.lower().split())


def _last_assistant_message(db: Session, user: User) -> Message | None:
    return (
        db.query(Message)
        .filter(Message.user_id == user.id, Message.role == "assistant", Message.content.isnot(None))
        .order_by(Message.created_at.desc())
        .first()
    )


def _assistant_requested_menu_save(db: Session, user: User) -> bool:
    last = _last_assistant_message(db, user)
    if not last or not last.content:
        return False
    text = _normalize_whitespace(last.content)
    return (
        "save this meal to your menu" in text
        or "save this to your menu" in text
        or "add this to your menu" in text
    )


def _assistant_requested_menu_update(db: Session, user: User) -> bool:
    last = _last_assistant_message(db, user)
    if not last or not last.content:
        return False
    text = _normalize_whitespace(last.content)
    return "update your base menu item" in text or "update the base meal template" in text


def _extract_template_name_from_message(message_text: str) -> str | None:
    text = message_text.strip()
    patterns = [
        r"(?:call it|name it|save (?:it|this|this meal) as|add (?:it|this|this meal) as)\s+([a-zA-Z0-9][^.!?\n]+)",
        r"(?:template name is|menu name is)\s+([a-zA-Z0-9][^.!?\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip().strip("\"'")
        candidate = re.sub(r"\s+", " ", candidate)
        if candidate:
            return candidate[:80]
    return None


def _parse_food_items(food_log: FoodLog) -> list[dict]:
    try:
        parsed = json.loads(food_log.items) if isinstance(food_log.items, str) else food_log.items
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict) or isinstance(p, str)]
    except Exception:
        pass
    if food_log.items:
        return [{"name": str(food_log.items)}]
    return []


def _latest_food_log(db: Session, user: User, lookback_hours: int = 72) -> FoodLog | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))
    return (
        db.query(FoodLog)
        .filter(FoodLog.user_id == user.id, FoodLog.logged_at >= cutoff)
        .order_by(FoodLog.logged_at.desc())
        .first()
    )


def _food_log_from_saved_output(db: Session, user: User, saved_out: dict[str, Any] | None) -> FoodLog | None:
    if not isinstance(saved_out, dict):
        return None
    raw_id = saved_out.get("food_log_id")
    try:
        food_log_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return (
        db.query(FoodLog)
        .filter(FoodLog.user_id == user.id, FoodLog.id == food_log_id)
        .first()
    )


def _template_payload_from_food_log(food_log: FoodLog, name_override: str | None = None) -> dict:
    items = _parse_food_items(food_log)
    ingredient_names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
        else:
            name = str(item).strip()
        if name:
            ingredient_names.append(name)

    name = (name_override or "").strip()
    if not name:
        name = (food_log.meal_label or "").strip()
    if not name and ingredient_names:
        name = ingredient_names[0]
    if not name:
        name = "Saved Meal"

    payload = {
        "name": name,
        "ingredients": ingredient_names,
        "servings": 1.0,
        "calories": food_log.calories,
        "protein_g": food_log.protein_g,
        "carbs_g": food_log.carbs_g,
        "fat_g": food_log.fat_g,
        "fiber_g": food_log.fiber_g,
        "sodium_mg": food_log.sodium_mg,
        "notes": (food_log.notes or "").strip() or None,
    }
    return payload


def _has_menu_save_intent(db: Session, user: User, message_text: str) -> bool:
    norm = _normalize_whitespace(message_text)
    if any(keyword in norm for keyword in MENU_SAVE_KEYWORDS):
        return True
    if _assistant_requested_menu_save(db, user):
        if norm in MENU_CONFIRM_WORDS:
            return True
        if norm.startswith("yes"):
            return True
        if "save" in norm or "add it" in norm:
            return True
    if norm in MENU_CONFIRM_WORDS and "menu" in norm:
        return True
    return False


def _has_menu_update_intent(db: Session, user: User, message_text: str) -> bool:
    norm = _normalize_whitespace(message_text)
    if any(keyword in norm for keyword in MENU_UPDATE_KEYWORDS):
        return True
    if _assistant_requested_menu_update(db, user):
        if norm in MENU_CONFIRM_WORDS:
            return True
        if norm.startswith("yes"):
            return True
        if "update" in norm or "base meal" in norm:
            return True
    if norm in MENU_CONFIRM_WORDS and "update" in norm:
        return True
    return False


def _looks_like_food_logging_message(message_text: str) -> bool:
    text = _normalize_whitespace(message_text)
    strong_cues = (
        "i had ",
        "i ate ",
        "i drank ",
        "for lunch",
        "for breakfast",
        "for dinner",
        "for snack",
        "my lunch was",
        "my breakfast was",
        "my dinner was",
    )
    if any(cue in text for cue in strong_cues):
        return True
    quantity_tokens = (" cup", " cups", " tbsp", " tsp", " oz", " ml", " g ", " gram", " grams", " scoop", " scoops")
    if "," in text and any(token in text for token in quantity_tokens):
        return True
    return False


def _try_handle_menu_template_action(
    db: Session,
    user: User,
    message_text: str,
    source_food_log: FoodLog | None = None,
) -> dict[str, Any] | None:
    save_intent = _has_menu_save_intent(db, user, message_text)
    update_intent = _has_menu_update_intent(db, user, message_text)
    if not save_intent and not update_intent:
        return None

    latest = source_food_log or _latest_food_log(db, user, lookback_hours=72)
    if not latest:
        return {
            "status": "failed",
            "action": "save" if save_intent else "update",
            "reason": "No recent food log found to build a menu item.",
        }

    template_name = _extract_template_name_from_message(message_text)
    payload = _template_payload_from_food_log(latest, name_override=template_name)
    if update_intent and latest.meal_template_id and not template_name:
        existing = (
            db.query(MealTemplate)
            .filter(MealTemplate.user_id == user.id, MealTemplate.id == latest.meal_template_id)
            .first()
        )
        if existing:
            payload["name"] = existing.name

    payload["change_note"] = "Updated from chat-confirmed base meal adjustment" if update_intent else "Created from chat food log"

    try:
        out = tool_registry.execute(
            "meal_template_upsert",
            payload,
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {
            "status": "success",
            "action": "update" if update_intent else "save",
            "result": out,
            "template_name": payload.get("name"),
        }
    except Exception as e:
        return {
            "status": "failed",
            "action": "update" if update_intent else "save",
            "reason": str(e),
        }


def _has_modification_cues(message_text: str) -> bool:
    text = _normalize_whitespace(message_text)
    cues = [
        "added ",
        "add ",
        "without ",
        "no ",
        "minus ",
        "instead ",
        "swap ",
        "substitute ",
        "extra ",
        "reduced ",
        "less ",
    ]
    return any(c in text for c in cues)


def _build_menu_followup_hint(
    db: Session,
    user: User,
    category: str,
    message_text: str,
    parsed_log: dict[str, Any] | None,
    saved_out: dict[str, Any] | None,
    menu_action_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if category != "log_food" or not isinstance(saved_out, dict):
        return None

    if isinstance(menu_action_result, dict):
        if str(menu_action_result.get("status", "")).strip().lower() == "success":
            return None

    used_template = bool(saved_out.get("used_template", False))
    if not used_template:
        meal_name = ""
        if isinstance(parsed_log, dict):
            meal_name = str(parsed_log.get("meal_label", "")).strip()
        if not meal_name:
            latest = _latest_food_log(db, user, lookback_hours=24)
            if latest:
                meal_name = (latest.meal_label or "").strip()
        return {
            "type": "ask_save_menu",
            "meal_name": meal_name,
        }

    if used_template and _has_modification_cues(message_text):
        return {
            "type": "ask_update_base",
            "meal_template_id": saved_out.get("meal_template_id"),
        }
    return None


def _format_menu_context(menu_action: dict[str, Any] | None, followup_hint: dict[str, Any] | None) -> str:
    lines: list[str] = []
    if menu_action:
        status = str(menu_action.get("status", "")).strip()
        action = str(menu_action.get("action", "save")).strip()
        lines.append("## Menu Action")
        if status == "success":
            lines.append(f"- Action: {action}")
            lines.append(f"- Status: success")
            if menu_action.get("template_name"):
                lines.append(f"- Template: {menu_action['template_name']}")
            lines.append("Acknowledge that the menu item was updated.")
        else:
            lines.append(f"- Action: {action}")
            lines.append(f"- Status: failed")
            lines.append(f"- Reason: {menu_action.get('reason', 'Unknown error')}")
            lines.append("Explain briefly what failed and ask for clarification.")

    if followup_hint:
        hint_type = str(followup_hint.get("type", "")).strip()
        lines.append("## Menu Follow-Up")
        if hint_type == "ask_save_menu":
            meal_name = str(followup_hint.get("meal_name", "")).strip()
            if meal_name:
                lines.append(f"The user logged a meal (`{meal_name}`) that is not in menu templates.")
            else:
                lines.append("The user logged a meal that is not in menu templates.")
            lines.append("Ask one short follow-up question: do they want to save it to their menu?")
        elif hint_type == "ask_update_base":
            lines.append("The user logged a template meal with modifications.")
            lines.append("Ask one short follow-up question: should this adjustment update the base menu item or stay one-off?")

    return "\n".join(lines).strip()


def _followup_line_from_hint(followup_hint: dict[str, Any] | None) -> str:
    if not followup_hint:
        return ""
    hint_type = str(followup_hint.get("type", "")).strip()
    if hint_type == "ask_save_menu":
        meal_name = str(followup_hint.get("meal_name", "")).strip()
        if meal_name:
            return f"Do you want me to save `{meal_name}` to your menu for quick future logging?"
        return "Do you want me to save this meal to your menu for quick future logging?"
    if hint_type == "ask_update_base":
        return "Do you want this adjustment to update the base menu item, or keep it as a one-off change today?"
    return ""


def _response_already_has_followup(full_response: str, followup_hint: dict[str, Any] | None) -> bool:
    if not followup_hint:
        return True
    text = _normalize_whitespace(full_response)
    hint_type = str(followup_hint.get("type", "")).strip()
    if hint_type == "ask_save_menu":
        return "save" in text and "menu" in text and "?" in full_response
    if hint_type == "ask_update_base":
        return "update" in text and ("base meal" in text or "one-off" in text) and "?" in full_response
    return False


def _extract_energy_level(message_text: str) -> int | None:
    text = _normalize_whitespace(message_text)
    strong_low = ["exhausted", "very tired", "crashed", "drained", "no energy"]
    mild_low = ["tired", "low energy", "sluggish", "sleepy"]
    mild_high = ["good energy", "energized", "more energy", "felt good"]
    strong_high = ["great energy", "very energized", "excellent energy", "super energetic"]
    if any(k in text for k in strong_low):
        return -2
    if any(k in text for k in mild_low):
        return -1
    if any(k in text for k in strong_high):
        return 2
    if any(k in text for k in mild_high):
        return 1
    return None


def _extract_gi_signals(message_text: str) -> tuple[list[str], int | None]:
    text = _normalize_whitespace(message_text)
    tags: list[str] = []
    for tag, variants in GI_SYMPTOM_KEYWORDS.items():
        if any(v in text for v in variants):
            tags.append(tag)

    severity = None
    if tags:
        if any(w in text for w in ["severe", "very bad", "awful"]):
            severity = 5
        elif any(w in text for w in ["bad", "painful", "significant"]):
            severity = 4
        elif any(w in text for w in ["moderate"]):
            severity = 3
        elif any(w in text for w in ["mild", "slight", "little"]):
            severity = 2
        else:
            severity = 3
    return tags, severity


def _has_meal_context_reference(message_text: str) -> bool:
    text = _normalize_whitespace(message_text)
    return any(keyword in text for keyword in MEAL_CONTEXT_KEYWORDS)


def _resolve_recent_template_for_signal(
    db: Session,
    user: User,
    message_text: str,
) -> tuple[int | None, int | None]:
    # First try direct name resolution from user's phrase.
    try:
        resolved = tool_registry.execute(
            "meal_template_resolve_name",
            {"query": message_text},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        matches = resolved.get("matches", []) if isinstance(resolved, dict) else []
        if matches:
            for top in matches[:3]:
                if not isinstance(top, dict):
                    continue
                score = float(top.get("score", 0) or 0)
                reason = str(top.get("reason", "")).strip().lower()
                if score < 0.8 and reason not in {"exact_name_match", "contains_match"}:
                    continue
                template = top.get("template", {}) if isinstance(top, dict) else {}
                template_id = template.get("id")
                if template_id is None:
                    continue
                latest_log = (
                    db.query(FoodLog)
                    .filter(FoodLog.user_id == user.id, FoodLog.meal_template_id == int(template_id))
                    .order_by(FoodLog.logged_at.desc())
                    .first()
                )
                return int(template_id), (latest_log.id if latest_log else None)
    except Exception:
        pass

    # Fallback only when message has explicit meal context.
    if not _has_meal_context_reference(message_text):
        return None, None

    # Fallback: most recent template-linked food log in the last 12h.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    row = (
        db.query(FoodLog)
        .filter(
            FoodLog.user_id == user.id,
            FoodLog.meal_template_id.isnot(None),
            FoodLog.logged_at >= cutoff,
        )
        .order_by(FoodLog.logged_at.desc())
        .first()
    )
    if row and row.meal_template_id:
        return int(row.meal_template_id), int(row.id)
    return None, None


def _capture_meal_response_signal_if_any(
    db: Session,
    user: User,
    message_text: str,
    source_message_id: int | None = None,
) -> bool:
    energy = _extract_energy_level(message_text)
    gi_tags, gi_severity = _extract_gi_signals(message_text)
    if energy is None and not gi_tags:
        return False

    # Avoid binding generic energy/GI chatter to meals unless meal context is present.
    if not gi_tags and energy is not None and not _has_meal_context_reference(message_text):
        return False

    template_id, food_log_id = _resolve_recent_template_for_signal(db, user, message_text)
    if template_id is None and food_log_id is None:
        return False

    payload: dict[str, Any] = {
        "meal_template_id": template_id,
        "food_log_id": food_log_id,
        "energy_level": energy,
        "gi_symptom_tags": gi_tags,
        "gi_severity": gi_severity,
        "notes": message_text.strip()[:300],
    }
    if source_message_id is not None:
        payload["source_message_id"] = source_message_id

    try:
        tool_registry.execute(
            "meal_response_signal_write",
            payload,
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return True
    except Exception as e:
        logger.warning(f"Meal response signal write failed: {e}")
        return False


async def _log_agent_feedback_if_needed(
    db: Session,
    provider,
    user: User,
    message_text: str,
    specialist_id: str,
    specialist_name: str,
):
    if not _has_feedback_signal(message_text):
        return

    try:
        result = await provider.chat(
            messages=[{"role": "user", "content": message_text}],
            model=provider.get_utility_model(),
            system=FEEDBACK_EXTRACT_PROMPT,
            stream=False,
        )
        track_usage_from_result(
            db=db,
            user_id=user.id,
            result=result,
            model_used=provider.get_utility_model(),
            operation="feedback_extract",
            usage_type="utility",
        )
        text = (result.get("content") or "").strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
        entries = parsed.get("entries", []) if isinstance(parsed, dict) else []
        if not isinstance(entries, list):
            return

        now = datetime.now(timezone.utc)
        for raw in entries[:3]:
            if not isinstance(raw, dict):
                continue
            f_type = str(raw.get("feedback_type", "other")).strip().lower()
            if f_type not in {"bug", "enhancement", "missing", "other"}:
                f_type = "other"
            title = str(raw.get("title", "")).strip()
            if not title:
                continue
            details = str(raw.get("details", "")).strip() or None

            # Skip near-duplicate auto-feedback in a short window.
            cutoff = now - timedelta(minutes=30)
            dup = (
                db.query(FeedbackEntry)
                .filter(
                    FeedbackEntry.source == "agent",
                    FeedbackEntry.specialist_id == specialist_id,
                    FeedbackEntry.feedback_type == f_type,
                    FeedbackEntry.title == title,
                    FeedbackEntry.created_at >= cutoff,
                )
                .first()
            )
            if dup:
                continue

            row = FeedbackEntry(
                feedback_type=f_type,
                title=title,
                details=details,
                source="agent",
                specialist_id=specialist_id,
                specialist_name=specialist_name,
                created_by_user_id=user.id,
            )
            db.add(row)

    except Exception as e:
        logger.warning(f"Agent feedback extraction failed: {e}")


async def _mark_checklist_completed_for_meds(
    db: Session,
    provider,
    user: User,
    combined_input: str,
):
    """Mark today's medication checklist items completed based on message intent."""
    settings = user.settings
    if not settings:
        return

    text = combined_input.lower()
    took_signal = any(
        k in text
        for k in ["took", "taken", "had my", "i did my", "this morning", "this evening", "just took"]
    )
    if not took_signal:
        return

    med_items = parse_structured_list(settings.medications)
    med_names = [item.get("name", "") for item in med_items if item.get("name")]
    if not med_names:
        return

    def _contains_bp_keyword(med_name: str) -> bool:
        m = med_name.lower()
        return any(k in m for k in BP_MED_KEYWORDS)

    mentioned_specific = [m for m in med_names if m.lower() in text]
    targets: list[str] = []

    if mentioned_specific:
        targets = mentioned_specific
    else:
        # First pass: standardized resolver tool (handles "morning meds", "blood pressure meds", etc.)
        try:
            resolved = tool_registry.execute(
                "medication_resolve_reference",
                {"query": combined_input},
                ToolContext(db=db, user=user, specialist_id="orchestrator"),
            )
            for match in resolved.get("matches", []):
                name = str(match.get("name", "")).strip()
                if name and name in med_names and name not in targets:
                    targets.append(name)
        except ToolExecutionError as e:
            logger.warning(f"Medication resolver tool failed: {e}")
        except Exception as e:
            logger.warning(f"Medication resolver tool unexpected failure: {e}")

    if not targets:
        try:
            med_list = "\n".join([f"- {m}" for m in med_names])
            user_payload = (
                f"Message:\n{combined_input}\n\n"
                f"Medication list:\n{med_list}\n"
            )
            result = await provider.chat(
                messages=[{"role": "user", "content": user_payload}],
                model=provider.get_utility_model(),
                system=MED_MATCH_PROMPT,
                stream=False,
            )
            track_usage_from_result(
                db=db,
                user_id=user.id,
                result=result,
                model_used=provider.get_utility_model(),
                operation="medication_match",
                usage_type="utility",
            )
            text_out = (result.get("content") or "").strip()
            if "```" in text_out:
                text_out = text_out.split("```")[1]
                if text_out.startswith("json"):
                    text_out = text_out[4:]
                text_out = text_out.strip()
            parsed = json.loads(text_out)
            matched = parsed.get("matched_medications", []) if isinstance(parsed, dict) else []
            if isinstance(matched, list):
                allowed = {m.lower(): m for m in med_names}
                for raw_name in matched:
                    key = str(raw_name).strip().lower()
                    if key in allowed and allowed[key] not in targets:
                        targets.append(allowed[key])
        except Exception as e:
            logger.warning(f"AI med matching failed, falling back to heuristic: {e}")

    if not targets:
        if "blood pressure" in text or "bp " in f"{text} ":
            targets = [m for m in med_names if _contains_bp_keyword(m)]
        else:
            targets = []

    if not targets:
        return

    try:
        tool_registry.execute(
            "checklist_mark_taken",
            {
                "item_type": "medication",
                "names": targets,
                "target_date": today_utc().isoformat(),
                "completed": True,
            },
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
    except Exception as e:
        logger.warning(f"Checklist medication write tool failed: {e}")


async def _mark_checklist_completed_for_supplements(
    db: Session,
    provider,
    user: User,
    combined_input: str,
):
    """Mark today's supplement checklist items completed based on intake intent."""
    settings = user.settings
    if not settings:
        return

    text = combined_input.lower()
    took_signal = any(
        k in text
        for k in ["took", "taken", "had my", "i did my", "this morning", "this evening", "just took"]
    )
    if not took_signal:
        return

    supp_items = parse_structured_list(settings.supplements)
    supp_names = [item.get("name", "").strip() for item in supp_items if item.get("name")]
    if not supp_names:
        return

    targets: list[str] = []

    # 1) Direct / normalized match (handles entries like "IM8")
    norm_text = _normalize_alnum(combined_input)
    for name in supp_names:
        n = name.lower()
        norm_name = _normalize_alnum(name)
        if n in text or (norm_name and norm_name in norm_text):
            targets.append(name)

    # 2) Standardized resolver tool (handles phrases like "my vitamins", "morning supplements")
    if not targets:
        try:
            resolved = tool_registry.execute(
                "supplement_resolve_reference",
                {"query": combined_input},
                ToolContext(db=db, user=user, specialist_id="orchestrator"),
            )
            for match in resolved.get("matches", []):
                name = str(match.get("name", "")).strip()
                if name and name in supp_names and name not in targets:
                    targets.append(name)
        except ToolExecutionError as e:
            logger.warning(f"Supplement resolver tool failed: {e}")
        except Exception as e:
            logger.warning(f"Supplement resolver tool unexpected failure: {e}")

    # 3) AI semantic mapping fallback
    if not targets:
        try:
            supp_list = "\n".join([f"- {s}" for s in supp_names])
            user_payload = (
                f"Message:\n{combined_input}\n\n"
                f"Supplement list:\n{supp_list}\n"
            )
            result = await provider.chat(
                messages=[{"role": "user", "content": user_payload}],
                model=provider.get_utility_model(),
                system=SUPP_MATCH_PROMPT,
                stream=False,
            )
            track_usage_from_result(
                db=db,
                user_id=user.id,
                result=result,
                model_used=provider.get_utility_model(),
                operation="supplement_match",
                usage_type="utility",
            )
            text_out = (result.get("content") or "").strip()
            if "```" in text_out:
                text_out = text_out.split("```")[1]
                if text_out.startswith("json"):
                    text_out = text_out[4:]
                text_out = text_out.strip()
            parsed = json.loads(text_out)
            matched = parsed.get("matched_supplements", []) if isinstance(parsed, dict) else []
            if isinstance(matched, list):
                allowed = {s.lower(): s for s in supp_names}
                for raw_name in matched:
                    key = str(raw_name).strip().lower()
                    if key in allowed and allowed[key] not in targets:
                        targets.append(allowed[key])
        except Exception as e:
            logger.warning(f"AI supplement matching failed, falling back to heuristics: {e}")

    # 4) Last-resort fallback for explicit group phrases
    if not targets and ("my supplements" in text or "my vitamin" in text or "my vitamins" in text):
        targets = list(supp_names)

    if not targets:
        return

    try:
        tool_registry.execute(
            "checklist_mark_taken",
            {
                "item_type": "supplement",
                "names": targets,
                "target_date": today_utc().isoformat(),
                "completed": True,
            },
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
    except Exception as e:
        logger.warning(f"Checklist supplement write tool failed: {e}")


def _has_question_intent(text: str) -> bool:
    t = text.lower()
    question_markers = [
        "?",
        "how much",
        "should i",
        "tell me about",
        "what is",
        "what are",
        "is this",
        "can i",
    ]
    return any(marker in t for marker in question_markers)


def _has_explicit_taking_intent(text: str) -> bool:
    t = " ".join(text.lower().split())
    taking_markers = [
        "i take",
        "i'm taking",
        "i am taking",
        "i took",
        "took my",
        "had my",
        "i use",
        "i used",
        "my medication",
        "my medications",
        "my supplement",
        "my supplements",
        "i started",
        "i am on",
        "i'm on",
        "prescribed",
        "this morning",
        "this evening",
        "just took",
        "every day",
        "daily",
    ]
    return any(marker in t for marker in taking_markers)


async def _apply_profile_updates(
    db: Session,
    provider,
    user: User,
    message_text: str,
    combined_input: str,
    category: str,
):
    """Auto-sync profile meds/supplements/conditions from message context."""
    settings = user.settings
    if not settings:
        return

    try:
        result = await provider.chat(
            messages=[{"role": "user", "content": f"{PROFILE_EXTRACT_PROMPT}\n\nMessage: {combined_input}"}],
            model=provider.get_utility_model(),
            system="You are a strict data extraction assistant. Return only JSON.",
            stream=False,
        )
        track_usage_from_result(
            db=db,
            user_id=user.id,
            result=result,
            model_used=provider.get_utility_model(),
            operation="profile_extract",
            usage_type="utility",
        )
        text = (result.get("content") or "").strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        extracted = json.loads(text)
        if not isinstance(extracted, dict):
            extracted = {}

        # Convert AI output to structured items (handles both dicts and strings)
        raw_meds = extracted.get("medications", [])
        raw_supps = extracted.get("supplements", [])
        med_items: list[StructuredItem] = [to_structured(x) for x in raw_meds if x]
        supp_items: list[StructuredItem] = [to_structured(x) for x in raw_supps if x]

        conditions = [str(x).strip() for x in extracted.get("medical_conditions", []) if str(x).strip()]
        dietary = [str(x).strip() for x in extracted.get("dietary_preferences", []) if str(x).strip()]
        goals = [str(x).strip() for x in extracted.get("health_goals", []) if str(x).strip()]
        family = [str(x).strip() for x in extracted.get("family_history", []) if str(x).strip()]

        # Drop generic placeholders like "blood pressure meds"
        med_items = [m for m in med_items if not _is_generic_medication_phrase(m.get("name", ""))]

        # Move likely-Rx items from supplements to medications
        moved_to_meds: list[StructuredItem] = []
        remaining_supps: list[StructuredItem] = []
        for s in supp_items:
            if _looks_like_medication(s.get("name", "")):
                moved_to_meds.append(s)
            else:
                remaining_supps.append(s)
        med_items = med_items + moved_to_meds
        supp_items = remaining_supps

        explicit_taking = _has_explicit_taking_intent(message_text)
        question_like = _has_question_intent(message_text)

        # Prevent question-only messages from polluting profile
        if category not in {"log_supplement"}:
            if question_like and not explicit_taking:
                med_items = []
                supp_items = []
            elif not explicit_taking:
                med_items = []
                supp_items = []

        if not med_items and not supp_items and not conditions and not dietary and not goals and not family:
            # Even when extractor returns nothing new, run cleanup on existing data
            cleaned = cleanup_structured_list(settings.supplements)
            if cleaned != settings.supplements:
                settings.supplements = cleaned
            await _mark_checklist_completed_for_meds(db, provider, user, combined_input)
            await _mark_checklist_completed_for_supplements(db, provider, user, combined_input)
            return

        tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator")

        # Standardized structured upserts via tools
        if med_items:
            for med in med_items:
                try:
                    tool_registry.execute("medication_upsert", {"item": med}, tool_ctx)
                except Exception as e:
                    logger.warning(f"Medication upsert tool failed for {med.get('name')}: {e}")

        if supp_items:
            for supp in supp_items:
                try:
                    tool_registry.execute("supplement_upsert", {"item": supp}, tool_ctx)
                except Exception as e:
                    logger.warning(f"Supplement upsert tool failed for {supp.get('name')}: {e}")

        # Standardized list-field patching via tool
        list_patch: dict[str, list[str]] = {}
        if conditions:
            list_patch["medical_conditions"] = _merge_plain_list(settings.medical_conditions, conditions)
        if dietary:
            list_patch["dietary_preferences"] = _merge_plain_list(settings.dietary_preferences, dietary)
        if goals:
            list_patch["health_goals"] = _merge_plain_list(settings.health_goals, goals)
        if family:
            list_patch["family_history"] = _merge_plain_list(settings.family_history, family)
        if list_patch:
            try:
                tool_registry.execute("profile_patch", {"patch": list_patch}, tool_ctx)
            except Exception as e:
                logger.warning(f"Profile patch tool failed: {e}")

        await _mark_checklist_completed_for_meds(db, provider, user, combined_input)
        await _mark_checklist_completed_for_supplements(db, provider, user, combined_input)
    except Exception as e:
        logger.warning(f"Profile auto-sync extraction failed: {e}")
        # Even if profile extraction fails, still try checklist updates from intent text.
        try:
            await _mark_checklist_completed_for_meds(db, provider, user, combined_input)
        except Exception as med_err:
            logger.warning(f"Checklist medication fallback failed: {med_err}")
        try:
            await _mark_checklist_completed_for_supplements(db, provider, user, combined_input)
        except Exception as supp_err:
            logger.warning(f"Checklist supplement fallback failed: {supp_err}")


async def save_structured_log(db: Session, user: User, category: str, data: dict):
    """Save parsed structured data to the appropriate log table."""
    tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator")
    out: dict[str, Any] | None = None
    if category == "log_food" and data:
        out = tool_registry.execute(
            "food_log_write",
            {
                "meal_label": data.get("meal_label"),
                "items": data.get("items", []),
                "calories": data.get("calories"),
                "protein_g": data.get("protein_g"),
                "carbs_g": data.get("carbs_g"),
                "fat_g": data.get("fat_g"),
                "fiber_g": data.get("fiber_g"),
                "sodium_mg": data.get("sodium_mg"),
                "notes": data.get("notes"),
                "servings": data.get("servings"),
                "use_template_if_found": True,
            },
            tool_ctx,
        )

    elif category == "log_vitals" and data:
        out = tool_registry.execute(
            "vitals_log_write",
            {
                "weight_kg": data.get("weight_kg"),
                "bp_systolic": data.get("bp_systolic"),
                "bp_diastolic": data.get("bp_diastolic"),
                "heart_rate": data.get("heart_rate"),
                "blood_glucose": data.get("blood_glucose"),
                "temperature_c": data.get("temperature_c"),
                "spo2": data.get("spo2"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_exercise" and data:
        out = tool_registry.execute(
            "exercise_log_write",
            {
                "exercise_type": data.get("exercise_type", "other"),
                "duration_minutes": data.get("duration_minutes"),
                "details": data.get("details"),
                "max_hr": data.get("max_hr"),
                "avg_hr": data.get("avg_hr"),
                "calories_burned": data.get("calories_burned"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_supplement" and data:
        out = tool_registry.execute(
            "supplement_log_write",
            {
                "supplements": data.get("supplements", []),
                "timing": data.get("timing"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_fasting" and data:
        out = tool_registry.execute(
            "fasting_manage",
            {
                "action": data.get("action", "start"),
                "fast_type": data.get("fast_type"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_sleep" and data:
        out = tool_registry.execute(
            "sleep_log_write",
            {
                "duration_minutes": data.get("duration_minutes"),
                "quality": data.get("quality"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_hydration" and data:
        out = tool_registry.execute(
            "hydration_log_write",
            {
                "amount_ml": data.get("amount_ml", 250),
                "source": data.get("source", "water"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    db.commit()
    return out


async def process_chat(
    db: Session,
    user: User,
    message: str,
    image_bytes: bytes | None = None,
) -> AsyncGenerator[dict, None]:
    """Main chat orchestration. Yields streaming response chunks."""
    settings = user.settings
    if not settings or not settings.api_key_encrypted:
        yield {"type": "error", "text": "Please configure your API key in Settings before chatting."}
        return

    api_key = decrypt_api_key(settings.api_key_encrypted)
    provider = get_provider(
        settings.ai_provider,
        api_key,
        reasoning_model=settings.reasoning_model,
        utility_model=settings.utility_model,
    )

    # 1. If image attached, analyze it first
    image_context = ""
    if image_bytes:
        analysis = await analyze_image(provider, image_bytes)
        if analysis["success"]:
            image_context = f"\n[Image analysis: {analysis['content']}]"

    combined_input = message + image_context

    # 2. Classify intent
    overrides = parse_overrides(user.specialist_config)
    enabled_specialists = get_enabled_specialist_ids(overrides)
    specialist_override = None
    if user.specialist_config and user.specialist_config.active_specialist != "auto":
        specialist_override = user.specialist_config.active_specialist

    intent = await classify_intent(
        provider,
        combined_input,
        specialist_override,
        allowed_specialists=enabled_specialists,
        db=db,
        user_id=user.id,
    )
    category = intent["category"]
    specialist = intent["specialist"]
    specialist_name = _resolve_specialist_name(overrides, specialist)

    # 2b. Auto-log global feedback from user bug/enhancement messages under specialist.
    await _log_agent_feedback_if_needed(
        db=db,
        provider=provider,
        user=user,
        message_text=message,
        specialist_id=specialist,
        specialist_name=specialist_name,
    )
    db.commit()

    # 2c. Always attempt intake checklist marking from intent text.
    # This keeps dashboard meds/supplement checkboxes in sync even if
    # category extraction/profile extraction misses on a turn.
    try:
        await _mark_checklist_completed_for_meds(db, provider, user, combined_input)
        await _mark_checklist_completed_for_supplements(db, provider, user, combined_input)
        db.commit()
    except Exception as e:
        logger.warning(f"Checklist sync from chat failed: {e}")

    has_menu_save_intent = _has_menu_save_intent(db, user, message)
    has_menu_update_intent = _has_menu_update_intent(db, user, message)
    menu_command_only = (has_menu_save_intent or has_menu_update_intent) and not _looks_like_food_logging_message(message)
    menu_action_result: dict[str, Any] | None = None
    if menu_command_only:
        menu_action_result = _try_handle_menu_template_action(
            db=db,
            user=user,
            message_text=message,
            source_food_log=_latest_food_log(db, user, lookback_hours=72),
        )

    # 3. Parse and save structured data if it's a logging intent
    parsed_log_data: dict[str, Any] | None = None
    saved_log_out: dict[str, Any] | None = None
    if category.startswith("log_") and not menu_command_only:
        user_profile = ""
        if settings.current_weight_kg:
            if settings.weight_unit == "lb":
                user_profile = f"Weight: {kg_to_lb(settings.current_weight_kg):.1f}lb"
            else:
                user_profile = f"Weight: {settings.current_weight_kg}kg"
        parsed_log_data = await parse_log_data(
            provider,
            combined_input,
            category,
            user_profile=user_profile,
            db=db,
            user_id=user.id,
        )
        if parsed_log_data:
            try:
                saved_log_out = await save_structured_log(db, user, category, parsed_log_data)
            except ToolExecutionError as e:
                logger.warning(f"Structured log tool write failed ({category}): {e}")
            except Exception as e:
                logger.warning(f"Structured log save failed ({category}): {e}")

    # 3a. Chat-driven menu actions (save/update meal templates).
    # Prefer the current turn's food log when available to avoid stale meal capture.
    if menu_action_result is None:
        source_food_log = _food_log_from_saved_output(db, user, saved_log_out)
        menu_action_result = _try_handle_menu_template_action(
            db=db,
            user=user,
            message_text=message,
            source_food_log=source_food_log,
        )

    menu_followup_hint = _build_menu_followup_hint(
        db=db,
        user=user,
        category=category,
        message_text=message,
        parsed_log=parsed_log_data,
        saved_out=saved_log_out,
        menu_action_result=menu_action_result,
    )

    # 3b. Auto-sync profile fields from user message/image context
    # Run for supplement/medical/general chats and any image-assisted message.
    if image_bytes or category in {
        "log_supplement",
        "ask_supplement",
        "ask_medical",
        "ask_nutrition",
        "general_chat",
        "manual_override",
    }:
        await _apply_profile_updates(
            db=db,
            provider=provider,
            user=user,
            message_text=message,
            combined_input=combined_input,
            category=category,
        )
        db.commit()

    # 3c. Optional live web search for supported specialists/questions.
    web_results: list[dict] = []
    if _should_use_web_search(message, category, specialist):
        try:
            search_out = tool_registry.execute(
                "web_search",
                {
                    "query": message,
                    "max_results": settings.WEB_SEARCH_MAX_RESULTS,
                },
                ToolContext(db=db, user=user, specialist_id=specialist),
            )
            web_results = search_out.get("results", []) if isinstance(search_out, dict) else []
        except Exception as e:
            logger.warning(f"web_search tool failed: {e}")

    # 3d. Provide authoritative current time/date context when asked.
    time_context = ""
    if _should_include_time_context(message):
        try:
            time_out = tool_registry.execute(
                "time_now",
                {},
                ToolContext(db=db, user=user, specialist_id=specialist),
            )
            time_context = _format_time_context(time_out)
        except Exception as e:
            logger.warning(f"time_now tool failed: {e}")

    menu_context = _format_menu_context(menu_action_result, menu_followup_hint)

    # 4. Build context
    system_context = build_context(db, user, specialist)
    if web_results:
        system_context = f"{system_context}\n\n{_format_web_search_context(web_results)}"
    if time_context:
        system_context = f"{system_context}\n\n{time_context}"
    if menu_context:
        system_context = f"{system_context}\n\n{menu_context}"

    # 5. Get recent messages for conversation history
    recent = get_recent_messages(db, user, limit=20)
    messages = recent + [{"role": "user", "content": combined_input}]

    # 6. Save user message
    user_msg = Message(
        user_id=user.id,
        role="user",
        content=message,
        has_image=bool(image_bytes),
    )
    db.add(user_msg)
    db.commit()

    # 6b. Capture meal response signal from chat if present (energy/GI patterns).
    try:
        _capture_meal_response_signal_if_any(
            db=db,
            user=user,
            message_text=message,
            source_message_id=user_msg.id,
        )
    except Exception as e:
        logger.warning(f"Meal response capture failed: {e}")

    # 7. Generate response with reasoning model (streaming)
    full_response = ""
    tokens_in = 0
    tokens_out = 0

    try:
        stream = await provider.chat(
            messages=messages,
            model=provider.get_reasoning_model(),
            system=system_context,
            stream=True,
        )
        # Defensive guard: some provider implementations may return a coroutine
        # that resolves to an async iterator for streaming.
        if inspect.iscoroutine(stream):
            stream = await stream
        if not hasattr(stream, "__aiter__"):
            raise TypeError(f"Expected async iterator, got {type(stream).__name__}")

        async for chunk in stream:
            if chunk.get("type") == "chunk":
                text = chunk.get("text", "")
                full_response += text
                yield {"type": "chunk", "text": text}
            elif chunk.get("type") == "done":
                tokens_in = chunk.get("tokens_in", 0)
                tokens_out = chunk.get("tokens_out", 0)

        followup_line = _followup_line_from_hint(menu_followup_hint)
        if followup_line and not _response_already_has_followup(full_response, menu_followup_hint):
            append_text = f"\n\n{followup_line}" if full_response else followup_line
            full_response += append_text
            yield {"type": "chunk", "text": append_text}

        yield {"type": "done", "specialist": specialist, "category": category}

    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        error_msg = f"I encountered an error: {str(e)}. Please try again."
        full_response = error_msg
        yield {"type": "error", "text": error_msg}

    # 8. Save assistant message
    assistant_msg = Message(
        user_id=user.id,
        role="assistant",
        content=full_response,
        specialist_used=specialist,
        model_used=provider.get_reasoning_model(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(assistant_msg)
    db.commit()
