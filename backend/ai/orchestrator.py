import json
import logging
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
    SupplementLog, FastingLog, SleepLog, HydrationLog,
)
from utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)


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
    specialist_override = None
    if user.specialist_config and user.specialist_config.active_specialist != "auto":
        specialist_override = user.specialist_config.active_specialist

    intent = await classify_intent(provider, combined_input, specialist_override)
    category = intent["category"]
    specialist = intent["specialist"]

    # 3. Parse and save structured data if it's a logging intent
    if category.startswith("log_"):
        parsed = await parse_log_data(
            provider,
            combined_input,
            category,
            user_profile=f"Weight: {settings.current_weight_kg}kg" if settings.current_weight_kg else "",
        )
        if parsed:
            await save_structured_log(db, user, category, parsed)

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
