import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User, UserSettings, Message
from utils.encryption import encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/settings", tags=["settings"])
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


@router.put("/models")
def update_models(
    update: ModelsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    s.reasoning_model = update.reasoning_model
    s.utility_model = update.utility_model
    db.commit()
    return {"status": "ok"}


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

    for field, value in payload.items():
        setattr(s, field, value)
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

    # Set default models for the provider if not specified
    default_models = _get_default_models()
    defaults = default_models.get(req.ai_provider, default_models.get("anthropic", {}))
    s.reasoning_model = req.reasoning_model or defaults["reasoning"]
    s.utility_model = req.utility_model or defaults["utility"]

    db.commit()
    return {"status": "ok", "ai_provider": s.ai_provider}


@router.get("/api-key/status", response_model=APIKeyStatusResponse)
def get_api_key_status(user: User = Depends(get_current_user)):
    s = user.settings
    return APIKeyStatusResponse(
        ai_provider=s.ai_provider,
        has_api_key=bool(s.api_key_encrypted),
        reasoning_model=s.reasoning_model,
        utility_model=s.utility_model,
    )


@router.post("/api-key/validate")
async def validate_api_key(
    user: User = Depends(get_current_user),
):
    """Validate the stored API key by making a test API call."""
    s = user.settings
    if not s.api_key_encrypted:
        raise HTTPException(status_code=400, detail="No API key configured")

    api_key = decrypt_api_key(s.api_key_encrypted)

    # Import here to avoid circular imports
    from ai.providers import get_provider
    try:
        provider = get_provider(s.ai_provider, api_key)
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

    query = db.query(
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
        query = query.filter(Message.created_at > reset_at)
    rows = query.group_by(Message.model_used).all()

    pricing = _get_pricing()
    models = []
    total_cost = 0.0

    for row in rows:
        model_id = row.model_used or "unknown"
        t_in = row.tokens_in or 0
        t_out = row.tokens_out or 0
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
            "request_count": row.request_count,
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
