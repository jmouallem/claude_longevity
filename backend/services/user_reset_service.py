import json
import logging
from pathlib import Path

from config import settings as app_settings
from db.models import (
    AnalysisProposal,
    AnalysisRun,
    CoachingPlanAdjustment,
    CoachingPlanTask,
    DailyChecklistItem,
    ExerciseLog,
    ExercisePlan,
    FastingLog,
    FeedbackEntry,
    FoodLog,
    HydrationLog,
    IntakeSession,
    HealthOptimizationFramework,
    MealTemplate,
    Message,
    ModelUsageEvent,
    Notification,
    PasskeyChallenge,
    PasskeyCredential,
    SleepLog,
    SpecialistConfig,
    Summary,
    SupplementLog,
    User,
    UserSettings,
    VitalsLog,
)
from services.health_framework_service import ensure_default_frameworks
from services.coaching_plan_service import ensure_plan_seeded

logger = logging.getLogger(__name__)

_MODELS_FILE = Path(__file__).parent.parent / "data" / "models.json"
_FALLBACK_ANTHROPIC_DEFAULTS = {
    "reasoning": "claude-sonnet-4-5-20250929",
    "utility": "claude-haiku-4-5-20251001",
    "deep_thinking": "claude-sonnet-4-5-20250929",
}


def _anthropic_defaults() -> dict[str, str]:
    try:
        payload = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        defaults = payload.get("defaults", {}).get("anthropic", {})
        reasoning = str(defaults.get("reasoning", "")).strip() or _FALLBACK_ANTHROPIC_DEFAULTS["reasoning"]
        utility = str(defaults.get("utility", "")).strip() or _FALLBACK_ANTHROPIC_DEFAULTS["utility"]
        deep = str(defaults.get("deep_thinking", "")).strip() or reasoning
        return {"reasoning": reasoning, "utility": utility, "deep_thinking": deep}
    except Exception:
        return dict(_FALLBACK_ANTHROPIC_DEFAULTS)


def reset_user_data_for_user(db, user: User) -> dict[str, int]:
    image_paths = [
        str(row.image_path).strip()
        for row in db.query(Message.image_path)
        .filter(Message.user_id == user.id, Message.image_path.isnot(None))
        .all()
        if str(row.image_path).strip()
    ]

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
    db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id).delete(synchronize_session=False)
    db.query(AnalysisRun).filter(AnalysisRun.user_id == user.id).delete(synchronize_session=False)
    db.query(CoachingPlanTask).filter(CoachingPlanTask.user_id == user.id).delete(synchronize_session=False)
    db.query(CoachingPlanAdjustment).filter(CoachingPlanAdjustment.user_id == user.id).delete(synchronize_session=False)
    db.query(HealthOptimizationFramework).filter(HealthOptimizationFramework.user_id == user.id).delete(synchronize_session=False)
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user.id).delete(synchronize_session=False)
    db.query(PasskeyChallenge).filter(PasskeyChallenge.user_id == user.id).delete(synchronize_session=False)

    defaults = _anthropic_defaults()
    s = user.settings
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
    s.ai_provider = "anthropic"
    s.api_key_encrypted = None
    s.reasoning_model = defaults["reasoning"]
    s.utility_model = defaults["utility"]
    s.deep_thinking_model = defaults["deep_thinking"]
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
    s.coaching_why = None
    s.plan_visibility_mode = "top3"
    s.plan_max_visible_tasks = 3
    s.usage_reset_at = None
    s.intake_completed_at = None
    s.intake_skipped_at = None

    cfg = user.specialist_config
    if not cfg:
        cfg = SpecialistConfig(user_id=user.id)
        db.add(cfg)
    cfg.active_specialist = "auto"
    cfg.specialist_overrides = None

    ensure_default_frameworks(db, user.id)
    ensure_plan_seeded(db, user)
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
            if upload_root in path.parents and path.exists():
                path.unlink()
                removed_files += 1
        except Exception as e:
            logger.warning(f"Failed to remove uploaded file '{path}': {e}")

    return {"removed_files": removed_files}
