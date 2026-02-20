import json
import logging
import inspect
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy.orm import Session

from ai.context_builder import build_context, get_recent_messages
from ai.specialist_router import classify_intent
from ai.log_parser import parse_log_data
from ai.image_analyzer import analyze_image
from ai.providers import get_provider
from db.models import (
    User, Message, FoodLog, VitalsLog, ExerciseLog,
    SupplementLog, FastingLog, SleepLog, HydrationLog, DailyChecklistItem,
)
from services.specialists_config import get_enabled_specialist_ids, parse_overrides
from utils.encryption import decrypt_api_key
from utils.datetime_utils import today_utc
from utils.units import kg_to_lb

logger = logging.getLogger(__name__)

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
    merge_structured_items,
    cleanup_structured_list,
    looks_like_medication as _looks_like_medication,
)


def _parse_string_list(raw: str | None) -> list[str]:
    """Parse a JSON array of strings, or comma-separated text."""
    if not raw:
        return []
    txt = raw.strip()
    if txt.startswith("["):
        try:
            arr = json.loads(txt)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [s.strip() for s in txt.split(",") if s.strip()]


def _merge_profile_items(existing: str | None, new_items: list[str]) -> str | None:
    """Merge plain string lists (conditions, goals, etc.). Deduplicates."""
    merged: list[str] = []
    seen: set[str] = set()
    for item in _parse_string_list(existing) + [x.strip() for x in new_items if x and x.strip()]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return json.dumps(merged) if merged else None


def _is_generic_medication_phrase(item: str) -> bool:
    t = " ".join(item.lower().split())
    return t in GENERIC_MEDICATION_PHRASES


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

    d_iso = today_utc().isoformat()
    for med in targets:
        row = (
            db.query(DailyChecklistItem)
            .filter(
                DailyChecklistItem.user_id == user.id,
                DailyChecklistItem.target_date == d_iso,
                DailyChecklistItem.item_type == "medication",
                DailyChecklistItem.item_name == med,
            )
            .first()
        )
        if not row:
            row = DailyChecklistItem(
                user_id=user.id,
                target_date=d_iso,
                item_type="medication",
                item_name=med,
                completed=True,
            )
            db.add(row)
        else:
            row.completed = True


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
            return

        # Merge structured items for meds and supplements
        if med_items:
            settings.medications = merge_structured_items(settings.medications, med_items)
        if supp_items:
            settings.supplements = merge_structured_items(settings.supplements, supp_items)

        # Always run cleanup to deduplicate and absorb fragments
        settings.supplements = cleanup_structured_list(settings.supplements)
        settings.medications = cleanup_structured_list(settings.medications)

        # Merge plain string lists
        if conditions:
            settings.medical_conditions = _merge_profile_items(settings.medical_conditions, conditions)
        if dietary:
            settings.dietary_preferences = _merge_profile_items(settings.dietary_preferences, dietary)
        if goals:
            settings.health_goals = _merge_profile_items(settings.health_goals, goals)
        if family:
            settings.family_history = _merge_profile_items(settings.family_history, family)

        await _mark_checklist_completed_for_meds(db, provider, user, combined_input)
    except Exception as e:
        logger.warning(f"Profile auto-sync extraction failed: {e}")


async def save_structured_log(db: Session, user: User, category: str, data: dict):
    """Save parsed structured data to the appropriate log table."""
    now = datetime.now(timezone.utc)

    if category == "log_food" and data:
        log = FoodLog(
            user_id=user.id,
            logged_at=now,
            meal_label=data.get("meal_label"),
            items=json.dumps(data.get("items", [])),
            calories=data.get("calories"),
            protein_g=data.get("protein_g"),
            carbs_g=data.get("carbs_g"),
            fat_g=data.get("fat_g"),
            fiber_g=data.get("fiber_g"),
            sodium_mg=data.get("sodium_mg"),
            notes=data.get("notes"),
        )
        db.add(log)

    elif category == "log_vitals" and data:
        log = VitalsLog(
            user_id=user.id,
            logged_at=now,
            weight_kg=data.get("weight_kg"),
            bp_systolic=data.get("bp_systolic"),
            bp_diastolic=data.get("bp_diastolic"),
            heart_rate=data.get("heart_rate"),
            blood_glucose=data.get("blood_glucose"),
            temperature_c=data.get("temperature_c"),
            spo2=data.get("spo2"),
            notes=data.get("notes"),
        )
        db.add(log)

    elif category == "log_exercise" and data:
        log = ExerciseLog(
            user_id=user.id,
            logged_at=now,
            exercise_type=data.get("exercise_type", "other"),
            duration_minutes=data.get("duration_minutes"),
            details=json.dumps(data.get("details")) if data.get("details") else None,
            max_hr=data.get("max_hr"),
            avg_hr=data.get("avg_hr"),
            calories_burned=data.get("calories_burned"),
            notes=data.get("notes"),
        )
        db.add(log)

    elif category == "log_supplement" and data:
        log = SupplementLog(
            user_id=user.id,
            logged_at=now,
            supplements=json.dumps(data.get("supplements", [])),
            timing=data.get("timing"),
            notes=data.get("notes"),
        )
        db.add(log)

    elif category == "log_fasting" and data:
        action = data.get("action", "start")
        if action == "start":
            log = FastingLog(
                user_id=user.id,
                fast_start=now,
                fast_type=data.get("fast_type"),
                notes=data.get("notes"),
            )
            db.add(log)
        elif action == "end":
            # Find the active fast and close it
            active = db.query(FastingLog).filter(
                FastingLog.user_id == user.id,
                FastingLog.fast_end.is_(None),
            ).order_by(FastingLog.fast_start.desc()).first()
            if active:
                active.fast_end = now
                delta = now - active.fast_start
                active.duration_minutes = int(delta.total_seconds() / 60)

    elif category == "log_sleep" and data:
        log = SleepLog(
            user_id=user.id,
            duration_minutes=data.get("duration_minutes"),
            quality=data.get("quality"),
            notes=data.get("notes"),
        )
        db.add(log)

    elif category == "log_hydration" and data:
        log = HydrationLog(
            user_id=user.id,
            logged_at=now,
            amount_ml=data.get("amount_ml", 250),
            source=data.get("source", "water"),
            notes=data.get("notes"),
        )
        db.add(log)

    db.commit()


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
    provider = get_provider(settings.ai_provider, api_key)

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
    )
    category = intent["category"]
    specialist = intent["specialist"]

    # 3. Parse and save structured data if it's a logging intent
    if category.startswith("log_"):
        user_profile = ""
        if settings.current_weight_kg:
            if settings.weight_unit == "lb":
                user_profile = f"Weight: {kg_to_lb(settings.current_weight_kg):.1f}lb"
            else:
                user_profile = f"Weight: {settings.current_weight_kg}kg"
        parsed = await parse_log_data(
            provider,
            combined_input,
            category,
            user_profile=user_profile,
        )
        if parsed:
            await save_structured_log(db, user, category, parsed)

    # 3b. Auto-sync profile fields from user message/image context
    # Run for supplement/medical/general chats and any image-assisted message.
    if image_bytes or category in {
        "log_supplement",
        "ask_supplement",
        "ask_medical",
        "ask_nutrition",
        "general_chat",
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

    # 4. Build context
    system_context = build_context(db, user, specialist)

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
