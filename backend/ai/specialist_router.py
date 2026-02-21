import json
import logging

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


async def classify_intent(
    provider,
    message: str,
    user_override: str | None = None,
    allowed_specialists: list[str] | None = None,
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

    if user_override and user_override != "auto":
        specialist = user_override if user_override in allowed else "orchestrator"
        return {"category": "manual_override", "specialist": specialist, "confidence": 1.0}

    try:
        routing_prompt = ROUTING_PROMPT_TEMPLATE.format(specialists=", ".join(allowed))
        result = await provider.chat(
            messages=[{"role": "user", "content": f"{routing_prompt}\n\nMessage: {message}"}],
            model=provider.get_utility_model(),
            system="You are a classification assistant. Return only valid JSON.",
            stream=False,
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
        specialist = parsed.get("specialist", "orchestrator")
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
        logger.warning(f"Intent classification failed: {e}, defaulting to orchestrator")
        return {"category": "general_chat", "specialist": "orchestrator", "confidence": 0.0}
