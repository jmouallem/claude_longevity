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
    try:
        columns = {col["name"] for col in inspector.get_columns("user_settings")}
    except Exception:
        # Table may not exist yet on first boot.
        return

    alter_statements: list[str] = []
    if "height_unit" not in columns:
        alter_statements.append("ALTER TABLE user_settings ADD COLUMN height_unit TEXT DEFAULT 'cm'")
    if "weight_unit" not in columns:
        alter_statements.append("ALTER TABLE user_settings ADD COLUMN weight_unit TEXT DEFAULT 'kg'")
    if "hydration_unit" not in columns:
        alter_statements.append("ALTER TABLE user_settings ADD COLUMN hydration_unit TEXT DEFAULT 'ml'")
    if "usage_reset_at" not in columns:
        alter_statements.append("ALTER TABLE user_settings ADD COLUMN usage_reset_at DATETIME")

    if not alter_statements:
        return

    with engine.begin() as conn:
        for stmt in alter_statements:
            conn.execute(text(stmt))
        # Backfill nulls for any rows created before defaults existed.
        conn.execute(text("UPDATE user_settings SET height_unit = COALESCE(height_unit, 'cm')"))
        conn.execute(text("UPDATE user_settings SET weight_unit = COALESCE(weight_unit, 'kg')"))
        conn.execute(text("UPDATE user_settings SET hydration_unit = COALESCE(hydration_unit, 'ml')"))
