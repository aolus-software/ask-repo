"""Application settings, loaded from the environment (and `.env` in development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "AskRepo API"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = True

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS — set as a JSON array in the environment, e.g. '["http://localhost:3000"]'
    cors_origins: list[str] = ["http://localhost:3000"]

    # Datastores — wired ahead of the milestones that use them, not read yet.
    # Postgres: users/projects/qa_pairs (M0). Qdrant: vectors (M1).
    # Redis: rate limiting (M0), then the ingestion job queue (M1).
    database_url: str = "postgresql://askrepo:askrepo@localhost:5432/askrepo"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    """Cached so settings are parsed once per process."""
    return Settings()
