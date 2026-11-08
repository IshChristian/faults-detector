from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str
    redis_url: str
    secret_key: str
    credentials_encryption_key: str
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    media_root: Path = Path("/app/media")
    default_timezone: str = "Africa/Kigali"
    login_rate_limit_per_minute: int = 5
    cookie_secure: bool = True
    storage_backend: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
