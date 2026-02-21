import json
import logging

from sqlalchemy.orm import Session

from ai.usage_tracker import track_usage_from_result

logger = logging.getLogger(__name__)

PARSE_FOOD_PROMPT = """Extract structured food logging data from this message. The user is logging what they ate or drank.

Return ONLY valid JSON with this structure:
{
    "logged_at": "ISO datetime or HH:MM or null",
    "meal_label": "Meal 1" or "Snack" or "Lunch" etc.,
    "items": [{"name": "food name", "quantity": "amount", "unit": "g/oz/cups/etc"}],
    "calories": estimated total calories (number),
    "protein_g": estimated grams (number),
    "carbs_g": estimated grams (number),
    "fat_g": estimated grams (number),
    "fiber_g": estimated grams (number),
    "sodium_mg": estimated mg (number),
    "notes": "any relevant notes"
}

Be as accurate as possible with nutritional estimates. If unsure, provide reasonable estimates and note they are estimated."""

PARSE_VITALS_PROMPT = """Extract structured vitals data from this message.

Return ONLY valid JSON with this structure:
{
    "logged_at": "ISO datetime or HH:MM or null",
    "weight_kg": number or null,
    "bp_systolic": number or null,
    "bp_diastolic": number or null,
    "heart_rate": number or null,
    "blood_glucose": number or null,
    "temperature_c": number or null,
    "spo2": number or null,
    "notes": "any relevant notes"
}

Convert units if needed (lbs to kg: divide by 2.205, °F to °C: (F-32)*5/9).
Only include fields that were mentioned."""

PARSE_EXERCISE_PROMPT = """Extract structured exercise data from this message.

Return ONLY valid JSON with this structure:
{
    "logged_at": "ISO datetime or HH:MM or null",
    "exercise_type": "zone2_cardio" | "strength" | "hiit" | "mobility" | "walk" | "run" | "cycling" | "swimming" | "yoga" | "other",
    "duration_minutes": number,
    "details": {"exercises": [], "sets": null, "reps": null, "weight": null, "distance": null, "incline": null, "speed": null},
    "max_hr": number or null,
    "avg_hr": number or null,
    "calories_burned": estimated number or null,
    "notes": "any relevant notes"
}"""

PARSE_SUPPLEMENT_PROMPT = """Extract structured supplement/medication intake data from this message.

Return ONLY valid JSON with this structure:
{
    "logged_at": "ISO datetime or HH:MM or null",
    "supplements": [{"name": "supplement name", "dose": "amount with unit"}],
    "timing": "morning" | "with_meal" | "evening" | "pre_workout" | "post_workout",
    "notes": "any relevant notes"
}"""

PARSE_FASTING_PROMPT = """Extract fasting intent from this message.

Return ONLY valid JSON with this structure:
{
    "action": "start" | "end",
    "fast_start": "ISO datetime or HH:MM or null",
    "fast_end": "ISO datetime or HH:MM or null",
    "fast_type": "training_day" | "recovery_day" | "extended" | null,
    "notes": "any relevant notes"
}"""

PARSE_SLEEP_PROMPT = """Extract sleep data from this message.

Return ONLY valid JSON with this structure:
{
    "action": "start" | "end" | "auto",
    "sleep_start": "HH:MM" or null,
    "sleep_end": "HH:MM" or null,
    "duration_minutes": number or null,
    "quality": "poor" | "fair" | "good" | "excellent" | null,
    "notes": "any relevant notes"
}

Rules:
- If user indicates going to bed/sleeping now, set action to "start".
- If user indicates waking up or ending sleep, set action to "end".
- If no explicit clock time is provided, leave sleep_start/sleep_end as null.
- If uncertain, use action = "auto".
"""

PARSE_HYDRATION_PROMPT = """Extract hydration data from this message.

Return ONLY valid JSON with this structure:
{
    "logged_at": "ISO datetime or HH:MM or null",
    "amount_ml": number (convert cups to ml: 1 cup = 250ml, 1 glass = 250ml, 1 bottle = 500ml, 1 liter = 1000ml),
    "source": "water" | "coffee" | "tea" | "broth" | "juice" | "other",
    "notes": "any relevant notes"
}"""

CATEGORY_TO_PROMPT = {
    "log_food": PARSE_FOOD_PROMPT,
    "log_vitals": PARSE_VITALS_PROMPT,
    "log_exercise": PARSE_EXERCISE_PROMPT,
    "log_supplement": PARSE_SUPPLEMENT_PROMPT,
    "log_fasting": PARSE_FASTING_PROMPT,
    "log_sleep": PARSE_SLEEP_PROMPT,
    "log_hydration": PARSE_HYDRATION_PROMPT,
}


async def parse_log_data(
    provider,
    message: str,
    category: str,
    user_profile: str = "",
    db: Session | None = None,
    user_id: int | None = None,
) -> dict | None:
    """Use utility model to parse structured data from free-form text."""
    prompt = CATEGORY_TO_PROMPT.get(category)
    if not prompt:
        return None

    context = ""
    if user_profile:
        context = f"\nUser context: {user_profile}\n"

    try:
        result = await provider.chat(
            messages=[{"role": "user", "content": f"{prompt}{context}\n\nMessage: {message}"}],
            model=provider.get_utility_model(),
            system="You are a data extraction assistant. Return only valid JSON, no explanation.",
            stream=False,
        )
        if db is not None and user_id is not None:
            track_usage_from_result(
                db=db,
                user_id=user_id,
                result=result,
                model_used=provider.get_utility_model(),
                operation=f"log_parse:{category}",
                usage_type="utility",
            )

        text = result["content"].strip()
        # Handle markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)
    except Exception as e:
        logger.error(f"Log parsing failed for category {category}: {e}")
        return None
