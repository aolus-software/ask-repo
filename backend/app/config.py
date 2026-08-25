"""Application settings, loaded from the environment (and `.env` in development)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRET_KEY = "dev-insecure-change-me"


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

    # Datastores. Postgres and Redis are read from M0; Qdrant from M1.
    database_url: str = "postgresql+asyncpg://askrepo:askrepo@localhost:5432/askrepo"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str = PLACEHOLDER_SECRET_KEY
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "askrepo_refresh"
    refresh_cookie_path: str = "/auth"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Two tabs refreshing at once would otherwise log the user out (D12).
    refresh_rotation_grace_seconds: int = 10

    # Passwords
    password_min_length: int = 12
    # bcrypt ignores anything past 72 bytes, so this is a correctness bound (D24).
    password_max_bytes: int = 72
    bcrypt_cost: int = 12
    common_password_list_path: Path = (
        Path(__file__).parent / "core" / "data" / "common-passwords.txt"
    )

    # Bootstrap
    bootstrap_admin_emails: list[str] = ["superuser@example.com", "admin@example.com"]
    bootstrap_admin_password: str | None = None

    # Login rate limiting
    login_rate_per_minute_ip: int = 5
    login_rate_per_hour_email: int = 10
    # Caddy sits in front (docs/PRD.md:304); without this every request looks like
    # it came from the proxy and the per-IP limit becomes instance-wide.
    trusted_proxy_hops: int = 0

    @model_validator(mode="after")
    def _reject_development_defaults_in_production(self) -> Self:
        """Fail fast rather than serve production traffic with a known signing key."""
        if self.app_env != "production":
            return self
        if self.secret_key == PLACEHOLDER_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set to a real value when APP_ENV=production")
        if not self.refresh_cookie_secure:
            raise ValueError("REFRESH_COOKIE_SECURE cannot be false when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so settings are parsed once per process."""
    return Settings()
