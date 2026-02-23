from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from db.models import HealthOptimizationFramework, User, UserSettings


FRAMEWORK_TYPES: dict[str, dict[str, Any]] = {
    "dietary": {
        "label": "Dietary Framework",
        "classifier_label": "Dietary Strategy",
        "description": "Structured eating patterns used to guide nutrition recommendations.",
        "examples": ["Keto", "DASH", "Mediterranean", "Carnivore", "Low-FODMAP"],
    },
    "training": {
        "label": "Training Framework",
        "classifier_label": "Training Protocol",
        "description": "Structured movement systems that shape training advice and progression.",
        "examples": ["HIIT", "Zone 2", "Strength Progression", "5x5", "CrossFit"],
    },
    "metabolic_timing": {
        "label": "Metabolic Timing Framework",
        "classifier_label": "Metabolic Timing Strategy",
        "description": "Timing strategies for eating/training windows to support metabolic goals.",
        "examples": ["Intermittent Fasting", "Time-Restricted Eating", "Carb Cycling"],
    },
    "micronutrient": {
        "label": "Supplement / Micronutrient Framework",
        "classifier_label": "Micronutrient Strategy",
        "description": "Nutrient optimization approaches for supplement and micronutrient planning.",
        "examples": ["Micronutrient Density Focus", "Longevity Supplement Stack", "Mitochondrial Support"],
    },
    "expert_derived": {
        "label": "Thought Leader / Evidence Framework",
        "classifier_label": "Expert-Derived Framework",
        "description": "Evidence frameworks tied to specific researchers/clinicians.",
        "examples": ["Dr. Rhonda Patrick", "Dr. Mindy Pelz", "Peter Attia", "Andrew Huberman"],
    },
}

FRAMEWORK_STRATEGY_DETAILS: dict[str, dict[str, Any]] = {
    "keto": {
        "summary": "Lower-carb, higher-fat pattern that can improve appetite control and glycemic stability.",
        "supports": ["weight loss", "blood sugar", "metabolic health", "triglycerides"],
        "watch_out_for": ["high LDL response", "strict adherence burden"],
    },
    "dash": {
        "summary": "Blood-pressure focused pattern emphasizing produce, potassium, fiber, and lower sodium.",
        "supports": ["lower blood pressure", "heart health", "weight management"],
        "watch_out_for": ["sodium tracking consistency"],
    },
    "mediterranean": {
        "summary": "Whole-food pattern centered on vegetables, legumes, fish, olive oil, and moderate portions.",
        "supports": ["heart health", "longevity", "weight management", "inflammation"],
        "watch_out_for": ["portion drift from calorie-dense fats"],
    },
    "carnivore": {
        "summary": "Animal-food dominant pattern sometimes used for elimination and satiety experiments.",
        "supports": ["elimination trial", "satiety", "protein adequacy"],
        "watch_out_for": ["fiber reduction", "micronutrient diversity"],
    },
    "low fodmap": {
        "summary": "Structured elimination/reintroduction plan for GI sensitivity symptoms.",
        "supports": ["bloating reduction", "GI symptom control", "food sensitivity mapping"],
        "watch_out_for": ["temporary approach requiring reintroduction phase"],
    },
    "hiit": {
        "summary": "Short, high-intensity intervals designed to improve fitness and metabolic capacity quickly.",
        "supports": ["cardio fitness", "fat loss", "insulin sensitivity", "time-efficient training"],
        "watch_out_for": ["recovery load", "joint stress when deconditioned"],
    },
    "zone 2": {
        "summary": "Steady aerobic work at conversational pace to build mitochondrial and endurance capacity.",
        "supports": ["endurance", "heart health", "fat oxidation", "recovery-friendly conditioning"],
        "watch_out_for": ["progress may feel slow without consistency"],
    },
    "strength progression": {
        "summary": "Progressive overload approach to gradually build strength and preserve lean mass.",
        "supports": ["muscle gain", "metabolic health", "healthy aging", "bone health"],
        "watch_out_for": ["technique quality and recovery planning"],
    },
    "5x5": {
        "summary": "Simple barbell progression with five sets of five reps on core lifts.",
        "supports": ["strength gain", "training structure", "muscle retention"],
        "watch_out_for": ["load management for beginners or mobility limits"],
    },
    "crossfit": {
        "summary": "Mixed-modality high-intensity training combining strength, gymnastics, and conditioning.",
        "supports": ["overall fitness", "work capacity", "motivation through variety"],
        "watch_out_for": ["injury risk without form scaling and coaching"],
    },
    "intermittent fasting": {
        "summary": "Alternating eating and fasting windows to simplify intake timing and appetite control.",
        "supports": ["weight loss", "insulin sensitivity", "meal structure"],
        "watch_out_for": ["sleep disruption or overeating after long fasts"],
    },
    "time restricted eating": {
        "summary": "Consistent daily eating window aligned to circadian rhythm and routine.",
        "supports": ["metabolic health", "digestive regularity", "habit consistency"],
        "watch_out_for": ["undereating if window is too short"],
    },
    "carb cycling": {
        "summary": "Strategic variation of carbohydrate intake around training and recovery demands.",
        "supports": ["training performance", "body composition", "energy management"],
        "watch_out_for": ["complexity and tracking burden"],
    },
    "micronutrient density focus": {
        "summary": "Prioritizes nutrient-rich foods and coverage of key vitamins/minerals.",
        "supports": ["energy", "recovery", "immune support", "long-term resilience"],
        "watch_out_for": ["requires dietary variety and consistency"],
    },
    "longevity supplement stack": {
        "summary": "Structured supplement routine aligned to long-term health and risk profile.",
        "supports": ["routine consistency", "targeted nutrient support", "stack organization"],
        "watch_out_for": ["interaction risk and over-supplementation"],
    },
    "mitochondrial support": {
        "summary": "Focuses on habits/supplements that support cellular energy pathways.",
        "supports": ["energy", "fatigue management", "recovery quality"],
        "watch_out_for": ["benefits depend on sleep, nutrition, and adherence"],
    },
    "dr rhonda patrick": {
        "summary": "Evidence-heavy approach emphasizing micronutrients, sauna/exercise, and biomarker awareness.",
        "supports": ["nutrient optimization", "longevity habits", "evidence-based choices"],
        "watch_out_for": ["can be data-dense for beginners"],
    },
    "dr mindy pelz": {
        "summary": "Fasting-forward framework with cycle-based timing and metabolic flexibility themes.",
        "supports": ["fasting structure", "metabolic timing", "habit routine"],
        "watch_out_for": ["may need adaptation for schedule and medication timing"],
    },
    "peter attia": {
        "summary": "Performance medicine style framework focused on prevention, training zones, and biomarkers.",
        "supports": ["cardio longevity", "strength and VO2 goals", "risk-reduction planning"],
        "watch_out_for": ["high structure and tracking burden"],
    },
    "andrew huberman": {
        "summary": "Protocol-driven behavior framework around light, sleep, stress regulation, and routines.",
        "supports": ["sleep quality", "focus", "behavior consistency"],
        "watch_out_for": ["too many protocols can reduce adherence"],
    },
}


def _strategy_detail_for_name(name: str) -> dict[str, Any]:
    key = re.sub(r"[^a-z0-9]+", " ", str(name or "").strip().lower())
    key = " ".join(key.split())
    detail = FRAMEWORK_STRATEGY_DETAILS.get(key)
    return detail if isinstance(detail, dict) else {}


DEFAULT_FRAMEWORK_SEEDS: list[dict[str, Any]] = [
    {
        "framework_type": str(framework_type),
        "name": str(example_name),
        "priority_score": 60,
        "is_active": False,
        "source": "seed",
        "rationale": "Seed strategy example. Activate when relevant.",
        "metadata": _strategy_detail_for_name(str(example_name)),
    }
    for framework_type, meta in FRAMEWORK_TYPES.items()
    for example_name in (meta.get("examples") or [])
]

FRAMEWORK_TYPE_SET = set(FRAMEWORK_TYPES.keys())
FRAMEWORK_SOURCE_SET = {"seed", "intake", "user", "adaptive"}
LEGACY_BASELINE_NORMALIZED_NAMES = {
    "dietary framework baseline",
    "training framework baseline",
    "metabolic timing framework baseline",
    "micronutrient framework baseline",
    "expert derived framework baseline",
}


INFERENCE_PATTERNS: list[dict[str, Any]] = [
    {"framework_type": "dietary", "name": "Keto", "priority_score": 82, "patterns": (r"\bketo\b", r"\bketogenic\b")},
    {"framework_type": "dietary", "name": "DASH", "priority_score": 80, "patterns": (r"\bdash\b",)},
    {
        "framework_type": "dietary",
        "name": "Mediterranean",
        "priority_score": 80,
        "patterns": (r"\bmediterranean\b",),
    },
    {
        "framework_type": "dietary",
        "name": "Carnivore",
        "priority_score": 70,
        "patterns": (r"\bcarnivore\b",),
    },
    {
        "framework_type": "dietary",
        "name": "Low-FODMAP",
        "priority_score": 76,
        "patterns": (r"\bfodmap\b", r"\blow[\s-]?fodmap\b"),
    },
    {
        "framework_type": "training",
        "name": "HIIT",
        "priority_score": 74,
        "patterns": (r"\bhiit\b", r"high[\s-]?intensity"),
    },
    {"framework_type": "training", "name": "Zone 2", "priority_score": 76, "patterns": (r"\bzone\s*2\b",)},
    {
        "framework_type": "training",
        "name": "Strength Progression",
        "priority_score": 80,
        "patterns": (r"\bstrength\b", r"\bprogressive overload\b"),
    },
    {"framework_type": "training", "name": "5x5", "priority_score": 72, "patterns": (r"\b5x5\b",)},
    {"framework_type": "training", "name": "CrossFit", "priority_score": 70, "patterns": (r"\bcrossfit\b",)},
    {
        "framework_type": "metabolic_timing",
        "name": "Intermittent Fasting",
        "priority_score": 82,
        "patterns": (r"\bintermittent fasting\b", r"\bfasting window\b", r"\b16[:/ ]8\b"),
    },
    {
        "framework_type": "metabolic_timing",
        "name": "Time-Restricted Eating",
        "priority_score": 80,
        "patterns": (r"\btime[\s-]?restricted eating\b", r"\btre\b", r"\beating window\b"),
    },
    {
        "framework_type": "metabolic_timing",
        "name": "Carb Cycling",
        "priority_score": 72,
        "patterns": (r"\bcarb[\s-]?cycling\b",),
    },
    {
        "framework_type": "micronutrient",
        "name": "Supplement Stack",
        "priority_score": 74,
        "patterns": (r"\bsupplement stack\b", r"\bstack\b"),
    },
    {
        "framework_type": "micronutrient",
        "name": "Micronutrient Density Focus",
        "priority_score": 76,
        "patterns": (r"\bmicronutrient\b", r"\bmicronutrient density\b"),
    },
    {
        "framework_type": "micronutrient",
        "name": "Mitochondrial Support",
        "priority_score": 70,
        "patterns": (r"\bmitochondrial\b", r"\bmito support\b"),
    },
    {
        "framework_type": "expert_derived",
        "name": "Dr. Rhonda Patrick",
        "priority_score": 76,
        "patterns": (r"rhonda patrick",),
    },
    {
        "framework_type": "expert_derived",
        "name": "Dr. Mindy Pelz",
        "priority_score": 74,
        "patterns": (r"mindy pelz",),
    },
    {
        "framework_type": "expert_derived",
        "name": "Peter Attia",
        "priority_score": 76,
        "patterns": (r"peter attia", r"\battia\b"),
    },
    {
        "framework_type": "expert_derived",
        "name": "Andrew Huberman",
        "priority_score": 72,
        "patterns": (r"\bandrew huberman\b", r"\bhuberman\b"),
    },
]


def normalize_framework_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (name or "").strip().lower())
    return " ".join(normalized.split())


def _safe_json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _clamp_score(score: int | float | None, default: int = 50) -> int:
    if score is None:
        return default
    try:
        value = int(round(float(score)))
    except (TypeError, ValueError):
        value = default
    return max(0, min(100, value))


def _validate_framework_type(framework_type: str) -> str:
    ft = (framework_type or "").strip().lower()
    if ft not in FRAMEWORK_TYPE_SET:
        raise ValueError(
            f"Invalid framework_type `{framework_type}`. Allowed: {', '.join(sorted(FRAMEWORK_TYPE_SET))}"
        )
    return ft


def _validate_framework_source(source: str | None) -> str:
    src = (source or "user").strip().lower()
    if src not in FRAMEWORK_SOURCE_SET:
        src = "user"
    return src


def serialize_framework(row: HealthOptimizationFramework) -> dict[str, Any]:
    metadata_obj = _safe_json_loads(row.metadata_json)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "framework_type": row.framework_type,
        "framework_type_label": FRAMEWORK_TYPES.get(row.framework_type, {}).get("label", row.framework_type),
        "classifier_label": row.classifier_label,
        "name": row.name,
        "normalized_name": row.normalized_name,
        "priority_score": row.priority_score,
        "is_active": bool(row.is_active),
        "active_weight_pct": None,
        "source": row.source,
        "rationale": row.rationale,
        "metadata": metadata_obj if isinstance(metadata_obj, (dict, list)) else {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
}


def list_frameworks_for_user(db: Session, user_id: int) -> list[HealthOptimizationFramework]:
    return (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user_id)
        .order_by(
            HealthOptimizationFramework.framework_type.asc(),
            HealthOptimizationFramework.priority_score.desc(),
            HealthOptimizationFramework.created_at.asc(),
            HealthOptimizationFramework.id.asc(),
        )
        .all()
    )


def ensure_default_frameworks(db: Session, user_id: int) -> list[HealthOptimizationFramework]:
    existing = list_frameworks_for_user(db, user_id)

    # Cleanup legacy baseline-only seed rows so users see concrete strategy examples instead.
    removed_legacy = False
    for row in list(existing):
        if row.source == "seed" and row.normalized_name in LEGACY_BASELINE_NORMALIZED_NAMES:
            db.delete(row)
            removed_legacy = True
    if removed_legacy:
        db.flush()
        existing = list_frameworks_for_user(db, user_id)

    seed_by_normalized_name = {
        normalize_framework_name(str(seed.get("name") or "")): seed
        for seed in DEFAULT_FRAMEWORK_SEEDS
    }
    backfilled_existing = False
    for row in existing:
        seed = seed_by_normalized_name.get(str(row.normalized_name or ""))
        if not seed:
            continue
        if not row.rationale and seed.get("rationale"):
            row.rationale = str(seed.get("rationale") or "").strip() or None
            backfilled_existing = True
        existing_meta = _safe_json_loads(row.metadata_json)
        if not isinstance(existing_meta, dict) or not existing_meta:
            row.metadata_json = json.dumps(seed.get("metadata") or {}, ensure_ascii=True)
            backfilled_existing = True
    if backfilled_existing:
        db.flush()
        existing = list_frameworks_for_user(db, user_id)

    existing_names = {row.normalized_name for row in existing}

    for seed in DEFAULT_FRAMEWORK_SEEDS:
        seed_name = normalize_framework_name(str(seed["name"]))
        if seed_name in existing_names:
            continue
        upsert_framework(
            db=db,
            user_id=user_id,
            framework_type=str(seed["framework_type"]),
            name=str(seed["name"]),
            priority_score=int(seed["priority_score"]),
            is_active=bool(seed["is_active"]),
            source=str(seed.get("source", "seed")),
            rationale=str(seed.get("rationale") or ""),
            metadata=seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {},
            commit=False,
        )
        existing_names.add(seed_name)

    db.flush()
    return list_frameworks_for_user(db, user_id)


def _active_weight_pct_by_id(rows: list[HealthOptimizationFramework]) -> dict[int, int]:
    by_type: dict[str, list[HealthOptimizationFramework]] = {}
    for row in rows:
        if not bool(row.is_active):
            continue
        by_type.setdefault(str(row.framework_type), []).append(row)

    out: dict[int, int] = {}
    for active_rows in by_type.values():
        total = sum(max(int(r.priority_score or 0), 0) for r in active_rows)
        if total <= 0:
            base = 100 // len(active_rows)
            remainder = 100 - (base * len(active_rows))
            for idx, row in enumerate(active_rows):
                out[int(row.id)] = base + (1 if idx < remainder else 0)
            continue

        raw_pcts: list[tuple[HealthOptimizationFramework, float]] = [
            (row, (max(int(row.priority_score or 0), 0) / total) * 100.0) for row in active_rows
        ]
        floors: dict[int, int] = {int(row.id): int(pct) for row, pct in raw_pcts}
        assigned = sum(floors.values())
        remainder = max(100 - assigned, 0)
        ranked = sorted(raw_pcts, key=lambda x: (x[1] - int(x[1])), reverse=True)
        for idx in range(remainder):
            row = ranked[idx % len(ranked)][0]
            floors[int(row.id)] += 1
        out.update(floors)
    return out


def upsert_framework(
    db: Session,
    user_id: int,
    framework_type: str,
    name: str,
    priority_score: int | float | None = None,
    is_active: bool | None = None,
    source: str | None = None,
    rationale: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> tuple[HealthOptimizationFramework, list[int]]:
    ft = _validate_framework_type(framework_type)
    clean_name = " ".join((name or "").strip().split())
    if not clean_name:
        raise ValueError("Framework `name` is required")
    norm_name = normalize_framework_name(clean_name)
    if not norm_name:
        raise ValueError("Framework `name` is invalid")

    src = _validate_framework_source(source)
    score = _clamp_score(priority_score, default=50)
    meta = metadata if isinstance(metadata, dict) else {}
    classifier_label = FRAMEWORK_TYPES[ft]["classifier_label"]

    row = (
        db.query(HealthOptimizationFramework)
        .filter(
            HealthOptimizationFramework.user_id == user_id,
            HealthOptimizationFramework.normalized_name == norm_name,
        )
        .first()
    )
    created = False
    if not row:
        row = HealthOptimizationFramework(
            user_id=user_id,
            framework_type=ft,
            classifier_label=classifier_label,
            name=clean_name,
            normalized_name=norm_name,
            priority_score=score,
            is_active=bool(is_active) if is_active is not None else False,
            source=src,
            rationale=(rationale or "").strip() or None,
            metadata_json=json.dumps(meta, ensure_ascii=True),
        )
        db.add(row)
        db.flush()
        created = True
    else:
        row.framework_type = ft
        row.classifier_label = classifier_label
        row.name = clean_name
        row.priority_score = score
        if is_active is not None:
            row.is_active = bool(is_active)
        row.source = src
        if rationale is not None:
            row.rationale = rationale.strip() or None
        row.metadata_json = json.dumps(meta, ensure_ascii=True)

    demoted_ids: list[int] = []

    if commit:
        db.commit()
        db.refresh(row)
    elif created:
        db.flush()
    return row, demoted_ids


def update_framework(
    db: Session,
    user_id: int,
    framework_id: int,
    *,
    name: str | None = None,
    framework_type: str | None = None,
    priority_score: int | float | None = None,
    is_active: bool | None = None,
    source: str | None = None,
    rationale: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> tuple[HealthOptimizationFramework, list[int]]:
    row = (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user_id, HealthOptimizationFramework.id == framework_id)
        .first()
    )
    if not row:
        raise ValueError("Framework item not found")

    if name is not None:
        clean_name = " ".join(name.strip().split())
        if not clean_name:
            raise ValueError("Framework `name` cannot be empty")
        row.name = clean_name
        row.normalized_name = normalize_framework_name(clean_name)
        if not row.normalized_name:
            raise ValueError("Framework `name` is invalid")

    if framework_type is not None:
        ft = _validate_framework_type(framework_type)
        row.framework_type = ft
        row.classifier_label = FRAMEWORK_TYPES[ft]["classifier_label"]

    if priority_score is not None:
        row.priority_score = _clamp_score(priority_score, default=row.priority_score or 50)

    if is_active is not None:
        row.is_active = bool(is_active)

    if source is not None:
        row.source = _validate_framework_source(source)

    if rationale is not None:
        row.rationale = rationale.strip() or None

    if metadata is not None:
        row.metadata_json = json.dumps(metadata if isinstance(metadata, dict) else {}, ensure_ascii=True)

    demoted_ids: list[int] = []

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row, demoted_ids


def delete_framework(
    db: Session,
    user_id: int,
    framework_id: int,
    *,
    allow_seed_delete: bool = True,
    commit: bool = False,
) -> HealthOptimizationFramework:
    row = (
        db.query(HealthOptimizationFramework)
        .filter(HealthOptimizationFramework.user_id == user_id, HealthOptimizationFramework.id == framework_id)
        .first()
    )
    if not row:
        raise ValueError("Framework item not found")
    if not allow_seed_delete and row.source == "seed":
        raise ValueError("Seed framework items cannot be deleted")

    db.delete(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return row


def infer_framework_candidates_from_settings(settings: UserSettings | None) -> list[dict[str, Any]]:
    if not settings:
        return []

    evidence_chunks: list[str] = []
    for attr in ("dietary_preferences", "health_goals", "medical_conditions"):
        raw = getattr(settings, attr, None)
        if not raw:
            continue
        parsed = _safe_json_loads(raw)
        if isinstance(parsed, list):
            evidence_chunks.extend(str(v) for v in parsed if str(v).strip())
        else:
            evidence_chunks.append(str(raw))
    evidence_chunks.append(str(settings.fitness_level or ""))
    evidence_chunks.append(str(settings.supplements or ""))
    text = " ".join(evidence_chunks).lower()

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in INFERENCE_PATTERNS:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in rule["patterns"]):
            key = f"{rule['framework_type']}::{normalize_framework_name(str(rule['name']))}"
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "framework_type": rule["framework_type"],
                    "name": rule["name"],
                    "priority_score": rule["priority_score"],
                    "is_active": True,
                    "source": "intake",
                    "rationale": "Activated from intake/profile signals.",
                }
            )

    return candidates


def sync_frameworks_from_settings(
    db: Session,
    user: User,
    *,
    source: str = "intake",
    commit: bool = False,
) -> list[HealthOptimizationFramework]:
    ensure_default_frameworks(db, user.id)
    candidates = infer_framework_candidates_from_settings(user.settings)
    for candidate in candidates:
        upsert_framework(
            db=db,
            user_id=user.id,
            framework_type=str(candidate["framework_type"]),
            name=str(candidate["name"]),
            priority_score=int(candidate.get("priority_score", 70)),
            is_active=bool(candidate.get("is_active", True)),
            source=source,
            rationale=str(candidate.get("rationale") or ""),
            metadata={"inferred": True},
            commit=False,
        )

    if commit:
        db.commit()
    return list_frameworks_for_user(db, user.id)


def grouped_frameworks_for_user(db: Session, user_id: int) -> dict[str, list[dict[str, Any]]]:
    rows = list_frameworks_for_user(db, user_id)
    weight_map = _active_weight_pct_by_id(rows)
    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in FRAMEWORK_TYPES.keys()}
    for row in rows:
        payload = serialize_framework(row)
        if bool(row.is_active):
            payload["active_weight_pct"] = weight_map.get(int(row.id), 0)
        grouped.setdefault(row.framework_type, []).append(payload)
    return grouped


def active_frameworks_for_context(db: Session, user_id: int) -> list[HealthOptimizationFramework]:
    return (
        db.query(HealthOptimizationFramework)
        .filter(
            HealthOptimizationFramework.user_id == user_id,
            HealthOptimizationFramework.is_active.is_(True),
        )
        .order_by(
            HealthOptimizationFramework.priority_score.desc(),
            HealthOptimizationFramework.updated_at.desc(),
            HealthOptimizationFramework.id.desc(),
        )
        .all()
    )
