import json
import logging
import re

from sqlalchemy.orm import Session

from ai.usage_tracker import track_usage_from_result
from services.telemetry_context import record_ai_failure

logger = logging.getLogger(__name__)

ROUTING_PROMPT_TEMPLATE = """Classify this user message into ONE category and identify the best specialist.

Categories:
- log_food: User is reporting what they ate/drank
- log_vitals: User is reporting weight, BP, HR, blood glucose
- log_exercise: User is reporting a workout or activity
- log_supplement: User is reporting taking supplements/medications
- log_fasting: User is starting/ending a fast
- log_sleep: User is reporting sleep data
- log_hydration: User is reporting water/fluid intake
- intake_profile: User is setting up or updating baseline profile details (age, height, goals, meds, preferences)
- ask_nutrition: Question about diet, food choices, meal planning
- ask_exercise: Question about workouts, training
- ask_sleep: Question about sleep improvement
- ask_supplement: Question about supplements, timing, interactions
- ask_medical: Question involving symptoms, medications, health concerns
- general_chat: Greetings, motivation, general health topics

Specialists: {specialists}

Return ONLY valid JSON: {{"category": "...", "specialist": "...", "confidence": 0.0-1.0}}"""

CATEGORY_TO_SPECIALIST = {
    "log_food": "nutritionist",
    "log_vitals": "safety_clinician",
    "log_exercise": "movement_coach",
    "log_supplement": "supplement_auditor",
    "log_fasting": "nutritionist",
    "log_sleep": "sleep_expert",
    "log_hydration": "nutritionist",
    "intake_profile": "intake_coach",
    "ask_nutrition": "nutritionist",
    "ask_exercise": "movement_coach",
    "ask_sleep": "sleep_expert",
    "ask_supplement": "supplement_auditor",
    "ask_medical": "safety_clinician",
    "general_chat": "orchestrator",
}
VALID_CATEGORIES = set(CATEGORY_TO_SPECIALIST.keys())


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _looks_like_question(text: str) -> bool:
    if "?" in text:
        return True
    return bool(re.match(r"^(what|how|why|when|where|can|should|could|would|is|are|do|does|did)\b", text))


def _heuristic_category(message: str) -> str:
    text = _normalize_text(message)
    is_question = _looks_like_question(text)

    intake_cues = (
        "intake",
        "profile",
        "my age",
        "my height",
        "my weight",
        "goal weight",
        "timezone",
        "medical condition",
        "health goals",
        "dietary preference",
    )
    if _contains_any(text, intake_cues):
        return "intake_profile"

    if _contains_any(text, ("start fasting", "starting fast", "begin fast", "end fast", "broke my fast", "finished fasting", "fasting")):
        return "log_fasting"

    sleep_cues = ("going to bed", "went to bed", "fell asleep", "woke up", "sleep", "slept")
    if _contains_any(text, sleep_cues):
        return "ask_sleep" if is_question else "log_sleep"

    hydration_cues = ("drank water", "drink water", "hydration", "oz of water", "ml of water", "cups of water")
    if _contains_any(text, hydration_cues):
        return "log_hydration"

    exercise_cues = (
        "workout",
        "exercise",
        "training",
        "lifted",
        "strength",
        "hiit",
        "zone 2",
        "run",
        "walk",
        "cycling",
        "swim",
        "yoga",
    )
    if _contains_any(text, exercise_cues):
        return "ask_exercise" if is_question else "log_exercise"

    vitals_cues = ("blood pressure", " bp ", "bp ", "heart rate", " hr ", "hr ", "spo2", "glucose", "weight")
    if _contains_any(f" {text} ", vitals_cues):
        return "ask_medical" if is_question else "log_vitals"

    supplement_cues = (
        "supplement",
        "supplements",
        "vitamin",
        "vitamins",
        "medication",
        "medications",
        "meds",
        "pill",
        "took my",
    )
    if _contains_any(text, supplement_cues):
        return "ask_supplement" if is_question else "log_supplement"

    food_cues = (
        "i ate",
        "i had",
        "for breakfast",
        "for lunch",
        "for dinner",
        "snack",
        "meal",
        "coffee",
        "protein shake",
    )
    if _contains_any(text, food_cues):
        return "ask_nutrition" if is_question else "log_food"

    if is_question:
        if _contains_any(text, ("food", "nutrition", "diet", "calories", "macros")):
            return "ask_nutrition"
        if _contains_any(text, ("med", "medication", "supplement", "vitamin", "interaction")):
            return "ask_supplement"
        if _contains_any(text, ("symptom", "pain", "dizzy", "headache", "pressure", "doctor")):
            return "ask_medical"

    return "general_chat"


def _heuristic_intent(message: str, forced_specialist: str | None, allowed: list[str]) -> dict:
    category = _heuristic_category(message)
    specialist = forced_specialist or CATEGORY_TO_SPECIALIST.get(category, "orchestrator")
    if specialist not in allowed:
        specialist = "orchestrator"
    return {"category": category, "specialist": specialist, "confidence": 0.15}


async def classify_intent(
    provider,
    message: str,
    user_override: str | None = None,
    allowed_specialists: list[str] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    allow_model_call: bool = True,
) -> dict:
    """Classify user message intent and route to appropriate specialist."""
    allowed = allowed_specialists or [
        "nutritionist",
        "sleep_expert",
        "movement_coach",
        "supplement_auditor",
        "safety_clinician",
        "intake_coach",
        "orchestrator",
    ]

    forced_specialist = None
    if user_override and user_override != "auto":
        forced_specialist = user_override if user_override in allowed else "orchestrator"

    if not allow_model_call:
        return _heuristic_intent(message, forced_specialist, allowed)

    try:
        routing_prompt = ROUTING_PROMPT_TEMPLATE.format(specialists=", ".join(allowed))
        result = await provider.chat(
            messages=[{"role": "user", "content": f"{routing_prompt}\n\nMessage: {message}"}],
            model=provider.get_utility_model(),
            system="You are a classification assistant. Return only valid JSON.",
            stream=False,
        )
        if db is not None and user_id is not None:
            track_usage_from_result(
                db=db,
                user_id=user_id,
                result=result,
                model_used=provider.get_utility_model(),
                operation="intent_classification",
                usage_type="utility",
            )

        text = result["content"].strip()
        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        parsed = json.loads(text)
        category = parsed.get("category", "general_chat")
        if category not in VALID_CATEGORIES:
            category = _heuristic_category(message)
        specialist = forced_specialist or parsed.get("specialist", "orchestrator")
        if specialist not in allowed:
            specialist = CATEGORY_TO_SPECIALIST.get(category, "orchestrator")
        if specialist not in allowed:
            specialist = "orchestrator"
        return {
            "category": category,
            "specialist": specialist,
            "confidence": parsed.get("confidence", 0.5),
        }
    except Exception as e:
        record_ai_failure("utility", "intent_classification", str(e))
        logger.warning(f"Intent classification failed: {e}, using deterministic fallback")
        return _heuristic_intent(message, forced_specialist, allowed)
