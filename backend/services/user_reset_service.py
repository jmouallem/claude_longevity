import logging
from pathlib import Path

from config import settings as app_settings
from db.models import (
    AITurnTelemetry,
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
    MealResponseSignal,
    MealTemplate,
    MealTemplateVersion,
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
    UserGoal,
    UserSettings,
    VitalsLog,
)
from services.health_framework_service import ensure_default_frameworks
from services.coaching_plan_service import ensure_plan_seeded

logger = logging.getLogger(__name__)


def reset_user_data_for_user(db, user: User) -> dict[str, int]:
    image_paths = [
        str(row.image_path).strip()
        for row in db.query(Message.image_path)
        .filter(Message.user_id == user.id, Message.image_path.isnot(None))
        .all()
        if str(row.image_path).strip()
    ]

    # Delete tables with FK references first (bulk .delete() skips ORM cascades)
    db.query(MealResponseSignal).filter(MealResponseSignal.user_id == user.id).delete(synchronize_session=False)
    db.query(AITurnTelemetry).filter(AITurnTelemetry.user_id == user.id).delete(synchronize_session=False)
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
    db.query(MealTemplateVersion).filter(MealTemplateVersion.user_id == user.id).delete(synchronize_session=False)
    db.query(MealTemplate).filter(MealTemplate.user_id == user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(IntakeSession).filter(IntakeSession.user_id == user.id).delete(synchronize_session=False)
    db.query(FeedbackEntry).filter(FeedbackEntry.created_by_user_id == user.id).delete(synchronize_session=False)
    db.query(ModelUsageEvent).filter(ModelUsageEvent.user_id == user.id).delete(synchronize_session=False)
    db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id).delete(synchronize_session=False)
    db.query(AnalysisRun).filter(AnalysisRun.user_id == user.id).delete(synchronize_session=False)
    db.query(CoachingPlanTask).filter(CoachingPlanTask.user_id == user.id).delete(synchronize_session=False)
    db.query(UserGoal).filter(UserGoal.user_id == user.id).delete(synchronize_session=False)
    db.query(CoachingPlanAdjustment).filter(CoachingPlanAdjustment.user_id == user.id).delete(synchronize_session=False)
    db.query(HealthOptimizationFramework).filter(HealthOptimizationFramework.user_id == user.id).delete(synchronize_session=False)
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == user.id).delete(synchronize_session=False)
    db.query(PasskeyChallenge).filter(PasskeyChallenge.user_id == user.id).delete(synchronize_session=False)

    s = user.settings
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
    # Preserve ai_provider, api_key_encrypted, and model selections across reset
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
