from datetime import datetime
from sqlalchemy import (
    Column, Integer, Text, Float, Boolean, ForeignKey, Index,
    DateTime,
)
from sqlalchemy.orm import relationship
from db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, unique=True, nullable=False)
    username_normalized = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    role = Column(Text, nullable=False, default="user")  # user | admin
    token_version = Column(Integer, nullable=False, default=0)
    force_password_change = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    specialist_config = relationship("SpecialistConfig", back_populates="user", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")
    passkey_credentials = relationship("PasskeyCredential", back_populates="user", cascade="all, delete-orphan")
    passkey_challenges = relationship("PasskeyChallenge", back_populates="user", cascade="all, delete-orphan")
    intake_sessions = relationship("IntakeSession", back_populates="user", cascade="all, delete-orphan")
    meal_templates = relationship("MealTemplate", back_populates="user", cascade="all, delete-orphan")
    meal_template_versions = relationship("MealTemplateVersion", back_populates="user", cascade="all, delete-orphan")
    meal_response_signals = relationship("MealResponseSignal", back_populates="user", cascade="all, delete-orphan")
    optimization_frameworks = relationship("HealthOptimizationFramework", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    analysis_runs = relationship("AnalysisRun", back_populates="user", cascade="all, delete-orphan")
    analysis_proposals = relationship(
        "AnalysisProposal",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="AnalysisProposal.user_id",
    )
    admin_actions = relationship(
        "AdminAuditLog",
        back_populates="admin_user",
        cascade="all, delete-orphan",
        foreign_keys="AdminAuditLog.admin_user_id",
    )
    admin_target_actions = relationship(
        "AdminAuditLog",
        back_populates="target_user",
        cascade="all, delete-orphan",
        foreign_keys="AdminAuditLog.target_user_id",
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ai_provider = Column(Text, nullable=False, default="anthropic")
    api_key_encrypted = Column(Text)
    reasoning_model = Column(Text, default="claude-sonnet-4-20250514")
    utility_model = Column(Text, default="claude-haiku-4-5-20251001")
    deep_thinking_model = Column(Text, default="claude-sonnet-4-20250514")
    age = Column(Integer)
    sex = Column(Text)
    height_cm = Column(Float)
    current_weight_kg = Column(Float)
    goal_weight_kg = Column(Float)
    height_unit = Column(Text, default="cm")
    weight_unit = Column(Text, default="kg")
    hydration_unit = Column(Text, default="ml")
    medical_conditions = Column(Text)  # JSON array
    medications = Column(Text)  # JSON array
    supplements = Column(Text)  # JSON array
    family_history = Column(Text)  # JSON array
    fitness_level = Column(Text)
    dietary_preferences = Column(Text)  # JSON array
    health_goals = Column(Text)  # JSON array
    timezone = Column(Text, default="America/Edmonton")
    usage_reset_at = Column(DateTime, nullable=True)
    intake_completed_at = Column(DateTime, nullable=True)
    intake_skipped_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="settings")


class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    credential_id = Column(Text, nullable=False, unique=True)
    public_key = Column(Text, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    aaguid = Column(Text)
    device_type = Column(Text)
    backed_up = Column(Boolean, nullable=False, default=False)
    transports = Column(Text)  # JSON array
    label = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)

    user = relationship("User", back_populates="passkey_credentials")


class PasskeyChallenge(Base):
    __tablename__ = "passkey_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username_normalized = Column(Text, nullable=True)
    purpose = Column(Text, nullable=False)  # registration | authentication
    challenge = Column(Text, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="passkey_challenges")


class SpecialistConfig(Base):
    __tablename__ = "specialist_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    active_specialist = Column(Text, default="auto")
    specialist_overrides = Column(Text)  # JSON
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="specialist_config")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    specialist_used = Column(Text)
    model_used = Column(Text)
    tokens_in = Column(Integer)
    tokens_out = Column(Integer)
    has_image = Column(Boolean, default=False)
    image_path = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")


class ModelUsageEvent(Base):
    __tablename__ = "model_usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    usage_type = Column(Text, nullable=False, default="utility")  # utility | reasoning | deep_thinking | other
    operation = Column(Text)  # intent_classification, log_parse, summary_generate, etc.
    model_used = Column(Text, nullable=False)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class FoodLog(Base):
    __tablename__ = "food_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meal_template_id = Column(Integer, ForeignKey("meal_templates.id"), nullable=True)
    logged_at = Column(DateTime, nullable=False)
    meal_label = Column(Text)
    items = Column(Text, nullable=False)  # JSON array
    calories = Column(Float)
    protein_g = Column(Float)
    carbs_g = Column(Float)
    fat_g = Column(Float)
    fiber_g = Column(Float)
    sodium_mg = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    meal_template = relationship("MealTemplate", back_populates="food_logs")
    meal_response_signals = relationship("MealResponseSignal", back_populates="food_log", cascade="all, delete-orphan")


class MealTemplate(Base):
    __tablename__ = "meal_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    aliases = Column(Text)  # JSON array of alternate names
    ingredients = Column(Text)  # JSON array of ingredient lines
    servings = Column(Float, default=1.0)
    calories = Column(Float)
    protein_g = Column(Float)
    carbs_g = Column(Float)
    fat_g = Column(Float)
    fiber_g = Column(Float)
    sodium_mg = Column(Float)
    notes = Column(Text)
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="meal_templates")
    food_logs = relationship("FoodLog", back_populates="meal_template")
    versions = relationship("MealTemplateVersion", back_populates="meal_template", cascade="all, delete-orphan")
    response_signals = relationship("MealResponseSignal", back_populates="meal_template", cascade="all, delete-orphan")


class MealTemplateVersion(Base):
    __tablename__ = "meal_template_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meal_template_id = Column(Integer, ForeignKey("meal_templates.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    change_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="meal_template_versions")
    meal_template = relationship("MealTemplate", back_populates="versions")


class MealResponseSignal(Base):
    __tablename__ = "meal_response_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meal_template_id = Column(Integer, ForeignKey("meal_templates.id"), nullable=True)
    food_log_id = Column(Integer, ForeignKey("food_log.id"), nullable=True)
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    energy_level = Column(Integer)  # -2 very low, -1 low, 0 neutral, 1 good, 2 high
    gi_symptom_tags = Column(Text)  # JSON array
    gi_severity = Column(Integer)  # 1-5 scale
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="meal_response_signals")
    meal_template = relationship("MealTemplate", back_populates="response_signals")
    food_log = relationship("FoodLog", back_populates="meal_response_signals")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(Text, nullable=False, default="info")  # info | reminder | warning | system
    title = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    payload = Column(Text)  # JSON object
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime)

    user = relationship("User", back_populates="notifications")


class HealthOptimizationFramework(Base):
    __tablename__ = "health_optimization_frameworks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    framework_type = Column(Text, nullable=False)  # dietary | training | metabolic_timing | micronutrient | expert_derived
    classifier_label = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    priority_score = Column(Integer, nullable=False, default=50)  # 0-100
    is_active = Column(Boolean, nullable=False, default=False)
    source = Column(Text, nullable=False, default="seed")  # seed | intake | user | adaptive
    rationale = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="optimization_frameworks")


class WebSearchCache(Base):
    __tablename__ = "web_search_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_key = Column(Text, nullable=False, unique=True)
    query = Column(Text, nullable=False)
    provider = Column(Text, nullable=False, default="duckduckgo")
    results_json = Column(Text, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class HydrationLog(Base):
    __tablename__ = "hydration_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False)
    amount_ml = Column(Float, nullable=False)
    source = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class VitalsLog(Base):
    __tablename__ = "vitals_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False)
    weight_kg = Column(Float)
    bp_systolic = Column(Integer)
    bp_diastolic = Column(Integer)
    heart_rate = Column(Integer)
    blood_glucose = Column(Float)
    temperature_c = Column(Float)
    spo2 = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExerciseLog(Base):
    __tablename__ = "exercise_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False)
    exercise_type = Column(Text, nullable=False)
    duration_minutes = Column(Integer)
    details = Column(Text)  # JSON
    max_hr = Column(Integer)
    avg_hr = Column(Integer)
    calories_burned = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExercisePlan(Base):
    __tablename__ = "exercise_plan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_date = Column(Text, nullable=False)  # YYYY-MM-DD
    plan_type = Column(Text, nullable=False)  # rest_day | hiit | strength | zone2 | mobility | mixed
    title = Column(Text, nullable=False)
    description = Column(Text)
    target_minutes = Column(Integer)
    source = Column(Text, default="ai")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DailyChecklistItem(Base):
    __tablename__ = "daily_checklist_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_date = Column(Text, nullable=False)  # YYYY-MM-DD
    item_type = Column(Text, nullable=False)  # medication | supplement
    item_name = Column(Text, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupplementLog(Base):
    __tablename__ = "supplement_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False)
    supplements = Column(Text, nullable=False)  # JSON array
    timing = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class FastingLog(Base):
    __tablename__ = "fasting_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fast_start = Column(DateTime, nullable=False)
    fast_end = Column(DateTime)
    duration_minutes = Column(Integer)
    fast_type = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SleepLog(Base):
    __tablename__ = "sleep_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sleep_start = Column(DateTime)
    sleep_end = Column(DateTime)
    duration_minutes = Column(Integer)
    quality = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    summary_type = Column(Text, nullable=False)
    period_start = Column(Text, nullable=False)  # DATE as text for SQLite
    period_end = Column(Text, nullable=False)
    nutrition_summary = Column(Text)
    exercise_summary = Column(Text)
    vitals_summary = Column(Text)
    sleep_summary = Column(Text)
    fasting_summary = Column(Text)
    supplement_summary = Column(Text)
    mood_energy_summary = Column(Text)
    wins = Column(Text)
    concerns = Column(Text)
    recommendations = Column(Text)
    full_narrative = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    run_type = Column(Text, nullable=False)  # daily | weekly | monthly
    period_start = Column(Text, nullable=False)  # DATE as text for SQLite
    period_end = Column(Text, nullable=False)  # DATE as text for SQLite
    status = Column(Text, nullable=False, default="completed")  # running | completed | failed
    confidence = Column(Float)
    used_utility_model = Column(Text)
    used_reasoning_model = Column(Text)
    used_deep_model = Column(Text)
    metrics_json = Column(Text)  # JSON object
    missing_data_json = Column(Text)  # JSON array
    risk_flags_json = Column(Text)  # JSON array
    synthesis_json = Column(Text)  # JSON object
    summary_markdown = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    user = relationship("User", back_populates="analysis_runs")
    proposals = relationship("AnalysisProposal", back_populates="analysis_run", cascade="all, delete-orphan")


class AnalysisProposal(Base):
    __tablename__ = "analysis_proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)
    proposal_kind = Column(Text, nullable=False)  # guidance_update | prompt_adjustment | experiment
    status = Column(Text, nullable=False, default="pending")  # pending | approved | rejected | applied | expired
    title = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    confidence = Column(Float)
    requires_approval = Column(Boolean, default=True)
    proposal_json = Column(Text, nullable=False)  # JSON object payload
    diff_markdown = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note = Column(Text)
    applied_at = Column(DateTime)

    user = relationship("User", back_populates="analysis_proposals", foreign_keys=[user_id])
    analysis_run = relationship("AnalysisRun", back_populates="proposals")


class RequestTelemetryEvent(Base):
    __tablename__ = "request_telemetry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    request_group = Column(Text, nullable=False)  # chat | logs | dashboard | analysis
    path = Column(Text, nullable=False)
    method = Column(Text, nullable=False)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    db_query_count = Column(Integer, nullable=False, default=0)
    db_query_time_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class AITurnTelemetry(Base):
    __tablename__ = "ai_turn_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    specialist_id = Column(Text, nullable=False)
    intent_category = Column(Text, nullable=False)
    first_token_latency_ms = Column(Float, nullable=True)
    total_latency_ms = Column(Float, nullable=False, default=0.0)
    utility_calls = Column(Integer, nullable=False, default=0)
    reasoning_calls = Column(Integer, nullable=False, default=0)
    deep_calls = Column(Integer, nullable=False, default=0)
    utility_tokens_in = Column(Integer, nullable=False, default=0)
    utility_tokens_out = Column(Integer, nullable=False, default=0)
    reasoning_tokens_in = Column(Integer, nullable=False, default=0)
    reasoning_tokens_out = Column(Integer, nullable=False, default=0)
    deep_tokens_in = Column(Integer, nullable=False, default=0)
    deep_tokens_out = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    failures_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_type = Column(Text, nullable=False)  # bug | enhancement | missing | other
    title = Column(Text, nullable=False)
    details = Column(Text)
    source = Column(Text, nullable=False, default="user")  # user | agent
    specialist_id = Column(Text)
    specialist_name = Column(Text)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(Text, nullable=False)
    details_json = Column(Text)
    success = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    admin_user = relationship("User", back_populates="admin_actions", foreign_keys=[admin_user_id])
    target_user = relationship("User", back_populates="admin_target_actions", foreign_keys=[target_user_id])


class IntakeSession(Base):
    __tablename__ = "intake_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Text, nullable=False, default="active")  # active | completed | skipped
    current_index = Column(Integer, nullable=False, default=0)
    field_order = Column(Text, nullable=False)  # JSON array
    answers = Column(Text)  # JSON object keyed by field
    draft_patch = Column(Text)  # JSON object suitable for settings update
    skipped_fields = Column(Text)  # JSON array
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="intake_sessions")


# Indexes
Index("idx_messages_user_date", Message.user_id, Message.created_at)
Index("idx_model_usage_user_date", ModelUsageEvent.user_id, ModelUsageEvent.created_at)
Index("idx_model_usage_model", ModelUsageEvent.model_used)
Index("idx_passkey_credentials_user", PasskeyCredential.user_id, PasskeyCredential.created_at)
Index("idx_passkey_credentials_last_used", PasskeyCredential.user_id, PasskeyCredential.last_used_at)
Index("idx_passkey_challenges_purpose", PasskeyChallenge.purpose, PasskeyChallenge.expires_at)
Index("idx_passkey_challenges_user", PasskeyChallenge.user_id, PasskeyChallenge.expires_at)
Index("idx_meal_templates_user", MealTemplate.user_id)
Index("idx_meal_templates_user_name", MealTemplate.user_id, MealTemplate.normalized_name, unique=True)
Index("idx_meal_templates_user_archived", MealTemplate.user_id, MealTemplate.is_archived)
Index("idx_meal_template_versions_template", MealTemplateVersion.meal_template_id, MealTemplateVersion.version_number)
Index("idx_meal_template_versions_user", MealTemplateVersion.user_id, MealTemplateVersion.created_at)
Index("idx_meal_response_signals_user_date", MealResponseSignal.user_id, MealResponseSignal.created_at)
Index("idx_meal_response_signals_template", MealResponseSignal.meal_template_id, MealResponseSignal.created_at)
Index("idx_meal_response_signals_food_log", MealResponseSignal.food_log_id)
Index("idx_health_framework_user_type", HealthOptimizationFramework.user_id, HealthOptimizationFramework.framework_type, HealthOptimizationFramework.priority_score)
Index("idx_health_framework_user_name", HealthOptimizationFramework.user_id, HealthOptimizationFramework.normalized_name, unique=True)
Index("idx_health_framework_user_active", HealthOptimizationFramework.user_id, HealthOptimizationFramework.is_active, HealthOptimizationFramework.priority_score)
Index("idx_notifications_user_date", Notification.user_id, Notification.created_at)
Index("idx_notifications_user_read", Notification.user_id, Notification.is_read)
Index("idx_web_search_query_key", WebSearchCache.query_key, unique=True)
Index("idx_web_search_fetched_at", WebSearchCache.fetched_at)
Index("idx_food_log_user_date", FoodLog.user_id, FoodLog.logged_at)
Index("idx_food_log_template", FoodLog.meal_template_id, FoodLog.logged_at)
Index("idx_vitals_log_user_date", VitalsLog.user_id, VitalsLog.logged_at)
Index("idx_exercise_log_user_date", ExerciseLog.user_id, ExerciseLog.logged_at)
Index("idx_exercise_plan_user_date", ExercisePlan.user_id, ExercisePlan.target_date)
Index("idx_daily_checklist_user_date", DailyChecklistItem.user_id, DailyChecklistItem.target_date, DailyChecklistItem.item_type)
Index(
    "idx_daily_checklist_unique_item",
    DailyChecklistItem.user_id,
    DailyChecklistItem.target_date,
    DailyChecklistItem.item_type,
    DailyChecklistItem.item_name,
    unique=True,
)
Index("idx_summaries_user_type", Summary.user_id, Summary.summary_type, Summary.period_start)
Index("idx_fasting_log_user_date", FastingLog.user_id, FastingLog.fast_start)
Index("idx_feedback_created_at", FeedbackEntry.created_at)
Index("idx_feedback_type", FeedbackEntry.feedback_type)
Index("idx_users_username_normalized", User.username_normalized, unique=True)
Index("idx_users_role", User.role)
Index("idx_admin_audit_created_at", AdminAuditLog.created_at)
Index("idx_admin_audit_admin", AdminAuditLog.admin_user_id, AdminAuditLog.created_at)
Index("idx_admin_audit_target", AdminAuditLog.target_user_id, AdminAuditLog.created_at)
Index("idx_intake_session_user_status", IntakeSession.user_id, IntakeSession.status, IntakeSession.updated_at)
Index("idx_analysis_runs_user_type_period", AnalysisRun.user_id, AnalysisRun.run_type, AnalysisRun.period_end)
Index(
    "idx_analysis_runs_unique_window",
    AnalysisRun.user_id,
    AnalysisRun.run_type,
    AnalysisRun.period_start,
    AnalysisRun.period_end,
    unique=True,
)
Index("idx_analysis_runs_user_status", AnalysisRun.user_id, AnalysisRun.status, AnalysisRun.created_at)
Index("idx_analysis_proposals_user_status", AnalysisProposal.user_id, AnalysisProposal.status, AnalysisProposal.created_at)
Index("idx_analysis_proposals_run", AnalysisProposal.analysis_run_id, AnalysisProposal.status)
Index("idx_request_telemetry_group_date", RequestTelemetryEvent.request_group, RequestTelemetryEvent.created_at)
Index("idx_request_telemetry_user_date", RequestTelemetryEvent.user_id, RequestTelemetryEvent.created_at)
Index("idx_ai_turn_telemetry_user_date", AITurnTelemetry.user_id, AITurnTelemetry.created_at)
Index("idx_ai_turn_telemetry_specialist_date", AITurnTelemetry.specialist_id, AITurnTelemetry.created_at)
