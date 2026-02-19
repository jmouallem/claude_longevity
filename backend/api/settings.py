from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User, UserSettings
from utils.encryption import encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/settings", tags=["settings"])


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
    medical_conditions: Optional[str] = None
    medications: Optional[str] = None
    supplements: Optional[str] = None
    family_history: Optional[str] = None
    fitness_level: Optional[str] = None
    dietary_preferences: Optional[str] = None
    health_goals: Optional[str] = None
    timezone: Optional[str] = None


# Default models per provider
DEFAULT_MODELS = {
    "anthropic": {"reasoning": "claude-sonnet-4-20250514", "utility": "claude-haiku-4-5-20251001"},
    "openai": {"reasoning": "gpt-4o", "utility": "gpt-4o-mini"},
    "google": {"reasoning": "gemini-2.5-pro", "utility": "gemini-2.0-flash"},
}

# Available models per provider (for dropdown selection)
AVAILABLE_MODELS = {
    "anthropic": {
        "reasoning": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
        ],
        "utility": [
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        ],
    },
    "openai": {
        "reasoning": [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-2024-11-20", "name": "GPT-4o (Nov 2024)"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
            {"id": "o3-mini", "name": "o3-mini"},
        ],
        "utility": [
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "gpt-4o", "name": "GPT-4o"},
        ],
    },
    "google": {
        "reasoning": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ],
        "utility": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ],
    },
}


@router.get("/models")
def get_available_models(provider: str = "anthropic"):
    """Get available models for a given provider."""
    models = AVAILABLE_MODELS.get(provider, AVAILABLE_MODELS["anthropic"])
    defaults = DEFAULT_MODELS.get(provider, DEFAULT_MODELS["anthropic"])
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
    for field, value in update.model_dump(exclude_unset=True).items():
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
    defaults = DEFAULT_MODELS.get(req.ai_provider, DEFAULT_MODELS["anthropic"])
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
