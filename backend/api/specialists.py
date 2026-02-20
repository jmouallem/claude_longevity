from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User, SpecialistConfig
from services.specialists_config import (
    PROTECTED_IDS,
    get_effective_specialists,
    get_enabled_specialist_ids,
    get_specialist_prompt,
    get_system_prompt,
    normalize_specialist_id,
    parse_overrides,
    save_overrides,
)

router = APIRouter(prefix="/specialists", tags=["specialists"])

class SpecialistUpdate(BaseModel):
    active_specialist: str
    specialist_overrides: Optional[str] = None


class CustomSpecialistCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    color: str = "slate"
    prompt: str = ""


class PromptUpdate(BaseModel):
    prompt: str


class SpecialistMetaUpdate(BaseModel):
    name: str
    description: str = ""
    color: str = "slate"
    prompt: Optional[str] = None


def ensure_specialist_config(user: User, db: Session) -> SpecialistConfig:
    if user.specialist_config:
        return user.specialist_config
    config = SpecialistConfig(user_id=user.id)
    db.add(config)
    db.flush()
    user.specialist_config = config
    return config


@router.get("")
def get_specialists(user: User = Depends(get_current_user)):
    overrides = parse_overrides(user.specialist_config)
    specialists = get_effective_specialists(overrides)
    enabled_ids = {s["id"] for s in specialists}
    active = "auto"
    if user.specialist_config:
        current = user.specialist_config.active_specialist or "auto"
        active = current if current in enabled_ids else "auto"
    return {"specialists": specialists, "active": active, "protected_ids": sorted(PROTECTED_IDS)}


@router.put("")
def set_specialist(
    update: SpecialistUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    overrides = parse_overrides(config)
    allowed_ids = set(get_enabled_specialist_ids(overrides)) | {"auto"}
    if update.active_specialist not in allowed_ids:
        raise HTTPException(status_code=400, detail="Invalid specialist")

    config.active_specialist = update.active_specialist
    if update.specialist_overrides is not None:
        config.specialist_overrides = update.specialist_overrides
    db.commit()
    return {"status": "ok", "active": update.active_specialist}


@router.post("")
def add_specialist(
    req: CustomSpecialistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    sid = normalize_specialist_id(req.id)
    if not sid or sid in PROTECTED_IDS:
        raise HTTPException(status_code=400, detail="Invalid specialist id")

    overrides = parse_overrides(config)
    existing_ids = {s["id"] for s in get_effective_specialists(overrides)}
    if sid in existing_ids:
        raise HTTPException(status_code=409, detail="Specialist id already exists")

    custom = overrides.get("custom_specialists", [])
    if not isinstance(custom, list):
        custom = []
    custom.append(
        {
            "id": sid,
            "name": req.name.strip() or sid.replace("_", " ").title(),
            "description": req.description.strip(),
            "color": req.color.strip() or "slate",
        }
    )
    overrides["custom_specialists"] = custom

    prompt_overrides = overrides.get("specialist_prompts", {})
    if not isinstance(prompt_overrides, dict):
        prompt_overrides = {}
    if req.prompt.strip():
        prompt_overrides[sid] = req.prompt
    overrides["specialist_prompts"] = prompt_overrides

    save_overrides(config, overrides)
    db.commit()
    return {"status": "ok", "id": sid}


@router.delete("/{specialist_id}")
def remove_specialist(
    specialist_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    sid = normalize_specialist_id(specialist_id)
    if sid in PROTECTED_IDS:
        raise HTTPException(status_code=400, detail="This specialist cannot be removed")

    overrides = parse_overrides(config)
    custom = overrides.get("custom_specialists", [])
    if not isinstance(custom, list):
        custom = []
    custom_ids = {normalize_specialist_id(str(s.get("id", ""))) for s in custom if isinstance(s, dict)}

    if sid in custom_ids:
        overrides["custom_specialists"] = [
            s for s in custom if normalize_specialist_id(str(s.get("id", ""))) != sid
        ]
    else:
        disabled = set(overrides.get("disabled_specialists", []))
        disabled.add(sid)
        overrides["disabled_specialists"] = sorted(disabled)

    prompt_overrides = overrides.get("specialist_prompts", {})
    if isinstance(prompt_overrides, dict) and sid in prompt_overrides:
        prompt_overrides.pop(sid, None)
        overrides["specialist_prompts"] = prompt_overrides

    if config.active_specialist == sid:
        config.active_specialist = "auto"

    save_overrides(config, overrides)
    db.commit()
    return {"status": "ok"}


@router.post("/{specialist_id}/restore")
def restore_specialist(
    specialist_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    sid = normalize_specialist_id(specialist_id)
    if sid in PROTECTED_IDS:
        raise HTTPException(status_code=400, detail="Protected specialist cannot be restored")

    overrides = parse_overrides(config)
    disabled = set(overrides.get("disabled_specialists", []))
    if sid in disabled:
        disabled.remove(sid)
        overrides["disabled_specialists"] = sorted(disabled)
        save_overrides(config, overrides)
        db.commit()
    return {"status": "ok"}


@router.put("/{specialist_id}")
def update_specialist_meta(
    specialist_id: str,
    req: SpecialistMetaUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    sid = normalize_specialist_id(specialist_id)
    if sid == "auto":
        raise HTTPException(status_code=400, detail="Auto cannot be modified")

    overrides = parse_overrides(config)
    valid_ids = set(get_enabled_specialist_ids(overrides))
    if sid not in valid_ids:
        raise HTTPException(status_code=404, detail="Specialist not found")

    meta_overrides = overrides.get("specialist_meta_overrides", {})
    if not isinstance(meta_overrides, dict):
        meta_overrides = {}
    meta_overrides[sid] = {
        "name": req.name.strip() or sid.replace("_", " ").title(),
        "description": req.description.strip(),
        "color": req.color.strip() or "slate",
    }
    overrides["specialist_meta_overrides"] = meta_overrides

    if req.prompt is not None:
        prompt_overrides = overrides.get("specialist_prompts", {})
        if not isinstance(prompt_overrides, dict):
            prompt_overrides = {}
        prompt_overrides[sid] = req.prompt
        overrides["specialist_prompts"] = prompt_overrides

    save_overrides(config, overrides)
    db.commit()
    return {"status": "ok"}


@router.get("/prompts")
def get_prompts(user: User = Depends(get_current_user)):
    overrides = parse_overrides(user.specialist_config)
    specialists = get_effective_specialists(overrides)
    specialist_ids = [s["id"] for s in specialists if s["id"] != "auto"]
    return {
        "system_prompt": get_system_prompt(overrides),
        "specialist_prompts": {sid: get_specialist_prompt(sid, overrides) for sid in specialist_ids},
    }


@router.put("/prompts/system")
def update_system_prompt(
    req: PromptUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    overrides = parse_overrides(config)
    overrides["system_prompt_override"] = req.prompt
    save_overrides(config, overrides)
    db.commit()
    return {"status": "ok"}


@router.put("/prompts/{specialist_id}")
def update_specialist_prompt(
    specialist_id: str,
    req: PromptUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = ensure_specialist_config(user, db)
    sid = normalize_specialist_id(specialist_id)
    overrides = parse_overrides(config)
    valid_ids = set(get_enabled_specialist_ids(overrides))
    if sid not in valid_ids:
        raise HTTPException(status_code=404, detail="Specialist not found")

    prompt_overrides = overrides.get("specialist_prompts", {})
    if not isinstance(prompt_overrides, dict):
        prompt_overrides = {}
    prompt_overrides[sid] = req.prompt
    overrides["specialist_prompts"] = prompt_overrides
    save_overrides(config, overrides)
    db.commit()
    return {"status": "ok"}
