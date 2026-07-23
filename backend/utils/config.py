"""Centralized application configuration, loaded once from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings sourced from `.env`.

    Using pydantic-settings instead of raw `os.environ` gives us type
    coercion (e.g. EASY_MAX_WORDS -> int) and fails fast at startup if a
    required value is malformed, rather than crashing mid-request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    database_url: str = "sqlite:///./modelpilot.db"
    log_level: str = "INFO"

    easy_max_words: int = 30
    medium_max_words: int = 100


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    FastAPI's dependency-injection system calls this on every request that
    declares it as a dependency; `lru_cache` ensures the .env file is parsed
    only once per process instead of on every call.
    """
    return Settings()
