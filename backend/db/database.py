import time

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings
from services.telemetry_context import add_request_db_query


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


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    _ = cursor
    _ = statement
    _ = parameters
    _ = context
    _ = executemany
    conn.info.setdefault("_query_start_time", []).append(time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    _ = cursor
    _ = statement
    _ = parameters
    _ = context
    _ = executemany
    start_stack = conn.info.get("_query_start_time")
    if not start_stack:
        return
    started = start_stack.pop()
    duration_ms = max((time.perf_counter() - started) * 1000.0, 0.0)
    add_request_db_query(duration_ms)


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

    def _normalize_username(username: str) -> str:
        return " ".join((username or "").strip().split()).lower()

    def _table_columns(table_name: str) -> set[str]:
        try:
            return {col["name"] for col in inspector.get_columns(table_name)}
        except Exception:
            return set()

    user_columns = _table_columns("users")
    user_settings_columns = _table_columns("user_settings")
    meal_template_columns = _table_columns("meal_templates")
    food_log_columns = _table_columns("food_log")
    daily_checklist_columns = _table_columns("daily_checklist_item")
    if (
        not user_columns
        and not user_settings_columns
        and not meal_template_columns
        and not food_log_columns
        and not daily_checklist_columns
    ):
        # Tables may not exist yet on first boot.
        return

    alter_statements: list[str] = []
    if user_columns:
        if "username_normalized" not in user_columns:
            alter_statements.append("ALTER TABLE users ADD COLUMN username_normalized TEXT")
        if "role" not in user_columns:
            alter_statements.append("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        if "token_version" not in user_columns:
            alter_statements.append("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0")
        if "force_password_change" not in user_columns:
            alter_statements.append("ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 0")

    if user_settings_columns:
        if "height_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN height_unit TEXT DEFAULT 'cm'")
        if "weight_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN weight_unit TEXT DEFAULT 'kg'")
        if "hydration_unit" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN hydration_unit TEXT DEFAULT 'ml'")
        if "deep_thinking_model" not in user_settings_columns:
            alter_statements.append("ALTER TABLE user_settings ADD COLUMN deep_thinking_model TEXT")
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

        if user_columns:
            users = conn.execute(text("SELECT id, username, created_at FROM users ORDER BY created_at, id")).mappings().all()
            used_normalized: set[str] = set()
            used_usernames: set[str] = {str(row["username"]).strip() for row in users if row.get("username") is not None}
            for row in users:
                user_id = int(row["id"])
                raw_username = str(row["username"] or "").strip()
                if not raw_username:
                    raw_username = f"user{user_id}"
                normalized = _normalize_username(raw_username)
                if not normalized:
                    normalized = f"user{user_id}"

                final_username = raw_username
                final_normalized = normalized
                if final_normalized in used_normalized:
                    suffix = 2
                    base = raw_username
                    while True:
                        candidate_username = f"{base}_{suffix}"
                        candidate_normalized = _normalize_username(candidate_username)
                        if candidate_normalized not in used_normalized and candidate_username not in used_usernames:
                            final_username = candidate_username
                            final_normalized = candidate_normalized
                            break
                        suffix += 1
                    conn.execute(
                        text("UPDATE users SET username = :username WHERE id = :id"),
                        {"id": user_id, "username": final_username},
                    )
                    used_usernames.add(final_username)
                used_normalized.add(final_normalized)
                conn.execute(
                    text(
                        """
                        UPDATE users
                        SET username_normalized = :normalized,
                            role = COALESCE(role, 'user'),
                            token_version = COALESCE(token_version, 0),
                            force_password_change = COALESCE(force_password_change, 0)
                        WHERE id = :id
                        """
                    ),
                    {"id": user_id, "normalized": final_normalized},
                )
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_normalized ON users (username_normalized)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_role ON users (role)"))

        if user_settings_columns:
            # Backfill nulls for any rows created before defaults existed.
            conn.execute(text("UPDATE user_settings SET height_unit = COALESCE(height_unit, 'cm')"))
            conn.execute(text("UPDATE user_settings SET weight_unit = COALESCE(weight_unit, 'kg')"))
            conn.execute(text("UPDATE user_settings SET hydration_unit = COALESCE(hydration_unit, 'ml')"))
            conn.execute(text(
                """
                UPDATE user_settings
                SET deep_thinking_model = COALESCE(deep_thinking_model, reasoning_model, 'claude-sonnet-4-20250514')
                """
            ))
        if meal_template_columns:
            conn.execute(text("UPDATE meal_templates SET is_archived = COALESCE(is_archived, 0)"))
        if food_log_columns:
            conn.execute(text(
                """
                CREATE INDEX IF NOT EXISTS idx_food_log_template
                ON food_log (meal_template_id, logged_at)
                """
            ))

        if daily_checklist_columns:
            # Normalize names and dedupe legacy rows before enforcing uniqueness.
            conn.execute(text("UPDATE daily_checklist_item SET item_name = TRIM(item_name) WHERE item_name IS NOT NULL"))
            conn.execute(text(
                """
                DELETE FROM daily_checklist_item
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM daily_checklist_item
                    GROUP BY user_id, target_date, item_type, item_name
                )
                """
            ))
            conn.execute(text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_checklist_unique_item
                ON daily_checklist_item (user_id, target_date, item_type, item_name)
                """
            ))
            conn.execute(text(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_checklist_user_date
                ON daily_checklist_item (user_id, target_date, item_type)
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

        # Passkey (WebAuthn) credentials and challenge records.
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS passkey_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credential_id TEXT NOT NULL UNIQUE,
                public_key TEXT NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                aaguid TEXT,
                device_type TEXT,
                backed_up BOOLEAN NOT NULL DEFAULT 0,
                transports TEXT,
                label TEXT,
                created_at DATETIME,
                last_used_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS passkey_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username_normalized TEXT,
                purpose TEXT NOT NULL,
                challenge TEXT NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                is_used BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_passkey_credentials_user
            ON passkey_credentials (user_id, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_passkey_credentials_last_used
            ON passkey_credentials (user_id, last_used_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_passkey_challenges_purpose
            ON passkey_challenges (purpose, expires_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_passkey_challenges_user
            ON passkey_challenges (user_id, expires_at)
            """
        ))
        conn.execute(text("DELETE FROM passkey_challenges WHERE expires_at < CURRENT_TIMESTAMP"))

        # Per-user prioritized health optimization frameworks.
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS health_optimization_frameworks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                framework_type TEXT NOT NULL,
                classifier_label TEXT NOT NULL,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                priority_score INTEGER NOT NULL DEFAULT 50,
                is_active BOOLEAN NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'seed',
                rationale TEXT,
                metadata_json TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_health_framework_user_type
            ON health_optimization_frameworks (user_id, framework_type, priority_score)
            """
        ))
        conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_health_framework_user_name
            ON health_optimization_frameworks (user_id, normalized_name)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_health_framework_user_active
            ON health_optimization_frameworks (user_id, is_active, priority_score)
            """
        ))

        # Longitudinal analysis engine tables.
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                run_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                confidence FLOAT,
                used_utility_model TEXT,
                used_reasoning_model TEXT,
                used_deep_model TEXT,
                metrics_json TEXT,
                missing_data_json TEXT,
                risk_flags_json TEXT,
                synthesis_json TEXT,
                summary_markdown TEXT,
                created_at DATETIME,
                completed_at DATETIME,
                error_message TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS analysis_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                analysis_run_id INTEGER NOT NULL,
                proposal_kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                title TEXT NOT NULL,
                rationale TEXT NOT NULL,
                confidence FLOAT,
                requires_approval BOOLEAN DEFAULT 1,
                proposal_json TEXT NOT NULL,
                diff_markdown TEXT,
                created_at DATETIME,
                reviewed_at DATETIME,
                reviewer_user_id INTEGER,
                review_note TEXT,
                applied_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(id),
                FOREIGN KEY(reviewer_user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_user_type_period
            ON analysis_runs (user_id, run_type, period_end)
            """
        ))
        # Deduplicate legacy windows before enforcing one-run-per-window uniqueness.
        conn.execute(text(
            """
            DELETE FROM analysis_proposals
            WHERE analysis_run_id IN (
                SELECT id
                FROM analysis_runs
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM analysis_runs
                    GROUP BY user_id, run_type, period_start, period_end
                )
            )
            """
        ))
        conn.execute(text(
            """
            DELETE FROM analysis_runs
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM analysis_runs
                GROUP BY user_id, run_type, period_start, period_end
            )
            """
        ))
        # Remove any lingering orphan proposals.
        conn.execute(text(
            """
            DELETE FROM analysis_proposals
            WHERE analysis_run_id NOT IN (SELECT id FROM analysis_runs)
            """
        ))
        conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_runs_unique_window
            ON analysis_runs (user_id, run_type, period_start, period_end)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_user_status
            ON analysis_runs (user_id, status, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_proposals_user_status
            ON analysis_proposals (user_id, status, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_proposals_run
            ON analysis_proposals (analysis_run_id, status)
            """
        ))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                target_user_id INTEGER,
                action TEXT NOT NULL,
                details_json TEXT,
                success BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME,
                FOREIGN KEY(admin_user_id) REFERENCES users(id),
                FOREIGN KEY(target_user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at
            ON admin_audit_logs (created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_admin
            ON admin_audit_logs (admin_user_id, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_target
            ON admin_audit_logs (target_user_id, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS rate_limit_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                blocked BOOLEAN NOT NULL DEFAULT 0,
                retry_after_seconds INTEGER,
                user_id INTEGER,
                ip_address TEXT,
                details_json TEXT,
                created_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limit_audit_created_at
            ON rate_limit_audit_events (created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limit_audit_endpoint
            ON rate_limit_audit_events (endpoint, created_at)
            """
        ))
        conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limit_audit_user
            ON rate_limit_audit_events (user_id, created_at)
            """
        ))
