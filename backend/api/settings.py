import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from auth.utils import hash_password, verify_password
from db.database import get_db
from db.models import (
    User,
    UserSettings,
    Message,
    ModelUsageEvent,
)
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError
from services.health_framework_service import (
    FRAMEWORK_TYPES,
    delete_framework,
    ensure_default_frameworks,
    grouped_frameworks_for_user,
    serialize_framework,
    sync_frameworks_from_settings,
    update_framework,
    upsert_framework,
)
from services.user_reset_service import reset_user_data_for_user
from utils.encryption import encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_non_admin)])
ALLOWED_HEIGHT_UNITS = {"cm", "ft"}
ALLOWED_WEIGHT_UNITS = {"kg", "lb"}
ALLOWED_HYDRATION_UNITS = {"ml", "oz"}


class APIKeyRequest(BaseModel):
    ai_provider: str  # 'anthropic' | 'openai' | 'google'
    api_key: str
    reasoning_model: Optional[str] = None
    utility_model: Optional[str] = None
    deep_thinking_model: Optional[str] = None


class APIKeyStatusResponse(BaseModel):
    ai_provider: str
    has_api_key: bool
    reasoning_model: str
    utility_model: str
    deep_thinking_model: str


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
    deep_thinking_model: str
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


class FrameworkUpsertRequest(BaseModel):
    framework_type: str
    name: str
    priority_score: int = 50
    is_active: bool = False
    source: str = "user"
    rationale: Optional[str] = None
    metadata: Optional[dict] = None


class FrameworkUpdateRequest(BaseModel):
    framework_type: Optional[str] = None
    name: Optional[str] = None
    priority_score: Optional[int] = None
    is_active: Optional[bool] = None
    source: Optional[str] = None
    rationale: Optional[str] = None
    metadata: Optional[dict] = None


# Default models per provider
_MODELS_FILE = Path(__file__).parent.parent / "data" / "models.json"

_FALLBACK_DEFAULTS = {
    "anthropic": {
        "reasoning": "claude-sonnet-4-5-20250929",
        "utility": "claude-haiku-4-5-20251001",
        "deep_thinking": "claude-sonnet-4-5-20250929",
    },
    "openai": {
        "reasoning": "gpt-4o",
        "utility": "gpt-4o-mini",
        "deep_thinking": "gpt-4.1",
    },
    "google": {
        "reasoning": "gemini-2.5-pro",
        "utility": "gemini-2.0-flash",
        "deep_thinking": "gemini-2.5-pro",
    },
}

_FALLBACK_AVAILABLE = {
    "anthropic": {
        "reasoning": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
        ],
        "utility": [{"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"}],
        "deep_thinking": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
        ],
    },
    "openai": {
        "reasoning": [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "o4-mini", "name": "o4-mini"},
            {"id": "o3", "name": "o3"},
            {"id": "o3-mini", "name": "o3-mini"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
        ],
        "utility": [
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
        ],
        "deep_thinking": [
            {"id": "gpt-4.1", "name": "GPT-4.1"},
            {"id": "o3", "name": "o3"},
            {"id": "o3-mini", "name": "o3-mini"},
        ],
    },
    "google": {
        "reasoning": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ],
        "utility": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite"},
        ],
        "deep_thinking": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-pro-preview-05-06", "name": "Gemini 2.5 Pro Preview"},
        ],
    },
}

_FALLBACK_ROLE_HINTS = {
    "utility": {
        "title": "Utility (Fast Structured Work)",
        "description": "Use for extraction, parsing, classification, and other high-volume transforms.",
        "selection_tips": [
            "Prioritize speed and deterministic outputs.",
            "Move up one tier if extraction quality is weak.",
            "Keep utility models cost efficient.",
        ],
    },
    "reasoning": {
        "title": "Reasoning (Primary Coaching)",
        "description": "Use for day-to-day coaching dialogue and actionable recommendations.",
        "selection_tips": [
            "Balance quality and cost for chat frequency.",
            "Prefer strong instruction-following models.",
            "Move up when recommendations feel shallow.",
        ],
    },
    "deep_thinking": {
        "title": "Deep Thinking (Longitudinal Analytics)",
        "description": "Use for monthly synthesis, root-cause hypotheses, and adaptation proposals.",
        "selection_tips": [
            "Favor quality over speed for this role.",
            "Run with approval gates for adaptive changes.",
            "Use premium models for complex trend interpretation.",
        ],
    },
}

_FALLBACK_PRESETS = {
    "anthropic": {
        "budget": {
            "label": "Budget",
            "description": "Low-cost/faster setup.",
            "reasoning": "claude-sonnet-4-20250514",
            "utility": "claude-haiku-4-5-20251001",
            "deep_thinking": "claude-sonnet-4-20250514",
        },
        "balanced": {
            "label": "Balanced",
            "description": "Recommended quality/cost balance.",
            "reasoning": "claude-sonnet-4-5-20250929",
            "utility": "claude-haiku-4-5-20251001",
            "deep_thinking": "claude-sonnet-4-5-20250929",
        },
        "premium": {
            "label": "Premium",
            "description": "Highest quality and cost.",
            "reasoning": "claude-opus-4-6",
            "utility": "claude-haiku-4-5-20251001",
            "deep_thinking": "claude-opus-4-6",
        },
    },
    "openai": {
        "budget": {
            "label": "Budget",
            "description": "Low-cost/faster setup.",
            "reasoning": "o4-mini",
            "utility": "gpt-4o-mini",
            "deep_thinking": "o3-mini",
        },
        "balanced": {
            "label": "Balanced",
            "description": "Recommended quality/cost balance.",
            "reasoning": "gpt-4o",
            "utility": "gpt-4o-mini",
            "deep_thinking": "gpt-4.1",
        },
        "premium": {
            "label": "Premium",
            "description": "Highest quality and cost.",
            "reasoning": "o3",
            "utility": "gpt-4o-mini",
            "deep_thinking": "o3",
        },
    },
    "google": {
        "budget": {
            "label": "Budget",
            "description": "Low-cost/faster setup.",
            "reasoning": "gemini-2.5-flash",
            "utility": "gemini-2.0-flash-lite",
            "deep_thinking": "gemini-2.5-flash",
        },
        "balanced": {
            "label": "Balanced",
            "description": "Recommended quality/cost balance.",
            "reasoning": "gemini-2.5-pro",
            "utility": "gemini-2.0-flash",
            "deep_thinking": "gemini-2.5-pro",
        },
        "premium": {
            "label": "Premium",
            "description": "Highest quality and cost.",
            "reasoning": "gemini-2.5-pro-preview-05-06",
            "utility": "gemini-2.0-flash",
            "deep_thinking": "gemini-2.5-pro-preview-05-06",
        },
    },
}


def _load_models_config() -> dict:
    """Load model config from data/models.json, falling back to built-in defaults."""
    try:
        data = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {
        "defaults": data.get("defaults", _FALLBACK_DEFAULTS),
        "available": data.get("available", _FALLBACK_AVAILABLE),
        "role_hints": data.get("role_hints", _FALLBACK_ROLE_HINTS),
        "presets": data.get("presets", _FALLBACK_PRESETS),
        "pricing": data.get("pricing", {}),
    }


def _get_default_models() -> dict:
    return _load_models_config()["defaults"]


def _get_available_models() -> dict:
    return _load_models_config()["available"]


def _get_role_hints() -> dict:
    return _load_models_config()["role_hints"]


def _get_presets() -> dict:
    return _load_models_config()["presets"]


def _get_pricing() -> dict:
    return _load_models_config()["pricing"]


def _available_model_ids(provider: str) -> tuple[set[str], set[str], set[str]]:
    available = _get_available_models()
    provider_models = available.get(provider, available.get("anthropic", {}))
    reasoning_ids = {str(m.get("id", "")).strip() for m in provider_models.get("reasoning", []) if str(m.get("id", "")).strip()}
    utility_ids = {str(m.get("id", "")).strip() for m in provider_models.get("utility", []) if str(m.get("id", "")).strip()}
    deep_ids = {
        str(m.get("id", "")).strip()
        for m in provider_models.get("deep_thinking", provider_models.get("reasoning", []))
        if str(m.get("id", "")).strip()
    }
    return reasoning_ids, utility_ids, deep_ids


def _normalized_presets_for_provider(provider: str) -> dict:
    defaults = _get_default_models().get(provider, _get_default_models().get("anthropic", _FALLBACK_DEFAULTS["anthropic"]))
    raw_presets = _get_presets().get(provider, {})
    reasoning_ids, utility_ids, deep_ids = _available_model_ids(provider)

    out: dict[str, dict] = {}
    for preset_name, preset in raw_presets.items():
        if not isinstance(preset, dict):
            continue
        reasoning = str(preset.get("reasoning", "")).strip()
        utility = str(preset.get("utility", "")).strip()
        deep = str(preset.get("deep_thinking", "")).strip()
        out[preset_name] = {
            "label": str(preset.get("label", preset_name)).strip() or preset_name,
            "description": str(preset.get("description", "")).strip(),
            "reasoning": reasoning if reasoning and (not reasoning_ids or reasoning in reasoning_ids) else defaults["reasoning"],
            "utility": utility if utility and (not utility_ids or utility in utility_ids) else defaults["utility"],
            "deep_thinking": deep if deep and (not deep_ids or deep in deep_ids) else defaults.get("deep_thinking", defaults["reasoning"]),
        }

    if not out:
        out["balanced"] = {
            "label": "Balanced",
            "description": "Recommended quality/cost balance.",
            "reasoning": defaults["reasoning"],
            "utility": defaults["utility"],
            "deep_thinking": defaults.get("deep_thinking", defaults["reasoning"]),
        }
    return out


def _normalize_models_for_provider(
    provider: str,
    reasoning_model: str | None,
    utility_model: str | None,
    deep_thinking_model: str | None,
) -> tuple[str, str, str]:
    defaults = _get_default_models().get(provider, _get_default_models().get("anthropic", _FALLBACK_DEFAULTS["anthropic"]))
    reasoning_ids, utility_ids, deep_ids = _available_model_ids(provider)

    reasoning = (reasoning_model or "").strip()
    utility = (utility_model or "").strip()
    deep = (deep_thinking_model or "").strip()

    normalized_reasoning = reasoning if reasoning and (not reasoning_ids or reasoning in reasoning_ids) else defaults["reasoning"]
    normalized_utility = utility if utility and (not utility_ids or utility in utility_ids) else defaults["utility"]
    default_deep = defaults.get("deep_thinking", defaults["reasoning"])
    normalized_deep = deep if deep and (not deep_ids or deep in deep_ids) else default_deep
    return normalized_reasoning, normalized_utility, normalized_deep


def _sync_user_models_for_provider(user_settings: UserSettings) -> bool:
    normalized_reasoning, normalized_utility, normalized_deep = _normalize_models_for_provider(
        user_settings.ai_provider,
        user_settings.reasoning_model,
        user_settings.utility_model,
        user_settings.deep_thinking_model,
    )
    changed = False
    if user_settings.reasoning_model != normalized_reasoning:
        user_settings.reasoning_model = normalized_reasoning
        changed = True
    if user_settings.utility_model != normalized_utility:
        user_settings.utility_model = normalized_utility
        changed = True
    if user_settings.deep_thinking_model != normalized_deep:
        user_settings.deep_thinking_model = normalized_deep
        changed = True
    return changed


def _get_model_name(model_id: str) -> str:
    """Look up a friendly model name from the available models config."""
    available = _get_available_models()
    for provider_models in available.values():
        for role in ("reasoning", "utility", "deep_thinking"):
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
    role_hints = _get_role_hints()
    presets = _normalized_presets_for_provider(provider)
    return {
        "provider": provider,
        "reasoning_models": models["reasoning"],
        "utility_models": models["utility"],
        "deep_thinking_models": models.get("deep_thinking", models["reasoning"]),
        "default_reasoning": defaults["reasoning"],
        "default_utility": defaults["utility"],
        "default_deep_thinking": defaults.get("deep_thinking", defaults["reasoning"]),
        "role_hints": {
            "utility": role_hints.get("utility", _FALLBACK_ROLE_HINTS["utility"]),
            "reasoning": role_hints.get("reasoning", _FALLBACK_ROLE_HINTS["reasoning"]),
            "deep_thinking": role_hints.get("deep_thinking", _FALLBACK_ROLE_HINTS["deep_thinking"]),
        },
        "presets": presets,
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
        deep_thinking_model=s.deep_thinking_model or s.reasoning_model,
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
    deep_thinking_model: str


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
    normalized_reasoning, normalized_utility, normalized_deep = _normalize_models_for_provider(
        s.ai_provider,
        update.reasoning_model,
        update.utility_model,
        update.deep_thinking_model,
    )
    s.reasoning_model = normalized_reasoning
    s.utility_model = normalized_utility
    s.deep_thinking_model = normalized_deep
    db.commit()
    return {
        "status": "ok",
        "reasoning_model": normalized_reasoning,
        "utility_model": normalized_utility,
        "deep_thinking_model": normalized_deep,
    }


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

    # Profile updates can imply strategy framework activation (e.g., keto, IF).
    sync_frameworks_from_settings(db, user, source="user", commit=False)
    db.commit()
    return {"status": "ok"}


@router.get("/frameworks")
def list_frameworks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_default_frameworks(db, user.id)
    db.commit()
    rows = grouped_frameworks_for_user(db, user.id)
    return {
        "framework_types": FRAMEWORK_TYPES,
        "grouped": rows,
        "items": [item for items in rows.values() for item in items],
    }


@router.post("/frameworks")
def create_or_upsert_framework(
    payload: FrameworkUpsertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row, demoted_ids = upsert_framework(
            db=db,
            user_id=user.id,
            framework_type=payload.framework_type,
            name=payload.name,
            priority_score=payload.priority_score,
            is_active=payload.is_active,
            source=payload.source,
            rationale=payload.rationale,
            metadata=payload.metadata or {},
            commit=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "item": serialize_framework(row), "demoted_ids": demoted_ids}


@router.put("/frameworks/{framework_id}")
def patch_framework(
    framework_id: int,
    payload: FrameworkUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if framework_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid framework id")
    try:
        row, demoted_ids = update_framework(
            db=db,
            user_id=user.id,
            framework_id=framework_id,
            framework_type=payload.framework_type,
            name=payload.name,
            priority_score=payload.priority_score,
            is_active=payload.is_active,
            source=payload.source,
            rationale=payload.rationale,
            metadata=payload.metadata,
            commit=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "item": serialize_framework(row), "demoted_ids": demoted_ids}


@router.delete("/frameworks/{framework_id}")
def remove_framework(
    framework_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if framework_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid framework id")
    try:
        row = delete_framework(
            db=db,
            user_id=user.id,
            framework_id=framework_id,
            allow_seed_delete=True,
            commit=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "deleted_id": row.id}


@router.post("/frameworks/sync")
def sync_frameworks_from_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = sync_frameworks_from_settings(db, user, source="user", commit=True)
    return {
        "status": "ok",
        "count": len(rows),
        "items": [serialize_framework(row) for row in rows],
    }


@router.put("/api-key")
def set_api_key(
    req: APIKeyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = user.settings
    s.ai_provider = req.ai_provider
    s.api_key_encrypted = encrypt_api_key(req.api_key)

    normalized_reasoning, normalized_utility, normalized_deep = _normalize_models_for_provider(
        req.ai_provider,
        req.reasoning_model,
        req.utility_model,
        req.deep_thinking_model,
    )
    s.reasoning_model = normalized_reasoning
    s.utility_model = normalized_utility
    s.deep_thinking_model = normalized_deep

    db.commit()
    return {
        "status": "ok",
        "ai_provider": s.ai_provider,
        "reasoning_model": s.reasoning_model,
        "utility_model": s.utility_model,
        "deep_thinking_model": s.deep_thinking_model,
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
        deep_thinking_model=s.deep_thinking_model or s.reasoning_model,
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
            deep_thinking_model=s.deep_thinking_model,
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
    user.force_password_change = False
    user.token_version = int(user.token_version or 0) + 1
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
    result = reset_user_data_for_user(db, user)
    return {"status": "ok", "removed_files": result["removed_files"]}
