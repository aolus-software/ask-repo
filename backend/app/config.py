"""Application settings, loaded from the environment (and `.env` in development)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRET_KEY = "dev-insecure-change-me"
PLACEHOLDER_PAT_KEY = "dev-insecure-change-me"


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

    # Kafka — the ingestion job queue (docs/PRD.md §5, amended at M1).
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_ingest_topic: str = "askrepo.ingest.requested"
    kafka_consumer_group: str = "askrepo-ingest"
    # Concurrency is partition count: docs/PRD.md §4.1 caps ingestion at 2, and
    # here that cap is the topology rather than a setting one can raise by accident.
    kafka_ingest_partitions: int = 2
    kafka_max_attempts: int = 3

    # Embedding — provider selected at runtime, dimensions probed rather than declared.
    embedding_provider: Literal["ollama", "openai", "voyage"] = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_base_url: str = "http://localhost:11434"
    embedding_api_key: str = ""
    embedding_batch_size: int = 64

    # Ingestion — repository cloning and chunking.
    # Must be a JSON array. Any host not listed is rejected before DNS resolution.
    repo_host_allowlist: list[str] = ["github.com", "gitlab.com"]
    clone_timeout_seconds: int = 120
    repo_max_size_mb: int = 500
    # Scratch space, not a persistent volume: the working copy is deleted after
    # indexing, and reindex re-clones rather than pulling.
    repo_scratch_dir: Path = Path("/data/repos")
    chunk_size: int = 1200
    chunk_overlap: int = 150
    max_indexed_file_bytes: int = 1_048_576

    # Encrypts stored PATs at rest (docs/PRD.md §9). Backed up separately from
    # the database — a backup holding both is plaintext storage with extra steps.
    pat_encryption_key: str = PLACEHOLDER_PAT_KEY

    @model_validator(mode="after")
    def _reject_development_defaults_in_production(self) -> Self:
        """Fail fast rather than serve production traffic with a known signing key."""
        if self.app_env != "production":
            return self
        if self.secret_key == PLACEHOLDER_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set to a real value when APP_ENV=production")
        if not self.refresh_cookie_secure:
            raise ValueError("REFRESH_COOKIE_SECURE cannot be false when APP_ENV=production")
        if self.trusted_proxy_hops == 0:
            raise ValueError(
                "TRUSTED_PROXY_HOPS must be set to the number of proxies in front of the "
                "API when APP_ENV=production — left at 0 behind Caddy, every request "
                "looks like it came from the proxy and the per-IP rate limit becomes "
                "instance-wide"
            )
        if self.pat_encryption_key == PLACEHOLDER_PAT_KEY:
            raise ValueError(
                "PAT_ENCRYPTION_KEY must be set to a real Fernet key when "
                "APP_ENV=production — PATs encrypted with a known key are not encrypted. "
                "Generate: python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so settings are parsed once per process."""
    return Settings()
