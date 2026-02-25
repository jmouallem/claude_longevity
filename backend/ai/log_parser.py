import json
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ai.usage_tracker import track_usage_from_result
from services.telemetry_context import record_ai_failure

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


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _extract_time_token(message: str) -> str | None:
    match = re.search(r"\b(\d{1,2}:\d{2}\s?(?:am|pm)?)\b", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b(\d{1,2}\s?(?:am|pm))\b", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_time_tokens(message: str) -> list[str]:
    matches = re.finditer(
        r"\b(\d{1,2}:\d{2}\s?(?:am|pm)?|\d{1,2}\s?(?:am|pm))\b",
        message,
        flags=re.IGNORECASE,
    )
    tokens: list[str] = []
    for match in matches:
        token = str(match.group(1) or "").strip()
        if token:
            tokens.append(token)
    return tokens


def _clock_token_to_minutes(token: str | None) -> int | None:
    if not token:
        return None
    text = str(token).strip().lower().replace(".", "")
    patterns = ("%I:%M%p", "%I:%M %p", "%I%p", "%I %p", "%H:%M")
    for fmt in patterns:
        try:
            parsed = datetime.strptime(text.upper(), fmt)
            return int(parsed.hour) * 60 + int(parsed.minute)
        except ValueError:
            continue
    return None


def _duration_minutes_from_tokens(start_token: str | None, end_token: str | None) -> int | None:
    start_min = _clock_token_to_minutes(start_token)
    end_min = _clock_token_to_minutes(end_token)
    if start_min is None or end_min is None:
        return None
    if end_min < start_min:
        end_min += 24 * 60
    return max(end_min - start_min, 0)


def _deterministic_food_parse(message: str) -> dict:
    text = _normalize_text(message)
    lowered = text.lower()
    meal_label = "Meal"
    if "breakfast" in lowered:
        meal_label = "Breakfast"
    elif "lunch" in lowered:
        meal_label = "Lunch"
    elif "dinner" in lowered:
        meal_label = "Dinner"
    elif "snack" in lowered:
        meal_label = "Snack"

    base = text
    for cue in ("i had ", "i ate ", "for breakfast", "for lunch", "for dinner"):
        idx = lowered.find(cue)
        if idx >= 0 and cue.startswith("i "):
            base = text[idx + len(cue):]
            break
    base = re.sub(r"\b(for (breakfast|lunch|dinner|snack))\b", "", base, flags=re.IGNORECASE).strip(" .")
    if not base:
        base = text

    items: list[dict[str, str]] = []
    for raw in re.split(r",|\band\b", base, flags=re.IGNORECASE):
        name = _normalize_text(raw).strip(" .")
        if not name:
            continue
        items.append({"name": name, "quantity": "", "unit": ""})
    if not items:
        items = [{"name": base, "quantity": "", "unit": ""}]

    calories = None
    cal_match = re.search(r"(\d{1,4})\s*(k?cal|calories?)\b", lowered)
    if cal_match:
        try:
            calories = float(cal_match.group(1))
        except ValueError:
            calories = None

    return {
        "logged_at": _extract_time_token(message),
        "meal_label": meal_label,
        "items": items,
        "calories": calories,
        "protein_g": None,
        "carbs_g": None,
        "fat_g": None,
        "fiber_g": None,
        "sodium_mg": None,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_vitals_parse(message: str) -> dict:
    lowered = message.lower()
    bp_sys = None
    bp_dia = None
    bp_match = re.search(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b", lowered)
    if bp_match:
        bp_sys = int(bp_match.group(1))
        bp_dia = int(bp_match.group(2))

    weight = None
    weight_match = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(kg|lb|lbs)\b", lowered)
    if weight_match:
        weight = float(weight_match.group(1))
        if weight_match.group(2).startswith("lb"):
            weight = round(weight / 2.205, 3)

    hr = None
    hr_match = re.search(r"(?:heart rate|hr)\s*(?:is|at|:)?\s*(\d{2,3})\b", lowered)
    if hr_match:
        hr = int(hr_match.group(1))

    return {
        "logged_at": _extract_time_token(message),
        "weight_kg": weight,
        "bp_systolic": bp_sys,
        "bp_diastolic": bp_dia,
        "heart_rate": hr,
        "blood_glucose": None,
        "temperature_c": None,
        "spo2": None,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_exercise_parse(message: str) -> dict:
    lowered = message.lower()
    exercise_type = "other"
    mapping = {
        "strength": "strength",
        "hiit": "hiit",
        "walk": "walk",
        "run": "run",
        "cycling": "cycling",
        "bike": "cycling",
        "swim": "swimming",
        "yoga": "yoga",
        "mobility": "mobility",
        "zone 2": "zone2_cardio",
    }
    for cue, ex_type in mapping.items():
        if cue in lowered:
            exercise_type = ex_type
            break

    duration = None
    duration_match = re.search(r"\b(\d{1,3})\s*(min|mins|minutes)\b", lowered)
    if duration_match:
        duration = int(duration_match.group(1))

    return {
        "logged_at": _extract_time_token(message),
        "exercise_type": exercise_type,
        "duration_minutes": duration,
        "details": {},
        "max_hr": None,
        "avg_hr": None,
        "calories_burned": None,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_supplement_parse(message: str) -> dict | None:
    text = _normalize_text(message)
    lowered = text.lower()
    base = text
    for cue in ("i took ", "took my ", "had my ", "i had ", "i take "):
        idx = lowered.find(cue)
        if idx >= 0:
            base = text[idx + len(cue):]
            break
    base = base.strip(" .")
    if not base:
        return None

    supplements = []
    for raw in re.split(r",|\band\b", base, flags=re.IGNORECASE):
        name = _normalize_text(raw).strip(" .")
        if not name:
            continue
        supplements.append({"name": name, "dose": ""})

    if not supplements:
        return None

    timing = ""
    if "morning" in lowered:
        timing = "morning"
    elif "lunch" in lowered or "with lunch" in lowered:
        timing = "with_meal"
    elif "dinner" in lowered or "with dinner" in lowered:
        timing = "with_meal"
    elif "evening" in lowered or "bedtime" in lowered:
        timing = "evening"

    return {
        "logged_at": _extract_time_token(message),
        "supplements": supplements,
        "timing": timing,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_fasting_parse(message: str) -> dict:
    lowered = message.lower()
    time_tokens = _extract_time_tokens(message)
    has_last_first_meal = "last meal" in lowered and "first meal" in lowered and len(time_tokens) >= 2
    action = "start"
    if has_last_first_meal or any(
        k in lowered for k in ("end fast", "broke my fast", "break fast", "finished fast", "stop fast", "first meal")
    ):
        action = "end"
    fast_start = None
    fast_end = None
    if has_last_first_meal:
        fast_start, fast_end = time_tokens[0], time_tokens[1]
    elif action == "start":
        fast_start = _extract_time_token(message)
    else:
        if len(time_tokens) >= 2 and ("from" in lowered and ("to" in lowered or "until" in lowered or "till" in lowered)):
            fast_start, fast_end = time_tokens[0], time_tokens[1]
        else:
            fast_end = _extract_time_token(message)

    return {
        "action": action,
        "fast_start": fast_start,
        "fast_end": fast_end,
        "fast_type": None,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_sleep_parse(message: str) -> dict:
    lowered = message.lower()
    time_tokens = _extract_time_tokens(message)
    action = "auto"
    has_end_cue = any(k in lowered for k in ("woke up", "wake up", "got up", "slept", "sleep end"))
    has_start_cue = any(k in lowered for k in ("going to bed", "go to bed", "bedtime", "sleep now", "going to sleep", "went to bed", "fell asleep"))
    if has_end_cue:
        action = "end"
    elif has_start_cue:
        action = "start"

    sleep_start = None
    sleep_end = None
    if has_start_cue and has_end_cue and len(time_tokens) >= 2:
        start_pos = min((lowered.find(cue) for cue in ("going to bed", "go to bed", "bedtime", "sleep now", "going to sleep", "went to bed", "fell asleep") if cue in lowered), default=-1)
        end_pos = min((lowered.find(cue) for cue in ("woke up", "wake up", "got up", "slept", "sleep end") if cue in lowered), default=-1)
        first, second = time_tokens[0], time_tokens[1]
        if start_pos != -1 and end_pos != -1 and end_pos < start_pos:
            sleep_end, sleep_start = first, second
        else:
            sleep_start, sleep_end = first, second
    elif action == "start" and time_tokens:
        sleep_start = time_tokens[0]
    elif action == "end" and time_tokens:
        sleep_end = time_tokens[0]

    duration_minutes = _duration_minutes_from_tokens(sleep_start, sleep_end)
    return {
        "action": action,
        "sleep_start": sleep_start,
        "sleep_end": sleep_end,
        "duration_minutes": duration_minutes,
        "quality": None,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_hydration_parse(message: str) -> dict:
    lowered = message.lower()
    amount_ml = 250.0
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(ml|milliliters?|l|liters?|oz|ounces?|cup|cups|glass|glasses|bottle|bottles)\b", lowered)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        if unit.startswith("ml"):
            amount_ml = value
        elif unit.startswith("l"):
            amount_ml = value * 1000
        elif unit.startswith("oz") or unit.startswith("ounce"):
            amount_ml = value * 29.5735
        elif unit.startswith("cup") or unit.startswith("glass"):
            amount_ml = value * 250
        elif unit.startswith("bottle"):
            amount_ml = value * 500

    source = "water"
    if "coffee" in lowered:
        source = "coffee"
    elif "tea" in lowered:
        source = "tea"
    elif "juice" in lowered:
        source = "juice"

    return {
        "logged_at": _extract_time_token(message),
        "amount_ml": round(amount_ml, 2),
        "source": source,
        "notes": "Deterministic fallback parse",
    }


def _deterministic_parse_by_category(message: str, category: str) -> dict | None:
    if category == "log_food":
        return _deterministic_food_parse(message)
    if category == "log_vitals":
        return _deterministic_vitals_parse(message)
    if category == "log_exercise":
        return _deterministic_exercise_parse(message)
    if category == "log_supplement":
        return _deterministic_supplement_parse(message)
    if category == "log_fasting":
        return _deterministic_fasting_parse(message)
    if category == "log_sleep":
        return _deterministic_sleep_parse(message)
    if category == "log_hydration":
        return _deterministic_hydration_parse(message)
    return None


async def parse_log_data(
    provider,
    message: str,
    category: str,
    user_profile: str = "",
    db: Session | None = None,
    user_id: int | None = None,
    allow_model_call: bool = True,
) -> dict | None:
    """Use utility model to parse structured data from free-form text."""
    prompt = CATEGORY_TO_PROMPT.get(category)
    if not prompt:
        return None
    if not allow_model_call:
        return _deterministic_parse_by_category(message, category)

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

        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        logger.warning(f"Log parsing returned non-dict for category {category}; falling back")
        return _deterministic_parse_by_category(message, category)
    except Exception as e:
        record_ai_failure("utility", f"log_parse:{category}", str(e))
        logger.error(f"Log parsing failed for category {category}: {e}")
        return _deterministic_parse_by_category(message, category)


# ---------------------------------------------------------------------------
# Confidence-gated parse scoring
# ---------------------------------------------------------------------------

_CRITICAL_FIELDS: dict[str, list[str]] = {
    "log_food": ["items"],
    "log_vitals": [],  # any single vital is useful
    "log_exercise": ["exercise_type"],
    "log_supplement": ["supplements"],
    "log_hydration": ["amount_ml"],
    "log_sleep": [],  # action alone is useful
    "log_fasting": [],  # action alone is useful
}

_NOTABLE_FIELDS: dict[str, list[str]] = {
    "log_food": ["items", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g"],
    "log_vitals": ["weight_kg", "bp_systolic", "bp_diastolic", "heart_rate", "blood_glucose"],
    "log_exercise": ["exercise_type", "duration_minutes", "calories_burned"],
    "log_supplement": ["supplements"],
    "log_hydration": ["amount_ml", "source"],
    "log_sleep": ["sleep_start", "sleep_end", "duration_minutes", "quality"],
    "log_fasting": ["fast_start", "fast_end", "duration_minutes"],
}


def assess_parse_confidence(parsed: dict, category: str) -> tuple[str, list[str]]:
    """Score parse quality and return (confidence_level, missing_field_names).

    confidence_level is "high", "medium", or "low".
    missing_field_names lists notable fields that are absent/null.
    """
    notes = str(parsed.get("notes") or "").lower()
    is_fallback = "deterministic fallback" in notes or "low-confidence" in notes

    critical = _CRITICAL_FIELDS.get(category, [])
    notable = _NOTABLE_FIELDS.get(category, [])

    def _is_empty(val: object) -> bool:
        return val is None or val == "" or val == []

    critical_missing = [f for f in critical if _is_empty(parsed.get(f))]
    notable_missing = [f.replace("_", " ") for f in notable if _is_empty(parsed.get(f))]
    notable_present_count = len(notable) - len(notable_missing)

    if is_fallback or critical_missing:
        return "low", notable_missing

    if notable and notable_present_count <= len(notable) / 2:
        return "medium", notable_missing

    return "high", notable_missing
