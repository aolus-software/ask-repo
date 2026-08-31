"""Application settings, loaded from the environment (and `.env` in development)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
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
    embedding_api_key: str | None = None
    # `ge=1` is load-bearing, not decoration: at 0 the pipeline's batching loop
    # (`while len(batch) >= batch_size`) never drains, so it flushes empty batches
    # forever while the lease keeps renewing — no log, no timeout, no failure.
    embedding_batch_size: int = Field(default=64, ge=1)

    # Ingestion — repository cloning and chunking.
    # Must be a JSON array. Any host not listed is rejected before DNS resolution.
    repo_host_allowlist: list[str] = ["github.com", "gitlab.com"]
    # All three are resource controls, and a control set to zero or below is not
    # one: a zero timeout kills every clone, a zero cap rejects every repository,
    # and a zero file limit indexes nothing at all. Fail at startup instead.
    clone_timeout_seconds: int = Field(default=120, ge=1)
    repo_max_size_mb: int = Field(default=500, ge=1)
    # Scratch space, not a persistent volume: the working copy is deleted after
    # indexing, and reindex re-clones rather than pulling.
    repo_scratch_dir: Path = Path("/data/repos")
    chunk_size: int = 1200
    chunk_overlap: int = 150
    max_indexed_file_bytes: int = Field(default=1_048_576, ge=1)

    # Chat model — the answering LLM (docs/PRD.md §5). Separate from the embedding
    # provider on purpose: the two are different models with different endpoints,
    # and an instance commonly runs a local embedder with a hosted answerer.
    chat_provider: Literal["ollama", "openai"] = "ollama"
    chat_model: str = "qwen2.5-coder:14b"
    chat_base_url: str = "http://localhost:11434"
    chat_api_key: str | None = None
    # Low but not zero: code answers should be reproducible, not creative.
    chat_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    chat_timeout_seconds: int = Field(default=180, ge=1)
    # Ollama serialises inference internally, so uncapped concurrency does not make
    # answers arrive faster — it makes every answer slower and can exhaust a box
    # already running Postgres, Qdrant, Redis and Kafka (docs/PRD.md §9).
    chat_max_concurrency: int = Field(default=2, ge=1)

    # Retrieval. Every bound is `ge=`-guarded for the same reason
    # `embedding_batch_size` is: a zero does not fail, it silently sends an empty
    # context and the model answers from memory in the same confident tone.
    rag_top_k: int = Field(default=12, ge=1)
    rag_context_max_chars: int = Field(default=24_000, ge=1000)
    # Zero is legitimate here — it disables multi-turn memory entirely.
    rag_history_turns: int = Field(default=6, ge=0)
    # Cosine similarity a chunk must reach to be shown to the model at all. Below
    # this the embedder is saying "unrelated", and answering from unrelated code is
    # how a fluent, confident, entirely wrong answer gets produced. 0.0 disables the
    # floor; raise it if answers cite plausible-looking but irrelevant files.
    rag_min_score: float = Field(default=0.25, ge=0.0, le=1.0)
    # How many times retrieval may run for one question: the first attempt plus any
    # the grader asks for. `ge=1` rather than `ge=0` because zero does not fail — it
    # would skip retrieval entirely and refuse every question on the instance with
    # `no_context`, against an index that is perfectly healthy.
    rag_max_retrieval_attempts: int = Field(default=2, ge=1)
    # Both default on. They exist so `docs/PRD.md` §6's per-node local-vs-hosted
    # benchmark can run the graph with a node disabled and measure what it buys;
    # disabled, each short-circuits to the same value its failure path produces, so
    # there is one code path rather than two.
    rag_grade_evidence: bool = True
    rag_classify_intent: bool = True

    # Rows above which the export refuses rather than building a workbook in
    # memory. `openpyxl` allocates the whole book even in write-only mode, so this
    # cap is the only thing bounding it.
    qa_export_max_rows: int = 5000

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
