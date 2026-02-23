from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"  # development | test | staging | production
    APP_NAME: str = "Longevity Coach"
    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = "change-me-in-production-32bytes!"
    DATABASE_URL: str = "sqlite:///data/longevity.db"
    DATA_DIR: Path = Path("data")
    UPLOAD_DIR: Path = Path("data/uploads")
    CORS_ORIGINS: list[str] = [
        "http://localhost:8050",
        "http://localhost:8001",
        "https://localhost:8050",
        "https://127.0.0.1:8050",
    ]
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 72
    ADMIN_JWT_EXPIRY_HOURS: int = 12
    ADMIN_USERNAME: str = "longadmin"
    ADMIN_PASSWORD: str = "L0ngevity!123"
    ADMIN_DISPLAY_NAME: str = "Long Admin"
    ADMIN_FORCE_PASSWORD_CHANGE: bool = True
    ADMIN_RESET_PASSWORD_ON_STARTUP: bool = False
    ENABLE_WEB_SEARCH: bool = True
    WEB_SEARCH_ALLOWED_SPECIALISTS: list[str] = [
        "orchestrator",
        "nutritionist",
        "supplement_auditor",
        "safety_clinician",
        "movement_coach",
        "sleep_expert",
    ]
    WEB_SEARCH_MAX_RESULTS: int = 5
    WEB_SEARCH_TIMEOUT_SECONDS: int = 8
    WEB_SEARCH_CACHE_TTL_HOURS: int = 12
    WEB_SEARCH_CIRCUIT_FAIL_THRESHOLD: int = 3
    WEB_SEARCH_CIRCUIT_OPEN_SECONDS: int = 60
    ENABLE_LONGITUDINAL_ANALYSIS: bool = True
    ANALYSIS_AUTORUN_ON_CHAT: bool = True
    ANALYSIS_DAILY_HOUR_LOCAL: int = 20
    ANALYSIS_WEEKLY_WEEKDAY_LOCAL: int = 6  # Sunday
    ANALYSIS_MONTHLY_DAY_LOCAL: int = 1
    ANALYSIS_MAX_CATCHUP_WINDOWS: int = 6
    ANALYSIS_MAX_CATCHUP_WINDOWS_CHAT: int = 1
    ANALYSIS_AUTO_APPLY_PROPOSALS: bool = False
    ANALYSIS_AUTORUN_DEBOUNCE_SECONDS: int = 300
    UTILITY_CALL_BUDGET_LOG_TURN: int = 6
    UTILITY_CALL_BUDGET_NONLOG_TURN: int = 4
    ENABLE_PASSKEY_AUTH: bool = True
    PASSKEY_RP_ID: str = "localhost"
    PASSKEY_RP_NAME: str = "Longevity Coach"
    PASSKEY_ALLOWED_ORIGINS: list[str] = [
        "https://localhost:8050",
        "https://127.0.0.1:8050",
    ]
    PASSKEY_CHALLENGE_TTL_SECONDS: int = 300
    PASSKEY_USER_TOKEN_HOURS: int = 168
    AUTH_COOKIE_NAME: str = "longevity_session"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_HTTPONLY: bool = True
    AUTH_COOKIE_SAMESITE: str = "lax"  # strict | lax | none
    AUTH_COOKIE_DOMAIN: str | None = None
    AUTH_COOKIE_PATH: str = "/"
    SECURITY_HEADERS_ENABLED: bool = True
    SECURITY_CSP: str = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self' https: wss:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    RATE_LIMIT_AUTH_LOGIN_ATTEMPTS: int = 10
    RATE_LIMIT_AUTH_LOGIN_WINDOW_SECONDS: int = 300
    RATE_LIMIT_AUTH_REGISTER_ATTEMPTS: int = 5
    RATE_LIMIT_AUTH_REGISTER_WINDOW_SECONDS: int = 600
    RATE_LIMIT_CHAT_MESSAGES: int = 30
    RATE_LIMIT_CHAT_WINDOW_SECONDS: int = 60
    SLO_CHAT_P95_FIRST_TOKEN_MS: int = 3500
    SLO_DASHBOARD_P95_LOAD_MS: int = 1200
    SLO_ANALYSIS_RUN_COMPLETION_SLA_SECONDS: int = 120

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_production_like(self) -> bool:
        return (self.ENVIRONMENT or "").strip().lower() in {"production", "prod", "staging"}

    def validate_security_configuration(self) -> None:
        if not self.is_production_like:
            return

        errors: list[str] = []
        if self.SECRET_KEY == "change-me-in-production":
            errors.append("SECRET_KEY must be changed from the default value")
        if self.ENCRYPTION_KEY == "change-me-in-production-32bytes!":
            errors.append("ENCRYPTION_KEY must be changed from the default value")
        if len((self.ENCRYPTION_KEY or "").strip()) < 16:
            errors.append("ENCRYPTION_KEY must be at least 16 characters")
        if self.ADMIN_PASSWORD == "L0ngevity!123":
            errors.append("ADMIN_PASSWORD must be changed from the default value")
        if not self.AUTH_COOKIE_SECURE:
            errors.append("AUTH_COOKIE_SECURE must be true in production-like environments")
        if (self.AUTH_COOKIE_SAMESITE or "").strip().lower() == "none" and not self.AUTH_COOKIE_SECURE:
            errors.append("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")
        if errors:
            joined = "; ".join(errors)
            raise RuntimeError(f"Insecure production configuration: {joined}")


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
