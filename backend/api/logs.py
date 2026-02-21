from datetime import date, datetime, timezone
from typing import Optional
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import (
    User, FoodLog, HydrationLog, VitalsLog, ExerciseLog,
    SupplementLog, FastingLog, SleepLog, ExercisePlan, DailyChecklistItem,
)
from ai.context_builder import build_context
from ai.providers import get_provider
from ai.usage_tracker import track_usage_from_result
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError
from utils.encryption import decrypt_api_key
from utils.datetime_utils import start_of_day, end_of_day, today_utc
from utils.med_utils import parse_structured_list, structured_to_display

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(require_non_admin)])

DOSE_TOKEN_RE = re.compile(r"^\d[\d,.\s]*(mcg|mg|g|kg|iu|ml|units?|tabs?|caps?)\b", re.IGNORECASE)


# --- Pydantic Schemas ---

class FoodLogCreate(BaseModel):
    meal_label: Optional[str] = None
    items: str  # JSON string
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    notes: Optional[str] = None


class VitalsLogCreate(BaseModel):
    weight_kg: Optional[float] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    heart_rate: Optional[int] = None
    blood_glucose: Optional[float] = None
    temperature_c: Optional[float] = None
    spo2: Optional[float] = None
    notes: Optional[str] = None


class ExerciseLogCreate(BaseModel):
    exercise_type: str
    duration_minutes: Optional[int] = None
    details: Optional[str] = None  # JSON string
    max_hr: Optional[int] = None
    avg_hr: Optional[int] = None
    calories_burned: Optional[float] = None
    notes: Optional[str] = None


class HydrationLogCreate(BaseModel):
    amount_ml: float
    source: Optional[str] = "water"
    notes: Optional[str] = None


class SupplementLogCreate(BaseModel):
    supplements: str  # JSON string
    timing: Optional[str] = None
    notes: Optional[str] = None


class FastingLogCreate(BaseModel):
    action: str  # "start" or "end"
    fast_type: Optional[str] = None
    notes: Optional[str] = None


class SleepLogCreate(BaseModel):
    sleep_start: Optional[str] = None
    sleep_end: Optional[str] = None
    duration_minutes: Optional[int] = None
    quality: Optional[str] = None
    notes: Optional[str] = None


class ExercisePlanResponse(BaseModel):
    target_date: str
    plan_type: str
    title: str
    description: Optional[str] = None
    target_minutes: Optional[int] = None
    completed: bool
    status: str
    completed_minutes: int
    matching_sessions: int


class ChecklistItem(BaseModel):
    name: str
    dose: str = ""
    timing: str = ""
    completed: bool


class DailyChecklistResponse(BaseModel):
    target_date: str
    medications: list[ChecklistItem]
    supplements: list[ChecklistItem]


class ChecklistToggleRequest(BaseModel):
    target_date: Optional[str] = None
    item_type: str  # medication | supplement
    item_name: str
    completed: bool


# --- Helper ---

def get_logs_for_date(db, model, user_id, target_date, date_field="logged_at"):
    d = target_date or today_utc()
    field = getattr(model, date_field)
    return (
        db.query(model)
        .filter(model.user_id == user_id, field >= start_of_day(d), field <= end_of_day(d))
        .order_by(field)
        .all()
    )


def serialize_log(log, fields):
    result = {"id": log.id}
    for f in fields:
        val = getattr(log, f, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[f] = val
    return result


VALID_PLAN_TYPES = {"rest_day", "hiit", "strength", "zone2", "mobility", "mixed"}
PLAN_MATCH_TYPES = {
    "rest_day": set(),
    "hiit": {"hiit"},
    "strength": {"strength"},
    "zone2": {"zone2_cardio", "walk", "run", "cycling", "swimming"},
    "mobility": {"mobility", "yoga"},
    "mixed": {"zone2_cardio", "walk", "run", "cycling", "swimming", "hiit", "strength", "mobility", "yoga"},
}


def compute_plan_status(
    plan_type: str,
    target_minutes: Optional[int],
    exercise_logs: list[ExerciseLog],
    target_date: date,
) -> tuple[bool, str, int, int]:
    completed_minutes = sum(l.duration_minutes or 0 for l in exercise_logs)
    match_types = PLAN_MATCH_TYPES.get(plan_type, PLAN_MATCH_TYPES["mixed"])
    matching = [l for l in exercise_logs if l.exercise_type in match_types] if match_types else []
    matching_sessions = len(matching)
    today = today_utc()

    if plan_type == "rest_day":
        if completed_minutes == 0:
            return (target_date < today, "on_track" if target_date >= today else "completed", completed_minutes, 0)
        return (False, "off_plan", completed_minutes, 0)

    needed_minutes = target_minutes or 20
    matched_minutes = sum(l.duration_minutes or 0 for l in matching)
    done = matching_sessions > 0 and matched_minutes >= needed_minutes
    if done:
        return (True, "completed", completed_minutes, matching_sessions)
    if target_date < today:
        return (False, "missed", completed_minutes, matching_sessions)
    return (False, "pending", completed_minutes, matching_sessions)


def parse_plan_json(content: str) -> dict:
    import json

    text = content.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    plan_type = str(parsed.get("plan_type", "mixed")).strip().lower()
    if plan_type not in VALID_PLAN_TYPES:
        plan_type = "mixed"
    title = str(parsed.get("title", "Today's Exercise Plan")).strip() or "Today's Exercise Plan"
    description = str(parsed.get("description", "")).strip()
    target_minutes = parsed.get("target_minutes")
    try:
        target_minutes = int(target_minutes) if target_minutes is not None else None
    except (ValueError, TypeError):
        target_minutes = None
    return {
        "plan_type": plan_type,
        "title": title,
        "description": description,
        "target_minutes": target_minutes,
    }


def parse_tag_list(raw: Optional[str]) -> list[str]:
    def normalize(items: list[str]) -> list[str]:
        merged: list[str] = []
        for raw_item in items:
            item = " ".join(raw_item.split()).strip()
            if not item:
                continue
            if merged and DOSE_TOKEN_RE.match(item):
                merged[-1] = f"{merged[-1]} {item}".strip()
                continue
            merged.append(item)
        return merged

    if not raw:
        return []
    txt = raw.strip()
    if not txt:
        return []
    if txt.startswith("["):
        try:
            import json

            arr = json.loads(txt)
            if isinstance(arr, list):
                parsed = []
                for v in arr:
                    if isinstance(v, str):
                        parsed.append(v.strip())
                    elif isinstance(v, dict):
                        name = str(v.get("name", "")).strip()
                        if name:
                            parsed.append(name)
                return normalize([x for x in parsed if x])
        except Exception:
            pass
    return normalize([x.strip() for x in txt.split(",") if x.strip()])


# --- Food Logs ---

@router.get("/food")
def get_food_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, FoodLog, user.id, target_date)
    fields = [
        "logged_at",
        "meal_label",
        "meal_template_id",
        "items",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "fiber_g",
        "sodium_mg",
        "notes",
    ]
    return [serialize_log(l, fields) for l in logs]


@router.post("/food")
def create_food_log(data: FoodLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "food_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("food_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Vitals Logs ---

@router.get("/vitals")
def get_vitals_logs(
    target_date: Optional[date] = None,
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if date_from or date_to:
        start_date = date_from or date_to or today_utc()
        end_date = date_to or date_from or today_utc()
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        logs = (
            db.query(VitalsLog)
            .filter(
                VitalsLog.user_id == user.id,
                VitalsLog.logged_at >= start_of_day(start_date),
                VitalsLog.logged_at <= end_of_day(end_date),
            )
            .order_by(VitalsLog.logged_at)
            .all()
        )
    else:
        logs = get_logs_for_date(db, VitalsLog, user.id, target_date)
    fields = ["logged_at", "weight_kg", "bp_systolic", "bp_diastolic", "heart_rate", "blood_glucose", "temperature_c", "spo2", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/vitals")
def create_vitals_log(data: VitalsLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "vitals_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("vitals_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Exercise Logs ---

@router.get("/exercise")
def get_exercise_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, ExerciseLog, user.id, target_date)
    fields = ["logged_at", "exercise_type", "duration_minutes", "details", "max_hr", "avg_hr", "calories_burned", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/exercise")
def create_exercise_log(data: ExerciseLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "exercise_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("exercise_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/exercise-plan", response_model=ExercisePlanResponse)
def get_exercise_plan(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = target_date or today_utc()
    d_iso = d.isoformat()
    plan = (
        db.query(ExercisePlan)
        .filter(ExercisePlan.user_id == user.id, ExercisePlan.target_date == d_iso)
        .order_by(ExercisePlan.updated_at.desc())
        .first()
    )
    if not plan:
        return ExercisePlanResponse(
            target_date=d_iso,
            plan_type="mixed",
            title="No plan generated yet",
            description="Generate your AI daily summary to create today's exercise plan.",
            target_minutes=None,
            completed=False,
            status="not_set",
            completed_minutes=0,
            matching_sessions=0,
        )

    exercise_logs = get_logs_for_date(db, ExerciseLog, user.id, d)
    completed, status, completed_minutes, matching_sessions = compute_plan_status(
        plan.plan_type,
        plan.target_minutes,
        exercise_logs,
        d,
    )
    return ExercisePlanResponse(
        target_date=plan.target_date,
        plan_type=plan.plan_type,
        title=plan.title,
        description=plan.description,
        target_minutes=plan.target_minutes,
        completed=completed,
        status=status,
        completed_minutes=completed_minutes,
        matching_sessions=matching_sessions,
    )


@router.post("/exercise-plan/generate", response_model=ExercisePlanResponse)
async def generate_exercise_plan(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    if not settings or not settings.api_key_encrypted:
        raise HTTPException(status_code=400, detail="Please configure your API key in Settings before generating a plan.")

    d = target_date or today_utc()
    d_iso = d.isoformat()
    api_key = decrypt_api_key(settings.api_key_encrypted)
    provider = get_provider(
        settings.ai_provider,
        api_key,
        reasoning_model=settings.reasoning_model,
        utility_model=settings.utility_model,
        deep_thinking_model=getattr(settings, "deep_thinking_model", None),
    )
    system = build_context(db, user, "movement_coach")
    user_prompt = (
        "Create a practical exercise plan for this date based on user context.\n"
        f"Date: {d_iso}\n\n"
        "Return ONLY JSON with keys:\n"
        "{\n"
        '  "plan_type": "rest_day|hiit|strength|zone2|mobility|mixed",\n'
        '  "title": "short title",\n'
        '  "description": "one short paragraph",\n'
        '  "target_minutes": integer or null\n'
        "}\n"
    )
    result = await provider.chat(
        messages=[{"role": "user", "content": user_prompt}],
        model=provider.get_utility_model(),
        system=system,
        stream=False,
    )
    track_usage_from_result(
        db=db,
        user_id=user.id,
        result=result,
        model_used=provider.get_utility_model(),
        operation="exercise_plan_generate",
        usage_type="utility",
    )
    parsed = parse_plan_json(result["content"])

    try:
        tool_registry.execute(
            "exercise_plan_upsert",
            {
                "target_date": d_iso,
                "plan_type": parsed["plan_type"],
                "title": parsed["title"],
                "description": parsed["description"],
                "target_minutes": parsed["target_minutes"],
                "source": "ai",
            },
            ToolContext(db=db, user=user, specialist_id="movement_coach"),
        )
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    plan = (
        db.query(ExercisePlan)
        .filter(ExercisePlan.user_id == user.id, ExercisePlan.target_date == d_iso)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=500, detail="Failed to persist exercise plan")

    exercise_logs = get_logs_for_date(db, ExerciseLog, user.id, d)
    completed, status, completed_minutes, matching_sessions = compute_plan_status(
        plan.plan_type,
        plan.target_minutes,
        exercise_logs,
        d,
    )
    return ExercisePlanResponse(
        target_date=plan.target_date,
        plan_type=plan.plan_type,
        title=plan.title,
        description=plan.description,
        target_minutes=plan.target_minutes,
        completed=completed,
        status=status,
        completed_minutes=completed_minutes,
        matching_sessions=matching_sessions,
    )


@router.get("/checklist", response_model=DailyChecklistResponse)
def get_daily_checklist(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = target_date or today_utc()
    d_iso = d.isoformat()
    med_structured = parse_structured_list(user.settings.medications if user.settings else None)
    supp_structured = parse_structured_list(user.settings.supplements if user.settings else None)

    states = (
        db.query(DailyChecklistItem)
        .filter(DailyChecklistItem.user_id == user.id, DailyChecklistItem.target_date == d_iso)
        .all()
    )
    by_key = {(s.item_type, s.item_name.strip().lower()): bool(s.completed) for s in states}

    med_items = [
        ChecklistItem(
            name=item.get("name", ""),
            dose=item.get("dose", ""),
            timing=item.get("timing", ""),
            completed=by_key.get(("medication", item.get("name", "").lower()), False),
        )
        for item in med_structured if item.get("name")
    ]
    supp_items = [
        ChecklistItem(
            name=item.get("name", ""),
            dose=item.get("dose", ""),
            timing=item.get("timing", ""),
            completed=by_key.get(("supplement", item.get("name", "").lower()), False),
        )
        for item in supp_structured if item.get("name")
    ]
    return DailyChecklistResponse(target_date=d_iso, medications=med_items, supplements=supp_items)


@router.put("/checklist")
def toggle_daily_checklist(
    req: ChecklistToggleRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item_type = req.item_type.strip().lower()
    if item_type not in {"medication", "supplement"}:
        raise HTTPException(status_code=400, detail="item_type must be medication or supplement")
    name = req.item_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="item_name is required")
    d_iso = req.target_date or today_utc().isoformat()

    try:
        tool_registry.execute(
            "checklist_mark_taken",
            {
                "item_type": item_type,
                "target_date": d_iso,
                "names": [name],
                "completed": req.completed,
            },
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"status": "ok"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Hydration Logs ---

@router.get("/hydration")
def get_hydration_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, HydrationLog, user.id, target_date)
    fields = ["logged_at", "amount_ml", "source", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/hydration")
def create_hydration_log(data: HydrationLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "hydration_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("hydration_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Supplement Logs ---

@router.get("/supplements")
def get_supplement_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, SupplementLog, user.id, target_date)
    fields = ["logged_at", "supplements", "timing", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/supplements")
def create_supplement_log(data: SupplementLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "supplement_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("supplement_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Fasting Logs ---

@router.get("/fasting")
def get_fasting_logs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = (
        db.query(FastingLog)
        .filter(FastingLog.user_id == user.id)
        .order_by(FastingLog.fast_start.desc())
        .limit(10)
        .all()
    )
    fields = ["fast_start", "fast_end", "duration_minutes", "fast_type", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.get("/fasting/active")
def get_active_fast(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    active = (
        db.query(FastingLog)
        .filter(FastingLog.user_id == user.id, FastingLog.fast_end.is_(None))
        .order_by(FastingLog.fast_start.desc())
        .first()
    )
    if not active:
        return {"active": False}

    fast_start = active.fast_start if active.fast_start.tzinfo else active.fast_start.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - fast_start).total_seconds() / 60
    return {
        "active": True,
        "id": active.id,
        "fast_start": active.fast_start.isoformat(),
        "elapsed_minutes": int(elapsed),
        "fast_type": active.fast_type,
    }


@router.post("/fasting")
def manage_fasting(data: FastingLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "fasting_manage",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        if out.get("status") == "started":
            return {
                "id": out.get("fasting_log_id"),
                "status": "started",
                "fast_start": out.get("fast_start"),
            }
        if out.get("status") == "ended":
            return {
                "id": out.get("fasting_log_id"),
                "status": "ended",
                "duration_minutes": out.get("duration_minutes"),
            }
        return out
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Sleep Logs ---

@router.get("/sleep")
def get_sleep_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if target_date:
        logs = (
            db.query(SleepLog)
            .filter(SleepLog.user_id == user.id)
            .order_by(SleepLog.created_at.desc())
            .limit(7)
            .all()
        )
    else:
        logs = (
            db.query(SleepLog)
            .filter(SleepLog.user_id == user.id)
            .order_by(SleepLog.created_at.desc())
            .limit(7)
            .all()
        )
    fields = ["sleep_start", "sleep_end", "duration_minutes", "quality", "notes", "created_at"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/sleep")
def create_sleep_log(data: SleepLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        out = tool_registry.execute(
            "sleep_log_write",
            data.model_dump(),
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return {"id": out.get("sleep_log_id"), "status": "created"}
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Daily Totals ---

@router.get("/daily-totals")
def get_daily_totals(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get aggregated daily totals for food, hydration, exercise."""
    d = target_date or today_utc()
    day_start = start_of_day(d)
    day_end = end_of_day(d)

    # Food totals
    foods = db.query(FoodLog).filter(
        FoodLog.user_id == user.id, FoodLog.logged_at >= day_start, FoodLog.logged_at <= day_end
    ).all()
    food_totals = {
        "calories": sum(f.calories or 0 for f in foods),
        "protein_g": sum(f.protein_g or 0 for f in foods),
        "carbs_g": sum(f.carbs_g or 0 for f in foods),
        "fat_g": sum(f.fat_g or 0 for f in foods),
        "fiber_g": sum(f.fiber_g or 0 for f in foods),
        "sodium_mg": sum(f.sodium_mg or 0 for f in foods),
        "meal_count": len(foods),
    }

    # Hydration total
    hydrations = db.query(HydrationLog).filter(
        HydrationLog.user_id == user.id, HydrationLog.logged_at >= day_start, HydrationLog.logged_at <= day_end
    ).all()
    hydration_total = sum(h.amount_ml for h in hydrations)

    # Exercise total
    exercises = db.query(ExerciseLog).filter(
        ExerciseLog.user_id == user.id, ExerciseLog.logged_at >= day_start, ExerciseLog.logged_at <= day_end
    ).all()
    exercise_minutes = sum(e.duration_minutes or 0 for e in exercises)
    exercise_calories = sum(e.calories_burned or 0 for e in exercises)

    return {
        "date": d.isoformat(),
        "food": food_totals,
        "hydration_ml": hydration_total,
        "exercise_minutes": exercise_minutes,
        "exercise_calories_burned": exercise_calories,
    }
