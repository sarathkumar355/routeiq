"""
Application configuration.

All configuration is loaded from environment variables (via a local .env
file during development). Nothing here is hardcoded, and nothing here is
required for the app to boot in Phase 1 — DATABASE_URL and GEMINI_API_KEY
are optional so the service can start even before Postgres or the LLM key
are configured. Later phases will start depending on DATABASE_URL for real
functionality, but /health must never require it.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App metadata ---
    app_name: str = "RouteIQ"
    environment: str = "development"  # development | test | production

    # --- Database (optional in Phase 1) ---
    database_url: Optional[str] = None

    # --- AI provider (optional in Phase 1, required starting Phase 5) ---
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None



@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (avoids re-parsing env on every call)."""
    return Settings()
