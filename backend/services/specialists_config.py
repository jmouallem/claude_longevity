import json
import re
from pathlib import Path

from db.models import SpecialistConfig

CONTEXT_DIR = Path(__file__).parent.parent / "context"
SPECIALISTS_DIR = CONTEXT_DIR / "specialists"
SYSTEM_PROMPT_PATH = CONTEXT_DIR / "system_prompt.md"

DEFAULT_SPECIALISTS = [
    {"id": "orchestrator", "name": "Orchestrator", "description": "General health coaching and coordination", "color": "blue"},
    {"id": "nutritionist", "name": "Nutritionist", "description": "Food, diet, macros, meal planning", "color": "green"},
    {"id": "sleep_expert", "name": "Sleep Expert", "description": "Sleep optimization, circadian rhythm", "color": "indigo"},
    {"id": "movement_coach", "name": "Movement Coach", "description": "Exercise, workouts, training", "color": "orange"},
    {"id": "supplement_auditor", "name": "Supplement Auditor", "description": "Supplements, timing, interactions", "color": "purple"},
    {"id": "safety_clinician", "name": "Safety Clinician", "description": "Medical safety, vitals concerns", "color": "red"},
]
AUTO_SPECIALIST = {
    "id": "auto",
    "name": "Auto",
    "description": "Automatically selects the best specialist for each conversation. Recommended for most users.",
    "color": "emerald",
}
PROTECTED_IDS = {"auto", "orchestrator"}


def parse_overrides(config: SpecialistConfig | None) -> dict:
    raw = config.specialist_overrides if config else None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_overrides(config: SpecialistConfig, data: dict) -> None:
    config.specialist_overrides = json.dumps(data)


def normalize_specialist_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def get_default_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def get_default_specialist_prompt(specialist_id: str) -> str:
    path = SPECIALISTS_DIR / f"{specialist_id}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def get_system_prompt(overrides: dict) -> str:
    return overrides.get("system_prompt_override") or get_default_system_prompt()


def get_specialist_prompt(specialist_id: str, overrides: dict) -> str:
    prompt_overrides = overrides.get("specialist_prompts", {})
    if isinstance(prompt_overrides, dict) and specialist_id in prompt_overrides:
        return str(prompt_overrides[specialist_id] or "")
    return get_default_specialist_prompt(specialist_id)


def get_custom_specialists(overrides: dict) -> list[dict]:
    custom = overrides.get("custom_specialists", [])
    if not isinstance(custom, list):
        return []
    result: list[dict] = []
    for item in custom:
        if not isinstance(item, dict):
            continue
        sid = normalize_specialist_id(str(item.get("id", "")))
        if not sid or sid in PROTECTED_IDS:
            continue
        result.append(
            {
                "id": sid,
                "name": str(item.get("name", sid.replace("_", " ").title())),
                "description": str(item.get("description", "")),
                "color": str(item.get("color", "slate")),
                "custom": True,
            }
        )
    return result


def get_effective_specialists(overrides: dict) -> list[dict]:
    disabled = set(overrides.get("disabled_specialists", []))
    meta_overrides = overrides.get("specialist_meta_overrides", {})
    if not isinstance(meta_overrides, dict):
        meta_overrides = {}
    base = []
    for spec in DEFAULT_SPECIALISTS:
        if spec["id"] in disabled and spec["id"] not in PROTECTED_IDS:
            continue
        override = meta_overrides.get(spec["id"], {})
        if not isinstance(override, dict):
            override = {}
        base.append(
            {
                **spec,
                "name": str(override.get("name", spec["name"])),
                "description": str(override.get("description", spec["description"])),
                "color": str(override.get("color", spec["color"])),
                "custom": False,
            }
        )

    custom: list[dict] = []
    for spec in get_custom_specialists(overrides):
        if spec["id"] in disabled:
            continue
        override = meta_overrides.get(spec["id"], {})
        if not isinstance(override, dict):
            override = {}
        custom.append(
            {
                **spec,
                "name": str(override.get("name", spec["name"])),
                "description": str(override.get("description", spec["description"])),
                "color": str(override.get("color", spec["color"])),
            }
        )
    return [AUTO_SPECIALIST, *base, *custom]


def get_enabled_specialist_ids(overrides: dict) -> list[str]:
    return [s["id"] for s in get_effective_specialists(overrides) if s["id"] != "auto"]
