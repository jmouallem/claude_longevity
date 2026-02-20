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
    password_hash = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    specialist_config = relationship("SpecialistConfig", back_populates="user", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ai_provider = Column(Text, nullable=False, default="anthropic")
    api_key_encrypted = Column(Text)
    reasoning_model = Column(Text, default="claude-sonnet-4-20250514")
    utility_model = Column(Text, default="claude-haiku-4-5-20251001")
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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="settings")


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


class FoodLog(Base):
    __tablename__ = "food_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
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


# Indexes
Index("idx_messages_user_date", Message.user_id, Message.created_at)
Index("idx_food_log_user_date", FoodLog.user_id, FoodLog.logged_at)
Index("idx_vitals_log_user_date", VitalsLog.user_id, VitalsLog.logged_at)
Index("idx_exercise_log_user_date", ExerciseLog.user_id, ExerciseLog.logged_at)
Index("idx_exercise_plan_user_date", ExercisePlan.user_id, ExercisePlan.target_date)
Index("idx_daily_checklist_user_date", DailyChecklistItem.user_id, DailyChecklistItem.target_date, DailyChecklistItem.item_type)
Index("idx_summaries_user_type", Summary.user_id, Summary.summary_type, Summary.period_start)
Index("idx_fasting_log_user_date", FastingLog.user_id, FastingLog.fast_start)
