from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import (
    User, FoodLog, HydrationLog, VitalsLog, ExerciseLog,
    SupplementLog, FastingLog, SleepLog,
)
from utils.datetime_utils import start_of_day, end_of_day, today_utc

router = APIRouter(prefix="/logs", tags=["logs"])


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


# --- Food Logs ---

@router.get("/food")
def get_food_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, FoodLog, user.id, target_date)
    fields = ["logged_at", "meal_label", "items", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/food")
def create_food_log(data: FoodLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = FoodLog(user_id=user.id, logged_at=datetime.now(timezone.utc), **data.model_dump())
    db.add(log)
    db.commit()
    return {"id": log.id, "status": "created"}


# --- Vitals Logs ---

@router.get("/vitals")
def get_vitals_logs(
    target_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = get_logs_for_date(db, VitalsLog, user.id, target_date)
    fields = ["logged_at", "weight_kg", "bp_systolic", "bp_diastolic", "heart_rate", "blood_glucose", "temperature_c", "spo2", "notes"]
    return [serialize_log(l, fields) for l in logs]


@router.post("/vitals")
def create_vitals_log(data: VitalsLogCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = VitalsLog(user_id=user.id, logged_at=datetime.now(timezone.utc), **data.model_dump())
    db.add(log)
    db.commit()

    # Update current weight in user settings if weight was logged
    if data.weight_kg and user.settings:
        user.settings.current_weight_kg = data.weight_kg
        db.commit()

    return {"id": log.id, "status": "created"}


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
    log = ExerciseLog(user_id=user.id, logged_at=datetime.now(timezone.utc), **data.model_dump())
    db.add(log)
    db.commit()
    return {"id": log.id, "status": "created"}


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
    log = HydrationLog(user_id=user.id, logged_at=datetime.now(timezone.utc), **data.model_dump())
    db.add(log)
    db.commit()
    return {"id": log.id, "status": "created"}


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
    log = SupplementLog(user_id=user.id, logged_at=datetime.now(timezone.utc), **data.model_dump())
    db.add(log)
    db.commit()
    return {"id": log.id, "status": "created"}


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
    now = datetime.now(timezone.utc)
    if data.action == "start":
        log = FastingLog(user_id=user.id, fast_start=now, fast_type=data.fast_type, notes=data.notes)
        db.add(log)
        db.commit()
        return {"id": log.id, "status": "started", "fast_start": now.isoformat()}
    elif data.action == "end":
        active = (
            db.query(FastingLog)
            .filter(FastingLog.user_id == user.id, FastingLog.fast_end.is_(None))
            .order_by(FastingLog.fast_start.desc())
            .first()
        )
        if not active:
            return {"status": "no_active_fast"}
        active.fast_end = now
        fast_start = active.fast_start if active.fast_start.tzinfo else active.fast_start.replace(tzinfo=timezone.utc)
        active.duration_minutes = int((now - fast_start).total_seconds() / 60)
        db.commit()
        return {"id": active.id, "status": "ended", "duration_minutes": active.duration_minutes}
    return {"status": "invalid_action"}


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
    log = SleepLog(user_id=user.id, duration_minutes=data.duration_minutes, quality=data.quality, notes=data.notes)
    db.add(log)
    db.commit()
    return {"id": log.id, "status": "created"}


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
