import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from auth.utils import hash_password, verify_password
from config import settings as app_settings
from db.database import get_db
from db.models import (
    User,
    UserSettings,
    SpecialistConfig,
    Message,
    ModelUsageEvent,
    FoodLog,
    HydrationLog,
    VitalsLog,
    ExerciseLog,
    ExercisePlan,
    DailyChecklistItem,
    SupplementLog,
    FastingLog,
    SleepLog,
    Summary,
    MealTemplate,
    Notification,
    IntakeSession,
    FeedbackEntry,
)
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError
from utils.encryption import encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)
ALLOWED_HEIGHT_UNITS = {"cm", "ft"}
ALLOWED_WEIGHT_UNITS = {"kg", "lb"}
ALLOWED_HYDRATION_UNITS = {"ml", "oz"}


class APIKeyRequest(BaseModel):
    ai_provider: str  # 'anthropic' | 'openai' | 'google'
    api_key: str
    reasoning_model: Optional[str] = None
    utility_model: Optional[str] = None


class APIKeyStatusResponse(BaseModel):
    ai_provider: str
    has_api_key: bool
    reasoning_model: str
    utility_model: str


class ProfileUpdate(BaseModel):
    age: Optional[int] = None
    sex: Optional[str] = None
    height_cm: Optional[float] = None
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None
    height_unit: Optional[str] = None
    weight_unit: Optional[str] = None
    hydration_unit: Optional[str] = None
    medical_conditions: Optional[str] = None
    medications: Optional[str] = None
    supplements: Optional[str] = None
    family_history: Optional[str] = None
    fitness_level: Optional[str] = None
    dietary_preferences: Optional[str] = None
    health_goals: Optional[str] = None
    timezone: Optional[str] = None


class ProfileResponse(BaseModel):
    ai_provider: str
    has_api_key: bool
    reasoning_model: str
    utility_model: str
    age: Optional[int] = None
    sex: Optional[str] = None
    height_cm: Optional[float] = None
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None
    height_unit: str
    weight_unit: str
    hydration_unit: str
    medical_conditions: Optional[str] = None
    medications: Optional[str] = None
    supplements: Optional[str] = None
    family_history: Optional[str] = None
    fitness_level: Optional[str] = None
    dietary_preferences: Optional[str] = None
    health_goals: Optional[str] = None
    timezone: Optional[str] = None


# Default models per provider
_MODELS_FILE = Path(__file__).parent.parent / "data" / "models.json"

_FALLBACK_DEFAULTS = {
    "anthropic": {"reasoning": "claude-sonnet-4-20250514", "utility": "claude-haiku-4-5-20251001"},
    "openai": {"reasoning": "gpt-4o", "utility": "gpt-4o-mini"},
    "google": {"reasoning": "gemini-2.5-pro", "utility": "gemini-2.0-flash"},
}

_FALLBACK_AVAILABLE = {
    "anthropic": {
        "reasoning": [{"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"}],
        "utility": [{"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"}],
    },
    "openai": {
        "reasoning": [{"id": "gpt-4o", "name": "GPT-4o"}],
        "utility": [{"id": "gpt-4o-mini", "name": "GPT-4o Mini"}],
    },
    "google": {
        "reasoning": [{"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"}],
        "utility": [{"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"}],
    },
}


def _load_models() -> tuple[dict, dict]:
    """Load model config from data/models.json, falling back to built-in defaults."""
    try:
        data = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        return data.get("defaults", _FALLBACK_DEFAULTS), data.get("available", _FALLBACK_AVAILABLE)
    except Exception:
        return _FALLBACK_DEFAULTS, _FALLBACK_AVAILABLE


def _get_default_models() -> dict:
    return _load_models()[0]


def _get_available_models() -> dict:
    return _load_models()[1]


def _get_pricing() -> dict:
    """Load per-model pricing from data/models.json."""
    try:
        data = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        return data.get("pricing", {})
    except Exception:
        return {}


def _available_model_ids(provider: str) -> tuple[set[str], set[str]]:
    available = _get_available_models()
    provider_models = available.get(provider, available.get("anthropic", {}))
    reasoning_ids = {str(m.get("id", "")).strip() for m in provider_models.get("reasoning", []) if str(m.get("id", "")).strip()}
    utility_ids = {str(m.get("id", "")).strip() for m in provider_models.get("utility", []) if str(m.get("id", "")).strip()}
    return reasoning_ids, utility_ids


def _normalize_models_for_provider(
    provider: str,
    reasoning_model: str | None,
    utility_model: str | None,
) -> tuple[str, str]:
    defaults = _get_default_models().get(provider, _get_default_models().get("anthropic", _FALLBACK_DEFAULTS["anthropic"]))
    reasoning_ids, utility_ids = _available_model_ids(provider)

    reasoning = (reasoning_model or "").strip()
    utility = (utility_model or "").strip()

    normalized_reasoning = reasoning if reasoning and (not reasoning_ids or reasoning in reasoning_ids) else defaults["reasoning"]
    normalized_utility = utility if utility and (not utility_ids or utility in utility_ids) else defaults["utility"]
    return normalized_reasoning, normalized_utility


def _sync_user_models_for_provider(user_settings: UserSettings) -> bool:
    normalized_reasoning, normalized_utility = _normalize_models_for_provider(
        user_settings.ai_provider,
        user_settings.reasoning_model,
        user_settings.utility_model,
    )
    changed = False
    if user_settings.reasoning_model != normalized_reasoning:
        user_settings.reasoning_model = normalized_reasoning
        changed = True
    if user_settings.utility_model != normalized_utility:
        user_settings.utility_model = normalized_utility
        changed = True
    return changed


def _get_model_name(model_id: str) -> str:
    """Look up a friendly model name from the available models config."""
    available = _get_available_models()
    for provider_models in available.values():
        for role in ("reasoning", "utility"):
            for m in provider_models.get(role, []):
                if m["id"] == model_id:
                    return m["name"]
    return model_id


@router.get("/models")
def get_available_models(provider: str = "anthropic"):
    """Get available models for a given provider."""
    available = _get_available_models()
    default_models = _get_default_models()
    models = available.get(provider, available.get("anthropic", {}))
    defaults = default_models.get(provider, default_models.get("anthropic", {}))
    return {
        "provider": provider,
        "reasoning_models": models["reasoning"],
        "utility_models": models["utility"],
        "default_reasoning": defaults["reasoning"],
        "default_utility": defaults["utility"],
    }


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = user.settings
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    if _sync_user_models_for_provider(s):
        db.commit()
    return ProfileResponse(
        ai_provider=s.ai_provider,
        has_api_key=bool(s.api_key_encrypted),
        reasoning_model=s.reasoning_model,
        utility_model=s.utility_model,
        age=s.age,
        sex=s.sex,
        height_cm=s.height_cm,
        current_weight_kg=s.current_weight_kg,
        goal_weight_kg=s.goal_weight_kg,
        height_unit=s.height_unit or "cm",
        weight_unit=s.weight_unit or "kg",
        hydration_unit=s.hydration_unit or "ml",
        medical_conditions=s.medical_conditions,
        medications=s.medications,
        supplements=s.supplements,
        family_history=s.family_history,
        fitness_level=s.fitness_level,
        dietary_preferences=s.dietary_preferences,
        health_goals=s.health_goals,
        timezone=s.timezone,
    )


class ModelsUpdate(BaseModel):
    reasoning_model: str
    utility_model: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetUserDataRequest(BaseModel):
    current_password: str
    confirmation: str


@router.put("/models")
def update_models(
    update: ModelsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    normalized_reasoning, normalized_utility = _normalize_models_for_provider(
        s.ai_provider,
        update.reasoning_model,
        update.utility_model,
    )
    s.reasoning_model = normalized_reasoning
    s.utility_model = normalized_utility
    db.commit()
    return {"status": "ok", "reasoning_model": normalized_reasoning, "utility_model": normalized_utility}


@router.put("/profile")
def update_profile(
    update: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    payload = update.model_dump(exclude_unset=True)

    if "height_unit" in payload and payload["height_unit"] not in ALLOWED_HEIGHT_UNITS:
        raise HTTPException(status_code=400, detail="Invalid height_unit")
    if "weight_unit" in payload and payload["weight_unit"] not in ALLOWED_WEIGHT_UNITS:
        raise HTTPException(status_code=400, detail="Invalid weight_unit")
    if "hydration_unit" in payload and payload["hydration_unit"] not in ALLOWED_HYDRATION_UNITS:
        raise HTTPException(status_code=400, detail="Invalid hydration_unit")

    tool_ctx = ToolContext(db=db, user=user, specialist_id="orchestrator")
    patch_fields = {
        "age",
        "sex",
        "height_cm",
        "current_weight_kg",
        "goal_weight_kg",
        "height_unit",
        "weight_unit",
        "hydration_unit",
        "medical_conditions",
        "family_history",
        "fitness_level",
        "dietary_preferences",
        "health_goals",
        "timezone",
    }

    patch_payload = {k: v for k, v in payload.items() if k in patch_fields}
    try:
        if patch_payload:
            tool_registry.execute("profile_patch", {"patch": patch_payload}, tool_ctx)

        if "medications" in payload:
            tool_registry.execute("medication_set", {"items": payload.get("medications")}, tool_ctx)

        if "supplements" in payload:
            tool_registry.execute("supplement_set", {"items": payload.get("supplements")}, tool_ctx)
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile update failed: {str(e)}")

    db.commit()
    return {"status": "ok"}


@router.put("/api-key")
def set_api_key(
    req: APIKeyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    s.ai_provider = req.ai_provider
    s.api_key_encrypted = encrypt_api_key(req.api_key)

    normalized_reasoning, normalized_utility = _normalize_models_for_provider(
        req.ai_provider,
        req.reasoning_model,
        req.utility_model,
    )
    s.reasoning_model = normalized_reasoning
    s.utility_model = normalized_utility

    db.commit()
    return {
        "status": "ok",
        "ai_provider": s.ai_provider,
        "reasoning_model": s.reasoning_model,
        "utility_model": s.utility_model,
    }


@router.get("/api-key/status", response_model=APIKeyStatusResponse)
def get_api_key_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = user.settings
    if _sync_user_models_for_provider(s):
        db.commit()
    return APIKeyStatusResponse(
        ai_provider=s.ai_provider,
        has_api_key=bool(s.api_key_encrypted),
        reasoning_model=s.reasoning_model,
        utility_model=s.utility_model,
    )


@router.post("/api-key/validate")
async def validate_api_key(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate the stored API key by making a test API call."""
    s = user.settings
    if not s.api_key_encrypted:
        raise HTTPException(status_code=400, detail="No API key configured")

    api_key = decrypt_api_key(s.api_key_encrypted)

    # Import here to avoid circular imports
    from ai.providers import get_provider
    try:
        if _sync_user_models_for_provider(s):
            db.commit()
        provider = get_provider(
            s.ai_provider,
            api_key,
            reasoning_model=s.reasoning_model,
            utility_model=s.utility_model,
        )
        await provider.validate_key()
        return {"status": "valid", "ai_provider": s.ai_provider}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"API key validation failed: {str(e)}")


@router.get("/usage")
def get_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get per-model token usage and estimated cost since last reset."""
    s = user.settings
    reset_at = s.usage_reset_at if s else None

    assistant_query = db.query(
        Message.model_used,
        func.sum(Message.tokens_in).label("tokens_in"),
        func.sum(Message.tokens_out).label("tokens_out"),
        func.count().label("request_count"),
    ).filter(
        Message.user_id == user.id,
        Message.role == "assistant",
        Message.model_used.isnot(None),
    )
    if reset_at:
        assistant_query = assistant_query.filter(Message.created_at > reset_at)
    assistant_rows = assistant_query.group_by(Message.model_used).all()

    utility_query = db.query(
        ModelUsageEvent.model_used,
        func.sum(ModelUsageEvent.tokens_in).label("tokens_in"),
        func.sum(ModelUsageEvent.tokens_out).label("tokens_out"),
        func.count().label("request_count"),
    ).filter(
        ModelUsageEvent.user_id == user.id,
        ModelUsageEvent.model_used.isnot(None),
    )
    if reset_at:
        utility_query = utility_query.filter(ModelUsageEvent.created_at > reset_at)
    utility_rows = utility_query.group_by(ModelUsageEvent.model_used).all()

    usage_by_model: dict[str, dict[str, int]] = {}

    def _accumulate(rows):
        for row in rows:
            model_id = row.model_used or "unknown"
            rec = usage_by_model.setdefault(
                model_id,
                {"tokens_in": 0, "tokens_out": 0, "request_count": 0},
            )
            rec["tokens_in"] += int(row.tokens_in or 0)
            rec["tokens_out"] += int(row.tokens_out or 0)
            rec["request_count"] += int(row.request_count or 0)

    _accumulate(assistant_rows)
    _accumulate(utility_rows)

    pricing = _get_pricing()
    models = []
    total_cost = 0.0

    for model_id, rec in usage_by_model.items():
        t_in = rec["tokens_in"]
        t_out = rec["tokens_out"]
        price = pricing.get(model_id, {})
        cost_in = t_in * price.get("input_per_mtok", 0) / 1_000_000
        cost_out = t_out * price.get("output_per_mtok", 0) / 1_000_000
        cost = round(cost_in + cost_out, 4)
        total_cost += cost
        models.append({
            "model_id": model_id,
            "model_name": _get_model_name(model_id),
            "tokens_in": t_in,
            "tokens_out": t_out,
            "request_count": rec["request_count"],
            "cost_usd": cost,
        })

    models.sort(key=lambda m: m["cost_usd"], reverse=True)

    return {
        "models": models,
        "total_cost_usd": round(total_cost, 4),
        "reset_at": reset_at.isoformat() if reset_at else None,
    }


@router.post("/usage/reset")
def reset_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset usage counters by setting the reset timestamp to now."""
    s = user.settings
    s.usage_reset_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok", "reset_at": s.usage_reset_at.isoformat()}


@router.post("/password/change")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = (req.current_password or "").strip()
    new_password = req.new_password or ""
    if not current:
        raise HTTPException(status_code=400, detail="Current password is required")
    if not verify_password(current, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    user.password_hash = hash_password(new_password)
    db.commit()
    return {"status": "ok"}


@router.post("/reset-data")
def reset_user_data(
    req: ResetUserDataRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = (req.current_password or "").strip()
    if not current:
        raise HTTPException(status_code=400, detail="Current password is required")
    if not verify_password(current, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if (req.confirmation or "").strip().upper() != "RESET":
        raise HTTPException(status_code=400, detail='Type "RESET" to confirm')

    image_paths = [
        str(row.image_path).strip()
        for row in db.query(Message.image_path)
        .filter(Message.user_id == user.id, Message.image_path.isnot(None))
        .all()
        if str(row.image_path).strip()
    ]

    # Clear user-linked datasets while preserving the user account/password.
    db.query(FoodLog).filter(FoodLog.user_id == user.id).delete(synchronize_session=False)
    db.query(HydrationLog).filter(HydrationLog.user_id == user.id).delete(synchronize_session=False)
    db.query(VitalsLog).filter(VitalsLog.user_id == user.id).delete(synchronize_session=False)
    db.query(ExerciseLog).filter(ExerciseLog.user_id == user.id).delete(synchronize_session=False)
    db.query(ExercisePlan).filter(ExercisePlan.user_id == user.id).delete(synchronize_session=False)
    db.query(DailyChecklistItem).filter(DailyChecklistItem.user_id == user.id).delete(synchronize_session=False)
    db.query(SupplementLog).filter(SupplementLog.user_id == user.id).delete(synchronize_session=False)
    db.query(FastingLog).filter(FastingLog.user_id == user.id).delete(synchronize_session=False)
    db.query(SleepLog).filter(SleepLog.user_id == user.id).delete(synchronize_session=False)
    db.query(Summary).filter(Summary.user_id == user.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.user_id == user.id).delete(synchronize_session=False)
    db.query(MealTemplate).filter(MealTemplate.user_id == user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(IntakeSession).filter(IntakeSession.user_id == user.id).delete(synchronize_session=False)
    db.query(FeedbackEntry).filter(FeedbackEntry.created_by_user_id == user.id).delete(synchronize_session=False)
    db.query(ModelUsageEvent).filter(ModelUsageEvent.user_id == user.id).delete(synchronize_session=False)

    defaults = _get_default_models().get("anthropic", _FALLBACK_DEFAULTS["anthropic"])
    s = user.settings
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
    s.ai_provider = "anthropic"
    s.api_key_encrypted = None
    s.reasoning_model = defaults["reasoning"]
    s.utility_model = defaults["utility"]
    s.age = None
    s.sex = None
    s.height_cm = None
    s.current_weight_kg = None
    s.goal_weight_kg = None
    s.height_unit = "cm"
    s.weight_unit = "kg"
    s.hydration_unit = "ml"
    s.medical_conditions = None
    s.medications = None
    s.supplements = None
    s.family_history = None
    s.fitness_level = None
    s.dietary_preferences = None
    s.health_goals = None
    s.timezone = "America/Edmonton"
    s.usage_reset_at = None
    s.intake_completed_at = None
    s.intake_skipped_at = None

    cfg = user.specialist_config
    if not cfg:
        cfg = SpecialistConfig(user_id=user.id)
        db.add(cfg)
    cfg.active_specialist = "auto"
    cfg.specialist_overrides = None

    db.commit()

    removed_files = 0
    upload_root = app_settings.UPLOAD_DIR.resolve()
    for raw in image_paths:
        path = Path(raw)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        try:
            # Only delete files within configured upload directory.
            if upload_root in path.parents and path.exists():
                path.unlink()
                removed_files += 1
        except Exception as e:
            logger.warning(f"Failed to remove uploaded file '{path}': {e}")

    return {"status": "ok", "removed_files": removed_files}
