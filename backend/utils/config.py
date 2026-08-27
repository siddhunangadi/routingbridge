"""Centralized application configuration, loaded once from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings sourced from `.env`.

    Using pydantic-settings instead of raw `os.environ` gives us type
    coercion (for example, threshold text to a float) and fails fast at startup if a
    required value is malformed, rather than crashing mid-request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_api_key: str = ""
    openrouter_api_key: str = ""

    database_url: str = "sqlite:///./modelpilot.db"
    log_level: str = "INFO"

    router_mode: Literal["llm", "local", "validation"] = "local"
    local_router_artifact_dir: str = "artifacts/local_router"
    bge_cache_dir: str = "artifacts/bge"
    local_router_fallback_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    FastAPI's dependency-injection system calls this on every request that
    declares it as a dependency; `lru_cache` ensures the .env file is parsed
    only once per process instead of on every call.
    """
    return Settings()
