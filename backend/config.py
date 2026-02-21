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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
