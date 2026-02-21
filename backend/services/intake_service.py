import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from db.models import IntakeSession, UserSettings
from services.health_framework_service import sync_frameworks_from_settings
from utils.med_utils import cleanup_structured_list, merge_structured_items, parse_structured_list, to_structured
from utils.units import lb_to_kg


INTAKE_FIELD_ORDER = [
    "age",
    "sex",
    "height_cm",
    "current_weight_kg",
    "goal_weight_kg",
    "timezone",
    "fitness_level",
    "medical_conditions",
    "medications",
    "supplements",
    "dietary_preferences",
    "health_goals",
    "family_history",
]

REQUIRED_INTAKE_FIELDS = {
    "age",
    "sex",
    "height_cm",
    "current_weight_kg",
    "timezone",
}

FITNESS_LEVELS = {
    "sedentary": {"sedentary", "inactive", "low"},
    "lightly_active": {"lightly active", "light", "some activity", "walking"},
    "moderately_active": {"moderately active", "moderate"},
    "very_active": {"very active", "active"},
    "extremely_active": {"extremely active", "athlete", "intense", "high"},
}

SEX_MAP = {
    "male": "male",
    "m": "male",
    "female": "female",
    "f": "female",
    "other": "other",
    "non-binary": "other",
    "nonbinary": "other",
    "prefer not to say": "other",
}

TIMEZONE_ALIASES = {
    "mst": "America/Edmonton",
    "mdt": "America/Edmonton",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "est": "America/New_York",
    "edt": "America/New_York",
    "utc": "UTC",
    "gmt": "UTC",
}

TIMING_PATTERNS = [
    ("with breakfast", "with breakfast"),
    ("with lunch", "with lunch"),
    ("with dinner", "with dinner"),
    ("morning", "morning"),
    ("evening", "evening"),
    ("bedtime", "bedtime"),
    ("twice daily", "twice daily"),
    ("as needed", "as needed"),
]

LIST_FIELDS = {"medical_conditions", "dietary_preferences", "health_goals", "family_history"}
STRUCTURED_FIELDS = {"medications", "supplements"}


@dataclass(frozen=True)
class IntakeFieldSpec:
    field_id: str
    label: str
    question: str
    help_text: str
    options: tuple[str, ...] = ()


FIELD_SPECS = {
    "age": IntakeFieldSpec(
        field_id="age",
        label="Age",
        question="What is your age?",
        help_text="Use whole years (for example: 42).",
    ),
    "sex": IntakeFieldSpec(
        field_id="sex",
        label="Sex",
        question="What sex should I use for your profile?",
        help_text="Options: male, female, other.",
        options=("male", "female", "other"),
    ),
    "height_cm": IntakeFieldSpec(
        field_id="height_cm",
        label="Height",
        question="What is your height?",
        help_text="You can use `175 cm` or `5 ft 10 in`.",
    ),
    "current_weight_kg": IntakeFieldSpec(
        field_id="current_weight_kg",
        label="Current Weight",
        question="What is your current weight?",
        help_text="You can use `82 kg` or `180 lb`.",
    ),
    "goal_weight_kg": IntakeFieldSpec(
        field_id="goal_weight_kg",
        label="Goal Weight",
        question="What is your goal weight?",
        help_text="Optional. You can skip this.",
    ),
    "timezone": IntakeFieldSpec(
        field_id="timezone",
        label="Timezone",
        question="What timezone are you in?",
        help_text="Use an IANA timezone like `America/Edmonton` or a common alias like `MST`.",
    ),
    "fitness_level": IntakeFieldSpec(
        field_id="fitness_level",
        label="Fitness Level",
        question="How would you describe your current fitness level?",
        help_text="Options: sedentary, lightly active, moderately active, very active, extremely active.",
        options=("sedentary", "lightly_active", "moderately_active", "very_active", "extremely_active"),
    ),
    "medical_conditions": IntakeFieldSpec(
        field_id="medical_conditions",
        label="Medical Conditions",
        question="Any diagnosed medical conditions I should know about?",
        help_text="Comma-separate multiple items, or say `none`.",
    ),
    "medications": IntakeFieldSpec(
        field_id="medications",
        label="Medications",
        question="What medications are you currently taking?",
        help_text="Include brand/dose/timing if possible. Example: `Candesartan 4mg morning`.",
    ),
    "supplements": IntakeFieldSpec(
        field_id="supplements",
        label="Supplements",
        question="What supplements are you currently taking?",
        help_text="Include brand and dose details where possible.",
    ),
    "dietary_preferences": IntakeFieldSpec(
        field_id="dietary_preferences",
        label="Dietary Preferences",
        question="Any dietary preferences or restrictions?",
        help_text="Examples: no pork, vegetarian, low sodium.",
    ),
    "health_goals": IntakeFieldSpec(
        field_id="health_goals",
        label="Health Goals",
        question="What are your main health goals right now?",
        help_text="Examples: lower blood pressure, lose weight, improve energy.",
    ),
    "family_history": IntakeFieldSpec(
        field_id="family_history",
        label="Family History",
        question="Any relevant family health history?",
        help_text="Examples: heart disease, diabetes, stroke. You can also say `none`.",
    ),
}


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed
    except json.JSONDecodeError:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _split_list_text(text: str) -> list[str]:
    normalized = text.replace("\r", "\n").strip()
    if not normalized:
        return []
    split_on = r"(?:\n|;)|,(?=\s*[A-Za-z])"
    raw = re.split(split_on, normalized)
    out: list[str] = []
    for item in raw:
        clean = " ".join(item.split()).strip(" ,.-")
        if clean:
            out.append(clean)
    return out


def _is_none_response(text: str) -> bool:
    t = " ".join(text.lower().split())
    none_values = {
        "none",
        "no",
        "n/a",
        "na",
        "none currently",
        "none right now",
        "no medications",
        "no meds",
        "no supplements",
        "not taking any",
    }
    return t in none_values


def _dedupe_case_insensitive(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _extract_number(text: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_height_cm(answer: str) -> tuple[float | None, str | None]:
    t = answer.lower().strip()
    ft_in = re.search(r"(\d{1,2})\s*(?:ft|feet|')\s*(\d{1,2})?\s*(?:in|inches|\")?", t)
    if ft_in:
        feet = float(ft_in.group(1))
        inches = float(ft_in.group(2) or "0")
        cm = (feet * 12.0 + inches) * 2.54
        if 90 <= cm <= 260:
            return round(cm, 2), None
        return None, "Height looks out of range."

    num = _extract_number(t)
    if num is None:
        return None, "Could not read a height value."

    if "cm" in t or num > 10:
        cm = num
    elif "in" in t or "inch" in t:
        cm = num * 2.54
    else:
        cm = num * 30.48

    if not (90 <= cm <= 260):
        return None, "Height looks out of range."
    return round(cm, 2), None


def _parse_weight_kg(answer: str, preferred_unit: str | None) -> tuple[float | None, str | None]:
    t = answer.lower().strip()
    value = _extract_number(t)
    if value is None:
        return None, "Could not read a weight value."

    has_lb = any(x in t for x in ("lb", "lbs", "pound"))
    has_kg = "kg" in t
    unit = "lb" if has_lb else "kg"
    if not has_lb and not has_kg and preferred_unit == "lb":
        unit = "lb"

    kg = lb_to_kg(value) if unit == "lb" else value
    if not (25 <= kg <= 400):
        return None, "Weight looks out of range."
    return round(kg, 2), None


def _parse_timezone(answer: str) -> tuple[str | None, str | None]:
    candidate = answer.strip()
    if not candidate:
        return None, "Timezone cannot be empty."

    key = candidate.lower()
    if key in TIMEZONE_ALIASES:
        candidate = TIMEZONE_ALIASES[key]

    try:
        ZoneInfo(candidate)
        return candidate, None
    except ZoneInfoNotFoundError:
        pass

    if "/" not in candidate and " " in candidate:
        alt = candidate.replace(" ", "_")
        try:
            ZoneInfo(alt)
            return alt, None
        except ZoneInfoNotFoundError:
            pass

    return None, "Use a timezone like `America/Edmonton`."


def _parse_sex(answer: str) -> tuple[str | None, str | None]:
    key = " ".join(answer.lower().split())
    value = SEX_MAP.get(key)
    if value:
        return value, None
    return None, "Choose `male`, `female`, or `other`."


def _parse_fitness_level(answer: str) -> tuple[str | None, str | None]:
    text = " ".join(answer.lower().split())
    if text in FITNESS_LEVELS:
        return text, None
    for canonical, variants in FITNESS_LEVELS.items():
        if text in variants:
            return canonical, None
    return None, "Choose sedentary, lightly active, moderately active, very active, or extremely active."


def _parse_string_list(answer: str) -> tuple[list[str] | None, str | None]:
    if _is_none_response(answer):
        return None, None
    items = _dedupe_case_insensitive(_split_list_text(answer))
    if not items:
        return None, "Please provide at least one item, or type `none`."
    return items, None


def _extract_timing(text: str) -> tuple[str, str]:
    lower = text.lower()
    for pattern, canonical in TIMING_PATTERNS:
        if pattern in lower:
            cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" ,.-")
            return cleaned, canonical
    return text, ""


def _parse_structured_items(answer: str) -> tuple[list[dict[str, str]] | None, str | None]:
    if _is_none_response(answer):
        return None, None

    chunks = _split_list_text(answer)
    if not chunks:
        chunks = [answer.strip()]

    items: list[dict[str, str]] = []
    for chunk in chunks:
        if not chunk:
            continue
        cleaned_name, timing = _extract_timing(chunk)
        structured = to_structured(cleaned_name)
        name = str(structured.get("name", "")).strip()
        if not name:
            continue
        dose = str(structured.get("dose", "")).strip()
        row = {"name": name, "dose": dose, "timing": timing}
        items.append(row)

    if not items:
        return None, "Could not parse this list. Try `Name dose, Name dose`."
    return items, None


def field_has_value(settings: UserSettings, field_id: str) -> bool:
    value = getattr(settings, field_id, None)
    if field_id in STRUCTURED_FIELDS:
        return len(parse_structured_list(value)) > 0
    if field_id in LIST_FIELDS:
        parsed = _json_load(value, None)
        if isinstance(parsed, list):
            return len(parsed) > 0
        if isinstance(value, str):
            return any(part.strip() for part in value.split(","))
        return False
    return value is not None and str(value).strip() != ""


def compute_profile_completeness(settings: UserSettings) -> dict[str, Any]:
    completed: list[str] = []
    missing: list[str] = []
    required_missing: list[str] = []
    for field_id in INTAKE_FIELD_ORDER:
        if field_has_value(settings, field_id):
            completed.append(field_id)
        else:
            missing.append(field_id)
            if field_id in REQUIRED_INTAKE_FIELDS:
                required_missing.append(field_id)

    total = len(INTAKE_FIELD_ORDER)
    percent = round((len(completed) / total) * 100) if total else 100
    return {
        "completed_fields": completed,
        "missing_fields": missing,
        "required_missing_fields": required_missing,
        "percent": percent,
        "is_complete": len(required_missing) == 0,
    }


def _answers_map(session: IntakeSession) -> dict[str, Any]:
    parsed = _json_load(session.answers, {})
    return parsed if isinstance(parsed, dict) else {}


def _draft_patch(session: IntakeSession) -> dict[str, Any]:
    parsed = _json_load(session.draft_patch, {})
    return parsed if isinstance(parsed, dict) else {}


def _skipped_fields(session: IntakeSession) -> list[str]:
    parsed = _json_load(session.skipped_fields, [])
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return []


def _field_order(session: IntakeSession) -> list[str]:
    parsed = _json_load(session.field_order, [])
    if isinstance(parsed, list):
        return [str(x) for x in parsed if str(x) in FIELD_SPECS]
    return list(INTAKE_FIELD_ORDER)


def _next_unfilled_index(
    settings: UserSettings,
    order: list[str],
    patch: dict[str, Any],
    skipped: set[str],
    start_index: int = 0,
) -> int:
    idx = max(start_index, 0)
    while idx < len(order):
        field_id = order[idx]
        if field_id in skipped:
            idx += 1
            continue
        if field_id in patch:
            idx += 1
            continue
        if field_has_value(settings, field_id):
            idx += 1
            continue
        return idx
    return idx


def ensure_active_session(db: Session, settings: UserSettings, restart: bool = False) -> IntakeSession:
    active = (
        db.query(IntakeSession)
        .filter(IntakeSession.user_id == settings.user_id, IntakeSession.status == "active")
        .order_by(IntakeSession.updated_at.desc())
        .first()
    )

    if active and not restart:
        return active

    now = datetime.now(timezone.utc)
    if active and restart:
        active.status = "skipped"
        active.finished_at = now
        settings.intake_skipped_at = now

    row = IntakeSession(
        user_id=settings.user_id,
        status="active",
        current_index=0,
        field_order=_json_dump(INTAKE_FIELD_ORDER),
        answers=_json_dump({}),
        draft_patch=_json_dump({}),
        skipped_fields=_json_dump([]),
    )
    db.add(row)
    db.flush()
    return row


def get_active_session(db: Session, user_id: int) -> IntakeSession | None:
    return (
        db.query(IntakeSession)
        .filter(IntakeSession.user_id == user_id, IntakeSession.status == "active")
        .order_by(IntakeSession.updated_at.desc())
        .first()
    )


def get_latest_session(db: Session, user_id: int) -> IntakeSession | None:
    return (
        db.query(IntakeSession)
        .filter(IntakeSession.user_id == user_id)
        .order_by(IntakeSession.updated_at.desc())
        .first()
    )


def get_current_field(session: IntakeSession, settings: UserSettings) -> IntakeFieldSpec | None:
    if session.status != "active":
        return None
    order = _field_order(session)
    patch = _draft_patch(session)
    skipped = set(_skipped_fields(session))
    idx = _next_unfilled_index(settings, order, patch, skipped, session.current_index)
    session.current_index = idx
    if idx >= len(order):
        return None
    return FIELD_SPECS[order[idx]]


def skip_current_field(session: IntakeSession, settings: UserSettings) -> IntakeFieldSpec | None:
    current = get_current_field(session, settings)
    if not current:
        return None
    skipped = _skipped_fields(session)
    if current.field_id not in skipped:
        skipped.append(current.field_id)
        session.skipped_fields = _json_dump(skipped)
    session.current_index += 1
    return get_current_field(session, settings)


def parse_answer(field_id: str, answer: str, settings: UserSettings) -> tuple[Any, str | None]:
    if field_id == "age":
        num = _extract_number(answer)
        if num is None:
            return None, "Please provide your age in years."
        age = int(round(num))
        if age < 1 or age > 120:
            return None, "Age must be between 1 and 120."
        return age, None

    if field_id == "sex":
        return _parse_sex(answer)

    if field_id == "height_cm":
        return _parse_height_cm(answer)

    if field_id in {"current_weight_kg", "goal_weight_kg"}:
        return _parse_weight_kg(answer, settings.weight_unit)

    if field_id == "timezone":
        return _parse_timezone(answer)

    if field_id == "fitness_level":
        return _parse_fitness_level(answer)

    if field_id in LIST_FIELDS:
        return _parse_string_list(answer)

    if field_id in STRUCTURED_FIELDS:
        return _parse_structured_items(answer)

    return None, "Unknown intake field."


def apply_answer_to_session(
    session: IntakeSession,
    settings: UserSettings,
    answer: str,
    field_id: str | None = None,
) -> tuple[IntakeFieldSpec | None, str | None]:
    current = get_current_field(session, settings)
    if not current:
        return None, "No pending intake question."

    target_field = field_id or current.field_id
    if target_field != current.field_id:
        return current, f"Expected answer for `{current.field_id}`."

    parsed_value, err = parse_answer(target_field, answer, settings)
    if err:
        return current, err

    answers = _answers_map(session)
    patch = _draft_patch(session)

    answers[target_field] = {"raw": answer, "parsed": parsed_value}
    patch[target_field] = parsed_value
    session.answers = _json_dump(answers)
    session.draft_patch = _json_dump(patch)
    session.current_index += 1

    return get_current_field(session, settings), None


def skip_session(session: IntakeSession, settings: UserSettings) -> None:
    now = datetime.now(timezone.utc)
    session.status = "skipped"
    session.finished_at = now
    settings.intake_skipped_at = now


def _apply_patch_to_settings(settings: UserSettings, patch: dict[str, Any]) -> None:
    for field_id, value in patch.items():
        if field_id in STRUCTURED_FIELDS:
            if value is None:
                setattr(settings, field_id, None)
                continue
            raw_items = [to_structured(item) for item in value if item]
            merged = merge_structured_items(getattr(settings, field_id), raw_items)
            setattr(settings, field_id, cleanup_structured_list(merged))
            continue

        if field_id in LIST_FIELDS:
            if value is None:
                setattr(settings, field_id, None)
            else:
                as_list = [str(v).strip() for v in value if str(v).strip()]
                setattr(settings, field_id, _json_dump(as_list) if as_list else None)
            continue

        setattr(settings, field_id, value)


def finalize_session(session: IntakeSession, settings: UserSettings, db: Session | None = None) -> dict[str, Any]:
    patch = _draft_patch(session)
    _apply_patch_to_settings(settings, patch)

    now = datetime.now(timezone.utc)
    session.status = "completed"
    session.finished_at = now
    settings.intake_completed_at = now
    settings.intake_skipped_at = None

    if db is not None and settings.user is not None:
        sync_frameworks_from_settings(db, settings.user, source="intake", commit=False)

    return patch


def session_state(session: IntakeSession, settings: UserSettings) -> dict[str, Any]:
    current = get_current_field(session, settings)
    order = _field_order(session)
    skipped = _skipped_fields(session)
    patch = _draft_patch(session)
    completeness = compute_profile_completeness(settings)

    patch_preview = dict(patch)
    if "medications" in patch_preview and patch_preview["medications"] is None:
        patch_preview["medications"] = []
    if "supplements" in patch_preview and patch_preview["supplements"] is None:
        patch_preview["supplements"] = []

    completed_count = 0
    for field_id in order:
        if field_id in skipped:
            completed_count += 1
            continue
        if field_id in patch:
            completed_count += 1
            continue
        if field_has_value(settings, field_id):
            completed_count += 1

    return {
        "session_id": session.id,
        "status": session.status,
        "progress_completed": completed_count,
        "progress_total": len(order),
        "current_field_id": current.field_id if current else None,
        "current_question": current.question if current else None,
        "current_help_text": current.help_text if current else None,
        "current_options": list(current.options) if current else [],
        "draft_profile_patch": patch_preview,
        "skipped_fields": skipped,
        "answers": _answers_map(session),
        "profile_completeness": completeness,
        "ready_to_finish": current is None,
    }
