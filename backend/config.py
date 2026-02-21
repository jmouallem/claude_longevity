from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = "change-me-in-production-32bytes!"
    DATABASE_URL: str = "sqlite:///data/longevity.db"
    DATA_DIR: Path = Path("data")
    UPLOAD_DIR: Path = Path("data/uploads")
    CORS_ORIGINS: list[str] = ["http://localhost:8050", "http://localhost:8001"]
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
    ENABLE_LONGITUDINAL_ANALYSIS: bool = True
    ANALYSIS_AUTORUN_ON_CHAT: bool = True
    ANALYSIS_DAILY_HOUR_LOCAL: int = 20
    ANALYSIS_WEEKLY_WEEKDAY_LOCAL: int = 6  # Sunday
    ANALYSIS_MONTHLY_DAY_LOCAL: int = 1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
