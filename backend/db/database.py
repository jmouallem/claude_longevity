from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


# Enable WAL mode for better concurrent read performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_startup_migrations() -> None:
    """Apply lightweight schema fixes for existing SQLite databases."""
    inspector = inspect(engine)

    def _table_columns(table_name: str) -> set[str]:
        try:
            return {col["name"] for col in inspector.get_columns(table_name)}
        except Exception:
            return set()

    user_settings_columns = _table_columns("user_settings")
    meal_template_columns = _table_columns("meal_templates")
    food_log_columns = _table_columns("food_log")
    if not user_settings_columns and not meal_template_columns and not food_log_columns:
        # Tables may not exist yet on first boot.
        return

    alter_statements: list[str] = []
    if user_settings_columns:
        if "height_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN height_unit TEXT DEFAULT 'cm'")
        if "weight_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN weight_unit TEXT DEFAULT 'kg'")
        if "hydration_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN hydration_unit TEXT DEFAULT 'ml'")
        if "usage_reset_at" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN usage_reset_at DATETIME")
        if "intake_completed_at" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN intake_completed_at DATETIME")
        if "intake_skipped_at" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN intake_skipped_at DATETIME")

    if meal_template_columns:
        if "is_archived" not in meal_template_columns:
            alter_statements.append("ALTER TABLE meal_templates ADD COLUMN is_archived BOOLEAN DEFAULT 0")
        if "archived_at" not in meal_template_columns:
            alter_statements.append("ALTER TABLE meal_templates ADD COLUMN archived_at DATETIME")
    if food_log_columns:
        if "meal_template_id" not in food_log_columns:
            alter_statements.append("ALTER TABLE food_log ADD COLUMN meal_template_id INTEGER")

    with engine.begin() as conn:
        for stmt in alter_statements:
            conn.execute(text(stmt))

        if user_settings_columns:
            # Backfill nulls for any rows created before defaults existed.
            conn.execute(text("UPDATE user_settings SET height_unit = COALESCE(height_unit, 'cm')"))
            conn.execute(text("UPDATE user_settings SET weight_unit = COALESCE(weight_unit, 'kg')"))
            conn.execute(text("UPDATE user_settings SET hydration_unit = COALESCE(hydration_unit, 'ml')"))
        if meal_template_columns:
            conn.execute(text("UPDATE meal_templates SET is_archived = COALESCE(is_archived, 0)"))
        if food_log_columns:
            conn.execute(text(
                """
                CREATE INDEX IF NOT EXISTS idx_food_log_template
                ON food_log (meal_template_id, logged_at)
                """
            ))

        # New supporting tables for meal versioning + response analytics.
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS meal_template_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meal_template_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                change_note TEXT,
                created_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(meal_template_id) REFERENCES meal_templates(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS meal_response_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meal_template_id INTEGER,
                food_log_id INTEGER,
                source_message_id INTEGER,
                energy_level INTEGER,
                gi_symptom_tags TEXT,
                gi_severity INTEGER,
                notes TEXT,
                created_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(meal_template_id) REFERENCES meal_templates(id),
                FOREIGN KEY(food_log_id) REFERENCES food_log(id),
                FOREIGN KEY(source_message_id) REFERENCES messages(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_meal_templates_user_archived
            ON meal_templates (user_id, is_archived)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_meal_template_versions_template
            ON meal_template_versions (meal_template_id, version_number)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_meal_response_signals_user_date
            ON meal_response_signals (user_id, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_meal_response_signals_template
            ON meal_response_signals (meal_template_id, created_at)
            """
        ))
