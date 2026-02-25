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


def _looks_like_food_planning_question(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if not _looks_like_question(normalized):
        return False
    past_log_cues = (
        "i had ",
        "i ate ",
        "i drank ",
        "my lunch was",
        "my breakfast was",
        "my dinner was",
        "just had",
        "just ate",
        "just drank",
    )
    if any(cue in normalized for cue in past_log_cues):
        return False
    planning_patterns = (
        r"\bcan\s+i\s+(?:have|eat|drink|try)\b",
        r"\bcould\s+i\s+(?:have|eat|drink|try)\b",
        r"\bshould\s+i\s+(?:have|eat|drink|try)\b",
        r"\bwould\s+it\s+be\s+ok(?:ay)?\s+(?:to|if\s+i)\s+(?:have|eat|drink|try)\b",
        r"\bis\s+it\s+ok(?:ay)?\s+(?:to|if\s+i)\s+(?:have|eat|drink|try)\b",
    )
    return any(re.search(pattern, normalized) for pattern in planning_patterns)


_SUPPLEMENT_NAMES = (
    "creatine",
    "fish oil",
    "magnesium",
    "zinc",
    "iron",
    "collagen",
    "probiotic",
    "omega",
    "bcaa",
    "fat burner",
    "pre workout",
    "pre-workout",
    "ashwagandha",
    "melatonin",
    "coq10",
    "curcumin",
    "turmeric",
    "d3",
    "b12",
    "multivitamin",
    "electrolyte",
)


def _heuristic_log_categories(message: str) -> list[str]:
    """Return ALL matching log_* categories for a message (multi-intent scan).

    Unlike ``_heuristic_category`` which returns the *first* match via an
    if/elif chain, this function runs *independent* checks for every log
    category so that multi-intent messages like "drank 24 oz with creatine"
    can populate multiple entries in the orchestrator's ``log_categories``.
    """
    text = _normalize_text(message)
    if not text:
        return []
    categories: list[str] = []
    is_question = _looks_like_question(text)
    # Questions go to ask_* categories, not log_* categories
    if is_question:
        return []

    # --- Fasting ---
    fasting_cues = (
        "start fasting", "starting fast", "begin fast", "end fast",
        "broke my fast", "finished fasting", "fasting window", "i fasted",
    )
    if _contains_any(text, fasting_cues):
        categories.append("log_fasting")

    # --- Sleep ---
    sleep_cues = ("going to bed", "went to bed", "fell asleep", "woke up",
                  "slept", "sleep start", "sleep end", "bed at", "hours of sleep")
    if _contains_any(text, sleep_cues):
        categories.append("log_sleep")

    # --- Hydration ---
    hydration_cues = ("drank water", "drink water", "hydration", "oz of water",
                      "ml of water", "cups of water", "glasses of water")
    if _contains_any(text, hydration_cues):
        categories.append("log_hydration")
    # Quantity + fluid unit with drinking context (e.g., "drank 24 oz")
    if "log_hydration" not in categories:
        if re.search(r"\b\d+\s*(oz|ml|cups?|glasses?|liters?|litres?)\b", text):
            if _contains_any(text, ("drank", "drink", "water", "hydrat")):
                categories.append("log_hydration")

    # --- Exercise ---
    exercise_cues = (
        "workout", "exercise", "training session", "lifted", "strength train",
        "hiit", "zone 2", "cycling", "swim", "yoga", "pushup", "push-up",
        "pull-up", "pullup", "squat", "deadlift", "bench press",
    )
    if _contains_any(text, exercise_cues):
        categories.append("log_exercise")
    # Standalone activity words checked with word boundaries to reduce false positives
    if "log_exercise" not in categories:
        if re.search(r"\b(ran|jogged|walked|biked|hiked)\b", text):
            categories.append("log_exercise")
        elif re.search(r"\b(run|walk|jog)\b", text) and re.search(r"\b\d+\s*(min|minute|hour|hr|mile|km)\b", text):
            categories.append("log_exercise")

    # --- Vitals ---
    vitals_cues = ("blood pressure", "heart rate", "spo2", "glucose", "blood sugar")
    if _contains_any(text, vitals_cues):
        categories.append("log_vitals")
    # Weight with a numeric value (avoid matching "goal weight" which is intake)
    if "log_vitals" not in categories:
        if re.search(r"\b\d+(\.\d+)?\s*(lbs?|kg|pounds?)\b", text) and "goal" not in text:
            categories.append("log_vitals")
    # BP pattern (e.g., "120/80")
    if "log_vitals" not in categories:
        if re.search(r"\b\d{2,3}\s*/\s*\d{2,3}\b", text):
            categories.append("log_vitals")

    # --- Supplements ---
    supplement_cues = (
        "supplement", "supplements", "vitamin", "vitamins", "medication",
        "medications", "meds", "pill", "took my",
    )
    if _contains_any(text, supplement_cues):
        categories.append("log_supplement")
    # Named supplements (e.g., "creatine", "fish oil")
    if "log_supplement" not in categories:
        if _contains_any(text, _SUPPLEMENT_NAMES):
            categories.append("log_supplement")

    # --- Food ---
    food_log_cues = (
        "i ate", "i had", "had a ", "ate a ", "for breakfast", "for lunch",
        "for dinner", "for snack", "my breakfast was", "my lunch was",
        "my dinner was", "i made ", "i cooked ", "i'm eating ", "im eating ",
        "i am eating ",
    )
    if _contains_any(text, food_log_cues):
        categories.append("log_food")
    if "log_food" not in categories:
        if re.search(r"\bfor\s+(breakfast|lunch|dinner|snack)\b", text):
            categories.append("log_food")
    # "i drank" is food when it involves a food-like beverage
    if "log_food" not in categories and "i drank" in text:
        food_item_cues = ("shake", "smoothie", "juice", "coffee", "tea", "milk",
                          "latte", "espresso", "soda", "beer", "wine")
        if _contains_any(text, food_item_cues):
            categories.append("log_food")
    # Named food beverages without "i drank" (e.g., "protein shake after my run")
    if "log_food" not in categories:
        food_beverage_cues = ("protein shake", "smoothie", "coffee", "latte")
        if _contains_any(text, food_beverage_cues):
            categories.append("log_food")

    return categories


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

    hydration_cues = ("drank water", "drink water", "hydration", "oz of water",
                      "ml of water", "cups of water", "glasses of water")
    if _contains_any(text, hydration_cues):
        return "log_hydration"
    # Quantity + fluid unit with drinking verb (e.g., "drank 24 oz")
    if re.search(r"\b\d+\s*(oz|ml|cups?|glasses?|liters?|litres?)\b", text):
        if _contains_any(text, ("drank", "drink")):
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
    if not is_question and _contains_any(text, _SUPPLEMENT_NAMES):
        return "log_supplement"

    food_log_cues = (
        "i ate",
        "i had",
        "i drank",
        "for breakfast",
        "for lunch",
        "for dinner",
        "for snack",
        "my breakfast was",
        "my lunch was",
        "my dinner was",
        "snack",
    )
    if _contains_any(text, food_log_cues):
        if is_question and _looks_like_food_planning_question(text):
            return "ask_nutrition"
        return "log_food"
    food_question_cues = ("meal", "coffee", "protein shake", "nutrition", "diet", "calories", "macros")
    if is_question and _contains_any(text, food_question_cues):
        return "ask_nutrition"

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
