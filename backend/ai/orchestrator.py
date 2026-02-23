import json
import logging
import inspect
import re
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncGenerator

from sqlalchemy.orm import Session

from config import settings
from ai.context_builder import build_context, get_recent_messages
from ai.specialist_router import classify_intent
from ai.log_parser import parse_log_data
from ai.image_analyzer import analyze_image
from ai.providers import get_provider
from ai.usage_tracker import track_model_usage, track_usage_from_result
from db.database import SessionLocal
from db.models import (
    User,
    Message,
    FeedbackEntry,
    FoodLog,
    MealTemplate,
    VitalsLog,
    ExerciseLog,
    HydrationLog,
    SupplementLog,
    FastingLog,
    SleepLog,
    Notification,
    UserGoal,
)
from services.analysis_service import run_due_analyses_for_user_id
from services.coaching_plan_service import get_plan_snapshot
from services.specialists_config import get_enabled_specialist_ids, get_effective_specialists, parse_overrides
from services.telemetry_context import (
    clear_ai_turn_scope,
    consume_ai_turn_scope,
    get_ai_turn_scope,
    mark_ai_first_token,
    record_ai_failure,
    start_ai_turn_scope,
    update_ai_turn_scope,
)
from services.telemetry_service import persist_ai_turn_event
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError
from utils.encryption import decrypt_api_key
from utils.time_inference import infer_event_datetime, infer_target_date_iso
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
CHAT_VERBOSITY_MODES = {"normal", "summarized", "straight"}
TIME_CONFIRMATION_KIND = "time_confirmation"
TIME_CONFIRM_ACK_TERMS = {
    "yes",
    "y",
    "yep",
    "yeah",
    "correct",
    "confirmed",
    "thats right",
    "that's right",
    "right",
    "sounds right",
    "looks right",
}
TIME_CONFIRM_REJECT_TERMS = {
    "no",
    "nope",
    "wrong",
    "incorrect",
    "not right",
    "thats wrong",
    "that's wrong",
}
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
LOW_SIGNAL_CHECKIN_PHRASES = {
    "hi",
    "hello",
    "hey",
    "morning",
    "good morning",
    "good afternoon",
    "good evening",
    "hello coach",
    "hi coach",
    "hey coach",
    "check in",
    "checking in",
    "what now",
    "whats next",
    "what's next",
    "start",
    "start today",
}
_ANALYSIS_DISPATCH_LOCK: asyncio.Lock = asyncio.Lock()
_ANALYSIS_LAST_DISPATCH_TS: dict[int, float] = {}
_ANALYSIS_INFLIGHT_USERS: set[int] = set()


class UtilityCallBudget:
    def __init__(self, category: str):
        is_log = str(category or "").startswith("log_")
        self.limit = (
            max(int(settings.UTILITY_CALL_BUDGET_LOG_TURN), 1)
            if is_log
            else max(int(settings.UTILITY_CALL_BUDGET_NONLOG_TURN), 1)
        )

    def can_call(self, operation: str) -> bool:
        scope = get_ai_turn_scope()
        used = int(getattr(scope, "utility_calls", 0) if scope else 0)
        if used < self.limit:
            return True
        logger.info(
            "Utility call budget exceeded; skipping operation=%s used=%s limit=%s",
            operation,
            used,
            self.limit,
        )
        return False
SLEEP_START_CUES = (
    "heading to bed",
    "going to bed",
    "go to bed",
    "bed now",
    "sleep now",
    "going to sleep",
    "good night",
)
SLEEP_END_CUES = (
    "woke up",
    "wake up",
    "waking up",
    "awake now",
    "got up",
    "morning",
)
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

SUPPLEMENT_INTAKE_PHRASES = {
    "supplement",
    "supplements",
    "vitamin",
    "vitamins",
    "multivitamin",
    "stack",
    "fat burner",
    "omega",
    "coq10",
    "creatine",
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
  "matched_medications": ["exact names from provided medication list that user says they took"],
  "matched_supplements": ["exact names from provided supplement list that user says they took"],
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
- matched_medications and matched_supplements must only include names that exactly match provided current lists.
"""

GOAL_SYNC_EXTRACT_PROMPT = """Extract goal create/update actions from a coaching chat turn.

Return ONLY valid JSON:
{
  "action": "none|create|update|create_or_update",
  "create_goals": [
    {
      "title": "string",
      "description": "string",
      "goal_type": "weight_loss|cardiovascular|fitness|metabolic|energy|sleep|habit|custom",
      "target_value": 0,
      "target_unit": "string",
      "baseline_value": 0,
      "target_date": "YYYY-MM-DD",
      "priority": 1,
      "why": "string"
    }
  ],
  "update_goals": [
    {
      "goal_id": 0,
      "title_match": "existing goal title fragment",
      "title": "optional new title",
      "description": "optional",
      "goal_type": "optional",
      "target_value": 0,
      "target_unit": "optional",
      "baseline_value": 0,
      "current_value": 0,
      "target_date": "YYYY-MM-DD",
      "priority": 1,
      "status": "active|paused|completed|abandoned",
      "why": "optional"
    }
  ]
}

Rules:
- If the message is only kickoff/planning text (e.g., starts with "Goal-setting kickoff:"), return action "none".
- Only create/update when the user explicitly confirms goals or asks to change/refine goals.
- Never invent goals not grounded in the user message.
- Keep create_goals/update_goals empty when unsure.
"""

from utils.med_utils import (
    StructuredItem,
    to_structured,
    parse_structured_list,
    cleanup_structured_list,
    looks_like_medication as _looks_like_medication,
    is_generic_medication_name,
    is_generic_supplement_name,
)


def _is_generic_medication_phrase(item: str) -> bool:
    return is_generic_medication_name(item)


def _is_generic_supplement_phrase(item: str) -> bool:
    return is_generic_supplement_name(item)


def _normalize_alnum(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _looks_like_medication_intake(text: str, med_names: list[str]) -> bool:
    normalized_text = " ".join(text.lower().split())
    alnum_text = _normalize_alnum(text)
    if any(name.lower() in normalized_text or _normalize_alnum(name) in alnum_text for name in med_names):
        return True
    return any(
        phrase in normalized_text
        for phrase in (
            "medication",
            "medications",
            "med",
            "meds",
            "blood pressure",
            "bp meds",
            "bp medications",
        )
    )


def _looks_like_supplement_intake(text: str, supp_names: list[str]) -> bool:
    normalized_text = " ".join(text.lower().split())
    alnum_text = _normalize_alnum(text)
    if any(name.lower() in normalized_text or _normalize_alnum(name) in alnum_text for name in supp_names):
        return True
    return any(phrase in normalized_text for phrase in SUPPLEMENT_INTAKE_PHRASES)


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


def _execute_web_search_in_worker(
    user_id: int,
    specialist_id: str,
    query: str,
    max_results: int,
) -> dict[str, Any]:
    worker_db = SessionLocal()
    try:
        worker_user = worker_db.get(User, user_id)
        if not worker_user:
            raise RuntimeError("User not found for web search execution")
        out = tool_registry.execute(
            "web_search",
            {
                "query": query,
                "max_results": max_results,
            },
            ToolContext(db=worker_db, user=worker_user, specialist_id=specialist_id),
        )
        worker_db.commit()
        return out if isinstance(out, dict) else {}
    finally:
        worker_db.close()


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


def _is_low_signal_checkin(message_text: str) -> bool:
    normalized = " ".join(str(message_text or "").strip().lower().split())
    if not normalized:
        return False
    compact = re.sub(r"[^\w\s']", "", normalized).strip()
    if len(compact) > 48:
        return False
    return compact in LOW_SIGNAL_CHECKIN_PHRASES


def _safe_daily_plan_snapshot(db: Session, user: User) -> dict[str, Any] | None:
    try:
        return get_plan_snapshot(db, user, cycle_type="daily")
    except Exception as e:
        logger.warning(f"Unable to load daily plan snapshot for proactive check-in: {e}")
        return None


def _format_target_label(task: dict[str, Any]) -> str:
    value = task.get("target_value")
    unit = str(task.get("target_unit") or "").strip()
    if value is None:
        return ""
    try:
        numeric = float(value)
        if numeric.is_integer():
            value_txt = str(int(numeric))
        else:
            value_txt = f"{numeric:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        value_txt = str(value).strip()
    if not value_txt:
        return ""
    return f"{value_txt}{(' ' + unit) if unit else ''}"


def _first_action_prompt_from_task(task: dict[str, Any] | None) -> str:
    if not task:
        return "tell me the first thing you've had to eat or drink today, and I'll log it now."
    metric = str(task.get("target_metric") or "").strip().lower()
    if metric == "meals_logged":
        return "log your next meal now (what you had + amount), and I'll record it immediately."
    if metric == "hydration_ml":
        return "log one water entry now (for example 250 ml / 8 oz), and I'll update hydration progress."
    if metric == "exercise_minutes":
        return "confirm today's workout type and minutes now so we lock in today's movement target."
    if metric == "sleep_minutes":
        return "share last night's sleep start/end (or total hours) now, and I'll update sleep progress."
    if metric == "medication_adherence":
        return "confirm whether you took your scheduled medications, and I'll mark the checklist now."
    if metric == "supplement_adherence":
        return "confirm whether you took your scheduled supplements, and I'll mark the checklist now."
    return "confirm one task you can complete in the next 10 minutes, and I'll mark progress with you."


def _compose_proactive_checkin_reply(snapshot: dict[str, Any] | None, user: User) -> str:
    tasks = ((snapshot or {}).get("upcoming_tasks") or [])[:3]
    stats = (snapshot or {}).get("stats") or {}
    prefs = (snapshot or {}).get("preferences") or {}
    why = str(prefs.get("coaching_why") or "").strip()

    lines = ["Great check-in. We are in execution mode."]

    if tasks:
        lines.append("Today's top priorities:")
        for idx, task in enumerate(tasks, start=1):
            title = str(task.get("title") or f"Task {idx}").strip()
            target = _format_target_label(task)
            if target:
                lines.append(f"{idx}. {title} (target: {target})")
            else:
                lines.append(f"{idx}. {title}")
    else:
        lines.append("No pending tasks are visible right now, so we'll start with one high-impact log and rebuild momentum.")

    try:
        completed = int(stats.get("completed") or 0)
        total = int(stats.get("total") or 0)
        if total > 0:
            lines.append(f"Progress today: {completed}/{total} tasks completed.")
    except (TypeError, ValueError):
        pass

    if why:
        lines.append(f"Why this matters: {why}")

    lines.append(f"Let's start now: {_first_action_prompt_from_task(tasks[0] if tasks else None)}")
    return "\n".join(lines)


def _extract_json_payload(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def _known_name_matches(candidates: list[str] | None, allowed_names: list[str]) -> list[str]:
    if not candidates:
        return []
    allow_map = {str(name).strip().lower(): str(name).strip() for name in allowed_names if str(name).strip()}
    out: list[str] = []
    for raw in candidates:
        key = str(raw).strip().lower()
        resolved = allow_map.get(key)
        if resolved and resolved not in out:
            out.append(resolved)
    return out


async def _dispatch_due_analysis_if_allowed(user_id: int) -> None:
    if not settings.ENABLE_LONGITUDINAL_ANALYSIS or not settings.ANALYSIS_AUTORUN_ON_CHAT:
        return
    now_mono = time.monotonic()
    debounce_s = max(int(settings.ANALYSIS_AUTORUN_DEBOUNCE_SECONDS), 5)
    should_dispatch = False

    async with _ANALYSIS_DISPATCH_LOCK:
        last = _ANALYSIS_LAST_DISPATCH_TS.get(user_id, 0.0)
        if user_id in _ANALYSIS_INFLIGHT_USERS:
            return
        if (now_mono - last) < debounce_s:
            return
        _ANALYSIS_LAST_DISPATCH_TS[user_id] = now_mono
        _ANALYSIS_INFLIGHT_USERS.add(user_id)
        should_dispatch = True

    if not should_dispatch:
        return

    async def _runner() -> None:
        try:
            await run_due_analyses_for_user_id(user_id, trigger="chat")
        except Exception as e:
            logger.warning(f"Due longitudinal analysis dispatch failed: {e}")
        finally:
            async with _ANALYSIS_DISPATCH_LOCK:
                _ANALYSIS_INFLIGHT_USERS.discard(user_id)

    asyncio.create_task(_runner())


def _normalize_chat_verbosity(value: str | None) -> str:
    if not value:
        return "normal"
    norm = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "summary": "summarized",
        "summarize": "summarized",
        "straight_to_the_point": "straight",
        "to_the_point": "straight",
        "direct": "straight",
    }
    norm = aliases.get(norm, norm)
    if norm not in CHAT_VERBOSITY_MODES:
        return "normal"
    return norm


def _verbosity_style_context(mode: str) -> str:
    if mode == "summarized":
        return (
            "## Response Style Override\n"
            "Use summarized mode for this reply.\n"
            "- Be concise and easy to scan.\n"
            "- Prefer short bullets or very short sections.\n"
            "- Keep only the most relevant context and actions.\n"
            "- Avoid motivational filler or long explanations.\n"
            "- If this is a logging response, still include totals/macros when applicable.\n"
            "- End with one concrete next step."
        )
    if mode == "straight":
        return (
            "## Response Style Override\n"
            "Use straight-to-the-point mode for this reply.\n"
            "- Be direct, minimal, and actionable.\n"
            "- Default to 2-4 short lines.\n"
            "- No long preambles, no motivational filler, no emoji.\n"
            "- Avoid numbered lists unless the user explicitly asks for a list.\n"
            "- Keep explanation to essentials unless safety requires more detail.\n"
            "- If this is a logging response, still include totals/macros when applicable.\n"
            "- End with one concrete next step."
        )
    return ""


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_clock_time_token(text: str) -> str | None:
    match = re.search(
        r"\b((?:\d{1,2}:\d{2}\s?(?:am|pm)?)|(?:\d{1,2}\s?(?:am|pm)))\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip()


def _normalize_sleep_payload(message_text: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload

    text = _normalize_whitespace(message_text)
    action = str(payload.get("action", "")).strip().lower()
    if action not in {"start", "end", "auto"}:
        has_start_cue = any(cue in text for cue in SLEEP_START_CUES)
        has_end_cue = any(cue in text for cue in SLEEP_END_CUES)
        if has_end_cue and not has_start_cue:
            action = "end"
        elif has_start_cue and not has_end_cue:
            action = "start"
        else:
            action = "auto"
    payload["action"] = action

    time_token = _extract_clock_time_token(text)
    if action == "start" and not payload.get("sleep_start") and time_token:
        payload["sleep_start"] = time_token
    elif action == "end" and not payload.get("sleep_end") and time_token:
        payload["sleep_end"] = time_token

    return payload


def _apply_inferred_event_time(
    category: str,
    message_text: str,
    payload: dict[str, Any] | None,
    reference_utc: datetime | None,
    timezone_name: str | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload

    inference = infer_event_datetime(message_text, reference_utc, timezone_name)
    inferred = inference.event_utc.isoformat()

    def _attach_confidence_metadata() -> None:
        payload["_inferred_time_confidence"] = inference.confidence
        payload["_inferred_time_reason"] = inference.reason

    if category in {"log_food", "log_vitals", "log_exercise", "log_hydration", "log_supplement"}:
        if not payload.get("logged_at") and not payload.get("event_time"):
            payload["logged_at"] = inferred
            _attach_confidence_metadata()
        return payload

    if category == "log_fasting":
        action = str(payload.get("action", "")).strip().lower()
        if action == "start" and not payload.get("fast_start"):
            payload["fast_start"] = inferred
            _attach_confidence_metadata()
        elif action == "end" and not payload.get("fast_end"):
            payload["fast_end"] = inferred
            _attach_confidence_metadata()
        return payload

    if category == "log_sleep":
        action = str(payload.get("action", "")).strip().lower()
        if action == "start" and not payload.get("sleep_start"):
            payload["sleep_start"] = inferred
            _attach_confidence_metadata()
        elif action == "end" and not payload.get("sleep_end"):
            payload["sleep_end"] = inferred
            _attach_confidence_metadata()
        return payload

    return payload


def _build_time_inference_context(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    confidence = str(payload.get("_inferred_time_confidence", "")).strip().lower()
    if confidence != "low":
        return ""
    reason = str(payload.get("_inferred_time_reason", "")).strip() or "unknown"
    return (
        "## Time Confirmation\n"
        "Event time was inferred with low confidence.\n"
        f"- Inference reason: {reason}\n"
        "- In your reply, include one short confirmation question about the logged time/date.\n"
        "- Keep the log as recorded unless the user corrects it."
    )


def _parse_notification_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_confirmation_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9:\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_confirmation_ack(message_text: str) -> bool:
    cleaned = _clean_confirmation_text(message_text)
    if not cleaned:
        return False
    if cleaned in TIME_CONFIRM_ACK_TERMS:
        return True
    return any(cleaned.startswith(f"{term} ") for term in TIME_CONFIRM_ACK_TERMS)


def _is_confirmation_reject(message_text: str) -> bool:
    cleaned = _clean_confirmation_text(message_text)
    if not cleaned:
        return False
    if cleaned in TIME_CONFIRM_REJECT_TERMS:
        return True
    return any(cleaned.startswith(f"{term} ") for term in TIME_CONFIRM_REJECT_TERMS)


def _has_explicit_date_token(message_text: str) -> bool:
    return bool(
        re.search(r"\b\d{4}-\d{2}-\d{2}\b", message_text)
        or re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", message_text)
        or re.search(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b",
            message_text,
            flags=re.IGNORECASE,
        )
    )


def _should_consume_time_confirmation_message(message_text: str) -> bool:
    normalized = _normalize_whitespace(message_text)
    if not normalized:
        return False
    if " and " in normalized or "," in normalized or ";" in normalized:
        return False
    return len(normalized.split()) <= 12


def _resolve_time_confirmation_target(
    category: str,
    payload: dict[str, Any] | None,
    saved_out: dict[str, Any] | None,
) -> tuple[int, str, str] | None:
    if not isinstance(payload, dict) or not isinstance(saved_out, dict):
        return None

    base = {
        "log_food": ("food_log_id", "logged_at"),
        "log_vitals": ("vitals_log_id", "logged_at"),
        "log_exercise": ("exercise_log_id", "logged_at"),
        "log_hydration": ("hydration_log_id", "logged_at"),
        "log_supplement": ("supplement_log_id", "logged_at"),
    }

    if category in base:
        id_key, field = base[category]
    elif category == "log_fasting":
        action = str(payload.get("action", "")).strip().lower()
        id_key = "fasting_log_id"
        field = "fast_end" if action == "end" else "fast_start"
    elif category == "log_sleep":
        action = str(payload.get("action", "")).strip().lower()
        id_key = "sleep_log_id"
        field = "sleep_end" if action == "end" else "sleep_start"
    else:
        return None

    try:
        row_id = int(saved_out.get(id_key))
    except (TypeError, ValueError):
        return None

    recorded_time = payload.get(field) or payload.get("logged_at") or payload.get("event_time")
    recorded_iso = str(recorded_time or "").strip()
    if not recorded_iso:
        return None
    return row_id, field, recorded_iso


def _persist_low_confidence_time_confirmation(
    db: Session,
    user: User,
    category: str,
    parsed_payload: dict[str, Any] | None,
    saved_out: dict[str, Any] | None,
) -> Notification | None:
    if not isinstance(parsed_payload, dict):
        return None
    if str(parsed_payload.get("_inferred_time_confidence", "")).strip().lower() != "low":
        return None

    target = _resolve_time_confirmation_target(category, parsed_payload, saved_out)
    if not target:
        return None
    row_id, field, recorded_iso = target
    reason = str(parsed_payload.get("_inferred_time_reason", "")).strip() or "unknown"

    existing_rows = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.category == "system",
            Notification.is_read.is_(False),
        )
        .order_by(Notification.created_at.desc())
        .limit(25)
        .all()
    )
    for row in existing_rows:
        payload = _parse_notification_payload(row.payload)
        try:
            payload_record_id = int(payload.get("record_id", -1))
        except (TypeError, ValueError):
            payload_record_id = -1
        if (
            payload.get("kind") == TIME_CONFIRMATION_KIND
            and str(payload.get("category")) == category
            and payload_record_id == row_id
            and str(payload.get("field")) == field
        ):
            payload.update(
                {
                    "status": "pending",
                    "inferred_iso": recorded_iso,
                    "reason": reason,
                    "confidence": "low",
                }
            )
            row.payload = json.dumps(payload, ensure_ascii=True)
            row.title = "Confirm logged time"
            row.message = "I inferred this event time with low confidence. Please confirm or provide a corrected time."
            return row

    payload = {
        "kind": TIME_CONFIRMATION_KIND,
        "status": "pending",
        "category": category,
        "record_id": row_id,
        "field": field,
        "inferred_iso": recorded_iso,
        "reason": reason,
        "confidence": "low",
    }
    notification = Notification(
        user_id=user.id,
        category="system",
        title="Confirm logged time",
        message="I inferred this event time with low confidence. Please confirm or provide a corrected time.",
        payload=json.dumps(payload, ensure_ascii=True),
        is_read=False,
    )
    db.add(notification)
    return notification


def _latest_pending_time_confirmation(db: Session, user: User) -> tuple[Notification | None, dict[str, Any] | None]:
    rows = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.category == "system",
            Notification.is_read.is_(False),
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    for row in rows:
        payload = _parse_notification_payload(row.payload)
        if payload.get("kind") == TIME_CONFIRMATION_KIND and str(payload.get("status", "pending")) == "pending":
            return row, payload
    return None, None


def _apply_time_correction_to_row(
    db: Session,
    user: User,
    payload: dict[str, Any],
    corrected_utc: datetime,
) -> bool:
    category = str(payload.get("category", "")).strip().lower()
    field = str(payload.get("field", "")).strip()
    try:
        row_id = int(payload.get("record_id"))
    except (TypeError, ValueError):
        return False

    model_map: dict[str, type] = {
        "log_food": FoodLog,
        "log_vitals": VitalsLog,
        "log_exercise": ExerciseLog,
        "log_hydration": HydrationLog,
        "log_supplement": SupplementLog,
        "log_fasting": FastingLog,
        "log_sleep": SleepLog,
    }
    model = model_map.get(category)
    if model is None:
        return False

    row = db.get(model, row_id)
    if row is None or int(getattr(row, "user_id", -1)) != int(user.id):
        return False
    if not hasattr(row, field):
        return False

    setattr(row, field, corrected_utc)

    if isinstance(row, SleepLog) and row.sleep_start and row.sleep_end:
        minutes = int((row.sleep_end - row.sleep_start).total_seconds() // 60)
        row.duration_minutes = max(0, minutes)
    if isinstance(row, FastingLog) and row.fast_start and row.fast_end:
        minutes = int((row.fast_end - row.fast_start).total_seconds() // 60)
        row.duration_minutes = max(0, minutes)
    return True


def _build_pending_time_confirmation_context(payload: dict[str, Any]) -> str:
    category = str(payload.get("category", "event")).replace("log_", "").replace("_", " ")
    field = str(payload.get("field", "time")).replace("_", " ")
    inferred_iso = str(payload.get("inferred_iso", "")).strip() or "unknown"
    reason = str(payload.get("reason", "")).strip() or "unknown"
    return (
        "## Pending Time Confirmation\n"
        "There is an unresolved low-confidence event time.\n"
        f"- Event type: {category}\n"
        f"- Field: {field}\n"
        f"- Currently recorded: {inferred_iso}\n"
        f"- Inference reason: {reason}\n"
        "- Ask the user to confirm this time or provide a corrected date/time in this reply.\n"
        "- Do not describe this timestamp as final until confirmed."
    )


def _handle_pending_time_confirmation(
    db: Session,
    user: User,
    message_text: str,
    reference_utc: datetime,
    timezone_name: str | None,
) -> dict[str, Any]:
    note, payload = _latest_pending_time_confirmation(db, user)
    if note is None or payload is None:
        return {"context": "", "skip_log_parse": False}

    if _is_confirmation_ack(message_text):
        payload["status"] = "confirmed"
        payload["confirmed_at"] = reference_utc.isoformat()
        note.payload = json.dumps(payload, ensure_ascii=True)
        note.is_read = True
        note.read_at = reference_utc
        db.commit()
        return {
            "context": "## Time Confirmation\nThe user has confirmed a previously inferred event time. Acknowledge confirmation briefly.",
            "skip_log_parse": _should_consume_time_confirmation_message(message_text),
        }

    if _extract_clock_time_token(message_text) or _has_explicit_date_token(message_text):
        corrected = infer_event_datetime(message_text, reference_utc, timezone_name)
        if _apply_time_correction_to_row(db, user, payload, corrected.event_utc):
            payload["status"] = "corrected"
            payload["corrected_iso"] = corrected.event_utc.isoformat()
            payload["corrected_at"] = reference_utc.isoformat()
            note.payload = json.dumps(payload, ensure_ascii=True)
            note.is_read = True
            note.read_at = reference_utc
            db.commit()
            return {
                "context": (
                    "## Time Correction Applied\n"
                    f"User corrected the prior event time. Updated value: {corrected.event_utc.isoformat()}.\n"
                    "Acknowledge the correction and continue."
                ),
                "skip_log_parse": _should_consume_time_confirmation_message(message_text),
            }

    if _is_confirmation_reject(message_text):
        return {
            "context": (
                "## Pending Time Confirmation\n"
                "User rejected a previously inferred event time.\n"
                "- Ask for the exact date/time now.\n"
                "- Keep the current value as provisional until corrected."
            ),
            "skip_log_parse": False,
        }

    return {
        "context": _build_pending_time_confirmation_context(payload),
        "skip_log_parse": False,
    }


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
    if (
        "save this meal to your menu" in text
        or "save this to your menu" in text
        or "add this to your menu" in text
    ):
        return True
    # Also accept named variants like:
    # "Do you want me to save Lunch to your menu for quick future logging?"
    return bool(
        re.search(r"\b(?:save|add)\b.{0,80}\bto your menu\b", text, flags=re.IGNORECASE)
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


def _build_log_write_context(
    category: str,
    parsed_log: dict[str, Any] | None,
    saved_out: dict[str, Any] | None,
    write_error: str | None,
) -> str:
    if not category.startswith("log_"):
        return ""
    if isinstance(saved_out, dict):
        return (
            "## Write Status\n"
            "- Structured log write: success\n"
            "- You may confirm this event as saved."
        )
    if isinstance(parsed_log, dict):
        reason = (write_error or "unknown").strip() or "unknown"
        return (
            "## Write Status\n"
            "- Structured log write: failed\n"
            f"- Failure reason: {reason}\n"
            "- Do not claim this event was saved.\n"
            "- Tell the user save failed and ask them to retry."
        )
    return (
        "## Write Status\n"
        "- No structured payload could be extracted for this logging intent.\n"
        "- Do not claim this event was saved."
    )


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
    utility_budget: UtilityCallBudget | None = None,
):
    if not _has_feedback_signal(message_text):
        return
    if utility_budget and not utility_budget.can_call("feedback_extract"):
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
        record_ai_failure("utility", "feedback_extract", str(e))
        logger.warning(f"Agent feedback extraction failed: {e}")


async def _mark_checklist_completed_for_meds(
    db: Session,
    _provider,
    user: User,
    combined_input: str,
    reference_utc: datetime | None = None,
    extracted_matches: list[str] | None = None,
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
    med_names = [
        item.get("name", "")
        for item in med_items
        if item.get("name") and not _is_generic_medication_phrase(item.get("name", ""))
    ]
    if not med_names:
        return
    if not _looks_like_medication_intake(combined_input, med_names):
        return

    def _contains_bp_keyword(med_name: str) -> bool:
        m = med_name.lower()
        return any(k in m for k in BP_MED_KEYWORDS)

    mentioned_specific = [m for m in med_names if m.lower() in text]
    targets: list[str] = []

    extracted_targets = _known_name_matches(extracted_matches, med_names)

    if extracted_targets:
        targets = extracted_targets
    elif mentioned_specific:
        targets = mentioned_specific
    else:
        # First pass: standardized resolver tool (handles "morning meds", "blood pressure meds", etc.)
        try:
            resolved = tool_registry.execute(
                "medication_resolve_reference",
                {"query": combined_input},
                ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc),
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
        if "blood pressure" in text or "bp " in f"{text} ":
            targets = [m for m in med_names if _contains_bp_keyword(m)]
        else:
            targets = []

    if not targets:
        return

    target_date = infer_target_date_iso(
        combined_input,
        reference_utc,
        getattr(getattr(user, "settings", None), "timezone", None),
    )

    try:
        tool_registry.execute(
            "checklist_mark_taken",
            {
                "item_type": "medication",
                "names": targets,
                "target_date": target_date,
                "completed": True,
            },
            ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc),
        )
    except Exception as e:
        logger.warning(f"Checklist medication write tool failed: {e}")


async def _mark_checklist_completed_for_supplements(
    db: Session,
    _provider,
    user: User,
    combined_input: str,
    reference_utc: datetime | None = None,
    extracted_matches: list[str] | None = None,
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
    supp_names = [
        item.get("name", "").strip()
        for item in supp_items
        if item.get("name") and not _is_generic_supplement_phrase(item.get("name", ""))
    ]
    if not supp_names:
        return
    if not _looks_like_supplement_intake(combined_input, supp_names):
        return

    targets: list[str] = []
    extracted_targets = _known_name_matches(extracted_matches, supp_names)

    # 1) Direct / normalized match (handles entries like "IM8")
    if extracted_targets:
        targets.extend(extracted_targets)
    else:
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
                ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc),
            )
            for match in resolved.get("matches", []):
                name = str(match.get("name", "")).strip()
                if name and name in supp_names and name not in targets:
                    targets.append(name)
        except ToolExecutionError as e:
            logger.warning(f"Supplement resolver tool failed: {e}")
        except Exception as e:
            logger.warning(f"Supplement resolver tool unexpected failure: {e}")

    # 4) Last-resort fallback for explicit group phrases
    if not targets and ("my supplements" in text or "my vitamin" in text or "my vitamins" in text):
        targets = list(supp_names)

    if not targets:
        return

    target_date = infer_target_date_iso(
        combined_input,
        reference_utc,
        getattr(getattr(user, "settings", None), "timezone", None),
    )

    try:
        tool_registry.execute(
            "checklist_mark_taken",
            {
                "item_type": "supplement",
                "names": targets,
                "target_date": target_date,
                "completed": True,
            },
            ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc),
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


def _normalize_text_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _looks_like_goal_turn(message_text: str) -> bool:
    t = " ".join(str(message_text or "").strip().lower().split())
    if not t:
        return False
    goal_terms = (
        "goal-setting kickoff:",
        "goal-refinement kickoff:",
        "goal",
        "goals",
        "target",
        "deadline",
        "timeline",
        "refine",
        "adjust",
        "by ",
        "workout",
        "hiit",
        "strength",
    )
    return any(term in t for term in goal_terms)


def _goal_save_intent(message_text: str) -> bool:
    t = " ".join(str(message_text or "").strip().lower().split())
    signals = (
        "sounds good",
        "go ahead",
        "save",
        "finalize",
        "lock it in",
        "yes",
        "update to",
        "i want to target",
    )
    return any(signal in t for signal in signals)


def _response_claims_goal_saved(text: str) -> bool:
    t = " ".join(str(text or "").strip().lower().split())
    save_terms = ("saved", "save these goals", "i'll save", "let me save", "now save", "go ahead and save")
    if not any(term in t for term in save_terms):
        return False
    return "goal" in t


def _resolve_goal_for_update(
    existing_goals: list[UserGoal],
    goal_id: int | None = None,
    title_match: str | None = None,
) -> UserGoal | None:
    if goal_id:
        for row in existing_goals:
            if int(row.id) == int(goal_id):
                return row

    match_key = _normalize_text_key(title_match)
    if not match_key:
        return None
    for row in existing_goals:
        title_key = _normalize_text_key(row.title)
        if match_key and title_key and (match_key in title_key or title_key in match_key):
            return row
    return None


def _goal_sync_followup_text(goal_sync: dict[str, Any], assistant_response: str) -> str | None:
    created_titles = [str(x).strip() for x in (goal_sync.get("created_titles") or []) if str(x).strip()]
    updated_titles = [str(x).strip() for x in (goal_sync.get("updated_titles") or []) if str(x).strip()]
    created = int(goal_sync.get("created") or 0)
    updated = int(goal_sync.get("updated") or 0)

    if created or updated:
        lines: list[str] = []
        if created_titles:
            lines.append(f"Saved goals: {', '.join(created_titles)}.")
        elif created:
            lines.append(f"Saved {created} new goal(s).")
        if updated_titles:
            lines.append(f"Updated goals: {', '.join(updated_titles)}.")
        elif updated:
            lines.append(f"Updated {updated} existing goal(s).")
        lines.append("Return to the Goals page to review your 5-day timeline and start check-ins.")
        return "\n".join(lines)

    if goal_sync.get("goal_context") and _response_claims_goal_saved(assistant_response):
        return (
            "I have not persisted goal changes yet. Confirm the exact target(s) and timeline(s), "
            "and I will save them before we move on."
        )
    return None


async def _apply_goal_updates(
    db: Session,
    provider,
    user: User,
    message_text: str,
    reference_utc: datetime | None = None,
    utility_budget: UtilityCallBudget | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "goal_context": False,
        "save_intent": False,
        "attempted": False,
        "created": 0,
        "updated": 0,
        "created_titles": [],
        "updated_titles": [],
    }

    if not _looks_like_goal_turn(message_text):
        return summary
    summary["goal_context"] = True
    summary["save_intent"] = _goal_save_intent(message_text)

    if utility_budget and not utility_budget.can_call("goal_sync_extract"):
        return summary

    existing_goals = (
        db.query(UserGoal)
        .filter(UserGoal.user_id == user.id, UserGoal.status == "active")
        .order_by(UserGoal.priority.asc(), UserGoal.created_at.asc())
        .all()
    )
    existing_payload = [
        {
            "goal_id": int(row.id),
            "title": row.title,
            "goal_type": row.goal_type,
            "target_value": row.target_value,
            "target_unit": row.target_unit,
            "target_date": row.target_date,
            "priority": row.priority,
        }
        for row in existing_goals
    ]
    recent_messages = (
        db.query(Message)
        .filter(Message.user_id == user.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(6)
        .all()
    )
    recent_context_payload: list[dict[str, str]] = []
    for row in reversed(recent_messages):
        role = str(row.role or "").strip().lower()
        if role not in {"assistant", "user"}:
            continue
        content = str(row.content or "").strip()
        if not content:
            continue
        recent_context_payload.append({"role": role, "content": content[:1200]})

    try:
        result = await provider.chat(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Current goals JSON:\n{json.dumps(existing_payload, ensure_ascii=True)}\n\n"
                        f"Recent conversation JSON:\n{json.dumps(recent_context_payload, ensure_ascii=True)}\n\n"
                        f"User message:\n{message_text}"
                    ),
                }
            ],
            model=provider.get_utility_model(),
            system=GOAL_SYNC_EXTRACT_PROMPT,
            stream=False,
        )
        track_usage_from_result(
            db=db,
            user_id=user.id,
            result=result,
            model_used=provider.get_utility_model(),
            operation="goal_sync_extract",
            usage_type="utility",
        )
        parsed = _extract_json_payload(result.get("content"))
    except Exception as e:
        record_ai_failure("utility", "goal_sync_extract", str(e))
        logger.warning(f"Goal sync extraction failed: {e}")
        return summary

    summary["attempted"] = True
    action = str(parsed.get("action") or "none").strip().lower()
    if action not in {"create", "update", "create_or_update"}:
        return summary

    tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc)
    valid_goal_types = {"weight_loss", "cardiovascular", "fitness", "metabolic", "energy", "sleep", "habit", "custom"}
    valid_statuses = {"active", "paused", "completed", "abandoned"}

    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    create_rows = parsed.get("create_goals", [])
    if isinstance(create_rows, list) and action in {"create", "create_or_update"}:
        for item in create_rows[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            duplicate = _resolve_goal_for_update(existing_goals, title_match=title)
            if duplicate:
                continue

            payload: dict[str, Any] = {"title": title}
            goal_type = str(item.get("goal_type") or "custom").strip().lower()
            payload["goal_type"] = goal_type if goal_type in valid_goal_types else "custom"
            for key in ("description", "target_unit", "target_date", "why"):
                value = item.get(key)
                if value is not None and str(value).strip():
                    payload[key] = str(value).strip()
            target_value = _to_float(item.get("target_value"))
            baseline_value = _to_float(item.get("baseline_value"))
            if target_value is not None:
                payload["target_value"] = target_value
            if baseline_value is not None:
                payload["baseline_value"] = baseline_value
            priority = _to_int(item.get("priority"))
            if priority is not None:
                payload["priority"] = max(1, min(priority, 5))

            try:
                out = tool_registry.execute("create_goal", payload, tool_ctx)
                row = (out or {}).get("goal") if isinstance(out, dict) else None
                if isinstance(row, dict):
                    summary["created"] = int(summary["created"] or 0) + 1
                    summary["created_titles"].append(str(row.get("title") or title))
            except Exception as e:
                logger.warning(f"Goal create tool failed for '{title}': {e}")

    update_rows = parsed.get("update_goals", [])
    if isinstance(update_rows, list) and action in {"update", "create_or_update"}:
        refreshed_goals = (
            db.query(UserGoal)
            .filter(UserGoal.user_id == user.id, UserGoal.status == "active")
            .order_by(UserGoal.priority.asc(), UserGoal.created_at.asc())
            .all()
        )
        for item in update_rows[:5]:
            if not isinstance(item, dict):
                continue
            goal_id = _to_int(item.get("goal_id"))
            title_match = str(item.get("title_match") or item.get("title") or "").strip() or None
            match = _resolve_goal_for_update(refreshed_goals, goal_id=goal_id, title_match=title_match)
            if not match:
                continue

            payload: dict[str, Any] = {"goal_id": int(match.id)}
            for key in ("title", "description", "target_unit", "target_date", "why"):
                if key in item and item.get(key) is not None:
                    value = str(item.get(key)).strip()
                    payload[key] = value if value else None
            if "goal_type" in item and item.get("goal_type") is not None:
                goal_type = str(item.get("goal_type")).strip().lower()
                payload["goal_type"] = goal_type if goal_type in valid_goal_types else "custom"
            if "status" in item and item.get("status") is not None:
                status = str(item.get("status")).strip().lower()
                if status in valid_statuses:
                    payload["status"] = status

            for key in ("target_value", "baseline_value", "current_value"):
                if key in item:
                    value = _to_float(item.get(key))
                    if value is not None:
                        payload[key] = value
            if "priority" in item:
                priority = _to_int(item.get("priority"))
                if priority is not None:
                    payload["priority"] = max(1, min(priority, 5))

            if len(payload) <= 1:
                continue
            try:
                out = tool_registry.execute("update_goal", payload, tool_ctx)
                row = (out or {}).get("goal") if isinstance(out, dict) else None
                if isinstance(row, dict):
                    summary["updated"] = int(summary["updated"] or 0) + 1
                    summary["updated_titles"].append(str(row.get("title") or match.title))
            except Exception as e:
                logger.warning(f"Goal update tool failed for goal_id={match.id}: {e}")

    return summary


async def _apply_profile_updates(
    db: Session,
    provider,
    user: User,
    message_text: str,
    combined_input: str,
    category: str,
    reference_utc: datetime | None = None,
    utility_budget: UtilityCallBudget | None = None,
) -> dict[str, list[str]]:
    """Auto-sync profile meds/supplements/conditions from message context."""
    settings = user.settings
    if not settings:
        return {"matched_medications": [], "matched_supplements": []}

    # Opportunistic cleanup of legacy generic placeholders ("morning meds", "my vitamins").
    existing_meds = parse_structured_list(settings.medications)
    cleaned_meds = [m for m in existing_meds if not _is_generic_medication_phrase(m.get("name", ""))]
    meds_json = cleanup_structured_list(json.dumps(cleaned_meds, ensure_ascii=True)) if cleaned_meds else None
    if meds_json != settings.medications:
        settings.medications = meds_json

    existing_supps = parse_structured_list(settings.supplements)
    cleaned_supps = [s for s in existing_supps if not _is_generic_supplement_phrase(s.get("name", ""))]
    supps_json = cleanup_structured_list(json.dumps(cleaned_supps, ensure_ascii=True)) if cleaned_supps else None
    if supps_json != settings.supplements:
        settings.supplements = supps_json

    current_med_names = [str(item.get("name", "")).strip() for item in cleaned_meds if str(item.get("name", "")).strip()]
    current_supp_names = [str(item.get("name", "")).strip() for item in cleaned_supps if str(item.get("name", "")).strip()]

    if utility_budget and not utility_budget.can_call("profile_extract"):
        return {"matched_medications": [], "matched_supplements": []}

    try:
        med_list = "\n".join(f"- {name}" for name in current_med_names) if current_med_names else "- (none)"
        supp_list = "\n".join(f"- {name}" for name in current_supp_names) if current_supp_names else "- (none)"
        user_payload = (
            f"{PROFILE_EXTRACT_PROMPT}\n\n"
            f"Current medication list:\n{med_list}\n\n"
            f"Current supplement list:\n{supp_list}\n\n"
            f"Message: {combined_input}"
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": user_payload}],
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
        extracted = _extract_json_payload(result.get("content"))

        matched_meds = _known_name_matches(extracted.get("matched_medications"), current_med_names)
        matched_supps = _known_name_matches(extracted.get("matched_supplements"), current_supp_names)

        # Convert AI output to structured items (handles both dicts and strings)
        raw_meds = extracted.get("medications", [])
        raw_supps = extracted.get("supplements", [])
        med_items: list[StructuredItem] = [to_structured(x) for x in raw_meds if x]
        supp_items: list[StructuredItem] = [to_structured(x) for x in raw_supps if x]

        conditions = [str(x).strip() for x in extracted.get("medical_conditions", []) if str(x).strip()]
        dietary = [str(x).strip() for x in extracted.get("dietary_preferences", []) if str(x).strip()]
        goals = [str(x).strip() for x in extracted.get("health_goals", []) if str(x).strip()]
        family = [str(x).strip() for x in extracted.get("family_history", []) if str(x).strip()]

        # Drop generic placeholders like "blood pressure meds" / "morning meds"
        med_items = [m for m in med_items if not _is_generic_medication_phrase(m.get("name", ""))]
        supp_items = [s for s in supp_items if not _is_generic_supplement_phrase(s.get("name", ""))]

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
            cleaned_supp = cleanup_structured_list(settings.supplements)
            if cleaned_supp != settings.supplements:
                settings.supplements = cleaned_supp
            cleaned_med = cleanup_structured_list(settings.medications)
            if cleaned_med != settings.medications:
                settings.medications = cleaned_med
            return {
                "matched_medications": matched_meds,
                "matched_supplements": matched_supps,
            }

        tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc)

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
        if med_items or supp_items or list_patch:
            try:
                tool_registry.execute("framework_sync_from_profile", {}, tool_ctx)
            except Exception as e:
                logger.warning(f"Framework sync tool failed: {e}")
        return {
            "matched_medications": matched_meds,
            "matched_supplements": matched_supps,
        }
    except Exception as e:
        record_ai_failure("utility", "profile_extract", str(e))
        logger.warning(f"Profile auto-sync extraction failed: {e}")
        return {"matched_medications": [], "matched_supplements": []}


async def save_structured_log(
    db: Session,
    user: User,
    category: str,
    data: dict,
    reference_utc: datetime | None = None,
):
    """Save parsed structured data to the appropriate log table."""
    tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator", reference_utc=reference_utc)
    out: dict[str, Any] | None = None
    if category == "log_food" and data:
        out = tool_registry.execute(
            "food_log_write",
            {
                "logged_at": data.get("logged_at") or data.get("event_time"),
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
                "logged_at": data.get("logged_at") or data.get("event_time"),
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
                "logged_at": data.get("logged_at") or data.get("event_time"),
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
                "logged_at": data.get("logged_at") or data.get("event_time"),
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
                "fast_start": data.get("fast_start"),
                "fast_end": data.get("fast_end"),
                "fast_type": data.get("fast_type"),
                "notes": data.get("notes"),
            },
            tool_ctx,
        )

    elif category == "log_sleep" and data:
        out = tool_registry.execute(
            "sleep_log_write",
            {
                "action": data.get("action"),
                "sleep_start": data.get("sleep_start"),
                "sleep_end": data.get("sleep_end"),
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
                "logged_at": data.get("logged_at") or data.get("event_time"),
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
    verbosity: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Main chat orchestration. Yields streaming response chunks."""
    user_settings = user.settings
    if not user_settings or not user_settings.api_key_encrypted:
        yield {"type": "error", "text": "Please configure your API key in Settings before chatting."}
        return

    api_key = decrypt_api_key(user_settings.api_key_encrypted)
    message_received_utc = datetime.now(timezone.utc)
    turn_started_perf = time.perf_counter()
    start_ai_turn_scope(user_id=user.id, specialist_id="orchestrator", intent_category="general_chat")
    provider = get_provider(
        user_settings.ai_provider,
        api_key,
        reasoning_model=user_settings.reasoning_model,
        utility_model=user_settings.utility_model,
        deep_thinking_model=getattr(user_settings, "deep_thinking_model", None),
    )

    # 1. If image attached, analyze it first
    image_context = ""
    if image_bytes:
        analysis = await analyze_image(provider, image_bytes)
        if analysis["success"]:
            image_context = f"\n[Image analysis: {analysis['content']}]"

    combined_input = message + image_context
    time_confirmation_gate = _handle_pending_time_confirmation(
        db=db,
        user=user,
        message_text=message,
        reference_utc=message_received_utc,
        timezone_name=getattr(user_settings, "timezone", None),
    )

    # 2. Classify intent
    overrides = parse_overrides(user.specialist_config)
    enabled_specialists = get_enabled_specialist_ids(overrides)
    specialist_override = None
    if user.specialist_config and user.specialist_config.active_specialist != "auto":
        specialist_override = user.specialist_config.active_specialist

    classify_allow_model = True
    scope = get_ai_turn_scope()
    if scope is not None:
        classify_allow_model = int(scope.utility_calls or 0) < max(int(settings.UTILITY_CALL_BUDGET_NONLOG_TURN), 1)

    intent = await classify_intent(
        provider,
        combined_input,
        specialist_override,
        allowed_specialists=enabled_specialists,
        db=db,
        user_id=user.id,
        allow_model_call=classify_allow_model,
    )
    category = intent["category"]
    specialist = intent["specialist"]
    try:
        intent_confidence = float(intent.get("confidence") or 0.0)
    except (TypeError, ValueError):
        intent_confidence = 0.0
    update_ai_turn_scope(specialist_id=specialist, intent_category=category)
    specialist_name = _resolve_specialist_name(overrides, specialist)
    utility_budget = UtilityCallBudget(category)
    low_signal_checkin = _is_low_signal_checkin(message) and category in {"general_chat", "manual_override"}

    if low_signal_checkin:
        daily_plan_snapshot = _safe_daily_plan_snapshot(db, user)
        proactive_reply = _compose_proactive_checkin_reply(daily_plan_snapshot, user)
        first_token_ms = (time.perf_counter() - turn_started_perf) * 1000.0

        user_msg = Message(
            user_id=user.id,
            role="user",
            content=message,
            has_image=bool(image_bytes),
            created_at=message_received_utc,
        )
        db.add(user_msg)
        db.commit()

        assistant_msg = Message(
            user_id=user.id,
            role="assistant",
            content=proactive_reply,
            specialist_used=specialist,
            model_used="rule_based_checkin",
            tokens_in=0,
            tokens_out=0,
        )
        db.add(assistant_msg)
        db.commit()

        mark_ai_first_token(first_token_ms)
        yield {"type": "chunk", "text": proactive_reply}
        yield {"type": "done", "specialist": specialist, "category": category}

        total_turn_latency_ms = (time.perf_counter() - turn_started_perf) * 1000.0
        turn_scope = consume_ai_turn_scope()
        if turn_scope:
            try:
                persist_ai_turn_event(
                    {
                        "user_id": turn_scope.user_id,
                        "message_id": assistant_msg.id,
                        "specialist_id": turn_scope.specialist_id,
                        "intent_category": turn_scope.intent_category,
                        "first_token_latency_ms": turn_scope.first_token_latency_ms,
                        "total_latency_ms": total_turn_latency_ms,
                        "utility_calls": turn_scope.utility_calls,
                        "reasoning_calls": turn_scope.reasoning_calls,
                        "deep_calls": turn_scope.deep_calls,
                        "utility_tokens_in": turn_scope.utility_tokens_in,
                        "utility_tokens_out": turn_scope.utility_tokens_out,
                        "reasoning_tokens_in": turn_scope.reasoning_tokens_in,
                        "reasoning_tokens_out": turn_scope.reasoning_tokens_out,
                        "deep_tokens_in": turn_scope.deep_tokens_in,
                        "deep_tokens_out": turn_scope.deep_tokens_out,
                        "failure_count": turn_scope.failure_count,
                        "failures_json": json.dumps(turn_scope.failures, ensure_ascii=True),
                    }
                )
            except Exception as e:
                logger.warning(f"AI turn telemetry persistence failed: {e}")
        else:
            clear_ai_turn_scope()
        return

    # 2b. Auto-log global feedback from user bug/enhancement messages under specialist.
    await _log_agent_feedback_if_needed(
        db=db,
        provider=provider,
        user=user,
        message_text=message,
        specialist_id=specialist,
        specialist_name=specialist_name,
        utility_budget=utility_budget,
    )
    db.commit()

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
    log_write_error: str | None = None
    if category.startswith("log_") and not menu_command_only and not bool(time_confirmation_gate.get("skip_log_parse")):
        user_profile = ""
        if user_settings.current_weight_kg:
            if user_settings.weight_unit == "lb":
                user_profile = f"Weight: {kg_to_lb(user_settings.current_weight_kg):.1f}lb"
            else:
                user_profile = f"Weight: {user_settings.current_weight_kg}kg"
        parsed_log_data = await parse_log_data(
            provider,
            combined_input,
            category,
            user_profile=user_profile,
            db=db,
            user_id=user.id,
            allow_model_call=utility_budget.can_call(f"log_parse:{category}"),
        )
        if category == "log_sleep":
            parsed_log_data = _normalize_sleep_payload(message, parsed_log_data)
        parsed_log_data = _apply_inferred_event_time(
            category=category,
            message_text=message,
            payload=parsed_log_data,
            reference_utc=message_received_utc,
            timezone_name=getattr(user_settings, "timezone", None),
        )
        if parsed_log_data:
            try:
                saved_log_out = await save_structured_log(
                    db,
                    user,
                    category,
                    parsed_log_data,
                    reference_utc=message_received_utc,
                )
                _persist_low_confidence_time_confirmation(
                    db=db,
                    user=user,
                    category=category,
                    parsed_payload=parsed_log_data,
                    saved_out=saved_log_out,
                )
                db.commit()
            except ToolExecutionError as e:
                log_write_error = str(e)
                logger.warning(f"Structured log tool write failed ({category}): {e}")
            except Exception as e:
                log_write_error = str(e)
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
    extracted_profile_refs = {"matched_medications": [], "matched_supplements": []}
    should_profile_sync = bool(image_bytes) or category in {
        "log_supplement",
        "ask_supplement",
        "ask_medical",
        "ask_nutrition",
        "general_chat",
        "manual_override",
    }
    if should_profile_sync and not image_bytes and not category.startswith("log_") and intent_confidence < 0.6:
        should_profile_sync = False

    if should_profile_sync:
        extracted_profile_refs = await _apply_profile_updates(
            db=db,
            provider=provider,
            user=user,
            message_text=message,
            combined_input=combined_input,
            category=category,
            reference_utc=message_received_utc,
            utility_budget=utility_budget,
        )
        db.commit()

    # 3c. Attempt checklist marking once per turn, using merged extraction
    # output when available to avoid extra utility model calls.
    try:
        await _mark_checklist_completed_for_meds(
            db,
            provider,
            user,
            combined_input,
            reference_utc=message_received_utc,
            extracted_matches=extracted_profile_refs.get("matched_medications"),
        )
        await _mark_checklist_completed_for_supplements(
            db,
            provider,
            user,
            combined_input,
            reference_utc=message_received_utc,
            extracted_matches=extracted_profile_refs.get("matched_supplements"),
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Checklist sync from chat failed: {e}")

    # 3d. Goal sync: persist structured goal create/update actions when the
    # user confirms goal-setting or refinement details in chat.
    goal_sync_result: dict[str, Any] = {
        "goal_context": False,
        "save_intent": False,
        "attempted": False,
        "created": 0,
        "updated": 0,
        "created_titles": [],
        "updated_titles": [],
    }
    try:
        goal_sync_result = await _apply_goal_updates(
            db=db,
            provider=provider,
            user=user,
            message_text=message,
            reference_utc=message_received_utc,
            utility_budget=utility_budget,
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Goal sync from chat failed: {e}")

    # 3e. Optional live web search for supported specialists/questions.
    web_results: list[dict] = []
    if _should_use_web_search(message, category, specialist):
        try:
            search_out = await asyncio.to_thread(
                _execute_web_search_in_worker,
                user.id,
                specialist,
                message,
                settings.WEB_SEARCH_MAX_RESULTS,
            )
            web_results = search_out.get("results", []) if isinstance(search_out, dict) else []
        except Exception as e:
            logger.warning(f"web_search tool failed: {e}")

    # 3f. Provide authoritative current time/date context when asked.
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
    log_write_context = _build_log_write_context(
        category=category,
        parsed_log=parsed_log_data,
        saved_out=saved_log_out,
        write_error=log_write_error,
    )
    verbosity_context = _verbosity_style_context(_normalize_chat_verbosity(verbosity))
    time_inference_context = _build_time_inference_context(parsed_log_data)
    pending_time_confirmation_context = str(time_confirmation_gate.get("context", "") or "")

    # 3g. Trigger due longitudinal analysis windows in background with debounce/lock.
    await _dispatch_due_analysis_if_allowed(user.id)

    # 4. Build context
    system_context = build_context(db, user, specialist, intent_category=category)
    if web_results:
        system_context = f"{system_context}\n\n{_format_web_search_context(web_results)}"
    if time_context:
        system_context = f"{system_context}\n\n{time_context}"
    if menu_context:
        system_context = f"{system_context}\n\n{menu_context}"
    if log_write_context:
        system_context = f"{system_context}\n\n{log_write_context}"
    if time_inference_context:
        system_context = f"{system_context}\n\n{time_inference_context}"
    if pending_time_confirmation_context:
        system_context = f"{system_context}\n\n{pending_time_confirmation_context}"
    if verbosity_context:
        system_context = f"{system_context}\n\n{verbosity_context}"
    if int(goal_sync_result.get("created") or 0) > 0 or int(goal_sync_result.get("updated") or 0) > 0:
        system_context = (
            f"{system_context}\n\n"
            f"[Goal sync completed this turn: created={int(goal_sync_result.get('created') or 0)}, "
            f"updated={int(goal_sync_result.get('updated') or 0)}. Acknowledge changes succinctly.]"
        )

    # 5. Get recent messages for conversation history
    recent = get_recent_messages(db, user, limit=20)
    messages = recent + [{"role": "user", "content": combined_input}]

    # 6. Save user message
    user_msg = Message(
        user_id=user.id,
        role="user",
        content=message,
        has_image=bool(image_bytes),
        created_at=message_received_utc,
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
    first_token_recorded = False

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
                if text and not first_token_recorded:
                    mark_ai_first_token((time.perf_counter() - turn_started_perf) * 1000.0)
                    first_token_recorded = True
                yield {"type": "chunk", "text": text}
            elif chunk.get("type") == "done":
                tokens_in = chunk.get("tokens_in", 0)
                tokens_out = chunk.get("tokens_out", 0)

        track_model_usage(
            db=db,
            user_id=user.id,
            model_used=provider.get_reasoning_model(),
            operation="chat_generate",
            usage_type="reasoning",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

        followup_line = _followup_line_from_hint(menu_followup_hint)
        if followup_line and not _response_already_has_followup(full_response, menu_followup_hint):
            append_text = f"\n\n{followup_line}" if full_response else followup_line
            full_response += append_text
            yield {"type": "chunk", "text": append_text}

        goal_followup = _goal_sync_followup_text(goal_sync_result, full_response)
        if goal_followup:
            append_text = f"\n\n{goal_followup}" if full_response else goal_followup
            full_response += append_text
            yield {"type": "chunk", "text": append_text}

        yield {"type": "done", "specialist": specialist, "category": category}

    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        record_ai_failure("reasoning", "chat_generate", str(e))
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

    total_turn_latency_ms = (time.perf_counter() - turn_started_perf) * 1000.0
    turn_scope = consume_ai_turn_scope()
    if turn_scope:
        try:
            persist_ai_turn_event(
                {
                    "user_id": turn_scope.user_id,
                    "message_id": assistant_msg.id,
                    "specialist_id": turn_scope.specialist_id,
                    "intent_category": turn_scope.intent_category,
                    "first_token_latency_ms": turn_scope.first_token_latency_ms,
                    "total_latency_ms": total_turn_latency_ms,
                    "utility_calls": turn_scope.utility_calls,
                    "reasoning_calls": turn_scope.reasoning_calls,
                    "deep_calls": turn_scope.deep_calls,
                    "utility_tokens_in": turn_scope.utility_tokens_in,
                    "utility_tokens_out": turn_scope.utility_tokens_out,
                    "reasoning_tokens_in": turn_scope.reasoning_tokens_in,
                    "reasoning_tokens_out": turn_scope.reasoning_tokens_out,
                    "deep_tokens_in": turn_scope.deep_tokens_in,
                    "deep_tokens_out": turn_scope.deep_tokens_out,
                    "failure_count": turn_scope.failure_count,
                    "failures_json": json.dumps(turn_scope.failures, ensure_ascii=True),
                }
            )
        except Exception as e:
            logger.warning(f"AI turn telemetry persistence failed: {e}")
    else:
        clear_ai_turn_scope()
