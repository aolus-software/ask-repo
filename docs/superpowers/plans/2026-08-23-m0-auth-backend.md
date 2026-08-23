# AskRepo M0 — Auth & Accounts (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend half of M0 — a persistence layer, an admin-provisioned auth API with rotating refresh tokens, and login rate limiting — so every later milestone can attribute a request to a user.

**Architecture:** Three layers, route → service → repository, on async SQLAlchemy 2.0. Identity is established once per request by an HTTP middleware that decodes the bearer token, loads the user row, and blocks every route outside `/auth` while `must_change_password` is set; dependencies read what it stashed. Access tokens are stateless 15-minute JWTs returned in the response body; refresh tokens are opaque, stored as SHA-256 hashes, rotated on use, and carried in an httpOnly cookie.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (asyncpg), Alembic, bcrypt, PyJWT, redis-py (async), Pydantic v2 / pydantic-settings, pytest + pytest-asyncio, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-08-23-m0-auth-backend-design.md` — read it alongside this plan. Decision IDs below (D1–D24) refer to its §2 table; section refs (§4, §5, …) refer to its sections.

## Global Constraints

- **Python** `>=3.13`; **line length** 100; ruff selects `E,F,I,UP,B,ANN,T20,LOG,G,RUF`.
- **Every function and method carries annotated parameters and an explicit return type**, including `-> None` (`.claude/rules/clean-code.md`). Enforced by ruff `ANN` and, from Task 1, mypy.
- **Never `print()`** (ruff `T20`). Module-level `logger = logging.getLogger(__name__)`.
- **`# noqa` / `# type: ignore` require a reason on the same line.**
- **Every request and response schema inherits `ApiModel`** from `app/schemas/base.py` — `snake_case` internally, `camelCase` on the wire (`.claude/rules/response-api.md`).
- **Every route declares `response_model`, `status_code`, a `summary`, and an exhaustive `responses` block** traced from what the handler and its dependencies actually raise.
- **Every error raised by application code uses `AppError`**, never bare `HTTPException`.
- **Services never import `select` / `insert` / `update` from SQLAlchemy.** Only repositories do.
- **All reads go through `BaseRepository.active_select()`**; a query wanting deleted rows uses a method whose name says so (`get_including_deleted`).
- **No secret in any response, log, or traceback** — no `password`, `password_hash`, raw token, or full `DATABASE_URL`.
- **Timestamps:** UTC, timezone-aware, `timestamptz` columns.
- **IDs:** application-generated `uuid4`, never sequential.
- **Password policy:** minimum 12 characters, maximum **72 bytes after UTF-8 encoding** (D24), rejected if in the vendored wordlist. bcrypt cost 12.
- **`403` vs `404`:** `403` when the caller may see the resource but not act on it; `404` when they should not learn it exists.
- **Tests require datastores.** `make infra` must be running. Tests use the `askrepo_test` database and Redis DB index 15.
- **Docs change in the same commit as the code that invalidates them** (`.claude/rules/documentation.md`). Each task below names its own doc edits; Task 14 handles only the cross-cutting sweep.

---

## File Structure

**New — core primitives (no HTTP, no DB):**
- `app/core/security.py` — bcrypt hash/verify/needs-rehash, SHA-256, JWT encode/decode, opaque token mint. Raises its own exceptions, never `HTTPException`.
- `app/core/passwords.py` — password policy check against length bounds and a wordlist.
- `app/core/data/common-passwords.txt` — vendored wordlist (data, not code).
- `app/core/errors.py` — `ErrorCode`, `AppError`, exception handlers.
- `app/core/access.py` — `ProjectScope`, `resolve_project_scope`. The phase-2 seam.

**New — persistence:**
- `app/models/base.py` — `Base` with an explicit naming convention, `TimestampMixin`, `SoftDeleteMixin`.
- `app/models/user.py`, `app/models/refresh_token.py` — one model per file.
- `app/db/session.py` — lazily built async engine, sessionmaker, `get_session`.
- `app/repositories/base.py` — `BaseRepository`, owner of the soft-delete guarantee.
- `app/repositories/user.py`, `app/repositories/refresh_token.py`.
- `alembic.ini`, `alembic/env.py`, `alembic/versions/<rev>_initial_auth_tables.py`.

**New — HTTP:**
- `app/core/middleware.py` — `AuthenticatedUser`, `AuthContext`, `AuthContextMiddleware`.
- `app/core/rate_limit.py` — Redis fixed-window limiter dependency.
- `app/api/deps.py` — `CurrentUser` / `AdminUser` aliases, session and service providers.
- `app/schemas/pagination.py`, `app/schemas/errors.py`, `app/schemas/auth.py`, `app/schemas/user.py`.
- `app/services/user.py`, `app/services/auth.py`.
- `app/api/routes/users.py`, `app/api/routes/auth.py`.
- `app/cli.py` — `seed-admins`.

**Modified:**
- `backend/pyproject.toml` — dependencies, pytest asyncio config, mypy config.
- `app/config.py` — new settings plus production validation.
- `app/main.py` — middleware registration (gate **before** CORS), exception handlers, two routers.
- `backend/tests/conftest.py` — database and Redis harness.
- `backend/.env.example`, `infra/backend.Dockerfile`, `infra/docker-compose.yml`, `Makefile`.
- Docs and rules per each task, plus Task 15.

**Why these boundaries:** the four `app/core/*` primitives have no dependencies on each other and no I/O, so Tasks 3–5 can be reviewed in isolation. Repositories are split from services so the soft-delete guarantee is testable without business logic. The middleware is its own task because it is the one piece whose failure mode is silent (a route that should be gated but isn't).

---

## Task 1: Dependencies, settings, and production validation

Nothing else can be written until the settings that everything reads exist and the toolchain can install.

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` with the fields below; `get_settings() -> Settings` (already exists, unchanged signature). Every later task reads settings through `Depends(get_settings)` or, in the middleware and CLI, by calling `get_settings()` directly.

New `Settings` fields, exact names and defaults:

```python
secret_key: str = "dev-insecure-change-me"
access_token_ttl_minutes: int = 15
refresh_token_ttl_days: int = 30
refresh_cookie_name: str = "askrepo_refresh"
refresh_cookie_path: str = "/auth"
refresh_cookie_secure: bool = True
refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
refresh_rotation_grace_seconds: int = 10
bootstrap_admin_emails: list[str] = ["superuser@example.com", "admin@example.com"]
bootstrap_admin_password: str | None = None
password_min_length: int = 12
password_max_bytes: int = 72
bcrypt_cost: int = 12
login_rate_per_minute_ip: int = 5
login_rate_per_hour_email: int = 10
trusted_proxy_hops: int = 0
common_password_list_path: Path = Path(__file__).parent / "core" / "data" / "common-passwords.txt"
```

`database_url`'s default changes to `postgresql+asyncpg://askrepo:askrepo@localhost:5432/askrepo`.

- [ ] **Step 1: Add dependencies**

In `backend/pyproject.toml`, set `dependencies` and `dev` to:

```toml
dependencies = [
    "fastapi>=0.120.0",
    "pydantic[email]>=2.10.0",
    "pydantic-settings>=2.7.0",
    "uvicorn[standard]>=0.34.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "bcrypt>=4.2.0",
    "pyjwt>=2.10.0",
    "redis>=5.2.0",
]

[dependency-groups]
dev = [
    "httpx>=0.28.0",
    "mypy>=1.14.0",
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "ruff>=0.9.0",
]
```

`pydantic[email]` brings `email-validator`, which `EmailStr` needs. `sqlalchemy[asyncio]` brings `greenlet`, which the async engine needs.

- [ ] **Step 2: Add pytest asyncio and mypy configuration**

Replace the `[tool.pytest.ini_options]` block and append a mypy block:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
# Session scope: the engine fixture is session-scoped, and a function-scoped
# loop would leave it bound to a closed loop on the second test.
asyncio_default_fixture_loop_scope = "session"

[tool.mypy]
python_version = "3.13"
files = ["app", "tests"]
strict = true
# SQLAlchemy 2.0 ships PEP 484 typing natively — no plugin, no sqlalchemy2-stubs.
```

- [ ] **Step 3: Install and confirm the toolchain resolves**

Run: `cd backend && uv sync`
Expected: resolves and installs without error. `uv run python -c "import bcrypt, jwt, asyncpg, alembic, redis"` prints nothing and exits 0.

- [ ] **Step 4: Write the failing settings tests**

Create `backend/tests/test_config.py`:

```python
"""Settings defaults and the production guards.

`Settings` is the only place that reads the environment (`CLAUDE.md`), so a wrong
default here is invisible until deployment. The production validators exist because
`SECURITY.md:54` promises operators that a real `SECRET_KEY` is required.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_database_url_default_uses_the_async_driver() -> None:
    """A sync driver silently breaks the async engine at first connect."""
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_password_max_bytes_is_bcryptsafe() -> None:
    """bcrypt ignores input past 72 bytes; a larger cap would allow silent truncation."""
    assert Settings().password_max_bytes == 72


def test_development_tolerates_the_placeholder_secret() -> None:
    settings = Settings(app_env="development")

    assert settings.secret_key == "dev-insecure-change-me"


def test_production_rejects_the_placeholder_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production")


def test_production_rejects_an_insecure_refresh_cookie() -> None:
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            app_env="production",
            secret_key="a-real-secret-value-for-testing-only",
            refresh_cookie_secure=False,
        )


def test_production_accepts_a_complete_configuration() -> None:
    settings = Settings(
        app_env="production",
        secret_key="a-real-secret-value-for-testing-only",
    )

    assert settings.app_env == "production"
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL — `test_database_url_default_uses_the_async_driver` and the three production tests fail; `test_password_max_bytes_is_bcryptsafe` fails with `AttributeError`.

- [ ] **Step 6: Add the settings and the validator**

In `backend/app/config.py`, add imports and the new fields, then the validator. The full new content of the class body follows the existing Application/Server/CORS blocks:

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRET_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    # ... existing model_config, Application, Server, CORS blocks unchanged ...

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
    common_password_list_path: Path = Path(__file__).parent / "core" / "data" / "common-passwords.txt"

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
```

`bootstrap_admin_password` is deliberately **not** validated here: only the seed command needs it, and an already-seeded instance must be able to boot without it (§11).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 8: Document every new setting**

Append to `backend/.env.example`, after the existing Datastores block. Change the `DATABASE_URL` line in that block to `postgresql+asyncpg://askrepo:askrepo@localhost:5432/askrepo` and update its comment to note the driver is required, not optional.

```bash
# --- Auth ---
# Signs access tokens. MUST be replaced in production — the app refuses to boot
# with this value when APP_ENV=production. Generate: openssl rand -hex 32
SECRET_KEY=dev-insecure-change-me
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=30

# The refresh token is an httpOnly cookie, never readable by JavaScript.
REFRESH_COOKIE_NAME=askrepo_refresh
REFRESH_COOKIE_PATH=/auth
# `Secure` is on even in development: browsers treat http://localhost as a secure
# context, so the cookie is still set, and dev matches production.
REFRESH_COOKIE_SECURE=true
# `lax` covers same-site deployments, localhost:3000 -> localhost:8000 included.
# A genuinely cross-site deployment needs `none`, which requires Secure=true.
REFRESH_COOKIE_SAMESITE=lax
# Grace period in which a just-rotated token is not treated as a replay, so two
# browser tabs refreshing at once do not log the user out.
REFRESH_ROTATION_GRACE_SECONDS=10

# --- Passwords ---
PASSWORD_MIN_LENGTH=12
# bcrypt ignores input past 72 bytes. Raising this would allow two different long
# passwords to authenticate against the same hash. Do not raise it.
PASSWORD_MAX_BYTES=72
BCRYPT_COST=12

# --- Bootstrap admins ---
# Seeded by `make seed` / the container entrypoint. Both accounts are created with
# must_change_password set. Change them before letting anyone else in.
BOOTSTRAP_ADMIN_EMAILS=["superuser@example.com","admin@example.com"]
BOOTSTRAP_ADMIN_PASSWORD=

# --- Login rate limiting ---
LOGIN_RATE_PER_MINUTE_IP=5
LOGIN_RATE_PER_HOUR_EMAIL=10
# Number of trusted reverse proxies in front of the API. 0 means ignore
# X-Forwarded-For entirely and trust the socket address. Behind one Caddy, set 1 —
# otherwise every request looks like it came from Caddy and the per-IP login limit
# becomes a single instance-wide limit.
TRUSTED_PROXY_HOPS=0
```

- [ ] **Step 9: Verify lint, types, and the full suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass. Existing `test_api_model.py` and `test_meta_routes.py` still pass.

- [ ] **Step 10: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py backend/.env.example backend/tests/test_config.py
git commit -m "feat(config): add auth settings and production guards

Adds the settings M0 needs — JWT signing and TTLs, refresh cookie
attributes, password policy bounds, bootstrap admin credentials, login
rate limits, and the trusted-proxy hop count — plus a validator that
refuses to boot production with the placeholder secret or an insecure
refresh cookie.

DATABASE_URL's default gains the +asyncpg driver; the sync driver would
fail at first connect once the async engine lands.

Adds SQLAlchemy, asyncpg, Alembic, bcrypt, PyJWT, redis, pytest-asyncio
and mypy. mypy runs strict over app and tests."
```

---

## Task 2: Models, migrations, and the database test harness

The harness is folded in here because a migration cannot be verified without a test database, and
nothing later can be tested without both.

**Files:**
- Create: `backend/app/models/__init__.py`, `base.py`, `user.py`, `refresh_token.py`
- Create: `backend/app/db/__init__.py`, `backend/app/db/session.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial_auth_tables.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_schema.py`
- Docs: `docs/PRD.md` §5.1 — the `refresh_tokens` exception to the soft-delete convention

**Interfaces:**
- Consumes: `Settings.database_url` (Task 1).
- Produces:
  - `app.models.base.Base` — `DeclarativeBase` with a naming convention.
  - `app.models.base.TimestampMixin` — `created_at: datetime`, `updated_at: datetime`.
  - `app.models.base.SoftDeleteMixin` — `deleted_at: datetime | None`.
  - `app.models.user.User` — columns per §4.
  - `app.models.refresh_token.RefreshToken`, `RevokedReason` (a `Literal` alias).
  - `app.db.session.get_engine() -> AsyncEngine`, `get_sessionmaker() -> async_sessionmaker[AsyncSession]`, `get_session() -> AsyncIterator[AsyncSession]` (FastAPI dependency), `reset_engine() -> None` (test hook).
  - Fixtures: `db_session`, `redis_client`, `app`, `client` (async).

- [ ] **Step 1: Create the declarative base and mixins**

Create `backend/app/models/base.py`:

```python
"""Declarative base and the column mixins every table shares.

The explicit naming convention matters more than it looks: without it, Postgres
names constraints itself, Alembic autogenerate produces churn on every run, and a
migration cannot reliably drop a constraint it did not name.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of every ORM model. `metadata` is Alembic's autogenerate target."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """`created_at` / `updated_at`, both timezone-aware.

    `onupdate` is a Python-side default: it fires for ORM flushes but NOT for bulk
    `UPDATE` statements. Repository methods issuing bulk updates set `updated_at`
    explicitly — see `.claude/rules/persistence.md`.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SoftDeleteMixin:
    """`deleted_at`. Rows are never removed; queries filter `deleted_at IS NULL`.

    Carrying this mixin is what makes `BaseRepository.active_select()` apply the
    filter, so a model that should be soft-deletable and lacks it will silently
    return deleted rows.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Create the User model**

Create `backend/app/models/user.py`:

```python
"""The `users` table — see `docs/PRD.md` §3 for the schema of record."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    """An account. Provisioned by an admin; there is no self-service signup."""

    __tablename__ = "users"
    __table_args__ = (
        # Partial: a soft-deleted account frees its address for reuse, and every
        # lookup filters `deleted_at IS NULL` anyway (D20). Doubles as the login
        # lookup index.
        Index(
            "uq_users_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # bcrypt output is always 60 chars; 255 leaves room for a future argon2id move.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Create the RefreshToken model**

Create `backend/app/models/refresh_token.py`:

```python
"""The `refresh_tokens` table.

Deliberately carries no `deleted_at`, unlike every other table: its lifecycle is
`revoked_at` / `expires_at`, and a third overlapping state column that nothing sets
would be worse than the documented exception (D14, `docs/PRD.md` §5.1).

Only the SHA-256 of a token is stored. The raw value exists in the response cookie
and nowhere else.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RevokedReason = Literal[
    "rotated",
    "replay",
    "logout",
    "logout_all",
    "password_change",
    "admin_reset",
    "user_deactivated",
]


class RefreshToken(Base):
    """One issued refresh token. Rotation inserts a successor sharing `family_id`."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        # No cascade: users are soft-deleted, never removed.
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    # The rotation chain. Replay detection revokes exactly one device's family.
    family_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # SHA-256 hex is always exactly 64 characters.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

- [ ] **Step 4: Export the models so Alembic sees them**

Create `backend/app/models/__init__.py`:

```python
"""ORM models. Importing this package registers every table on `Base.metadata`,
which is what makes Alembic autogenerate able to see them."""

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.refresh_token import RefreshToken, RevokedReason
from app.models.user import User

__all__ = [
    "Base",
    "RefreshToken",
    "RevokedReason",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
]
```

Create an empty `backend/app/db/__init__.py`.

- [ ] **Step 5: Create the session module**

Create `backend/app/db/session.py`:

```python
"""Async engine, sessionmaker, and the request-scoped session dependency.

The engine is built lazily rather than at import time, and that is load-bearing:
`AuthContextMiddleware` builds its own session from the sessionmaker instead of
through `Depends`, so a test that only overrode the `get_session` dependency would
leave the middleware talking to the development database. Lazy construction means a
settings override reaches both paths (§11).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory. Used by `get_session` and, directly, by the auth middleware."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose the engine and clear the cached factory. Test hook only."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request. Services own commits."""
    async with get_sessionmaker()() as session:
        yield session
```

`expire_on_commit=False` so a committed ORM object's attributes remain readable without a
refresh round-trip — services return objects that routes then serialize.

- [ ] **Step 6: Initialise Alembic**

Run: `cd backend && uv run alembic init -t async alembic`
Expected: creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`.

- [ ] **Step 7: Point Alembic at the app's settings and metadata**

Replace the body of `backend/alembic/env.py` with:

```python
"""Alembic environment. Reads the URL from app settings, not alembic.ini.

Keeping one source of configuration means `alembic upgrade head` and the running app
can never disagree about which database they mean.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

In `backend/alembic.ini`, set `script_location = alembic`, remove any `sqlalchemy.url` value
(leave the key absent — `env.py` supplies it), and set
`file_template = %%(rev)s_%%(slug)s` so revision filenames are readable.

- [ ] **Step 8: Write the initial migration**

Create `backend/alembic/versions/0001_initial_auth_tables.py`. Written by hand rather than
autogenerated so the partial index is unambiguous:

```python
"""initial auth tables

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(
        "uq_users_email_active",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="NO ACTION"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("uq_users_email_active", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 9: Write the test harness**

Replace `backend/tests/conftest.py` entirely:

```python
"""Shared fixtures.

Tests run against real Postgres and real Redis (D8): `timestamptz`, the partial
unique index on `email`, and asyncpg itself all behave differently on SQLite, and a
suite that passes on SQLite while production breaks is worse than no suite.

`make infra` must be running. See CONTRIBUTING.md.
"""

import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker, reset_engine
from app.models import Base

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_NAME = "askrepo_test"
TEST_REDIS_DB = 15


def _swap_database(url: str, name: str) -> str:
    """Replace the database name in a connection URL, keeping credentials and host."""
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture(scope="session", autouse=True)
def _test_environment() -> Iterator[None]:
    """Point settings at the test database and Redis DB before anything reads them.

    Environment rather than a dependency override, because the auth middleware calls
    `get_settings()` directly rather than through `Depends` (see app/db/session.py).
    """
    dev = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("APP_ENV", "test")
        patch.setenv("DATABASE_URL", _swap_database(dev.database_url, TEST_DB_NAME))
        patch.setenv("REDIS_URL", _swap_database(dev.redis_url, str(TEST_REDIS_DB)))
        patch.setenv("SECRET_KEY", "test-secret-key-not-used-anywhere-real")
        patch.setenv("BCRYPT_COST", "4")  # keep the suite fast; cost is not under test
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def _migrated_database(_test_environment: None) -> AsyncIterator[None]:
    """Create `askrepo_test` if absent and bring it to head.

    Runs the real migrations, never `create_all`: the migrations are part of what is
    under test, and the partial index must be exercised exactly as shipped.
    """
    settings = get_settings()
    admin_url = _swap_database(settings.database_url, "postgres").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    connection = await asyncpg.connect(admin_url)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await connection.close()

    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_ROOT, check=True
    )
    yield
    await reset_engine()


@pytest.fixture(autouse=True)
async def _clean_tables(_migrated_database: None) -> AsyncIterator[None]:
    """Empty every table between tests.

    TRUNCATE rather than a rolled-back outer transaction: services commit, and the
    savepoint-restart recipe needed to survive a commit is fragile enough to produce
    failures that look like product bugs.
    """
    tables = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session for tests that talk to repositories directly."""
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    """Redis on the test DB index, flushed before use."""
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def app() -> FastAPI:
    """A freshly built app, so middleware and overrides don't leak between tests."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client. `AsyncClient` rather than `TestClient` so route tests share
    the event loop with the database fixtures."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
```

`BCRYPT_COST=4` in tests is deliberate: cost 12 takes roughly a quarter-second per hash, and the
suite hashes on nearly every test. Cost correctness is asserted against settings in Task 1, not
by making every test slow.

- [ ] **Step 10: Write the failing schema tests**

Create `backend/tests/test_schema.py`:

```python
"""What the migration actually produced.

These assert against the live database rather than the model definitions, because a
model and a hand-written migration can disagree — and the migration is what runs.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_users_email_is_unique_only_among_live_rows(db_session: AsyncSession) -> None:
    """Soft-deleting an account frees its address for reuse (D20)."""
    await db_session.execute(
        text(
            "INSERT INTO users (id, name, email, password_hash, deleted_at)"
            " VALUES (gen_random_uuid(), 'A', 'a@example.com', 'x', now())"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, name, email, password_hash)"
            " VALUES (gen_random_uuid(), 'B', 'a@example.com', 'x')"
        )
    )
    await db_session.commit()

    live = await db_session.execute(
        text("SELECT count(*) FROM users WHERE email = 'a@example.com' AND deleted_at IS NULL")
    )
    assert live.scalar_one() == 1


async def test_two_live_rows_cannot_share_an_email(db_session: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    for _ in range(2):
        await db_session.execute(
            text(
                "INSERT INTO users (id, name, email, password_hash)"
                " VALUES (gen_random_uuid(), 'A', 'dup@example.com', 'x')"
            )
        )
    try:
        await db_session.commit()
    except IntegrityError:
        return
    raise AssertionError("expected the partial unique index to reject a duplicate live email")


async def test_timestamps_are_timezone_aware(db_session: AsyncSession) -> None:
    """`docs/PRD.md:321` requires timestamptz; a naive column loses the offset."""
    result = await db_session.execute(
        text(
            "SELECT data_type FROM information_schema.columns"
            " WHERE table_name = 'users' AND column_name = 'created_at'"
        )
    )
    assert result.scalar_one() == "timestamp with time zone"


async def test_refresh_tokens_has_no_deleted_at(db_session: AsyncSession) -> None:
    """D14: its lifecycle is revoked_at/expires_at. A third state column would rot."""
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'refresh_tokens' AND column_name = 'deleted_at'"
        )
    )
    assert result.scalar_one() == 0


async def test_token_hash_is_unique(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM pg_indexes"
            " WHERE tablename = 'refresh_tokens' AND indexname = 'uq_refresh_tokens_token_hash'"
        )
    )
    assert result.scalar_one() == 1


async def test_downgrade_then_upgrade_is_clean() -> None:
    """A migration that cannot be reversed cannot be iterated on safely."""
    import subprocess

    from tests.conftest import BACKEND_ROOT

    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(["uv", "run", "alembic", *args], cwd=BACKEND_ROOT, check=True)
```

- [ ] **Step 11: Run the schema tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_schema.py -v`
Expected: FAIL — the `askrepo_test` database and tables do not exist yet on the first run; after
the fixture creates them, failures should be zero. If the run errors with
`connection refused`, `make infra` is not running.

- [ ] **Step 12: Run the migration and confirm the suite passes**

Run: `cd backend && uv run pytest tests/test_schema.py -v`
Expected: PASS, 6 tests. `gen_random_uuid()` requires Postgres 13+; the Compose image is
`postgres:17-alpine`, so it is built in.

- [ ] **Step 13: Amend the PRD's soft-delete convention**

In `docs/PRD.md` §5.1, replace the soft-delete bullet with wording that scopes the convention and
names the exception:

```markdown
- **Soft delete:** every table representing a user-facing resource carries `deleted_at`, and all
  queries filter `deleted_at IS NULL`. Unique constraints must account for it — `users.email` is
  unique only among rows where `deleted_at IS NULL`, so a departed colleague's address can be
  reused.
- **`refresh_tokens` is an explicit exception.** Its lifecycle is `revoked_at` / `expires_at`, and
  a `deleted_at` column would be a third overlapping state that nothing sets. Revoked and expired
  rows are hard-deleted by a cleanup path (M1, with the job scheduler).
```

- [ ] **Step 14: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 15: Commit**

```bash
git add backend/app/models backend/app/db backend/alembic backend/alembic.ini \
        backend/tests/conftest.py backend/tests/test_schema.py docs/PRD.md
git commit -m "feat(db): add users and refresh_tokens with the async persistence layer

Declarative base with an explicit naming convention so Alembic diffs stay
stable, timestamp and soft-delete mixins, and the two M0 tables. The
unique index on users.email is partial, scoped to live rows, so a
soft-deleted account frees its address.

refresh_tokens carries no deleted_at: its lifecycle is
revoked_at/expires_at, and a third state column nothing sets would rot.
docs/PRD.md 5.1 is amended to scope the convention and name the
exception rather than leave the code contradicting it.

The engine is built lazily from settings, not at import: the auth
middleware will build sessions from the sessionmaker directly rather
than through Depends, so overriding only the dependency would leave it
pointed at the dev database.

Tests run against real Postgres in askrepo_test, migrated with alembic
rather than create_all so the partial index is exercised as shipped."
```

---

## Task 3: Cryptographic primitives

No HTTP, no database, no settings coupling beyond values passed in as arguments. Everything here
is a pure function, which is why it can be tested exhaustively and fast.

**Files:**
- Create: `backend/app/core/__init__.py`, `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`
- Docs: `docs/PRD.md:73`, `:110`, `:301`, `:382` — the argon2id → bcrypt amendments

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BCRYPT_MAX_BYTES: Final[int] = 72`
  - `hash_password(password: str, *, cost: int) -> str` — raises `PasswordTooLongError`
  - `verify_password(password: str, password_hash: str) -> bool`
  - `needs_rehash(password_hash: str, *, cost: int) -> bool`
  - `sha256_hex(value: str) -> str`
  - `generate_opaque_token() -> str`
  - `create_access_token(user_id: UUID, *, secret: str, ttl_minutes: int) -> tuple[str, int]` — returns `(token, expires_in_seconds)`
  - `decode_access_token(token: str, *, secret: str) -> UUID` — raises `TokenExpiredError` / `TokenInvalidError`
  - Exceptions: `PasswordTooLongError`, `TokenError`, `TokenExpiredError(TokenError)`, `TokenInvalidError(TokenError)`
  - `DUMMY_PASSWORD_HASH: Final[str]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_security.py`:

```python
"""Password hashing, token minting, and token decoding.

The distinction these tests protect is D13: bcrypt for passwords because they are
low-entropy and guessable, SHA-256 for refresh tokens because they are 256 random
bits and need an indexed lookup. Using either in the other's place is the easiest
way to get M0 wrong, and neither mistake is visible at runtime.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    BCRYPT_MAX_BYTES,
    DUMMY_PASSWORD_HASH,
    PasswordTooLongError,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_password,
    needs_rehash,
    sha256_hex,
    verify_password,
)

SECRET = "test-secret-key-not-used-anywhere-real"
COST = 4  # keep tests fast; the production value is asserted in test_config.py


def test_hash_then_verify_round_trips() -> None:
    hashed = hash_password("correct horse battery", cost=COST)

    assert verify_password("correct horse battery", hashed) is True


def test_verify_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery", cost=COST)

    assert verify_password("incorrect horse battery", hashed) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    """Per-row salt. Identical hashes would mean a missing or reused salt."""
    assert hash_password("same input", cost=COST) != hash_password("same input", cost=COST)


def test_hash_is_a_bcrypt_string_of_the_expected_length() -> None:
    hashed = hash_password("some password", cost=COST)

    assert hashed.startswith("$2b$")
    assert len(hashed) == 60


def test_verify_returns_false_for_a_malformed_hash() -> None:
    """A corrupt column value must not raise out of the auth path."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hashing_rejects_input_over_the_bcrypt_limit() -> None:
    """bcrypt ignores bytes past 72 — silently, if we let it (D24)."""
    with pytest.raises(PasswordTooLongError):
        hash_password("a" * (BCRYPT_MAX_BYTES + 1), cost=COST)


def test_the_limit_is_measured_in_bytes_not_characters() -> None:
    """A CJK passphrase reaches 72 bytes at roughly 24 characters."""
    password = "密" * 25  # 3 bytes each once UTF-8 encoded == 75 bytes

    assert len(password) < BCRYPT_MAX_BYTES
    with pytest.raises(PasswordTooLongError):
        hash_password(password, cost=COST)


def test_a_password_at_exactly_the_limit_is_accepted() -> None:
    hashed = hash_password("a" * BCRYPT_MAX_BYTES, cost=COST)

    assert verify_password("a" * BCRYPT_MAX_BYTES, hashed) is True


def test_needs_rehash_is_true_when_the_stored_cost_is_lower() -> None:
    hashed = hash_password("some password", cost=4)

    assert needs_rehash(hashed, cost=6) is True


def test_needs_rehash_is_false_at_the_configured_cost() -> None:
    hashed = hash_password("some password", cost=COST)

    assert needs_rehash(hashed, cost=COST) is False


def test_needs_rehash_is_false_for_an_unparseable_hash() -> None:
    """Never re-hash on the basis of a value we could not read."""
    assert needs_rehash("garbage", cost=COST) is False


def test_the_dummy_hash_verifies_nothing_but_costs_the_same_work() -> None:
    """Used for unknown emails so login timing does not reveal existence."""
    assert DUMMY_PASSWORD_HASH.startswith("$2b$")
    assert verify_password("any guess at all", DUMMY_PASSWORD_HASH) is False


def test_sha256_hex_is_stable_and_the_right_width() -> None:
    """64 characters is what the token_hash column is sized for."""
    digest = sha256_hex("a-token-value")

    assert digest == sha256_hex("a-token-value")
    assert len(digest) == 64


def test_opaque_tokens_are_unique_and_long() -> None:
    tokens = {generate_opaque_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(len(token) >= 43 for token in tokens)  # 32 bytes base64url


def test_access_token_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, secret=SECRET, ttl_minutes=15)

    assert decode_access_token(token, secret=SECRET) == user_id
    assert expires_in == 15 * 60


def test_access_token_carries_no_authorisation_claims() -> None:
    """is_admin and must_change_password would go stale for up to the token's TTL."""
    token, _ = create_access_token(uuid.uuid4(), secret=SECRET, ttl_minutes=15)
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert set(claims) == {"sub", "iat", "exp", "jti", "typ"}
    assert claims["typ"] == "access"


def test_each_access_token_has_a_distinct_jti() -> None:
    user_id = uuid.uuid4()
    first, _ = create_access_token(user_id, secret=SECRET, ttl_minutes=15)
    second, _ = create_access_token(user_id, secret=SECRET, ttl_minutes=15)

    assert first != second


def test_decoding_rejects_a_token_signed_with_another_key() -> None:
    token, _ = create_access_token(uuid.uuid4(), secret="a-different-secret", ttl_minutes=15)

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_an_expired_token() -> None:
    token, _ = create_access_token(uuid.uuid4(), secret=SECRET, ttl_minutes=-1)

    with pytest.raises(TokenExpiredError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_garbage() -> None:
    with pytest.raises(TokenInvalidError):
        decode_access_token("not.a.jwt", secret=SECRET)


def test_decoding_rejects_a_token_of_the_wrong_type() -> None:
    """`typ` guards against some future non-access token being replayed here."""
    claims = {
        "sub": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "typ": "something-else",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_a_non_uuid_subject() -> None:
    claims = {
        "sub": "not-a-uuid",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core'`.

- [ ] **Step 3: Write the implementation**

Create an empty `backend/app/core/__init__.py`, then `backend/app/core/security.py`:

```python
"""Password hashing, opaque token minting, and access-token encode/decode.

Two different hashes live here and they are not interchangeable (D13):

- **bcrypt** for passwords. Deliberately slow and salted, because a password is
  low-entropy and an attacker with the database will guess at it offline.
- **SHA-256** for refresh tokens. They are 256 random bits, so there is nothing to
  guess, and a fast digest is what makes an indexed lookup by token possible — a
  salted password hash would force a scan of every row.

Nothing here raises `HTTPException`. Mapping these exceptions to status codes is the
caller's job, which keeps this module usable from the CLI as well as from routes.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import bcrypt
import jwt

# bcrypt ignores input past this many bytes. Enforced rather than tolerated: left
# alone, two different long passwords sharing a 72-byte prefix would both
# authenticate, with no error and no log line (D24).
BCRYPT_MAX_BYTES: Final[int] = 72

_ACCESS_TOKEN_ALGORITHM: Final[str] = "HS256"
_ACCESS_TOKEN_TYPE: Final[str] = "access"
_OPAQUE_TOKEN_BYTES: Final[int] = 32


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte input limit."""


class TokenError(Exception):
    """Base class for access-token failures."""


class TokenExpiredError(TokenError):
    """The token was well-formed and correctly signed, but past its expiry."""


class TokenInvalidError(TokenError):
    """The token was malformed, wrongly signed, or of the wrong type."""


def hash_password(password: str, *, cost: int) -> str:
    """Hash a password with bcrypt at the given cost factor.

    Raises `PasswordTooLongError` above 72 UTF-8 bytes rather than letting bcrypt
    truncate silently.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise PasswordTooLongError(
            f"password is {len(encoded)} bytes; the maximum is {BCRYPT_MAX_BYTES}"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=cost)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored bcrypt hash.

    Returns `False` rather than raising for a malformed stored value: a corrupt row
    must not turn a failed login into a 500.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def needs_rehash(password_hash: str, *, cost: int) -> bool:
    """Whether a stored hash was written at a lower cost than currently configured.

    bcrypt embeds the cost in its prefix (`$2b$12$...`), so raising the configured
    cost can be applied to existing accounts on their next successful login (D22).
    """
    parts = password_hash.split("$")
    if len(parts) < 4 or not parts[2].isdigit():
        return False
    return int(parts[2]) < cost


def sha256_hex(value: str) -> str:
    """Hex SHA-256 digest — always 64 characters, matching `refresh_tokens.token_hash`."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_opaque_token() -> str:
    """A refresh token: 32 random bytes, URL-safe base64."""
    return secrets.token_urlsafe(_OPAQUE_TOKEN_BYTES)


def create_access_token(user_id: uuid.UUID, *, secret: str, ttl_minutes: int) -> tuple[str, int]:
    """Mint a signed access token. Returns the token and its lifetime in seconds.

    Deliberately carries no `is_admin` or `must_change_password` claim: both would go
    stale for up to `ttl_minutes`, and `docs/PRD.md:101` requires deactivation to end
    a session immediately.
    """
    issued_at = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl_minutes),
        "jti": str(uuid.uuid4()),
        "typ": _ACCESS_TOKEN_TYPE,
    }
    token = jwt.encode(claims, secret, algorithm=_ACCESS_TOKEN_ALGORITHM)
    return token, ttl_minutes * 60


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    """Verify an access token and return the user id it identifies."""
    try:
        claims = jwt.decode(token, secret, algorithms=[_ACCESS_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenExpiredError(str(error)) from error
    except jwt.PyJWTError as error:
        raise TokenInvalidError(str(error)) from error

    if claims.get("typ") != _ACCESS_TOKEN_TYPE:
        raise TokenInvalidError("token is not an access token")
    try:
        return uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as error:
        raise TokenInvalidError("token subject is not a UUID") from error


# Verified against when the email is unknown, so a login attempt costs the same work
# whether or not the account exists (`docs/PRD.md:114`).
DUMMY_PASSWORD_HASH: Final[str] = hash_password(secrets.token_urlsafe(32), cost=4)
```

`DUMMY_PASSWORD_HASH` is generated at cost 4, not the configured cost, purely so importing the
module is fast; its only job is to make `verify_password` do bcrypt-shaped work. If the timing
equivalence ever needs to be exact, this becomes a settings-driven value — noted, not built.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: PASS, 21 tests.

- [ ] **Step 5: Amend the PRD's four argon2id references**

All four must change together, or the PRD contradicts the code in the section a reader checks
first (spec §13):

- `docs/PRD.md:73` — the `User` schema comment becomes
  `password_hash: str                 # bcrypt — the raw password is never stored`
- `docs/PRD.md:110` — the policy line becomes: *"Password policy: minimum 12 characters, maximum
  72 bytes once UTF-8 encoded, rejected if it appears in a common-password list. Hashed with
  **bcrypt** at cost 12. The 72-byte maximum is bcrypt's input limit, not a preference: beyond it
  bcrypt ignores the remainder, so two different long passwords sharing a prefix would both
  authenticate."*
- `docs/PRD.md:301` — the tech-stack Auth row becomes
  `bcrypt hashing + JWT access / opaque refresh tokens`
- `docs/PRD.md:382` — §9's brute-force bullet ends
  *"Login rate limiting and bcrypt stand regardless."*

Add a line to §5's notes recording why: argon2id's 64 MiB per hash is a real cost on the single
shared VPS §5 targets alongside Postgres, Qdrant, Redis and possibly Ollama; bcrypt keeps the
property that matters, which is that each guess costs real time.

- [ ] **Step 6: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/__init__.py backend/app/core/security.py \
        backend/tests/test_security.py docs/PRD.md
git commit -m "feat(core): add password hashing and access-token primitives

bcrypt for passwords, SHA-256 for refresh tokens — different tools for
different jobs, and the module docstring says why so the next reader does
not unify them.

hash_password raises above 72 UTF-8 bytes rather than letting bcrypt
truncate. Left alone, two different long passwords sharing a 72-byte
prefix would both authenticate with no error and no log line; the check
is in bytes because a CJK passphrase hits the limit at ~24 characters.

Access tokens carry sub/iat/exp/jti/typ and nothing else. is_admin and
must_change_password are excluded deliberately: both would go stale for
up to the token TTL, and the PRD requires deactivation to end sessions
immediately.

Amends the four docs/PRD.md references to argon2id."
```

---

## Task 4: Password policy and the vendored wordlist

**Files:**
- Create: `backend/app/core/passwords.py`
- Create: `backend/app/core/data/common-passwords.txt`
- Test: `backend/tests/test_passwords.py`

**Interfaces:**
- Consumes: `BCRYPT_MAX_BYTES` (Task 3), `Settings.password_min_length` / `password_max_bytes` / `common_password_list_path` (Task 1).
- Produces:
  - `PasswordPolicyError(ValueError)` — carries a human-readable `reason`
  - `load_common_passwords(path: Path) -> frozenset[str]`
  - `check_password(password: str, *, min_length: int, max_bytes: int, common: frozenset[str]) -> None` — raises `PasswordPolicyError`
  - `get_common_passwords() -> frozenset[str]` — cached loader over the configured path

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_passwords.py`:

```python
"""Password policy.

The wordlist is injected rather than read from its real location, so these tests do
not depend on which list happens to be vendored. `docs/PRD.md:110` is the policy of
record.
"""

from pathlib import Path

import pytest

from app.core.passwords import (
    PasswordPolicyError,
    check_password,
    load_common_passwords,
)

COMMON = frozenset({"password123456", "letmeinplease"})


def test_a_good_password_passes() -> None:
    check_password("a-perfectly-fine-passphrase", min_length=12, max_bytes=72, common=COMMON)


def test_too_short_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="12 characters"):
        check_password("short", min_length=12, max_bytes=72, common=COMMON)


def test_a_password_at_the_minimum_is_accepted() -> None:
    check_password("a" * 12, min_length=12, max_bytes=72, common=COMMON)


def test_a_common_password_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="too common"):
        check_password("password123456", min_length=12, max_bytes=72, common=COMMON)


def test_the_common_check_ignores_case_and_surrounding_space() -> None:
    with pytest.raises(PasswordPolicyError, match="too common"):
        check_password("  PassWord123456 ", min_length=12, max_bytes=72, common=COMMON)


def test_over_the_byte_limit_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="72 bytes"):
        check_password("a" * 73, min_length=12, max_bytes=72, common=COMMON)


def test_the_byte_limit_counts_bytes_not_characters() -> None:
    """25 CJK characters are 75 UTF-8 bytes but only 25 characters."""
    with pytest.raises(PasswordPolicyError, match="72 bytes"):
        check_password("密" * 25, min_length=12, max_bytes=72, common=COMMON)


def test_the_error_message_names_bytes_so_a_user_is_not_counting_letters() -> None:
    with pytest.raises(PasswordPolicyError) as caught:
        check_password("密" * 25, min_length=12, max_bytes=72, common=COMMON)

    assert "bytes" in caught.value.reason


def test_loading_a_wordlist_normalises_and_skips_blanks(tmp_path: Path) -> None:
    listing = tmp_path / "words.txt"
    listing.write_text("Password1\n\n  hunter2  \n# a comment\n", encoding="utf-8")

    loaded = load_common_passwords(listing)

    assert loaded == frozenset({"password1", "hunter2"})


def test_loading_a_missing_wordlist_returns_empty_rather_than_raising(tmp_path: Path) -> None:
    """A missing data file must not stop the app booting; it degrades the check."""
    assert load_common_passwords(tmp_path / "absent.txt") == frozenset()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.passwords'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/passwords.py`:

```python
"""Password policy: length bounds and a common-password blocklist.

Policy lives here, in a service-layer helper, rather than in Pydantic field
constraints, so every rejection carries the same error code (`WEAK_PASSWORD`) instead
of being split between 422 for length and 400 for the wordlist.

The list is checked in-process against a vendored file. No network call: `SECURITY.md`
requires the instance to stay off the public internet, which rules out an online
breach-corpus API.
"""

import logging
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


class PasswordPolicyError(ValueError):
    """A password failed policy. `reason` is safe to show a user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_common_passwords(path: Path) -> frozenset[str]:
    """Read a wordlist into a set, lowercased and stripped.

    A missing file degrades the check to a no-op rather than preventing boot: the
    length minimum is doing most of the work, and an unbootable API is worse than a
    weaker blocklist.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Common-password list not found at %s; the check is disabled", path)
        return frozenset()

    return frozenset(
        stripped.lower()
        for line in raw.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


@lru_cache
def get_common_passwords() -> frozenset[str]:
    """The vendored list, read once per process."""
    return load_common_passwords(get_settings().common_password_list_path)


def check_password(
    password: str, *, min_length: int, max_bytes: int, common: frozenset[str]
) -> None:
    """Raise `PasswordPolicyError` if the password fails policy, else return."""
    if len(password) < min_length:
        raise PasswordPolicyError(f"Password must be at least {min_length} characters.")

    encoded_length = len(password.encode("utf-8"))
    if encoded_length > max_bytes:
        raise PasswordPolicyError(
            f"Password must be at most {max_bytes} bytes; this one is {encoded_length}. "
            "Non-ASCII characters use more than one byte each."
        )

    if password.strip().lower() in common:
        raise PasswordPolicyError("Password is too common. Choose something less predictable.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_passwords.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Vendor the wordlist**

The list is data, not code, and the tests above do not depend on it. Fetch it once and commit the
result:

```bash
mkdir -p backend/app/core/data
curl -fsSL \
  https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-10000.txt \
  -o backend/app/core/data/common-passwords.txt
wc -l backend/app/core/data/common-passwords.txt
```

Expected: roughly 10000 lines. This is a one-time vendoring step performed by a developer with
internet access — the running instance never fetches it.

If the fetch is unavailable, create the file with a header comment and any starter entries; the
loader tolerates a short or absent list, and `get_common_passwords` logs a warning when the file
is missing. Prepend this header either way:

```
# Common-password blocklist. Checked case-insensitively; blank lines and lines
# starting with '#' are ignored.
#
# Source: SecLists, Passwords/Common-Credentials/10-million-password-list-top-10000.txt
# Refresh by re-running the curl in docs/superpowers/plans/2026-08-23-m0-auth-backend.md.
```

- [ ] **Step 6: Confirm the vendored list loads and blocks something obvious**

Run:
```bash
cd backend && uv run python -c "
from app.core.passwords import get_common_passwords
words = get_common_passwords()
print(len(words), 'password' in words)
"
```
Expected: a count in the thousands and `True`.

- [ ] **Step 7: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/passwords.py backend/app/core/data/common-passwords.txt \
        backend/tests/test_passwords.py
git commit -m "feat(core): add password policy and vendored common-password list

Policy lives in a helper rather than Pydantic field constraints so every
rejection carries one error code, instead of splitting length into 422
and the wordlist into 400.

The byte limit is checked after UTF-8 encoding and the message says
'bytes', because a CJK or emoji passphrase hits 72 bytes at roughly 24
characters and a character-count message would read as wrong.

The wordlist is vendored and checked in-process — no network call, since
SECURITY.md requires the instance to stay off the public internet. A
missing file degrades the check and logs, rather than blocking boot."
```

---

## Task 5: The error contract

`docs/PRD.md:107` needs a machine-readable reason; `.claude/rules/router.md:152-156` forbids
inventing an error shape inside one router. This task decides the shape once, API-wide (D4).

**Files:**
- Create: `backend/app/core/errors.py`, `backend/app/schemas/errors.py`
- Modify: `backend/app/main.py` — register the handlers
- Test: `backend/tests/test_errors.py`
- Docs: `docs/PRD.md` §5.1 — the error-code contract; `.claude/rules/response-api.md` — the shape

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ErrorCode(StrEnum)` with members: `VALIDATION_ERROR`, `INTERNAL_ERROR`, `INVALID_CREDENTIALS`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `REFRESH_TOKEN_REUSED`, `PASSWORD_CHANGE_REQUIRED`, `ADMIN_REQUIRED`, `WEAK_PASSWORD`, `USER_NOT_FOUND`, `EMAIL_ALREADY_EXISTS`, `LAST_ADMIN`, `INVALID_SORT_FIELD`, `RATE_LIMITED`
  - `AppError(HTTPException)` — `__init__(status_code: int, code: ErrorCode, message: str)`
  - `error_detail(code: ErrorCode, message: str) -> dict[str, str]`
  - `register_exception_handlers(app: FastAPI) -> None`
  - `app.schemas.errors.ErrorBody`, `ErrorResponse`, `ValidationErrorBody`, `ValidationErrorResponse` — declared for OpenAPI `responses` blocks
  - `app.schemas.errors.ERROR_RESPONSES: dict[int, dict[str, object]]` — reusable per-status OpenAPI fragments

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_errors.py`:

```python
"""One error shape for the whole API.

`docs/PRD.md:107` requires a machine-readable reason so the frontend can force a
password change. router.md forbids inventing that shape in a single router, so it is
decided here and applied everywhere (D4). These tests are what stop a second shape
appearing later.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, ErrorCode, register_exception_handlers
from app.schemas.base import ApiModel


class _Body(ApiModel):
    new_password: str


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise AppError(403, ErrorCode.PASSWORD_CHANGE_REQUIRED, "Change your password first.")

    @app.post("/validated")
    def validated(body: _Body) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("something the client must never see")

    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_app_error_carries_a_code_and_a_message() -> None:
    async with await _client(_build_app()) as client:
        response = await client.get("/boom")

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "PASSWORD_CHANGE_REQUIRED",
            "message": "Change your password first.",
        }
    }


async def test_validation_errors_use_the_same_envelope() -> None:
    """Otherwise the frontend needs two parsers for one API."""
    async with await _client(_build_app()) as client:
        response = await client.post("/validated", json={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert isinstance(detail["message"], str)


async def test_validation_field_keys_are_camel_case() -> None:
    """docs/design.md renders a FieldError per field; it should not map loc arrays."""
    async with await _client(_build_app()) as client:
        response = await client.post("/validated", json={})

    assert "newPassword" in response.json()["detail"]["fields"]


async def test_an_unhandled_exception_leaks_nothing() -> None:
    async with await _client(_build_app()) as client:
        response = await client.get("/crash")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "INTERNAL_ERROR"
    assert "something the client must never see" not in response.text


async def test_every_error_code_is_screaming_snake_case() -> None:
    """The value is a wire contract; a renamed member breaks a frontend branch."""
    for code in ErrorCode:
        assert code.value == code.value.upper()
        assert " " not in code.value
```

Note: the `/crash` test needs `raise_server_exceptions=False` behaviour. `ASGITransport` already
propagates through the registered handler rather than re-raising, so no extra flag is needed —
verify this in Step 2 and, if the exception propagates instead, wrap the handler registration so
`ServerErrorMiddleware` is not bypassed.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.errors'`.

- [ ] **Step 3: Write the error module**

Create `backend/app/core/errors.py`:

```python
"""The API-wide error contract.

Every error this application raises serialises as:

    {"detail": {"code": "SOME_CODE", "message": "Human readable."}}

`code` is stable and machine-readable; `message` is for a person. Validation failures
carry an additional `fields` map so a form can render an error per field.

Deciding this once, here, is what `.claude/rules/router.md` means by "an API-wide
decision": a router that invented its own shape would leave clients parsing two.
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Stable machine-readable error identifiers. Values are part of the API."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    LAST_ADMIN = "LAST_ADMIN"
    INVALID_SORT_FIELD = "INVALID_SORT_FIELD"
    RATE_LIMITED = "RATE_LIMITED"


def error_detail(code: ErrorCode, message: str) -> dict[str, str]:
    """Build the `detail` object. One construction site, so the shape cannot drift."""
    return {"code": code.value, "message": message}


class AppError(HTTPException):
    """The only exception application code raises for a client-visible error.

    Subclasses `HTTPException` so FastAPI's own handling still applies, while forcing
    the structured detail.
    """

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=error_detail(code, message))
        self.code = code
        self.message = message


def _field_name(location: tuple[Any, ...]) -> str:
    """The field a validation error refers to, as the client spelled it.

    Pydantic reports `("body", "newPassword")`; the client wants `newPassword`, not the
    tuple. Non-body errors (query, path) keep their last element for the same reason.
    """
    parts = [str(part) for part in location if part not in {"body", "query", "path", "header"}]
    return ".".join(parts) if parts else "request"


async def _handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    """Reshape FastAPI's `loc`-array payload into the API's one error envelope."""
    assert isinstance(error, RequestValidationError)  # noqa: S101  # handler is registered for this type only
    fields = {_field_name(item["loc"]): item["msg"] for item in error.errors()}
    detail = error_detail(ErrorCode.VALIDATION_ERROR, "Request validation failed.")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": {**detail, "fields": fields}},
    )


async def _handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Log the real cause with a traceback; tell the client nothing about it."""
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": error_detail(ErrorCode.INTERNAL_ERROR, "Internal server error.")},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the handlers. Called once, from `create_app`."""
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
```

`status.HTTP_422_UNPROCESSABLE_CONTENT` is the current Starlette name; if the installed version
only has `HTTP_422_UNPROCESSABLE_ENTITY`, use that — verify with
`uv run python -c "from fastapi import status; print(status.HTTP_422_UNPROCESSABLE_CONTENT)"` and
adjust.

- [ ] **Step 4: Declare the response schemas for OpenAPI**

Create `backend/app/schemas/errors.py`:

```python
"""Error response models, declared so `responses` blocks reference a real schema.

These are never constructed by application code — `AppError` builds the payload. They
exist so `/docs` shows the actual error shape instead of FastAPI's default guess.
"""

from app.core.errors import ErrorCode
from app.schemas.base import ApiModel


class ErrorBody(ApiModel):
    code: ErrorCode
    message: str


class ErrorResponse(ApiModel):
    detail: ErrorBody


class ValidationErrorBody(ErrorBody):
    fields: dict[str, str]


class ValidationErrorResponse(ApiModel):
    detail: ValidationErrorBody


# Reusable fragments. A route spreads in only the statuses it can actually return —
# `.claude/rules/response-api.md` forbids copying a sibling route's block wholesale.
ERROR_RESPONSES: dict[int, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": "Semantically invalid input"},
    401: {"model": ErrorResponse, "description": "Missing, expired, or malformed access token"},
    403: {"model": ErrorResponse, "description": "Authenticated but not permitted"},
    404: {"model": ErrorResponse, "description": "Not found, or not visible to the caller"},
    409: {"model": ErrorResponse, "description": "Valid request, wrong state"},
    422: {"model": ValidationErrorResponse, "description": "Request validation failed"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
}
```

- [ ] **Step 5: Register the handlers in the app factory**

In `backend/app/main.py`, import `register_exception_handlers` and call it inside `create_app`
immediately after the `FastAPI(...)` construction, before the middleware block:

```python
from app.core.errors import register_exception_handlers

# ... inside create_app, after `app = FastAPI(...)`:
    register_exception_handlers(app)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_errors.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 7: Document the contract**

In `docs/PRD.md` §5.1, replace the "Error codes" bullet list with the same status mapping plus the
body shape:

```markdown
- **Error shape.** Every error the application raises serialises as
  `{"detail": {"code": "SOME_CODE", "message": "..."}}`. `code` is a stable,
  machine-readable identifier drawn from a single enum; `message` is for a person.
  Validation failures (`422`) carry an additional `fields` map keyed by the `camelCase`
  field name, so a form can render an error per field. This is one shape for the whole
  API — a route inventing its own leaves clients parsing two.
- **Error codes:**
  - `403` when the caller may see a thing but not do this to it — e.g. deleting someone
    else's project. Existence is not secret.
  - `404` when the caller may not know the thing exists — e.g. another user's conversation.
  - `409` for valid-but-wrong-state (querying a project that isn't `ready`).
  - `429` for rate limits.
```

In `.claude/rules/response-api.md`, add a section after "Exception → status mapping":

```markdown
## The error body has one shape

Application code raises `AppError(status_code, ErrorCode.SOME_CODE, "message")` — never bare
`HTTPException`, and never a hand-built dict. The wire shape is:

```json
{ "detail": { "code": "PASSWORD_CHANGE_REQUIRED", "message": "Change your password first." } }
```

`422` adds a `fields` map keyed by the `camelCase` field name the client sent, because
`docs/design.md` renders an error per field and should not be parsing Pydantic `loc` arrays.

`ErrorCode` values are a **wire contract**: renaming a member breaks a frontend branch. Add
members; do not rename them.

Declare error responses using the fragments in `app/schemas/errors.py`:

```python
from app.schemas.errors import ERROR_RESPONSES

@router.delete("/{user_id}", status_code=204, responses={
    k: ERROR_RESPONSES[k] for k in (401, 403, 404, 409)
})
```

Spread in only the statuses the route can actually return, traced through its handler and its
dependencies. Do not copy a sibling route's block.
```

Also amend that file's "429 becomes universal once rate limiting lands" section to match D7 —
rate limiting is applied per route by an explicit dependency, so `429` is declared only on routes
carrying a limiter, not on every route.

- [ ] **Step 8: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/errors.py backend/app/schemas/errors.py backend/app/main.py \
        backend/tests/test_errors.py docs/PRD.md .claude/rules/response-api.md
git commit -m "feat(core): decide the API-wide error contract

The PRD needs a machine-readable reason for the forced password change;
router.md forbids inventing an error shape inside one router. So the
shape is decided once here: detail is always {code, message}, with codes
from a single enum whose values are a wire contract.

Validation errors are reshaped into the same envelope with a fields map
keyed by the camelCase name the client sent — docs/design.md renders an
error per field and should not be parsing Pydantic loc arrays.

Unhandled exceptions log with a traceback and return an opaque 500.

Documents the contract in PRD 5.1 and response-api.md, and corrects that
rule's claim that 429 becomes universal: rate limiting is per-route via
an explicit dependency."
```

---

## Task 6: BaseRepository and UserRepository

The soft-delete guarantee lives here. Everything above this layer trusts it, so it is tested
directly rather than through a route.

**Files:**
- Create: `backend/app/repositories/__init__.py`, `base.py`, `user.py`
- Test: `backend/tests/test_user_repository.py`
- Docs: create `.claude/rules/persistence.md`

**Interfaces:**
- Consumes: `app.models` (Task 2), `AsyncSession`.
- Produces:
  - `BaseRepository[ModelT]` with `__init__(session: AsyncSession)`, `active_select() -> Select[tuple[ModelT]]`, `get(entity_id: UUID) -> ModelT | None`, `get_including_deleted(entity_id: UUID) -> ModelT | None`, `add(entity: ModelT) -> ModelT`, `soft_delete(entity: ModelT) -> None`
  - `UserRepository(BaseRepository[User])` with `get_by_email(email: str) -> User | None`, `email_exists(email: str) -> bool`, `list_page(*, page: int, limit: int, search: str | None, sort: str, descending: bool) -> tuple[Sequence[User], int]`, `count_active_admins(excluding: UUID | None = None) -> int`, `SORTABLE_FIELDS: frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_user_repository.py`:

```python
"""The soft-delete guarantee and the user queries built on it.

Tested at the repository level rather than through routes: this is the layer that
promises a deleted row is never returned, and a route test would pass even if the
promise were kept by accident somewhere else.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.user import UserRepository


async def _make_user(
    session: AsyncSession,
    *,
    email: str = "dev@example.com",
    name: str = "Dev",
    is_admin: bool = False,
    deleted: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email,
        password_hash="$2b$04$placeholderplaceholderplaceholderplaceholderplaceholderxx",
        is_admin=is_admin,
        must_change_password=False,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(user)
    await session.commit()
    return user


async def test_get_returns_a_live_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = UserRepository(db_session)

    assert (await repository.get(user.id)) is not None


async def test_get_hides_a_soft_deleted_user(db_session: AsyncSession) -> None:
    """The whole point of active_select()."""
    user = await _make_user(db_session, deleted=True)
    repository = UserRepository(db_session)

    assert (await repository.get(user.id)) is None


async def test_get_including_deleted_finds_it(db_session: AsyncSession) -> None:
    """An explicitly named escape hatch, so the intent is visible at the call site."""
    user = await _make_user(db_session, deleted=True)
    repository = UserRepository(db_session)

    assert (await repository.get_including_deleted(user.id)) is not None


async def test_get_by_email_is_case_insensitive_on_the_stored_value(
    db_session: AsyncSession,
) -> None:
    """Emails are normalised to lowercase before storage; lookups normalise too."""
    await _make_user(db_session, email="dev@example.com")
    repository = UserRepository(db_session)

    assert (await repository.get_by_email("DEV@Example.com")) is not None


async def test_get_by_email_hides_a_soft_deleted_user(db_session: AsyncSession) -> None:
    """A deactivated account must not be able to log in (docs/PRD.md:84)."""
    await _make_user(db_session, email="gone@example.com", deleted=True)
    repository = UserRepository(db_session)

    assert (await repository.get_by_email("gone@example.com")) is None


async def test_email_exists_ignores_deleted_rows(db_session: AsyncSession) -> None:
    """So a rehired colleague's address can be reused (D20)."""
    await _make_user(db_session, email="rehired@example.com", deleted=True)
    repository = UserRepository(db_session)

    assert (await repository.email_exists("rehired@example.com")) is False


async def test_soft_delete_sets_the_timestamp_rather_than_removing(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    repository = UserRepository(db_session)

    await repository.soft_delete(user)
    await db_session.commit()

    assert (await repository.get(user.id)) is None
    assert (await repository.get_including_deleted(user.id)) is not None


async def test_list_page_paginates_and_reports_the_total(db_session: AsyncSession) -> None:
    for index in range(5):
        await _make_user(db_session, email=f"user{index}@example.com", name=f"User {index}")
    repository = UserRepository(db_session)

    users, total = await repository.list_page(
        page=2, limit=2, search=None, sort="email", descending=False
    )

    assert total == 5
    assert [user.email for user in users] == ["user2@example.com", "user3@example.com"]


async def test_list_page_excludes_deleted_from_both_rows_and_total(
    db_session: AsyncSession,
) -> None:
    """A total that counts rows the page cannot show makes the last page empty."""
    await _make_user(db_session, email="live@example.com")
    await _make_user(db_session, email="dead@example.com", deleted=True)
    repository = UserRepository(db_session)

    users, total = await repository.list_page(
        page=1, limit=25, search=None, sort="email", descending=False
    )

    assert total == 1
    assert len(users) == 1


async def test_list_page_search_matches_name_or_email(db_session: AsyncSession) -> None:
    await _make_user(db_session, email="ada@example.com", name="Ada Lovelace")
    await _make_user(db_session, email="grace@example.com", name="Grace Hopper")
    repository = UserRepository(db_session)

    by_name, _ = await repository.list_page(
        page=1, limit=25, search="lovel", sort="email", descending=False
    )
    by_email, _ = await repository.list_page(
        page=1, limit=25, search="grace@", sort="email", descending=False
    )

    assert [user.name for user in by_name] == ["Ada Lovelace"]
    assert [user.name for user in by_email] == ["Grace Hopper"]


async def test_list_page_rejects_an_unknown_sort_field(db_session: AsyncSession) -> None:
    """Interpolating an arbitrary column name would be an injection point."""
    repository = UserRepository(db_session)

    with pytest.raises(ValueError, match="sort"):
        await repository.list_page(
            page=1, limit=25, search=None, sort="password_hash", descending=False
        )


async def test_count_active_admins_ignores_deleted_and_non_admins(
    db_session: AsyncSession,
) -> None:
    await _make_user(db_session, email="a1@example.com", is_admin=True)
    await _make_user(db_session, email="a2@example.com", is_admin=True, deleted=True)
    await _make_user(db_session, email="u1@example.com", is_admin=False)
    repository = UserRepository(db_session)

    assert (await repository.count_active_admins()) == 1


async def test_count_active_admins_can_exclude_one(db_session: AsyncSession) -> None:
    """Used by the last-admin guard: 'would this operation leave zero?' (D17)."""
    admin = await _make_user(db_session, email="only@example.com", is_admin=True)
    repository = UserRepository(db_session)

    assert (await repository.count_active_admins(excluding=admin.id)) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_user_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories'`.

- [ ] **Step 3: Write BaseRepository**

Create an empty `backend/app/repositories/__init__.py`, then `backend/app/repositories/base.py`:

```python
"""The base repository — and the single place the soft-delete filter is applied.

`docs/PRD.md:323` requires every query to exclude soft-deleted rows. Relying on each
query to remember would make that a convention; `active_select()` makes it structural.
A caller that genuinely wants deleted rows uses a differently named method, so the
intent is visible at the call site and greppable.

Repositories are the only layer allowed to import `select` / `insert` / `update`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import SoftDeleteMixin


class BaseRepository[ModelT: Any]:
    """CRUD shared by every repository. Subclasses set `model`."""

    model: ClassVar[Any]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def active_select(self) -> Select[tuple[ModelT]]:
        """A `SELECT` that already excludes soft-deleted rows.

        Every read in every repository starts here. Models without `SoftDeleteMixin`
        (`refresh_tokens`) get a plain select, so the method is safe to use uniformly.
        """
        statement = select(self.model)
        if issubclass(self.model, SoftDeleteMixin):
            statement = statement.where(self.model.deleted_at.is_(None))
        return statement

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key, excluding soft-deleted rows."""
        result = await self.session.execute(self.active_select().where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def get_including_deleted(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key without the soft-delete filter. Name says so on purpose."""
        result = await self.session.execute(select(self.model).where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        """Stage an insert. The caller's service owns the commit."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def soft_delete(self, entity: ModelT) -> None:
        """Mark a row deleted. The caller's service owns the commit."""
        entity.deleted_at = datetime.now(UTC)
        await self.session.flush()
```

- [ ] **Step 4: Write UserRepository**

Create `backend/app/repositories/user.py`:

```python
"""Queries over `users`."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Reads and writes for accounts. All reads exclude soft-deleted rows."""

    model = User

    # Allowlisted rather than free-form: `sort` arrives from a query parameter, and
    # interpolating an arbitrary column name would expose `password_hash` ordering
    # at best and be an injection point at worst.
    SORTABLE_FIELDS = frozenset({"name", "email", "created_at", "last_login_at"})

    async def get_by_email(self, email: str) -> User | None:
        """Find a live account by address. Normalises case, as storage does."""
        result = await self.session.execute(
            self.active_select().where(User.email == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Whether a live account already uses this address."""
        return (await self.get_by_email(email)) is not None

    async def list_page(
        self, *, page: int, limit: int, search: str | None, sort: str, descending: bool
    ) -> tuple[Sequence[User], int]:
        """One page of accounts plus the total matching count.

        The total uses the same filters as the rows, so the last page is never empty.
        """
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"unknown sort field: {sort}")

        statement = self.active_select()
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))

        count_result = await self.session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        total = count_result.scalar_one()

        column = getattr(User, sort)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * limit).limit(limit)

        rows = await self.session.execute(statement)
        return rows.scalars().all(), total

    async def count_active_admins(self, excluding: uuid.UUID | None = None) -> int:
        """How many live admins exist, optionally ignoring one.

        `excluding` answers "would this operation leave the instance with none?" — the
        last-admin guard (D17), which exists because the alternative is recovery by
        manual SQL.
        """
        statement = select(func.count()).select_from(User).where(
            User.deleted_at.is_(None), User.is_admin.is_(True)
        )
        if excluding is not None:
            statement = statement.where(User.id != excluding)
        result = await self.session.execute(statement)
        return result.scalar_one()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_user_repository.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 6: Write the persistence rule**

Create `.claude/rules/persistence.md`:

```markdown
---
paths:
  - "backend/app/models/**/*.py"
  - "backend/app/repositories/**/*.py"
  - "backend/app/db/**/*.py"
  - "backend/alembic/**/*.py"
---

# Persistence Rules

Three layers: route → service → repository. `router.md` owns the top; this file owns the bottom
two.

## Only repositories touch SQLAlchemy

`select`, `insert`, `update`, and `delete` are imported in `app/repositories/**` and nowhere
else. A service that builds a statement has moved a query somewhere nobody will look for it, and
puts it outside the reach of the soft-delete guarantee below.

Services own **business rules, transactions, and orchestration across repositories**. They call
repository methods and commit.

## The soft-delete filter is structural, not remembered

`docs/PRD.md:323` requires every read to exclude soft-deleted rows. `BaseRepository.active_select()`
applies `deleted_at IS NULL` for any model carrying `SoftDeleteMixin`. **Every read starts
there.**

A query that genuinely needs deleted rows uses a method whose name says so —
`get_including_deleted` — so the intent is visible at the call site and greppable. A
hand-written `select(Model)` inside a repository read is a defect even when its output is
currently correct.

`refresh_tokens` is the documented exception: it has no `deleted_at`, and its lifecycle is
`revoked_at` / `expires_at` (`docs/PRD.md` §5.1).

## Bulk updates must set `updated_at` themselves

`TimestampMixin.updated_at` uses SQLAlchemy's `onupdate`, which is a **Python-side** default: it
fires on an ORM flush and **not** on a bulk `UPDATE`. Any repository method issuing a bulk
update sets `updated_at` in the `values()` explicitly. Forgetting leaves rows whose
`updated_at` predates their last change, which is the kind of bug found months later while
debugging something else.

## `sort` is allowlisted, never interpolated

A list repository exposes `SORTABLE_FIELDS: frozenset[str]` and raises `ValueError` for anything
outside it. The route maps that to `400 INVALID_SORT_FIELD`. Passing a query parameter into
`getattr(Model, ...)` unchecked exposes every column, `password_hash` included.

## The engine is built lazily

`app/db/session.py` constructs the engine on first use from `get_settings()`, not at import
time. `AuthContextMiddleware` builds sessions from the sessionmaker directly rather than through
`Depends`, so an import-time engine would ignore a test's settings override and talk to the
development database. `reset_engine()` exists for tests and nothing else.

## Migrations, not `create_all`

Schema changes are Alembic revisions. `Base.metadata.create_all` is not used anywhere, including
in tests — the migrations are what runs in production, so they are what the suite exercises.

- `MetaData(naming_convention=...)` in `app/models/base.py` keeps constraint names deterministic;
  without it autogenerate churns and a migration cannot reliably drop a constraint it did not name.
- Write the revision by hand when autogenerate cannot express the intent. The partial unique index
  on `users.email` is the standing example.
- Every revision has a working `downgrade()`. A migration that cannot be reversed cannot be
  iterated on.

## Timestamps and IDs

`timestamptz`, timezone-aware, UTC (`docs/PRD.md:321`). Primary keys are application-generated
`uuid4` (`docs/PRD.md:322`) — never a database sequence, so an id in a URL reveals nothing about
volume or ordering.
```

Add the row to `CLAUDE.md`'s rule table and correct the count from **nine** to **ten**:

```markdown
| `persistence.md` | Any model, repository, migration, or session code |
```

- [ ] **Step 7: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/repositories backend/tests/test_user_repository.py \
        .claude/rules/persistence.md CLAUDE.md
git commit -m "feat(db): add the repository layer and the soft-delete guarantee

active_select() applies deleted_at IS NULL for any model carrying
SoftDeleteMixin, so excluding deleted rows is structural rather than
something each query remembers. Wanting deleted rows requires a method
whose name says so.

UserRepository allowlists sortable fields: sort arrives from a query
parameter, and passing it to getattr unchecked would expose ordering by
password_hash. count_active_admins(excluding=...) is the query the
last-admin guard needs.

Adds .claude/rules/persistence.md documenting the layering, the bulk-
update updated_at trap, and why the engine is lazy; CLAUDE.md's rule
count goes from nine to ten."
```

---

## Task 7: RefreshTokenRepository

Separate from Task 6 because the rotation-chain queries are where the bulk-update `updated_at`
trap and the family semantics live — a reviewer could reasonably accept the user repository and
reject this.

**Files:**
- Create: `backend/app/repositories/refresh_token.py`
- Test: `backend/tests/test_refresh_token_repository.py`

**Interfaces:**
- Consumes: `RefreshToken`, `RevokedReason` (Task 2), `BaseRepository` (Task 6).
- Produces `RefreshTokenRepository(BaseRepository[RefreshToken])`:
  - `get_by_hash(token_hash: str) -> RefreshToken | None`
  - `create(*, user_id: UUID, family_id: UUID, token_hash: str, expires_at: datetime) -> RefreshToken`
  - `mark_used(token: RefreshToken) -> None`
  - `revoke_family(family_id: UUID, *, reason: RevokedReason) -> int`
  - `revoke_all_for_user(user_id: UUID, *, reason: RevokedReason, except_token_id: UUID | None = None) -> int`
  - `revoke_one(token: RefreshToken, *, reason: RevokedReason) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_refresh_token_repository.py`:

```python
"""Rotation-chain queries.

`family_id` is what makes replay detection revoke exactly one device rather than
logging the user out everywhere, so these tests are mostly about blast radius.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.refresh_token import RefreshTokenRepository


async def _make_user(session: AsyncSession, email: str = "dev@example.com") -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=email,
        password_hash="$2b$04$placeholderplaceholderplaceholderplaceholderplaceholderxx",
        must_change_password=False,
    )
    session.add(user)
    await session.commit()
    return user


def _expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=30)


async def test_create_then_find_by_hash(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)

    created = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="a" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    found = await repository.get_by_hash("a" * 64)
    assert found is not None
    assert found.id == created.id


async def test_unknown_hash_returns_none(db_session: AsyncSession) -> None:
    repository = RefreshTokenRepository(db_session)

    assert (await repository.get_by_hash("b" * 64)) is None


async def test_mark_used_stamps_the_timestamp(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    token = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="c" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.mark_used(token)
    await db_session.commit()

    assert token.used_at is not None


async def test_revoke_family_hits_every_token_in_that_family_only(
    db_session: AsyncSession,
) -> None:
    """A replay must not log the user out of their other devices."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    compromised = uuid.uuid4()
    other = uuid.uuid4()
    for index, family in enumerate([compromised, compromised, other]):
        await repository.create(
            user_id=user.id,
            family_id=family,
            token_hash=str(index) * 64,
            expires_at=_expiry(),
        )
    await db_session.commit()

    revoked = await repository.revoke_family(compromised, reason="replay")
    await db_session.commit()

    assert revoked == 2
    survivor = await repository.get_by_hash("2" * 64)
    assert survivor is not None
    assert survivor.revoked_at is None


async def test_revoke_family_records_the_reason(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    await repository.create(
        user_id=user.id, family_id=family, token_hash="d" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.revoke_family(family, reason="replay")
    await db_session.commit()

    token = await repository.get_by_hash("d" * 64)
    assert token is not None
    assert token.revoked_reason == "replay"


async def test_revoke_family_does_not_re_revoke(db_session: AsyncSession) -> None:
    """Otherwise a second replay overwrites the original reason and timestamp."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    await repository.create(
        user_id=user.id, family_id=family, token_hash="e" * 64, expires_at=_expiry()
    )
    await db_session.commit()
    await repository.revoke_family(family, reason="logout")
    await db_session.commit()

    second = await repository.revoke_family(family, reason="replay")
    await db_session.commit()

    assert second == 0
    token = await repository.get_by_hash("e" * 64)
    assert token is not None
    assert token.revoked_reason == "logout"


async def test_revoke_all_for_user_can_spare_the_caller(db_session: AsyncSession) -> None:
    """change-password revokes all *other* sessions (docs/PRD.md:108)."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    keep = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="f" * 64, expires_at=_expiry()
    )
    await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="0" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    revoked = await repository.revoke_all_for_user(
        user.id, reason="password_change", except_token_id=keep.id
    )
    await db_session.commit()

    assert revoked == 1
    spared = await repository.get_by_hash("f" * 64)
    assert spared is not None
    assert spared.revoked_at is None


async def test_revoke_all_for_user_leaves_other_users_alone(db_session: AsyncSession) -> None:
    first = await _make_user(db_session, "first@example.com")
    second = await _make_user(db_session, "second@example.com")
    repository = RefreshTokenRepository(db_session)
    await repository.create(
        user_id=first.id, family_id=uuid.uuid4(), token_hash="1" * 64, expires_at=_expiry()
    )
    await repository.create(
        user_id=second.id, family_id=uuid.uuid4(), token_hash="3" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.revoke_all_for_user(first.id, reason="logout_all")
    await db_session.commit()

    untouched = await repository.get_by_hash("3" * 64)
    assert untouched is not None
    assert untouched.revoked_at is None


async def test_siblings_can_coexist_in_one_family(db_session: AsyncSession) -> None:
    """The grace window mints a sibling rather than reusing a stored raw token (D12)."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    for index in range(2):
        await repository.create(
            user_id=user.id,
            family_id=family,
            token_hash=f"{index}" * 64,
            expires_at=_expiry(),
        )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE family_id = :family"),
        {"family": family},
    )
    assert result.scalar_one() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_refresh_token_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.refresh_token'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/repositories/refresh_token.py`:

```python
"""Queries over `refresh_tokens`.

`refresh_tokens` carries no `deleted_at` (D14), so `active_select()` returns a plain
select here — which is why the base method checks for the mixin rather than assuming it.

Only the SHA-256 of a token is ever stored or compared. The raw value lives in the
response cookie and nowhere else.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update

from app.models.refresh_token import RefreshToken, RevokedReason
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Issue, consume, and revoke refresh tokens."""

    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Find a token by its stored digest. Hits the unique index."""
        result = await self.session.execute(
            self.active_select().where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Insert a token. A rotation successor reuses the parent's `family_id`."""
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        return await self.add(token)

    async def mark_used(self, token: RefreshToken) -> None:
        """Record that this token has been exchanged. Not the same as revoking it."""
        token.used_at = datetime.now(UTC)
        await self.session.flush()

    async def revoke_one(self, token: RefreshToken, *, reason: RevokedReason) -> None:
        """Revoke a single token, leaving the rest of its family alone."""
        if token.revoked_at is not None:
            return
        token.revoked_at = datetime.now(UTC)
        token.revoked_reason = reason
        await self.session.flush()

    async def revoke_family(self, family_id: uuid.UUID, *, reason: RevokedReason) -> int:
        """Revoke every unrevoked token in one rotation chain. Returns the count.

        Scoped to the family, not the user: a replay means one device's chain leaked,
        and logging the user out of their other devices would be collateral damage.

        This is a bulk `UPDATE`, so `onupdate` does not fire — but `refresh_tokens` has
        no `updated_at`, so there is nothing to set. See `.claude/rules/persistence.md`.
        """
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return result.rowcount

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        reason: RevokedReason,
        except_token_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every unrevoked token for one user. Returns the count.

        `except_token_id` spares the caller's own session, which is what
        `docs/PRD.md:108` means by revoking all *other* refresh tokens on a password
        change.
        """
        statement = update(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        if except_token_id is not None:
            statement = statement.where(RefreshToken.id != except_token_id)
        result = await self.session.execute(
            statement.values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return result.rowcount
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_refresh_token_repository.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/repositories/refresh_token.py backend/tests/test_refresh_token_repository.py
git commit -m "feat(db): add the refresh-token repository

Rotation-chain queries keyed on family_id, so replay detection revokes
one device's chain rather than every session the user has. revoke_family
and revoke_all_for_user skip already-revoked rows, so a second revocation
cannot overwrite the original reason.

revoke_all_for_user takes except_token_id, which is how change-password
revokes all *other* sessions while keeping the caller signed in."
```

---

## Task 8: AuthContextMiddleware and the auth dependencies

This is the task whose failure mode is silent — a route that should be gated but is not. Two
specific traps are called out below because both produce working-looking code.

**Files:**
- Create: `backend/app/core/middleware.py`, `backend/app/api/deps.py`
- Modify: `backend/app/main.py` — register the middleware **before** the CORS block
- Test: `backend/tests/test_auth_middleware.py`
- Docs: `docs/PRD.md` §4.0 — gate scope; `.claude/rules/router.md` — async handlers and the `CurrentUser` type

**Interfaces:**
- Consumes: `decode_access_token`, `TokenExpiredError`, `TokenInvalidError` (Task 3); `ErrorCode`, `AppError` (Task 5); `UserRepository` (Task 6); `get_sessionmaker` (Task 2).
- Produces:
  - `AuthenticatedUser` — frozen dataclass: `id: UUID`, `name: str`, `email: str`, `is_admin: bool`, `must_change_password: bool`
  - `AuthContext` — frozen dataclass: `user: AuthenticatedUser | None`, `error: ErrorCode | None`
  - `AuthContextMiddleware(BaseHTTPMiddleware)`
  - `GATE_EXEMPT_PREFIXES: tuple[str, ...]`
  - `app.api.deps.get_current_user(request: Request) -> AuthenticatedUser`
  - `app.api.deps.require_admin(...) -> AuthenticatedUser`
  - `app.api.deps.CurrentUser`, `AdminUser`, `SessionDep` type aliases

### Two traps

**Trap 1 — never short-circuit before establishing identity.** The gate check is path-scoped; the
decode is not. If the middleware returns early for `/auth`, `request.state.auth` is never set
there and `GET /auth/me` raises `RuntimeError` instead of returning the caller. Establish
identity for every request, then apply the `403` only outside the exempt prefixes.

**Trap 2 — middleware registration order is inverted.** Starlette's `add_middleware` **inserts at
index 0**, and `build_middleware_stack` applies the list reversed — so the **last**-added
middleware ends up **outermost**. For the gate's `403` to carry CORS headers, `CORSMiddleware`
must be outermost, which means the gate is added **first**. In `create_app`, the
`app.add_middleware(AuthContextMiddleware)` line goes **above** the existing
`app.add_middleware(CORSMiddleware, ...)` block. Step 1's test asserts the resulting property
rather than the ordering, so it stays honest if Starlette's internals change.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_auth_middleware.py`:

```python
"""Identity establishment and the forced-password-change gate.

Two regressions are pinned here on purpose:

- `/auth` routes must still receive identity. A middleware that skips the whole
  pipeline for exempt paths leaves `request.state.auth` unset, and `GET /auth/me`
  fails with RuntimeError rather than returning the caller.
- The gate's 403 must carry CORS headers, or the browser reports an opaque network
  error and the frontend never sees the code it is meant to branch on.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.config import get_settings
from app.core.security import create_access_token
from app.models import User


async def _make_user(
    session: AsyncSession,
    *,
    is_admin: bool = False,
    must_change_password: bool = False,
    deleted: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="$2b$04$placeholderplaceholderplaceholderplaceholderplaceholderxx",
        is_admin=is_admin,
        must_change_password=must_change_password,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(user)
    await session.commit()
    return user


def _token(user: User) -> str:
    settings = get_settings()
    token, _ = create_access_token(
        user.id, secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes
    )
    return token


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


@pytest.fixture
def probe_app(app: FastAPI) -> FastAPI:
    """The real app plus two probe routes, so the real middleware stack is exercised."""

    @app.get("/probe/any")
    async def probe_any(current_user: CurrentUser) -> dict[str, str]:
        return {"email": current_user.email}

    @app.get("/probe/admin")
    async def probe_admin(current_user: AdminUser) -> dict[str, str]:
        return {"email": current_user.email}

    return app


@pytest.fixture
async def probe_client(probe_app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=probe_app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_a_valid_token_reaches_the_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)

    async with probe_client as client:
        response = await client.get("/probe/any", headers=_auth(user))

    assert response.status_code == 200
    assert response.json()["email"] == user.email


async def test_no_header_is_401(probe_client: AsyncClient) -> None:
    async with probe_client as client:
        response = await client.get("/probe/any")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_a_garbage_token_is_401(probe_client: AsyncClient) -> None:
    async with probe_client as client:
        response = await client.get(
            "/probe/any", headers={"Authorization": "Bearer not.a.jwt"}
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_an_expired_token_reports_expiry_distinctly(probe_client: AsyncClient) -> None:
    """The frontend refreshes on TOKEN_EXPIRED and hard-logs-out on INVALID_TOKEN."""
    settings = get_settings()
    token, _ = create_access_token(uuid.uuid4(), secret=settings.secret_key, ttl_minutes=-1)

    async with probe_client as client:
        response = await client.get(
            "/probe/any", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_a_soft_deleted_users_live_token_stops_working(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:101 — deactivation ends sessions immediately, not in 15 minutes.

    This is the reason the middleware loads the user row on every request instead of
    trusting the token's claims.
    """
    user = await _make_user(db_session)
    headers = _auth(user)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    async with probe_client as client:
        response = await client.get("/probe/any", headers=headers)

    assert response.status_code == 401


async def test_a_non_admin_is_403_on_an_admin_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=False)

    async with probe_client as client:
        response = await client.get("/probe/admin", headers=_auth(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_an_admin_passes_the_admin_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=True)

    async with probe_client as client:
        response = await client.get("/probe/admin", headers=_auth(user))

    assert response.status_code == 200


async def test_the_gate_blocks_a_route_outside_auth(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, must_change_password=True)

    async with probe_client as client:
        response = await client.get("/probe/any", headers=_auth(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_the_gates_403_carries_cors_headers(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Without this the browser sees an opaque failure, not the code it must branch on.

    Asserts the property rather than the middleware ordering, so it survives a change
    in Starlette's internals.
    """
    user = await _make_user(db_session, must_change_password=True)
    headers = {**_auth(user), "Origin": "http://localhost:3000"}

    async with probe_client as client:
        response = await client.get("/probe/any", headers=headers)

    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_health_is_reachable_while_the_gate_is_active(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, must_change_password=True)

    async with probe_client as client:
        response = await client.get("/health/live", headers=_auth(user))

    assert response.status_code == 200


async def test_identity_is_established_even_on_exempt_paths(
    probe_app: FastAPI, db_session: AsyncSession
) -> None:
    """Trap 1: an early return for /auth would leave request.state.auth unset.

    Uses a probe mounted under the exempt prefix, since /auth/me does not exist yet.
    """

    @probe_app.get("/auth/probe-me")
    async def probe_me(current_user: CurrentUser) -> dict[str, bool]:
        return {"mustChange": current_user.must_change_password}

    user = await _make_user(db_session, must_change_password=True)
    transport = ASGITransport(app=probe_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/probe-me", headers=_auth(user))

    assert response.status_code == 200
    assert response.json()["mustChange"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_auth_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.deps'`.

- [ ] **Step 3: Write the middleware**

Create `backend/app/core/middleware.py`:

```python
"""Per-request identity, and the forced-password-change gate.

The middleware establishes identity for **every** request, then applies the `403` only
outside the exempt prefixes. Doing it the other way round — returning early for exempt
paths — leaves `request.state.auth` unset on `/auth` routes, so `GET /auth/me` fails
with a RuntimeError instead of returning the caller.

Why a middleware rather than a dependency: a route added later is gated with no action
taken. Why the user row is loaded every request rather than trusted from the token:
`docs/PRD.md:101` requires deactivating someone to end their sessions immediately, and
a stateless 15-minute token cannot deliver that.

Registration order matters. Starlette's `add_middleware` inserts at index 0 and the
stack is built reversed, so the last-added middleware is outermost. This one is
registered **before** `CORSMiddleware` so CORS ends up outside it and the gate's 403
carries the headers a browser needs to surface the body.
"""

import logging
import uuid
from dataclasses import dataclass

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.core.errors import ErrorCode, error_detail
from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_token
from app.db.session import get_sessionmaker
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)

# Paths where a pending password change does not block the request. The whole `/auth`
# surface is exempt so a user can see who they are, keep a live token while typing,
# and log out (docs/PRD.md §4.0). `/` is matched exactly, not as a prefix.
GATE_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/auth",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_BEARER_PREFIX = "Bearer "


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Request-scoped identity.

    A frozen snapshot rather than the ORM row: the middleware's session is closed
    before the handler runs, so passing the row would hand every handler a detached
    instance. Services load the full row when they need to mutate it.
    """

    id: uuid.UUID
    name: str
    email: str
    is_admin: bool
    # Carried because /auth routes run with the gate bypassed and may legitimately
    # observe it as true. Outside /auth, the gate has established it is false.
    must_change_password: bool


@dataclass(frozen=True, slots=True)
class AuthContext:
    """What the middleware resolved: a user, or the reason it could not."""

    user: AuthenticatedUser | None
    error: ErrorCode | None


def _is_gate_exempt(path: str) -> bool:
    """Whether a pending password change is tolerated on this path."""
    if path == "/":
        return True
    return path.startswith(GATE_EXEMPT_PREFIXES)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Decode the bearer token, load the user, and enforce the password-change gate."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.auth = await self._resolve(request)

        auth: AuthContext = request.state.auth
        if (
            auth.user is not None
            and auth.user.must_change_password
            and not _is_gate_exempt(request.url.path)
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": error_detail(
                        ErrorCode.PASSWORD_CHANGE_REQUIRED,
                        "You must change your password before using the rest of the API.",
                    )
                },
            )

        return await call_next(request)

    async def _resolve(self, request: Request) -> AuthContext:
        """Establish identity, or record why it could not be established.

        Never raises: a `401` is the dependency's job, so an unauthenticated request to
        a public route is unaffected by anything decided here.
        """
        header = request.headers.get("Authorization", "")
        if not header.startswith(_BEARER_PREFIX):
            return AuthContext(user=None, error=None)

        settings = get_settings()
        try:
            user_id = decode_access_token(
                header.removeprefix(_BEARER_PREFIX), secret=settings.secret_key
            )
        except TokenExpiredError:
            return AuthContext(user=None, error=ErrorCode.TOKEN_EXPIRED)
        except TokenInvalidError:
            return AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)

        # A session of its own: middleware cannot use `Depends`, and this one closes
        # before the handler's session opens.
        async with get_sessionmaker()() as session:
            user = await UserRepository(session).get(user_id)

        if user is None:
            # Covers both "never existed" and "soft-deleted since the token was issued".
            return AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)

        return AuthContext(
            user=AuthenticatedUser(
                id=user.id,
                name=user.name,
                email=user.email,
                is_admin=user.is_admin,
                must_change_password=user.must_change_password,
            ),
            error=None,
        )
```

- [ ] **Step 4: Write the dependencies**

Create `backend/app/api/deps.py`:

```python
"""Shared route dependencies.

These are this codebase's guards (`.claude/rules/router.md`). There is deliberately no
`require_password_changed`: the gate is enforced by `AuthContextMiddleware`, so it
cannot be forgotten on a new route.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthContext, AuthenticatedUser
from app.db.session import get_session


async def session_dependency() -> AsyncIterator[AsyncSession]:
    """Re-exported so routes depend on this module rather than on `app.db`."""
    async for session in get_session():
        yield session


def get_current_user(request: Request) -> AuthenticatedUser:
    """The caller, as resolved by `AuthContextMiddleware`.

    A missing `request.state.auth` means the middleware is not installed. That is a
    programming error, so it surfaces as a 500 rather than a 401 — a 401 would send
    someone hunting for a credential problem that does not exist.
    """
    auth: AuthContext | None = getattr(request.state, "auth", None)
    if auth is None:
        raise RuntimeError(
            "AuthContextMiddleware is not installed; request.state.auth is unset"
        )
    if auth.user is not None:
        return auth.user
    raise AppError(
        status.HTTP_401_UNAUTHORIZED,
        auth.error or ErrorCode.INVALID_TOKEN,
        "Authentication is required.",
    )


def require_admin(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """The caller, required to be an admin."""
    if not current_user.is_admin:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.ADMIN_REQUIRED,
            "This action requires an administrator account.",
        )
    return current_user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
SessionDep = Annotated[AsyncSession, Depends(session_dependency)]
```

- [ ] **Step 5: Register the middleware in the right position**

In `backend/app/main.py`, add the import and insert the registration **above** the existing
`app.add_middleware(CORSMiddleware, ...)` call:

```python
from app.core.middleware import AuthContextMiddleware

# ... inside create_app, after register_exception_handlers(app):

    # Registered BEFORE CORS on purpose. add_middleware inserts at index 0 and the
    # stack is applied reversed, so the last-added middleware is outermost — CORS
    # must be outside this one, or the gate's 403 reaches the browser without CORS
    # headers and the frontend sees an opaque network error.
    app.add_middleware(AuthContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        ...
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_auth_middleware.py -v`
Expected: PASS, 11 tests. If `test_the_gates_403_carries_cors_headers` fails, the two
`add_middleware` calls are in the wrong order — swap them; do not weaken the test.

- [ ] **Step 7: Update the PRD's gate scope and the router rule**

`docs/PRD.md` §4.0 — replace the `must_change_password` acceptance criterion:

```markdown
- When `must_change_password` is set, login succeeds but **every route outside `/auth`** returns
  `403` with the machine-readable code `PASSWORD_CHANGE_REQUIRED`, so the frontend can force the
  change. The whole `/auth` surface stays reachable: the user needs `GET /auth/me` to see who they
  are, `POST /auth/refresh` because the access token expires in 15 minutes while they are typing,
  and `POST /auth/logout` / `logout-all` to abandon the flow or kill other sessions first.
```

`.claude/rules/router.md` — three edits:

1. Change the canonical handler example from `def create_project(...)` to
   `async def create_project(...)`, and add: *"Handlers are `async def`. The persistence layer is
   async (`.claude/rules/persistence.md`); a sync handler would block the event loop or need a
   threadpool hop for every query."*
2. In "Access control lives in dependencies", change the aliases to annotate `AuthenticatedUser`
   and explain why:

```python
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]  # any authenticated user
AdminUser   = Annotated[AuthenticatedUser, Depends(require_admin)]     # is_admin, else 403
```

   *"`AuthenticatedUser` is a frozen dataclass, not the ORM `User`. `AuthContextMiddleware`
   resolves identity in its own session, which closes before the handler runs — passing the ORM
   row would hand every handler a detached instance. A service that needs to mutate the row loads
   it itself."*
3. Add a note that the forced-password-change gate is middleware, not a dependency, so a new
   route is covered without opting in — and that adding a route group under a **new** prefix
   means deciding whether it belongs in `GATE_EXEMPT_PREFIXES`.

- [ ] **Step 8: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/middleware.py backend/app/api/deps.py backend/app/main.py \
        backend/tests/test_auth_middleware.py docs/PRD.md .claude/rules/router.md
git commit -m "feat(auth): establish per-request identity and gate password changes

Middleware rather than a dependency, so a route added at M2 is gated
without opting in. It loads the user row on every authenticated request
rather than trusting the token: the PRD requires deactivation to end
sessions immediately, which a stateless 15-minute token cannot deliver.

Identity is established for every request and the 403 is applied only
outside /auth. The inverse — returning early for exempt paths — would
leave request.state.auth unset and make GET /auth/me raise RuntimeError.

Registered before CORSMiddleware, because add_middleware inserts at
index 0 and the stack is applied reversed: CORS has to end up outermost
or the gate's 403 reaches the browser stripped of CORS headers and the
frontend cannot read the code. A test asserts that property rather than
the ordering.

Identity crosses into handlers as a frozen AuthenticatedUser, not a
detached ORM row. Amends PRD 4.0's gate scope and router.md's handler
and alias examples to match."
```

---

## Task 9: Login rate limiting

**Files:**
- Create: `backend/app/core/rate_limit.py`
- Test: `backend/tests/test_rate_limit.py`
- Docs: `docs/PRD.md` §4.0 — the limiter's scope and the failures-only rule

**Interfaces:**
- Consumes: `Settings.redis_url` / `login_rate_*` / `trusted_proxy_hops` (Task 1); `AppError`, `ErrorCode` (Task 5).
- Produces:
  - `client_ip(request: Request, *, trusted_proxy_hops: int) -> str`
  - `RateLimiter` — `__init__(redis: Redis)`, `hit(key: str, *, limit: int, window_seconds: int) -> None` (raises `AppError(429)`), `reset(key: str) -> None`
  - `get_redis() -> Redis` (cached), `get_rate_limiter(...) -> RateLimiter` (FastAPI dependency)
  - `enforce_login_ip_limit(request: Request, ...) -> None` — FastAPI dependency
  - `LoginAttemptLimiter` — `__init__(limiter, settings)`, `check_email(email: str) -> None`, `record_failure(email: str) -> None`, `clear(email: str) -> None`
  - `RateLimiterDep`, `LoginAttemptLimiterDep` type aliases

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_rate_limit.py`:

```python
"""Fixed-window rate limiting, and the two decisions that are easy to get wrong.

`client_ip` matters because Caddy sits in front of the API (docs/PRD.md:304): read
naively, every request looks like it came from the proxy and "5 per minute per IP"
silently becomes "5 per minute for the whole instance" — two colleagues mistyping a
password would lock everyone out.

Failing open when Redis is unreachable is deliberate (D18): a Redis outage should
degrade brute-force protection, not lock the team out of their own tool.
"""

import pytest
import redis.asyncio as aioredis
from fastapi import Request
from starlette.datastructures import Headers

from app.core.errors import AppError
from app.core.rate_limit import RateLimiter, client_ip


def _request(*, peer: str, forwarded_for: str | None = None) -> Request:
    headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": (peer, 12345),
        "headers": Headers(headers).raw,
    }
    return Request(scope)


def test_zero_hops_ignores_the_forwarded_header() -> None:
    """Trusting the header with no proxy in front lets a client forge its own IP."""
    request = _request(peer="10.0.0.5", forwarded_for="1.2.3.4")

    assert client_ip(request, trusted_proxy_hops=0) == "10.0.0.5"


def test_one_hop_takes_the_entry_left_of_the_proxy() -> None:
    request = _request(peer="10.0.0.5", forwarded_for="203.0.113.9")

    assert client_ip(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_client_cannot_spoof_past_the_limit_by_prepending_entries() -> None:
    """Counting from the right is what makes the value untrustworthy-input-safe."""
    request = _request(peer="10.0.0.5", forwarded_for="9.9.9.9, 203.0.113.9")

    assert client_ip(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_missing_header_falls_back_to_the_socket() -> None:
    request = _request(peer="10.0.0.5")

    assert client_ip(request, trusted_proxy_hops=1) == "10.0.0.5"


async def test_hits_under_the_limit_pass(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)

    for _ in range(3):
        await limiter.hit("test:key", limit=3, window_seconds=60)


async def test_the_hit_over_the_limit_is_429(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:key", limit=3, window_seconds=60)

    with pytest.raises(AppError) as caught:
        await limiter.hit("test:key", limit=3, window_seconds=60)

    assert caught.value.status_code == 429
    assert caught.value.code == "RATE_LIMITED"


async def test_separate_keys_have_separate_budgets(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:a", limit=3, window_seconds=60)

    await limiter.hit("test:b", limit=3, window_seconds=60)


async def test_the_counter_expires(redis_client: aioredis.Redis) -> None:
    """Without a TTL the first window would bound the key forever."""
    limiter = RateLimiter(redis_client)
    await limiter.hit("test:ttl", limit=3, window_seconds=60)

    assert await redis_client.ttl("test:ttl") > 0


async def test_reset_clears_the_budget(redis_client: aioredis.Redis) -> None:
    """A successful login clears the per-email failure counter."""
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:reset", limit=3, window_seconds=60)

    await limiter.reset("test:reset")

    await limiter.hit("test:reset", limit=3, window_seconds=60)


async def test_an_unreachable_redis_fails_open() -> None:
    """D18: degrade the control rather than deny every login."""
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0", socket_connect_timeout=0.05)
    limiter = RateLimiter(unreachable)

    for _ in range(50):
        await limiter.hit("test:open", limit=1, window_seconds=60)

    await unreachable.aclose()


async def test_an_unreachable_redis_makes_reset_a_no_op() -> None:
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0", socket_connect_timeout=0.05)
    limiter = RateLimiter(unreachable)

    await limiter.reset("test:open")

    await unreachable.aclose()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.rate_limit'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/rate_limit.py`:

```python
"""Redis fixed-window rate limiting for the credential-checking routes.

Applied per route by an explicit dependency, not as global middleware (D7):
`docs/PRD.md:115` specifies only a login limit, and `SECURITY.md:42` puts
authenticated-user resource exhaustion outside the threat model, so a blanket limiter
would guard against something the project has deliberately declined to defend.

Fails open when Redis is unreachable (D18). A Redis outage on a single-VPS deployment
is one the operator is already fixing; refusing every login in the meantime turns a
degraded control into an outage.
"""

import logging
import time
from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request, status
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


def client_ip(request: Request, *, trusted_proxy_hops: int) -> str:
    """The caller's address, accounting for reverse proxies.

    Counts from the **right** of `X-Forwarded-For`, discarding one entry per trusted
    hop. The header is client-controlled, so counting from the left would let anyone
    evade a per-IP limit by prepending a fake entry.

    `trusted_proxy_hops=0` ignores the header entirely and trusts the socket address.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    index = len(entries) - trusted_proxy_hops
    if index < 0:
        # Fewer entries than configured hops: the chain is not what we were told to
        # expect, so trust the socket rather than a value we cannot place.
        logger.warning(
            "X-Forwarded-For has %d entries but %d proxy hops are configured",
            len(entries),
            trusted_proxy_hops,
        )
        return peer
    return entries[index]


class RateLimiter:
    """Fixed-window counters. One Redis key per (subject, window)."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        """Count one attempt against `key`; raise `AppError(429)` once over `limit`."""
        window = int(time.time()) // window_seconds
        windowed_key = f"{key}:{window}"
        try:
            async with self.redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(windowed_key)
                pipeline.expire(windowed_key, window_seconds)
                count, _ = await pipeline.execute()
        except RedisError:
            logger.error("Rate limiter unavailable; allowing %s", key, exc_info=True)
            return

        if int(count) > limit:
            raise AppError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many attempts. Try again shortly.",
            )

    async def reset(self, key: str) -> None:
        """Drop the current window's counter for `key`."""
        window = int(time.time()) // 3600
        try:
            # Clear both plausible windows so a minute-scoped and an hour-scoped key
            # can share this method without the caller tracking which it used.
            await self.redis.delete(f"{key}:{window}", f"{key}:{int(time.time()) // 60}")
        except RedisError:
            logger.error("Rate limiter unavailable; could not reset %s", key, exc_info=True)


@lru_cache
def get_redis() -> aioredis.Redis:
    """The process-wide Redis client, built once from settings."""
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def get_rate_limiter() -> RateLimiter:
    """FastAPI dependency providing the limiter."""
    return RateLimiter(get_redis())


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def enforce_login_ip_limit(
    request: Request, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Per-IP limit on a credential-checking route.

    Counted before the credential check, so it also bounds attempts against addresses
    that do not exist — which is what makes it the enumeration-resistant half of the
    pair.
    """
    address = client_ip(request, trusted_proxy_hops=settings.trusted_proxy_hops)
    await limiter.hit(
        f"rl:login:ip:{address}", limit=settings.login_rate_per_minute_ip, window_seconds=60
    )


class LoginAttemptLimiter:
    """The per-email half of the login limit, counting failures only.

    A raw per-email counter is a lockout weapon: anyone who knows a colleague's address
    could spend ten bad guesses an hour to keep them out. Counting only failures — and
    clearing on success — does not remove that, but it stops legitimate logins from
    consuming the budget.
    """

    def __init__(self, limiter: RateLimiter, settings: Settings) -> None:
        self.limiter = limiter
        self.settings = settings

    def _key(self, email: str) -> str:
        return f"rl:login:email:{email.strip().lower()}"

    async def check_email(self, email: str) -> None:
        """Raise `429` if this address has already failed too many times this hour."""
        window = 3600
        key = self._key(email)
        try:
            count = await self.limiter.redis.get(f"{key}:{int(time.time()) // window}")
        except RedisError:
            logger.error("Rate limiter unavailable; allowing %s", key, exc_info=True)
            return
        if count is not None and int(count) >= self.settings.login_rate_per_hour_email:
            raise AppError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many failed attempts for this account. Try again later.",
            )

    async def record_failure(self, email: str) -> None:
        """Count a failed attempt. Never raises — the caller is already returning 401."""
        try:
            await self.limiter.hit(
                self._key(email), limit=self.settings.login_rate_per_hour_email, window_seconds=3600
            )
        except AppError:
            # The limit is enforced by `check_email` on the next attempt; raising here
            # would turn a wrong password into a 429 and leak that the count is at its
            # ceiling for this address.
            return

    async def clear(self, email: str) -> None:
        """Reset the failure budget after a successful login."""
        await self.limiter.reset(self._key(email))


def get_login_attempt_limiter(limiter: RateLimiterDep, settings: SettingsDep) -> LoginAttemptLimiter:
    """FastAPI dependency providing the per-email limiter."""
    return LoginAttemptLimiter(limiter, settings)


LoginAttemptLimiterDep = Annotated[LoginAttemptLimiter, Depends(get_login_attempt_limiter)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rate_limit.py -v`
Expected: PASS, 11 tests. The two fail-open tests connect to port 6390, which nothing listens
on — that is the point; they must complete in well under a second thanks to
`socket_connect_timeout`.

- [ ] **Step 5: Document the limiter's scope**

`docs/PRD.md` §4.0 — replace the rate-limiting acceptance criterion:

```markdown
- Login is rate limited to 5/min/IP and 10/hour/email, returning `429`. Only **failed** attempts
  count toward the per-email limit and a successful login clears it — a raw per-email counter is
  a lockout weapon, since anyone knowing a colleague's address could spend the budget on their
  behalf. The per-IP limit is counted before the credential check, so it also bounds attempts
  against addresses that do not exist.
- `POST /auth/change-password` carries the same per-IP limit. It verifies `current_password`, so
  leaving it uncapped while login is capped only moves the target.
- Behind a reverse proxy, `TRUSTED_PROXY_HOPS` must be set to the number of proxies in front of
  the API. Left at `0` with Caddy in front, every request appears to come from Caddy and the
  per-IP limit becomes a single instance-wide limit.
```

- [ ] **Step 6: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/rate_limit.py backend/tests/test_rate_limit.py docs/PRD.md
git commit -m "feat(auth): add Redis login rate limiting

Per-route dependency rather than global middleware: the PRD specifies
only a login limit, and SECURITY.md puts authenticated-user resource
exhaustion outside the threat model.

client_ip counts X-Forwarded-For entries from the right, one per trusted
hop. The header is client-controlled, so counting from the left would let
anyone evade the per-IP limit by prepending an entry. At zero hops the
header is ignored entirely.

Only failed attempts count toward the per-email limit and success clears
it, so a colleague cannot spend someone else's budget to lock them out.
record_failure swallows its own 429 rather than converting a wrong
password into a 429 that leaks the counter's state.

Unreachable Redis fails open with an error log: an outage should degrade
brute-force protection, not deny every login."
```

---

## Task 10: The access resolver — the phase-2 seam

Small, and load-bearing out of proportion to its size: `docs/PRD.md:359` makes "read scoping
happens in exactly one function, confirmed by grep" a success criterion.

**Files:**
- Create: `backend/app/core/access.py`
- Test: `backend/tests/test_access.py`
- Docs: `docs/PRD.md` §4.1 and §5.1 — the resolver's signature

**Interfaces:**
- Consumes: `AuthenticatedUser` (Task 8).
- Produces: `ProjectScope` (frozen dataclass, `unrestricted: bool`, `ids: frozenset[UUID]`, classmethods `all()` and `of(ids)`), `resolve_project_scope(user: AuthenticatedUser) -> ProjectScope`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_access.py`:

```python
"""The one function that answers "which projects may this caller read?".

`docs/PRD.md:359` makes single-point read scoping a success criterion, and these tests
are what give it something to point at before M1 exists. When phase 2 lands, the diff
should be this function's body and this file — nothing else.
"""

import uuid

from app.core.access import ProjectScope, resolve_project_scope
from app.core.middleware import AuthenticatedUser


def _user(*, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        is_admin=is_admin,
        must_change_password=False,
    )


def test_phase_one_gives_a_regular_user_every_project() -> None:
    """Sharing is intended, not a leak — docs/PRD.md §4.1, SECURITY.md:34."""
    scope = resolve_project_scope(_user())

    assert scope.unrestricted is True


def test_phase_one_gives_an_admin_the_same_scope() -> None:
    """is_admin gates destructive operations, never reads."""
    assert resolve_project_scope(_user(is_admin=True)).unrestricted is True


def test_an_unrestricted_scope_carries_no_ids() -> None:
    """An id set alongside `unrestricted` would leave two sources of truth."""
    scope = ProjectScope.all()

    assert scope.ids == frozenset()


def test_a_restricted_scope_holds_exactly_the_given_ids() -> None:
    """The shape phase 2 will return."""
    first, second = uuid.uuid4(), uuid.uuid4()

    scope = ProjectScope.of([first, second, first])

    assert scope.unrestricted is False
    assert scope.ids == frozenset({first, second})


def test_a_restricted_scope_of_nothing_is_not_unrestricted() -> None:
    """The failure mode a `None` sentinel would have: empty must mean *no* access."""
    scope = ProjectScope.of([])

    assert scope.unrestricted is False
    assert scope.ids == frozenset()


def test_a_scope_is_immutable() -> None:
    """A caller must not be able to widen its own scope in place."""
    import dataclasses

    import pytest

    scope = ProjectScope.of([uuid.uuid4()])

    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.unrestricted = True  # type: ignore[misc]  # asserting immutability
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_access.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.access'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/access.py`:

```python
"""Read scoping — the single function that decides which projects a caller may see.

`docs/PRD.md` §2 and §5.1 require this to live in exactly one place, so phase 2's
per-project RBAC is a change to `resolve_project_scope`'s body and nothing else. A
route, service, or query that filters projects on its own is a defect even when its
output is currently identical (`.claude/rules/router.md`).

Returns an explicit `ProjectScope` rather than `list[UUID] | None`. A `None` sentinel
meaning "unrestricted" is fail-open: any accidental `None` anywhere would read as full
access. This way a caller has to branch on `unrestricted` deliberately, and an empty
`ids` set means no access rather than all of it.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Self

from app.core.middleware import AuthenticatedUser


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """Which projects a caller may read.

    Exactly one of the two states is meaningful: `unrestricted` (every project on the
    instance) or a concrete `ids` set. An unrestricted scope carries no ids, so there
    is never a second source of truth to disagree.
    """

    unrestricted: bool
    ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    @classmethod
    def all(cls) -> Self:
        """Every project on the instance. Phase 1's answer for everyone."""
        return cls(unrestricted=True, ids=frozenset())

    @classmethod
    def of(cls, ids: Iterable[uuid.UUID]) -> Self:
        """Exactly these projects. An empty set means none — not all."""
        return cls(unrestricted=False, ids=frozenset(ids))


def resolve_project_scope(user: AuthenticatedUser) -> ProjectScope:
    """Which projects this caller may read.

    Phase 1: every project on the instance, for every authenticated user. That is
    intended behaviour, not an oversight — `docs/PRD.md` §4.1 and `SECURITY.md:34` both
    say so, and `is_admin` gates destructive operations rather than reads.

    Phase 2 replaces this body with a membership lookup. Nothing that calls it changes.
    """
    return ProjectScope.all()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_access.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Record the signature in the PRD**

`docs/PRD.md` §4.1 — replace the "Access resolver" bullet:

```markdown
- **Access resolver.** All retrieval goes through one function, `resolve_project_scope(user)` in
  `backend/app/core/access.py`, which returns a `ProjectScope`: either `unrestricted` (phase 1's
  answer for every user) or a concrete set of project ids. Phase 2 replaces its body with a
  membership lookup and nothing else changes. Retrieval filters Qdrant from that scope — never
  from an unchecked path parameter. It returns a `ProjectScope` rather than a nullable list
  because a `None` meaning "unrestricted" is fail-open: an empty `ids` set must mean *no* access,
  not all of it.
```

Update the matching sentence in §5.1's "Attribution vs authorization" bullet to name
`resolve_project_scope` so a grep for the function finds the doc too.

- [ ] **Step 6: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/access.py backend/tests/test_access.py docs/PRD.md
git commit -m "feat(core): add the access resolver as the phase-2 seam

One function decides which projects a caller may read, so phase 2's
per-project RBAC is a change to its body and nothing else. Ships with a
test pinning the phase-1 contract — every user, admin or not, gets every
project — so the PRD's grep-verifiable criterion has something to point
at before M1 exists.

Returns an explicit ProjectScope rather than list[UUID] | None. A None
sentinel for 'unrestricted' is fail-open: any accidental None would read
as full access, whereas an empty ids set here means no access."
```

---

## Task 11: User schemas, UserService, and the `/users` router

**Files:**
- Create: `backend/app/schemas/pagination.py`, `backend/app/schemas/user.py`
- Create: `backend/app/services/__init__.py`, `backend/app/services/user.py`
- Create: `backend/app/api/routes/users.py`
- Modify: `backend/app/main.py` — mount the router
- Test: `backend/tests/test_users_api.py`
- Docs: `docs/PRD.md` §4.0 — reset-password body, `GET /users` visibility, the last-admin guard; `backend/README.md` — the route table

**Interfaces:**
- Consumes: `UserRepository` (Task 6), `RefreshTokenRepository` (Task 7), `CurrentUser`/`AdminUser`/`SessionDep` (Task 8), `AppError`/`ErrorCode` (Task 5), `check_password`/`get_common_passwords` (Task 4), `hash_password` (Task 3).
- Produces:
  - `ListQuery` (ApiModel): `page: int = 1`, `limit: int = 25`, `search: str | None = None`, `sort: str | None = None`, `sort_direction: Literal["asc","desc"] = "desc"`
  - `PaginatedResponse[T]` (ApiModel, generic): `items: list[T]`, `page: int`, `limit: int`, `total_count: int`, `total_pages: int`
  - `UserResponse`, `UserCreateRequest`, `UserUpdateRequest`, `ResetPasswordRequest`
  - `UserService` — `list(query) -> PaginatedResponse[UserResponse]`, `get(user_id) -> UserResponse`, `create(payload) -> UserResponse`, `update(user_id, payload, *, acting_admin_id) -> UserResponse`, `soft_delete(user_id, *, acting_admin_id) -> None`, `reset_password(user_id, payload) -> UserResponse`
  - `get_user_service(session) -> UserService`, `UserServiceDep`

- [ ] **Step 1: Write the shared pagination schemas**

Create `backend/app/schemas/pagination.py`:

```python
"""The one list-query and list-response shape, shared by every list route.

`.claude/rules/router.md` requires this: a per-resource pagination shape drifts, and a
bare array leaves a client unable to tell a last page from a filtered one.
"""

from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel

MAX_PAGE_SIZE = 100


class ListQuery(ApiModel):
    """Pagination, search, and sort for any list route.

    Inherits `ApiModel`, so `sort_direction` arrives on the wire as `sortDirection`.
    """

    page: int = Field(default=1, ge=1)
    # Capped so a caller cannot ask for the whole table in one request.
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = None
    sort: str | None = None
    sort_direction: Literal["asc", "desc"] = "desc"


class PaginatedResponse[ItemT](ApiModel):
    """A page of results plus the metadata needed to render a pager."""

    items: list[ItemT]
    page: int
    limit: int
    total_count: int
    total_pages: int

    @classmethod
    def build(
        cls, items: list[ItemT], *, page: int, limit: int, total_count: int
    ) -> "PaginatedResponse[ItemT]":
        """Derive `total_pages` in one place so routes cannot compute it differently."""
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        return cls(
            items=items, page=page, limit=limit, total_count=total_count, total_pages=total_pages
        )
```

- [ ] **Step 2: Write the user schemas**

Create `backend/app/schemas/user.py`:

```python
"""Request and response models for accounts.

`password_hash` is not a field on any response model here. Not excluded, not masked —
absent, so it cannot be serialised by accident (`.claude/rules/response-api.md`).
"""

import uuid
from datetime import datetime

from pydantic import EmailStr, field_validator

from app.schemas.base import ApiModel

# Bounds the work bcrypt is asked to do before policy runs. The real policy — minimum
# length and the wordlist — lives in the service so every rejection shares one code.
MAX_PASSWORD_FIELD_LENGTH = 256


class UserResponse(ApiModel):
    """An account as returned by the API."""

    id: uuid.UUID
    name: str
    email: EmailStr
    is_admin: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(ApiModel):
    """Admin-provisioned account. The password is communicated out of band."""

    name: str
    email: EmailStr
    password: str
    is_admin: bool = False

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """Lowercase at the boundary, so storage and lookup agree without citext."""
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value

    @field_validator("name")
    @classmethod
    def _require_a_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class UserUpdateRequest(ApiModel):
    """Partial update. Deliberately cannot change email or password.

    `docs/PRD.md:105` scopes this to name and the admin flag; password changes have
    their own two routes with their own revocation semantics.
    """

    name: str | None = None
    is_admin: bool | None = None

    @field_validator("name")
    @classmethod
    def _require_a_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value else value


class ResetPasswordRequest(ApiModel):
    """The admin supplies the new temporary password.

    Server-generating it would mean returning a secret in a response body, which
    `.claude/rules/response-api.md` forbids outright.
    """

    new_password: str

    @field_validator("new_password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value
```

- [ ] **Step 3: Write the failing route tests**

Create `backend/tests/test_users_api.py`:

```python
"""The /users surface.

Reads are open to any authenticated user; mutations are admin-only (D15). The
last-admin guard (D17) is what stops one mistaken click leaving an instance that can
only be recovered with manual SQL.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models import User

GOOD_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    name: str = "Dev",
    is_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email or f"{uuid.uuid4().hex}@example.com",
        password_hash=hash_password(GOOD_PASSWORD, cost=4),
        is_admin=is_admin,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    return user


def _auth(user: User) -> dict[str, str]:
    settings = get_settings()
    token, _ = create_access_token(
        user.id, secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes
    )
    return {"Authorization": f"Bearer {token}"}


async def test_an_admin_can_create_an_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user(db_session, is_admin=True)

    response = await client.post(
        "/users",
        headers=_auth(admin),
        json={
            "name": "New Dev",
            "email": "New.Dev@Example.com",
            "password": GOOD_PASSWORD,
            "isAdmin": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.dev@example.com"  # normalised at the boundary
    assert body["mustChangePassword"] is True


async def test_a_created_account_never_returns_a_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """response-api.md: passwords are absent from response models, not masked."""
    admin = await _make_user(db_session, is_admin=True)

    response = await client.post(
        "/users",
        headers=_auth(admin),
        json={"name": "New Dev", "email": "n@example.com", "password": GOOD_PASSWORD},
    )

    assert "password" not in response.text.lower()
    assert "$2b$" not in response.text


async def test_a_non_admin_cannot_create_an_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=False)

    response = await client.post(
        "/users",
        headers=_auth(user),
        json={"name": "New Dev", "email": "n@example.com", "password": GOOD_PASSWORD},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_a_duplicate_email_is_409(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _make_user(db_session, is_admin=True)
    await _make_user(db_session, email="taken@example.com")

    response = await client.post(
        "/users",
        headers=_auth(admin),
        json={"name": "Clash", "email": "taken@example.com", "password": GOOD_PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_a_soft_deleted_email_can_be_reused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D20: the partial unique index exists so a rehired colleague keeps their address."""
    admin = await _make_user(db_session, is_admin=True)
    departed = await _make_user(db_session, email="rehired@example.com")
    departed.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/users",
        headers=_auth(admin),
        json={"name": "Rehired", "email": "rehired@example.com", "password": GOOD_PASSWORD},
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "password", ["short", "password123456", "a" * 73], ids=["too-short", "too-common", "too-long"]
)
async def test_a_weak_password_is_400_with_one_code(
    client: AsyncClient, db_session: AsyncSession, password: str
) -> None:
    """One code for every policy failure — not 422 for length and 400 for the wordlist."""
    admin = await _make_user(db_session, is_admin=True)

    response = await client.post(
        "/users",
        headers=_auth(admin),
        json={"name": "Weak", "email": "w@example.com", "password": password},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "WEAK_PASSWORD"


async def test_any_authenticated_user_can_list_accounts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D15: from M1 every project shows created_by, which needs a name lookup."""
    user = await _make_user(db_session, is_admin=False)

    response = await client.get("/users", headers=_auth(user))

    assert response.status_code == 200


async def test_the_list_response_carries_pagination_metadata(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Never a bare array — router.md:128-146."""
    user = await _make_user(db_session)
    for index in range(3):
        await _make_user(db_session, email=f"extra{index}@example.com")

    response = await client.get("/users?page=1&limit=2", headers=_auth(user))
    body = response.json()

    assert set(body) == {"items", "page", "limit", "totalCount", "totalPages"}
    assert body["totalCount"] == 4
    assert body["totalPages"] == 2
    assert len(body["items"]) == 2


async def test_an_unknown_sort_field_is_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Sorting by password_hash must not be reachable from a query string."""
    user = await _make_user(db_session)

    response = await client.get("/users?sort=passwordHash", headers=_auth(user))

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_SORT_FIELD"


async def test_getting_an_unknown_user_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)

    response = await client.get(f"/users/{uuid.uuid4()}", headers=_auth(user))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "USER_NOT_FOUND"


async def test_an_admin_can_rename_a_user(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _make_user(db_session, is_admin=True)
    target = await _make_user(db_session, name="Old Name")

    response = await client.patch(
        f"/users/{target.id}", headers=_auth(admin), json={"name": "New Name"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_patch_cannot_change_the_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unknown fields are ignored, so the email must come back unchanged."""
    admin = await _make_user(db_session, is_admin=True)
    target = await _make_user(db_session, email="original@example.com")

    response = await client.patch(
        f"/users/{target.id}", headers=_auth(admin), json={"email": "hijack@example.com"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "original@example.com"


async def test_demoting_the_only_admin_is_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D17: the alternative is an instance recoverable only by manual SQL."""
    admin = await _make_user(db_session, is_admin=True)

    response = await client.patch(
        f"/users/{admin.id}", headers=_auth(admin), json={"isAdmin": False}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_ADMIN"


async def test_demoting_an_admin_is_fine_when_another_remains(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user(db_session, is_admin=True)
    await _make_user(db_session, email="second-admin@example.com", is_admin=True)

    response = await client.patch(
        f"/users/{admin.id}", headers=_auth(admin), json={"isAdmin": False}
    )

    assert response.status_code == 200


async def test_deleting_the_only_admin_is_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user(db_session, is_admin=True)

    response = await client.delete(f"/users/{admin.id}", headers=_auth(admin))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_ADMIN"


async def test_deleting_a_user_soft_deletes_and_revokes_their_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:84 — a soft-deleted user's refresh tokens are revoked with them."""
    admin = await _make_user(db_session, is_admin=True)
    target = await _make_user(db_session)
    from app.repositories.refresh_token import RefreshTokenRepository

    tokens = RefreshTokenRepository(db_session)
    await tokens.create(
        user_id=target.id,
        family_id=uuid.uuid4(),
        token_hash="a" * 64,
        expires_at=datetime.now(UTC).replace(year=2030),
    )
    await db_session.commit()

    response = await client.delete(f"/users/{target.id}", headers=_auth(admin))
    await db_session.commit()

    assert response.status_code == 204
    stored = await tokens.get_by_hash("a" * 64)
    assert stored is not None
    assert stored.revoked_reason == "user_deactivated"


async def test_reset_password_forces_a_change_and_revokes_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user(db_session, is_admin=True)
    target = await _make_user(db_session, must_change_password=False)

    response = await client.post(
        f"/users/{target.id}/reset-password",
        headers=_auth(admin),
        json={"newPassword": "another-fine-passphrase"},
    )

    assert response.status_code == 200
    assert response.json()["mustChangePassword"] is True


async def test_reset_password_never_echoes_the_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user(db_session, is_admin=True)
    target = await _make_user(db_session)

    response = await client.post(
        f"/users/{target.id}/reset-password",
        headers=_auth(admin),
        json={"newPassword": "another-fine-passphrase"},
    )

    assert "another-fine-passphrase" not in response.text


async def test_a_non_admin_cannot_reset_a_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=False)
    target = await _make_user(db_session)

    response = await client.post(
        f"/users/{target.id}/reset-password",
        headers=_auth(user),
        json={"newPassword": "another-fine-passphrase"},
    )

    assert response.status_code == 403
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_users_api.py -v`
Expected: FAIL — every test 404s, because `/users` is not mounted.

- [ ] **Step 5: Write the service**

Create an empty `backend/app/services/__init__.py`, then `backend/app/services/user.py`:

```python
"""Account provisioning and lifecycle.

Owns the rules, the transaction, and the orchestration across two repositories.
Imports no SQLAlchemy constructs — see `.claude/rules/persistence.md`.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import hash_password
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)

DEFAULT_SORT_FIELD = "created_at"


class UserService:
    """Business rules for `/users`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    def _hash(self, password: str) -> str:
        """Apply policy, then hash. One error code for every policy failure."""
        try:
            check_password(
                password,
                min_length=self.settings.password_min_length,
                max_bytes=self.settings.password_max_bytes,
                common=get_common_passwords(),
            )
        except PasswordPolicyError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.WEAK_PASSWORD, error.reason
            ) from error
        return hash_password(password, cost=self.settings.bcrypt_cost)

    async def _load(self, user_id: uuid.UUID) -> User:
        """Fetch a live account or raise `404`."""
        user = await self.users.get(user_id)
        if user is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.USER_NOT_FOUND, "No such user."
            )
        return user

    async def _guard_last_admin(self, user: User) -> None:
        """Refuse an operation that would leave the instance with no admin (D17)."""
        if not user.is_admin:
            return
        if await self.users.count_active_admins(excluding=user.id) == 0:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.LAST_ADMIN,
                "This is the only administrator account. Promote another admin first.",
            )

    async def list(self, query: ListQuery) -> PaginatedResponse[UserResponse]:
        """One page of accounts. Readable by any authenticated user (D15)."""
        try:
            rows, total = await self.users.list_page(
                page=query.page,
                limit=query.limit,
                search=query.search,
                sort=query.sort or DEFAULT_SORT_FIELD,
                descending=query.sort_direction == "desc",
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.INVALID_SORT_FIELD,
                f"Cannot sort by that field. Allowed: {sorted(self.users.SORTABLE_FIELDS)}.",
            ) from error

        return PaginatedResponse.build(
            [UserResponse.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get(self, user_id: uuid.UUID) -> UserResponse:
        """One account by id."""
        return UserResponse.model_validate(await self._load(user_id))

    async def create(self, payload: UserCreateRequest) -> UserResponse:
        """Provision an account. `must_change_password` is set on every new account."""
        if await self.users.email_exists(payload.email):
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EMAIL_ALREADY_EXISTS,
                "An account with that email already exists.",
            )

        user = User(
            id=uuid.uuid4(),
            name=payload.name,
            email=payload.email,
            password_hash=self._hash(payload.password),
            is_admin=payload.is_admin,
            must_change_password=True,
        )
        await self.users.add(user)
        await self.session.commit()
        return UserResponse.model_validate(user)

    async def update(self, user_id: uuid.UUID, payload: UserUpdateRequest) -> UserResponse:
        """Partial update of name and the admin flag."""
        user = await self._load(user_id)

        if payload.is_admin is False:
            await self._guard_last_admin(user)

        if payload.name is not None:
            user.name = payload.name
        if payload.is_admin is not None:
            user.is_admin = payload.is_admin

        await self.session.commit()
        return UserResponse.model_validate(user)

    async def soft_delete(self, user_id: uuid.UUID) -> None:
        """Deactivate an account and end every session it holds.

        The token revocation is what makes `docs/PRD.md:101`'s "immediately" true for
        refresh; the middleware's per-request row load covers the access token.
        """
        user = await self._load(user_id)
        await self._guard_last_admin(user)
        await self.users.soft_delete(user)
        await self.tokens.revoke_all_for_user(user.id, reason="user_deactivated")
        await self.session.commit()

    async def reset_password(
        self, user_id: uuid.UUID, payload: ResetPasswordRequest
    ) -> UserResponse:
        """Set an admin-supplied temporary password and force a change on next login."""
        user = await self._load(user_id)
        user.password_hash = self._hash(payload.new_password)
        user.must_change_password = True
        user.updated_at = datetime.now(UTC)
        await self.tokens.revoke_all_for_user(user.id, reason="admin_reset")
        await self.session.commit()
        return UserResponse.model_validate(user)
```

- [ ] **Step 6: Write the router**

Create `backend/app/api/routes/users.py`:

```python
"""Account provisioning.

Reads are open to any authenticated user; mutations require an admin (D15). That is
why the dependencies are per-route rather than one router-level `require_admin` — from
M1 every project and QA pair shows `created_by`, and turning an id into a name should
not need an admin token.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["Users"])


def get_user_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> UserService:
    """Provide the service with a request-scoped session."""
    return UserService(session, settings)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List accounts",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422)},
)
async def list_users(
    current_user: CurrentUser,
    service: UserServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[UserResponse]:
    return await service.list(query)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one account",
    responses={code: ERROR_RESPONSES[code] for code in (401, 404)},
)
async def get_user(
    user_id: uuid.UUID, current_user: CurrentUser, service: UserServiceDep
) -> UserResponse:
    return await service.get(user_id)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision an account",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 409, 422)},
)
async def create_user(
    payload: UserCreateRequest, current_user: AdminUser, service: UserServiceDep
) -> UserResponse:
    return await service.create(payload)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an account's name or admin flag",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    return await service.update(user_id, payload)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an account",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def delete_user(
    user_id: uuid.UUID, current_user: AdminUser, service: UserServiceDep
) -> None:
    await service.soft_delete(user_id)


@router.post(
    "/{user_id}/reset-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Set a temporary password for an account",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 404, 422)},
)
async def reset_user_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    current_user: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    return await service.reset_password(user_id, payload)
```

- [ ] **Step 7: Mount the router**

In `backend/app/main.py`, import `users` alongside the existing route imports and register it
after `health`:

```python
from app.api.routes import health, index, users

# ... inside create_app:
    app.include_router(index.router)
    app.include_router(health.router)
    app.include_router(users.router)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_users_api.py -v`
Expected: PASS, 20 tests.

- [ ] **Step 9: Update the PRD and the backend route table**

`docs/PRD.md` §4.0 — amend the users acceptance criterion:

```markdown
- `POST /users` (**admin only**) accepts `{name, email, password, isAdmin?}`, creates the account
  with `must_change_password=True`. `GET /users` and `GET /users/{id}` are readable by **any
  authenticated user** — from M1 every project and QA pair carries `created_by`, and turning an id
  into a name should not require an admin token. `PATCH /users/{id}` (**admin only**) updates
  name/admin flag; `DELETE /users/{id}` (**admin only**) soft-deletes and revokes that user's
  refresh tokens.
- `POST /users/{id}/reset-password` (**admin only**) accepts `{newPassword}` — the admin supplies
  it and communicates it out of band, because a server-generated password would have to be
  returned in a response body. It re-sets `must_change_password` and revokes all of that user's
  refresh tokens.
- **The last active admin cannot be demoted or deleted.** `PATCH` clearing `isAdmin`, or `DELETE`,
  returns `409` when the operation would leave the instance with zero active admins — otherwise
  recovery needs manual SQL, which §7 exists to avoid.
```

`backend/README.md` — add the route table (the table must be exhaustive per
`.claude/rules/documentation.md`):

```markdown
### Users

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/users` | any user | List accounts, paginated |
| `GET` | `/users/{id}` | any user | One account |
| `POST` | `/users` | admin | Provision an account |
| `PATCH` | `/users/{id}` | admin | Update name or admin flag |
| `DELETE` | `/users/{id}` | admin | Deactivate, revoking sessions |
| `POST` | `/users/{id}/reset-password` | admin | Set a temporary password |
```

- [ ] **Step 10: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/pagination.py backend/app/schemas/user.py backend/app/services \
        backend/app/api/routes/users.py backend/app/main.py \
        backend/tests/test_users_api.py docs/PRD.md backend/README.md
git commit -m "feat(users): add account provisioning

Reads open to any authenticated user, mutations admin-only. Reads are not
gated because from M1 every project and QA pair shows created_by, and
turning an id into a name should not need an admin token — the
alternative is a second, parallel directory endpoint later.

reset-password takes an admin-supplied password rather than generating
one: a generated password would have to be returned in a response body,
which response-api.md forbids outright.

The last active admin cannot be demoted or deleted. Without the guard one
mistaken click leaves an instance recoverable only by manual SQL, which
is exactly what the PRD's 'no manual database work' criterion is about.

Password policy failures all return 400 WEAK_PASSWORD — length is
checked in the service, not as a Pydantic constraint, so length and
wordlist rejections do not split across 422 and 400."
```

---

## Task 12: Auth schemas, AuthService, and the `/auth` router

The rotation logic is the substantive part. Its ordering is not arbitrary — expiry is checked
before replay so an old, honestly-expired token does not revoke a whole family.

**Files:**
- Create: `backend/app/schemas/auth.py`, `backend/app/services/auth.py`, `backend/app/api/routes/auth.py`
- Modify: `backend/app/main.py` — mount the router
- Test: `backend/tests/test_auth_api.py`
- Docs: `docs/PRD.md` §4.0 — cookie transport and the grace window; `backend/README.md` — the route table

**Interfaces:**
- Consumes everything from Tasks 3–9.
- Produces:
  - `LoginRequest`, `ChangePasswordRequest`, `AccessTokenResponse` (`access_token`, `token_type`, `expires_in`, `user`)
  - `AuthService` — `login(email, password) -> tuple[AccessTokenResponse, str]`, `refresh(raw_token) -> tuple[AccessTokenResponse, str]`, `change_password(user_id, payload, raw_token) -> UserResponse`, `logout(raw_token) -> None`, `logout_all(user_id) -> None`, `current(user_id) -> UserResponse`
  - Each token-issuing method returns `(response, raw_refresh_token)`; the route sets the cookie, so cookie mechanics stay out of the service.

- [ ] **Step 1: Write the schemas**

Create `backend/app/schemas/auth.py`:

```python
"""Request and response models for `/auth`.

The refresh token is never a field here. It travels only as an httpOnly cookie, so it
is unreadable by any script on the page (D3).
"""

from pydantic import EmailStr, field_validator

from app.schemas.base import ApiModel
from app.schemas.user import MAX_PASSWORD_FIELD_LENGTH, UserResponse


class LoginRequest(ApiModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        # Bounds bcrypt's work before any policy check runs.
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str

    @field_validator("current_password", "new_password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value


class AccessTokenResponse(ApiModel):
    """What login and refresh return. The refresh token is in the cookie, not here."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_auth_api.py`:

```python
"""The /auth surface: login, rotation, the gate, and revocation.

The rotation tests are the ones worth reading twice. Strict rotation would log out any
client that refreshes twice concurrently — two browser tabs is enough — so a 10-second
grace window mints a sibling token instead of treating the second use as a replay
(D12). Anything outside the window still revokes the whole family.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_password, sha256_hex
from app.models import User

PASSWORD = "a-perfectly-fine-passphrase"
NEW_PASSWORD = "another-entirely-fine-passphrase"


async def _make_user(
    session: AsyncSession,
    *,
    email: str = "dev@example.com",
    is_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=email,
        password_hash=hash_password(PASSWORD, cost=4),
        is_admin=is_admin,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str = "dev@example.com") -> tuple[str, str]:
    """Log in and return (access token, raw refresh cookie)."""
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    cookie = response.cookies[get_settings().refresh_cookie_name]
    return response.json()["accessToken"], cookie


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_returns_an_access_token_and_the_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == get_settings().access_token_ttl_minutes * 60
    assert body["user"]["email"] == "dev@example.com"


async def test_login_sets_an_httponly_refresh_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D3: unreadable by any script on the page, unlike localStorage."""
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "Path=/auth" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")


async def test_login_never_returns_the_refresh_token_in_the_body(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert "refresh" not in response.json()


async def test_login_records_last_login_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)

    await client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    await db_session.refresh(user)

    assert user.last_login_at is not None


async def test_a_wrong_password_and_an_unknown_email_are_indistinguishable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:114 — one uniform failure, so login cannot enumerate accounts."""
    await _make_user(db_session)

    wrong = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "wrong-but-long-enough"}
    )
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong-but-long-enough"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_a_soft_deleted_user_cannot_log_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401


async def test_the_sixth_login_attempt_in_a_minute_is_429(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    for _ in range(get_settings().login_rate_per_minute_ip):
        await client.post(
            "/auth/login", json={"email": "dev@example.com", "password": "wrong-but-long-enough"}
        )
    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


async def test_me_returns_the_caller(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user(db_session)
    access, _ = await _login(client)

    response = await client.get("/auth/me", headers=_bearer(access))

    assert response.status_code == 200
    assert response.json()["email"] == "dev@example.com"


async def test_refresh_rotates_the_cookie_and_returns_a_new_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 200
    assert response.cookies[name] != cookie


async def test_refresh_without_a_cookie_is_401(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_replaying_a_consumed_token_after_the_grace_window_revokes_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The point of rotation: a leaked token is detected on its second use."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name
    await client.post("/auth/refresh", cookies={name: cookie})

    # Age the consumed token past the grace window.
    await db_session.execute(
        text("UPDATE refresh_tokens SET used_at = :stale WHERE token_hash = :hash"),
        {"stale": datetime.now(UTC) - timedelta(hours=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "REFRESH_TOKEN_REUSED"

    remaining = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")
    )
    assert remaining.scalar_one() == 0


async def test_two_refreshes_inside_the_grace_window_both_succeed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D12: two tabs racing a refresh must not log the user out."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    first = await client.post("/auth/refresh", cookies={name: cookie})
    second = await client.post("/auth/refresh", cookies={name: cookie})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.cookies[name] != second.cookies[name]

    revoked = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL")
    )
    assert revoked.scalar_one() == 0


async def test_an_expired_refresh_token_does_not_revoke_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Expiry is checked before replay: an honestly-stale token is not an attack."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name
    await db_session.execute(
        text("UPDATE refresh_tokens SET expires_at = :past WHERE token_hash = :hash"),
        {"past": datetime.now(UTC) - timedelta(days=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_refresh_fails_once_the_owner_is_deactivated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    _, cookie = await _login(client)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/refresh", cookies={get_settings().refresh_cookie_name: cookie}
    )

    assert response.status_code == 401


async def test_change_password_clears_the_flag_and_works_with_the_same_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """must_change_password is not a claim, so no new access token is needed."""
    await _make_user(db_session, must_change_password=True)
    access, cookie = await _login(client)

    changed = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    listing = await client.get("/users", headers=_bearer(access))

    assert changed.status_code == 200
    assert changed.json()["mustChangePassword"] is False
    assert listing.status_code == 200


async def test_the_gate_blocks_users_until_the_password_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, must_change_password=True)
    access, _ = await _login(client)

    response = await client.get("/users", headers=_bearer(access))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_change_password_rejects_a_wrong_current_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, cookie = await _login(client)

    response = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": "not-the-current-one", "newPassword": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_change_password_rejects_a_weak_new_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, cookie = await _login(client)

    response = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": "short"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "WEAK_PASSWORD"


async def test_change_password_spares_the_callers_own_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:108 — all *other* refresh tokens are revoked."""
    await _make_user(db_session)
    access, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 200


async def test_logout_revokes_the_presented_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    logout = await client.post("/auth/logout", cookies={name: cookie})
    reuse = await client.post("/auth/refresh", cookies={name: cookie})

    assert logout.status_code == 204
    assert reuse.status_code == 401


async def test_logout_is_idempotent(client: AsyncClient) -> None:
    """Logging out twice, or with no cookie, is not an error condition."""
    response = await client.post("/auth/logout")

    assert response.status_code == 204


async def test_logout_all_revokes_every_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, first_cookie = await _login(client)
    _, second_cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    await client.post("/auth/logout-all", headers=_bearer(access))

    for cookie in (first_cookie, second_cookie):
        assert (await client.post("/auth/refresh", cookies={name: cookie})).status_code == 401


async def test_no_auth_response_ever_contains_a_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, _ = await _login(client)

    for response in (
        await client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD}),
        await client.get("/auth/me", headers=_bearer(access)),
    ):
        assert "$2b$" not in response.text
        assert "passwordHash" not in response.text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v`
Expected: FAIL — every request 404s; `/auth` is not mounted.

- [ ] **Step 4: Write the service**

Create `backend/app/services/auth.py`:

```python
"""Login, rotation, password change, and revocation.

Every token-issuing method returns `(response, raw_refresh_token)`. The route sets the
cookie, so cookie attributes stay an HTTP concern and the service stays testable
without a request.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_opaque_token,
    hash_password,
    needs_rehash,
    sha256_hex,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import AccessTokenResponse, ChangePasswordRequest
from app.schemas.user import UserResponse


class AuthService:
    """Business rules for `/auth`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    # --- helpers -----------------------------------------------------------

    def _invalid_credentials(self) -> AppError:
        """One uniform failure, so login cannot be used to enumerate accounts."""
        return AppError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_CREDENTIALS,
            "Incorrect email or password.",
        )

    def _invalid_token(self, code: ErrorCode = ErrorCode.INVALID_TOKEN) -> AppError:
        return AppError(status.HTTP_401_UNAUTHORIZED, code, "Session is no longer valid.")

    def _validate_new_password(self, password: str) -> str:
        try:
            check_password(
                password,
                min_length=self.settings.password_min_length,
                max_bytes=self.settings.password_max_bytes,
                common=get_common_passwords(),
            )
        except PasswordPolicyError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.WEAK_PASSWORD, error.reason
            ) from error
        return hash_password(password, cost=self.settings.bcrypt_cost)

    async def _issue(self, user: User, *, family_id: uuid.UUID | None = None) -> tuple[
        AccessTokenResponse, str
    ]:
        """Mint an access token and a refresh token, storing only the latter's digest."""
        access_token, expires_in = create_access_token(
            user.id,
            secret=self.settings.secret_key,
            ttl_minutes=self.settings.access_token_ttl_minutes,
        )
        raw_refresh = generate_opaque_token()
        await self.tokens.create(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=sha256_hex(raw_refresh),
            expires_at=datetime.now(UTC)
            + timedelta(days=self.settings.refresh_token_ttl_days),
        )
        response = AccessTokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )
        return response, raw_refresh

    async def _load_token(self, raw_token: str | None) -> RefreshToken:
        """Resolve a presented refresh token or raise `401`."""
        if not raw_token:
            raise self._invalid_token()
        token = await self.tokens.get_by_hash(sha256_hex(raw_token))
        if token is None:
            raise self._invalid_token()
        return token

    # --- operations --------------------------------------------------------

    async def login(self, email: str, password: str) -> tuple[AccessTokenResponse, str]:
        """Verify credentials and issue a new token pair.

        An unknown address is still verified against a dummy hash, so the response
        timing does not reveal whether the account exists (`docs/PRD.md:114`).
        """
        user = await self.users.get_by_email(email)
        if user is None:
            verify_password(password, DUMMY_PASSWORD_HASH)
            raise self._invalid_credentials()

        if not verify_password(password, user.password_hash):
            raise self._invalid_credentials()

        # The cost factor lives in the stored hash, so raising it later reaches
        # existing accounts on their next login (D22).
        if needs_rehash(user.password_hash, cost=self.settings.bcrypt_cost):
            user.password_hash = hash_password(password, cost=self.settings.bcrypt_cost)

        user.last_login_at = datetime.now(UTC)
        issued = await self._issue(user)
        await self.session.commit()
        return issued

    async def refresh(self, raw_token: str | None) -> tuple[AccessTokenResponse, str]:
        """Exchange a refresh token for a new pair, rotating it.

        Order matters. Expiry is checked before reuse so an honestly-stale token does
        not revoke a family; reuse inside the grace window mints a sibling rather than
        being treated as a replay (D12).
        """
        token = await self._load_token(raw_token)

        if token.revoked_at is not None:
            await self.tokens.revoke_family(token.family_id, reason="replay")
            await self.session.commit()
            raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)

        if token.expires_at <= datetime.now(UTC):
            raise self._invalid_token(ErrorCode.TOKEN_EXPIRED)

        if token.used_at is not None:
            grace = timedelta(seconds=self.settings.refresh_rotation_grace_seconds)
            if datetime.now(UTC) - token.used_at > grace:
                await self.tokens.revoke_family(token.family_id, reason="replay")
                await self.session.commit()
                raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)
            # Inside the window: two tabs raced. Mint a sibling in the same family.
            user = await self.users.get(token.user_id)
            if user is None:
                await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
                await self.session.commit()
                raise self._invalid_token()
            issued = await self._issue(user, family_id=token.family_id)
            await self.session.commit()
            return issued

        user = await self.users.get(token.user_id)
        if user is None:
            await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
            await self.session.commit()
            raise self._invalid_token()

        await self.tokens.mark_used(token)
        issued = await self._issue(user, family_id=token.family_id)
        await self.session.commit()
        return issued

    async def change_password(
        self, user_id: uuid.UUID, payload: ChangePasswordRequest, raw_token: str | None
    ) -> UserResponse:
        """Change the caller's own password, keeping their current session alive."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()

        if not verify_password(payload.current_password, user.password_hash):
            raise self._invalid_credentials()

        user.password_hash = self._validate_new_password(payload.new_password)
        user.must_change_password = False
        user.updated_at = datetime.now(UTC)

        # Revoke all *other* sessions (docs/PRD.md:108). The caller's own token is
        # identifiable because it arrived in the cookie.
        current = await self.tokens.get_by_hash(sha256_hex(raw_token)) if raw_token else None
        await self.tokens.revoke_all_for_user(
            user.id,
            reason="password_change",
            except_token_id=current.id if current else None,
        )
        await self.session.commit()
        return UserResponse.model_validate(user)

    async def logout(self, raw_token: str | None) -> None:
        """Revoke the presented token. Idempotent — no cookie is not an error."""
        if not raw_token:
            return
        token = await self.tokens.get_by_hash(sha256_hex(raw_token))
        if token is not None:
            await self.tokens.revoke_one(token, reason="logout")
            await self.session.commit()

    async def logout_all(self, user_id: uuid.UUID) -> None:
        """Revoke every refresh token the caller holds."""
        await self.tokens.revoke_all_for_user(user_id, reason="logout_all")
        await self.session.commit()

    async def current(self, user_id: uuid.UUID) -> UserResponse:
        """The caller's full account row, including fields identity does not carry."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()
        return UserResponse.model_validate(user)
```

- [ ] **Step 5: Write the router**

Create `backend/app/api/routes/auth.py`:

```python
"""Login, session rotation, and password change.

No route here is behind the forced-password-change gate: the whole `/auth` prefix is
exempt, so a user with a temporary password can see who they are, keep a live token
while typing, and log out (`docs/PRD.md` §4.0).

Cookie mechanics live here rather than in the service, so the service stays testable
without a request or response object.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.core.rate_limit import LoginAttemptLimiterDep, enforce_login_ip_limit
from app.schemas.auth import AccessTokenResponse, ChangePasswordRequest, LoginRequest
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
RefreshCookie = Annotated[str | None, Cookie(alias="askrepo_refresh")]


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    """Provide the service with a request-scoped session."""
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _set_refresh_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    """Attach the rotated refresh token. httpOnly, so no script can read it."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post(
    "/login",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in with email and password",
    dependencies=[Depends(enforce_login_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (401, 422, 429)},
)
async def login(
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    attempts: LoginAttemptLimiterDep,
) -> AccessTokenResponse:
    await attempts.check_email(payload.email)
    try:
        token_response, raw_refresh = await service.login(payload.email, payload.password)
    except Exception:
        # Only failures count toward the per-email budget, so a colleague cannot spend
        # someone else's allowance to lock them out.
        await attempts.record_failure(payload.email)
        raise
    await attempts.clear(payload.email)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_response


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the refresh token and issue a new access token",
    responses={code: ERROR_RESPONSES[code] for code in (401, 429)},
)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> AccessTokenResponse:
    token_response, raw_refresh = await service.refresh(refresh_token)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_response


@router.post(
    "/change-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change your own password",
    dependencies=[Depends(enforce_login_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422, 429)},
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    service: AuthServiceDep,
    refresh_token: RefreshCookie = None,
) -> UserResponse:
    return await service.change_password(current_user.id, payload, refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out of this device",
    responses={},
)
async def logout(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> None:
    await service.logout(refresh_token)
    _clear_refresh_cookie(response, settings)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out of every device",
    responses={401: ERROR_RESPONSES[401]},
)
async def logout_all(
    response: Response,
    current_user: CurrentUser,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    await service.logout_all(current_user.id)
    _clear_refresh_cookie(response, settings)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="The current account",
    responses={401: ERROR_RESPONSES[401]},
)
async def me(current_user: CurrentUser, service: AuthServiceDep) -> UserResponse:
    return await service.current(current_user.id)
```

`RefreshCookie` aliases the literal `"askrepo_refresh"` because FastAPI resolves the `Cookie`
alias at import time and cannot read a runtime setting. If `refresh_cookie_name` is ever changed
from its default, this alias must change with it — assert that in Step 6 rather than leaving it
implicit.

- [ ] **Step 6: Add a test pinning the cookie-name coupling**

Append to `backend/tests/test_auth_api.py`:

```python
def test_the_cookie_alias_matches_the_configured_name() -> None:
    """FastAPI resolves the Cookie alias at import time, so it cannot read a setting.

    If these ever diverge, refresh silently stops seeing the cookie and every session
    ends after 15 minutes with no error anywhere.
    """
    from app.api.routes.auth import RefreshCookie

    alias = RefreshCookie.__metadata__[0].alias
    assert alias == get_settings().refresh_cookie_name
```

- [ ] **Step 7: Mount the router**

In `backend/app/main.py`, add `auth` to the imports and register it **before** `users` so it
appears first in `/docs`:

```python
from app.api.routes import auth, health, index, users

# ... inside create_app:
    app.include_router(index.router)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_auth_api.py -v`
Expected: PASS, 23 tests.

If `test_the_sixth_login_attempt_in_a_minute_is_429` fails intermittently, the Redis test DB is
not being flushed between tests — check that the `redis_client` fixture is requested, or add an
autouse flush to `conftest.py`.

- [ ] **Step 9: Document the transport and the route table**

`docs/PRD.md` §4.0 — replace the login/refresh acceptance criteria:

```markdown
- `POST /auth/login` accepts `{email, password}` and returns a JWT access token (15 min,
  stateless) in the response body, plus an opaque refresh token (30 days) as an **httpOnly,
  `Secure`, `SameSite=Lax` cookie** scoped to `/auth`. The refresh token never appears in a
  response body: a 30-day credential in `localStorage` is readable by any script on the page.
  Because the cookie is `Secure`, the instance requires TLS — Caddy (§5) is not optional.
- `POST /auth/refresh` reads the cookie, issues a new access token, **rotates the refresh token**,
  and invalidates the old one. Presenting an already-consumed refresh token revokes the whole
  family — that is a replay signal — **except within a 10-second grace window**, where a sibling
  token is minted instead. Strict rotation would log out any client refreshing twice
  concurrently, and two browser tabs is enough. The cost is precise: for those 10 seconds a
  stolen-and-immediately-replayed token is not detected.
- `POST /auth/change-password` returns no new access token. `must_change_password` is not a token
  claim, so the caller's existing token starts working everywhere the moment the row changes.
```

`backend/README.md` — add the auth route table above the Users table:

```markdown
### Auth

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | none | Log in; sets the refresh cookie |
| `POST` | `/auth/refresh` | refresh cookie | Rotate the session |
| `POST` | `/auth/change-password` | access token | Change your own password |
| `POST` | `/auth/logout` | refresh cookie | Log out of this device |
| `POST` | `/auth/logout-all` | access token | Log out everywhere |
| `GET` | `/auth/me` | access token | The current account |
```

- [ ] **Step 10: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/services/auth.py \
        backend/app/api/routes/auth.py backend/app/main.py \
        backend/tests/test_auth_api.py docs/PRD.md backend/README.md
git commit -m "feat(auth): add login, rotation, and password change

Access token in the body, refresh token in an httpOnly Secure cookie
scoped to /auth. A 30-day credential in localStorage is readable by any
script on the page; this is not.

Rotation order is deliberate: revoked, then expired, then used. Expiry
before reuse means an honestly-stale token does not revoke a family. A
reuse inside the 10-second grace window mints a sibling in the same
family instead of a replay, because strict rotation logs out anyone with
two tabs open — and the cost is bounded to those 10 seconds.

change-password returns no new access token: must_change_password is not
a claim, so the caller's existing token works everywhere the moment the
row changes. It spares the caller's own refresh token and revokes the
rest.

Only failed logins count toward the per-email limit and success clears
it. Adds a test pinning the Cookie alias to the configured name — FastAPI
resolves the alias at import, so a divergence would silently end every
session after 15 minutes."
```

---

## Task 13: The seed-admins CLI and its wiring

**Files:**
- Create: `backend/app/cli.py`
- Modify: `infra/backend.Dockerfile`, `infra/docker-compose.yml`, `Makefile`
- Test: `backend/tests/test_cli.py`
- Docs: `README.md` quick start, `CONTRIBUTING.md`, `SECURITY.md`

**Interfaces:**
- Consumes: `UserRepository` (Task 6), `check_password`/`get_common_passwords` (Task 4), `hash_password` (Task 3), `get_sessionmaker` (Task 2), `Settings` (Task 1).
- Produces: `seed_admins() -> int` (async, returns the number created), `main(argv: list[str] | None = None) -> int` (exit code).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cli.py`:

```python
"""The bootstrap seed.

`docs/PRD.md` §7 requires bringing up a fresh instance with no manual database work, so
this must be automatic and safe to re-run: the container entrypoint invokes it on every
start.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import seed_admins
from app.config import get_settings


@pytest.fixture(autouse=True)
def _bootstrap_password() -> None:
    """The seed refuses to run without a password; most tests want one set."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-perfectly-fine-passphrase")
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


async def test_seeding_creates_both_bootstrap_admins(db_session: AsyncSession) -> None:
    created = await seed_admins()

    assert created == 2
    result = await db_session.execute(
        text("SELECT count(*) FROM users WHERE is_admin IS TRUE AND deleted_at IS NULL")
    )
    assert result.scalar_one() == 2


async def test_seeded_admins_must_change_their_password(db_session: AsyncSession) -> None:
    """SECURITY.md:54 tells the operator to change them; the flag enforces it."""
    await seed_admins()

    result = await db_session.execute(
        text("SELECT bool_and(must_change_password) FROM users WHERE is_admin IS TRUE")
    )
    assert result.scalar_one() is True


async def test_seeding_twice_creates_nothing_the_second_time(db_session: AsyncSession) -> None:
    """The entrypoint runs this on every container start."""
    await seed_admins()

    second = await seed_admins()

    assert second == 0
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 2


async def test_the_stored_password_is_hashed_not_plaintext(db_session: AsyncSession) -> None:
    await seed_admins()

    result = await db_session.execute(text("SELECT password_hash FROM users LIMIT 1"))
    stored = result.scalar_one()
    assert stored.startswith("$2b$")
    assert "a-perfectly-fine-passphrase" not in stored


async def test_seeding_refuses_without_a_password(db_session: AsyncSession) -> None:
    """A silent weak-password seed is worse than a failed boot."""
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="BOOTSTRAP_ADMIN_PASSWORD"):
            await seed_admins()

    get_settings.cache_clear()
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 0


async def test_seeding_refuses_a_password_failing_policy(db_session: AsyncSession) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="policy"):
            await seed_admins()

    get_settings.cache_clear()
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 0


async def test_a_soft_deleted_bootstrap_admin_is_reseeded(db_session: AsyncSession) -> None:
    """Otherwise deactivating the seeded admin leaves no recovery path."""
    await seed_admins()
    await db_session.execute(text("UPDATE users SET deleted_at = now()"))
    await db_session.commit()

    created = await seed_admins()

    assert created == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cli'`.

- [ ] **Step 3: Write the CLI**

Create `backend/app/cli.py`:

```python
"""Operational commands. Run as `python -m app.cli <command>`.

Kept out of the request-serving app deliberately (D6): boot side effects would run for
every `TestClient(create_app())`, and a failed seed would become a failed boot. The
container entrypoint invokes this after `alembic upgrade head`.
"""

import argparse
import asyncio
import logging
import sys
import uuid

from app.config import get_settings
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


async def seed_admins() -> int:
    """Create the bootstrap admin accounts if they are missing. Returns how many.

    Idempotent, because the container entrypoint runs it on every start. Refuses
    outright rather than seeding a weak password: an instance whose admin account has a
    guessable password is worse than one that failed to start and said why.
    """
    settings = get_settings()
    password = settings.bootstrap_admin_password
    if not password:
        raise ValueError(
            "BOOTSTRAP_ADMIN_PASSWORD is not set; refusing to seed administrator accounts"
        )

    try:
        check_password(
            password,
            min_length=settings.password_min_length,
            max_bytes=settings.password_max_bytes,
            common=get_common_passwords(),
        )
    except PasswordPolicyError as error:
        raise ValueError(f"BOOTSTRAP_ADMIN_PASSWORD fails password policy: {error.reason}") from error

    password_hash = hash_password(password, cost=settings.bcrypt_cost)
    created = 0

    async with get_sessionmaker()() as session:
        users = UserRepository(session)
        for email in settings.bootstrap_admin_emails:
            normalised = email.strip().lower()
            if await users.email_exists(normalised):
                logger.info("Bootstrap admin %s already exists; skipping", normalised)
                continue
            await users.add(
                User(
                    id=uuid.uuid4(),
                    name=normalised.split("@")[0],
                    email=normalised,
                    password_hash=password_hash,
                    is_admin=True,
                    must_change_password=True,
                )
            )
            created += 1
            logger.info("Created bootstrap admin %s", normalised)
        await session.commit()

    return created


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="app.cli", description="AskRepo operational commands")
    parser.add_argument("command", choices=["seed-admins"])
    arguments = parser.parse_args(argv)

    if arguments.command == "seed-admins":
        try:
            created = asyncio.run(seed_admins())
        except ValueError as error:
            logger.error("%s", error)
            return 1
        logger.info("Seeding complete; %d account(s) created", created)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Verify the command works end to end**

Run:
```bash
cd backend && BOOTSTRAP_ADMIN_PASSWORD=a-perfectly-fine-passphrase \
  uv run python -m app.cli seed-admins
```
Expected: exit 0, two `Created bootstrap admin` lines. Re-run: exit 0, two `already exists`
lines. Then without the variable: exit 1 and a message naming `BOOTSTRAP_ADMIN_PASSWORD`.

Note this writes to the **development** database, not `askrepo_test`. That is intended — it is
how a developer bootstraps their local instance.

- [ ] **Step 6: Wire the container entrypoint**

In `infra/backend.Dockerfile`, replace the `CMD` with a shell form that migrates and seeds first:

```dockerfile
# Migrate, seed the bootstrap admins (idempotent), then serve. Shell form so the
# chain runs in order and a failed migration stops the container rather than
# serving against an empty schema.
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed-admins && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
```

In `infra/docker-compose.yml`, add the new variables to the `backend` service's `environment`
block and change `DATABASE_URL` to the async driver:

```yaml
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-askrepo}:${POSTGRES_PASSWORD:-askrepo}@postgres:5432/${POSTGRES_DB:-askrepo}
      SECRET_KEY: ${SECRET_KEY:-dev-insecure-change-me}
      BOOTSTRAP_ADMIN_PASSWORD: ${BOOTSTRAP_ADMIN_PASSWORD:-change-me-on-first-login}
      # Nothing sits in front of the API in the dev stack, so trust the socket address.
      TRUSTED_PROXY_HOPS: ${TRUSTED_PROXY_HOPS:-0}
```

- [ ] **Step 7: Validate the Compose file**

Run: `cd infra && docker compose config --quiet`
Expected: no output, exit 0.

- [ ] **Step 8: Add the Makefile targets**

In the `Makefile`, add a `seed` target near `infra`, and extend `typecheck`:

```makefile
seed: ## Create the bootstrap admin accounts (idempotent)
	cd $(BACKEND) && uv run python -m app.cli seed-admins

migrate: ## Apply database migrations
	cd $(BACKEND) && uv run alembic upgrade head
```

Change the `typecheck` target to cover both apps:

```makefile
typecheck: ## Static types, both apps
	cd $(BACKEND) && uv run mypy .
	cd $(FRONTEND) && bunx tsc --noEmit
```

- [ ] **Step 9: Confirm the Make targets work**

Run: `make migrate && make seed`
Expected: migrations apply (or report "already at head"), then seeding reports created or
skipped. Then `make typecheck` runs mypy and tsc, both clean.

- [ ] **Step 10: Document the operator-facing pieces**

`README.md` — in the quick start, add the migrate/seed steps after `make infra`, and note that
`BOOTSTRAP_ADMIN_PASSWORD` must be set before the first `make seed` or `make up`. Tick the M0
roadmap checkbox and replace the "Status: pre-M0" banner.

`CONTRIBUTING.md` — state that `make check` now requires `make infra` first, because the backend
suite runs against real Postgres and Redis; and that `typecheck` now covers the backend.

`SECURITY.md` — extend "Notes for operators":

```markdown
- **Set `BOOTSTRAP_ADMIN_PASSWORD` before first boot**, and change both seeded accounts
  immediately after. The seed command refuses to run without it rather than inventing a
  password, so a missing value fails the boot loudly instead of quietly creating a guessable
  admin.
- **TLS is required, not optional.** The refresh token is a `Secure` cookie, so a browser will
  not send it over plain HTTP outside `localhost`. Run Caddy in front.
- **A Redis outage degrades login rate limiting.** The limiter fails open by design — an outage
  should not lock the whole team out — so brute-force protection is reduced to bcrypt's cost
  while Redis is down.
```

- [ ] **Step 11: Verify lint, types, and the whole suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -v`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add backend/app/cli.py backend/tests/test_cli.py infra/backend.Dockerfile \
        infra/docker-compose.yml Makefile README.md CONTRIBUTING.md SECURITY.md
git commit -m "feat(cli): add idempotent bootstrap admin seeding

A CLI command rather than a startup hook: boot side effects would run for
every TestClient(create_app()), and a failed seed would become a failed
boot. The container entrypoint chains it after alembic upgrade head.

Refuses to run without BOOTSTRAP_ADMIN_PASSWORD, and refuses a password
failing policy. An instance whose admin has a guessable password is worse
than one that failed to start and said why.

Re-seeds a soft-deleted bootstrap admin, so deactivating the seeded
account does not leave the instance with no recovery path.

Adds make seed and make migrate, extends make typecheck to the backend,
and records the operator's new responsibilities in SECURITY.md — the
Secure cookie makes TLS a hard requirement, and the rate limiter fails
open during a Redis outage."
```

---

## Task 14: Documentation sweep and end-to-end verification

Everything task-local has been documented alongside its code. What remains is the cross-cutting
set that no single earlier task owns, plus one test that proves the §7 success criterion rather
than asserting its parts.

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `backend/README.md`, `docs/PRD.md`
- Test: `backend/tests/test_m0_acceptance.py`

- [ ] **Step 1: Write the acceptance test**

Create `backend/tests/test_m0_acceptance.py`:

```python
"""The §7 success criterion, end to end.

Every other test asserts a part. This one asserts the whole sentence: "An admin can
bring up a fresh instance, log in as a seeded admin, change the initial password, and
create an account for a colleague — with no manual database work."
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import seed_admins
from app.config import get_settings

SEEDED_PASSWORD = "a-perfectly-fine-passphrase"
CHOSEN_PASSWORD = "an-entirely-different-passphrase"


@pytest.fixture(autouse=True)
def _bootstrap_password() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("BOOTSTRAP_ADMIN_PASSWORD", SEEDED_PASSWORD)
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


async def test_a_fresh_instance_can_be_brought_up_and_used(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A fresh instance: no rows at all.
    count = await db_session.execute(text("SELECT count(*) FROM users"))
    assert count.scalar_one() == 0

    # Bring it up. This is the only step that is not an API call, and it is a
    # documented command rather than manual SQL.
    assert await seed_admins() == 2

    # Log in as a seeded admin.
    login = await client.post(
        "/auth/login",
        json={"email": "superuser@example.com", "password": SEEDED_PASSWORD},
    )
    assert login.status_code == 200
    access = login.json()["accessToken"]
    cookie = login.cookies[get_settings().refresh_cookie_name]
    assert login.json()["user"]["mustChangePassword"] is True

    headers = {"Authorization": f"Bearer {access}"}

    # The rest of the API is closed until the password changes.
    blocked = await client.get("/users", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    # Change the initial password, using the token issued before the change.
    changed = await client.post(
        "/auth/change-password",
        headers=headers,
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": SEEDED_PASSWORD, "newPassword": CHOSEN_PASSWORD},
    )
    assert changed.status_code == 200
    assert changed.json()["mustChangePassword"] is False

    # Create an account for a colleague.
    colleague = await client.post(
        "/users",
        headers=headers,
        json={
            "name": "Colleague",
            "email": "colleague@example.com",
            "password": "yet-another-fine-passphrase",
            "isAdmin": False,
        },
    )
    assert colleague.status_code == 201
    assert colleague.json()["mustChangePassword"] is True

    # The colleague can log in and read the shared account list.
    theirs = await client.post(
        "/auth/login",
        json={"email": "colleague@example.com", "password": "yet-another-fine-passphrase"},
    )
    assert theirs.status_code == 200

    # ...and no response along the way carried a secret.
    for response in (login, changed, colleague, theirs):
        assert "$2b$" not in response.text
        assert "passwordHash" not in response.text


async def test_no_response_in_the_flow_leaks_the_refresh_token_in_a_body(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_admins()

    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": SEEDED_PASSWORD},
    )

    stored = await db_session.execute(text("SELECT token_hash FROM refresh_tokens LIMIT 1"))
    assert stored.scalar_one() not in login.text
```

- [ ] **Step 2: Run it**

Run: `cd backend && uv run pytest tests/test_m0_acceptance.py -v`
Expected: PASS, 2 tests. If the first fails at the `count == 0` assertion, the `_clean_tables`
fixture is not running — check it is autouse.

- [ ] **Step 3: Correct CLAUDE.md**

Three claims stop being true with M0:

1. **"Status: pre-M0."** Replace the paragraph: the backend now serves auth and account routes;
   Postgres and Redis are read; there is still no ingestion, no RAG, and no Qdrant use.
2. **"Datastores are wired but unread."** Rewrite: Postgres is read via the repository layer,
   Redis by the login rate limiter; Qdrant remains declared and unread until M1.
3. **The rule count.** `persistence.md` was added in Task 6 — confirm the table says **ten** rule
   files and lists it.

Also add, to the architecture notes, the three facts a reader cannot infer from any single file:

```markdown
### Identity is resolved once, in middleware

`AuthContextMiddleware` decodes the bearer token, loads the user row, and stashes a frozen
`AuthenticatedUser` on `request.state`. `CurrentUser` / `AdminUser` read it. Two consequences:
the user row is read on **every** authenticated request (which is what makes deactivation
immediate, per `docs/PRD.md:101`), and the middleware is registered **before** `CORSMiddleware`
so CORS ends up outermost and the gate's `403` carries CORS headers.

### The forced-password-change gate is structural

While `must_change_password` is set, every route outside `/auth` returns
`403 PASSWORD_CHANGE_REQUIRED` — enforced by middleware, not by a dependency, so a route added
later is covered without opting in. Adding a route group under a **new** prefix means deciding
whether it belongs in `GATE_EXEMPT_PREFIXES`.

### One error shape

Every error the app raises is `{"detail": {"code": ..., "message": ...}}`, built by `AppError`.
`ErrorCode` values are a wire contract — add members, never rename them. `422` adds a `fields`
map keyed by the `camelCase` field name.
```

- [ ] **Step 4: Correct README.md**

- Replace the status banner; tick M0 on the roadmap.
- Quick start: `make setup` → `make infra` → `make migrate` → `make seed` → `make dev`, with
  `BOOTSTRAP_ADMIN_PASSWORD` set before `make seed`.
- If the README carries a `curl` example, make it one that actually works against the committed
  code — a login against `/auth/login` — because `.claude/rules/documentation.md` requires
  examples to be real.

- [ ] **Step 5: Correct backend/README.md**

- The route table must be **exhaustive**: `/`, `/health`, `/health/live`, `/health/ready`, the six
  `/auth` routes, the six `/users` routes.
- Document every new config value (or point at `.env.example` as the canonical list and keep only
  the auth-specific notes here).
- Update the layout tree to match `app/` as it now stands.
- Add the dev commands: `uv run alembic upgrade head`, `uv run python -m app.cli seed-admins`, and
  the `make infra` prerequisite for `pytest`.

- [ ] **Step 6: Final PRD read-through**

Every §13 amendment from the spec should already be committed by an earlier task. Confirm by
grepping for the claims that were wrong at the start:

```bash
grep -n 'argon2' docs/PRD.md          # expect: no matches
grep -n 'every table carries' docs/PRD.md   # expect: the scoped wording, naming refresh_tokens
grep -n 'resolve_project_ids' docs/PRD.md .claude/rules/router.md  # expect: no matches
grep -rn 'Nine rule files' CLAUDE.md  # expect: no matches
```

Fix anything that still reads the old way. Also confirm §6's milestone list marks M0 complete.

- [ ] **Step 7: Full verification**

Run:
```bash
make infra
make check
cd infra && docker compose config --quiet
```
Expected: `make check` passes lint, format, mypy (backend and frontend), and the whole pytest
suite. Compose validates.

Then confirm the whole stack actually starts:
```bash
cd infra && BOOTSTRAP_ADMIN_PASSWORD=a-perfectly-fine-passphrase docker compose up --build -d
docker compose logs backend | tail -30
curl -s localhost:8000/health | head
curl -s -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"a-perfectly-fine-passphrase"}' | head -c 200
```
Expected: the backend log shows migrations applied and two admins created; `/health` returns
`ok`; the login returns an `accessToken` and `mustChangePassword: true`. Then
`docker compose down`.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md backend/README.md docs/PRD.md \
        backend/tests/test_m0_acceptance.py
git commit -m "docs: bring the docs in line with M0, and assert the criterion

CLAUDE.md's 'Status: pre-M0' and 'Datastores are wired but unread' both
stop being true: Postgres is read through the repository layer and Redis
by the login limiter. Adds the three facts a reader cannot infer from any
single file — identity resolved once in middleware, the gate being
structural rather than opt-in, and the single error shape.

Adds an end-to-end test for PRD 7's first success criterion. Every other
test asserts a part of it; this one asserts the whole sentence — fresh
instance, seeded admin logs in, is forced to change the password, creates
a colleague, colleague logs in, and no response along the way carries a
hash or a raw token."
```

---

## Self-Review

Run against the spec after writing, before execution.

**1. Spec coverage.** Every spec section maps to a task:

| Spec section | Task |
| --- | --- |
| §3 Module layout | 1–13 (each creates its slice) |
| §4 Data model, migrations | 2 |
| §5 Auth mechanics — primitives, policy | 3, 4 |
| §5 Rotation and replay, revocation matrix | 12 |
| §6 Middleware and dependencies | 8 |
| §7 Error contract | 5 |
| §8 Routes — `/auth`, `/users`, list contract | 11, 12 |
| §9 Rate limiting | 9 |
| §10 Access resolver | 10 |
| §11 Configuration, session lifecycle | 1, 2 |
| §12 Testing — fixtures, all 24 numbered cases | 2 (harness), 3–13 (cases), 14 (end-to-end) |
| §13 Docs and rules | distributed to the task that creates each divergence; 14 sweeps the rest |
| §14 M0 done means | 14 |
| §15 Known debt | carried, not implemented — correct |

Spec §12's numbered cases are all placed: 1–4 → Task 12; 5 → 11 and 12; 6, 6a → 3 and 12;
6b → 3 and 4; 7–9 → 12; 10–11 → 11; 12 → 8; 13 → 11; 14–15 → 8 and 5; 16 → 11, 12, 14;
17 → 8; 18 → 10; 19–21 → 9 and 12; 22–24 → 13.

**2. Placeholder scan.** No "TBD", no "add appropriate error handling", no "similar to Task N",
no "write tests for the above". Every code step carries the actual code. Three places name a
verification the implementer must perform rather than a value I could assert from here, each with
what to do either way — the `HTTP_422_UNPROCESSABLE_CONTENT` constant name (Task 5 Step 3), the
`ASGITransport` exception-propagation behaviour (Task 5 Step 1), and the wordlist fetch (Task 4
Step 5). Those are deliberate: guessing a library detail and writing it as fact would be worse.

**3. Type consistency** — checked across tasks:
- `AuthenticatedUser` — produced in Task 8, consumed by Tasks 10, 11, 12. Field set identical
  (`id`, `name`, `email`, `is_admin`, `must_change_password`) everywhere it is constructed,
  including in the Task 10 test helper.
- `RateLimiter.hit(key, *, limit, window_seconds)` — same signature in Task 9's implementation,
  its tests, and `LoginAttemptLimiter.record_failure`.
- `UserRepository.list_page(*, page, limit, search, sort, descending)` — Task 6 defines it,
  Task 11's service calls it with exactly those keywords.
- `revoke_all_for_user(user_id, *, reason, except_token_id=None)` — Task 7 defines it; Tasks 11
  and 12 both call it, Task 12 with `except_token_id`.
- `AppError(status_code, code, message)` — one signature, used in Tasks 8, 9, 11, 12.
- `hash_password(password, *, cost)` — Task 3; called in Tasks 11, 12, 13 and in test helpers.
- `ProjectScope` / `resolve_project_scope` — Task 10 only; nothing in M0 consumes it, which is
  expected and is why it ships with a contract test.

**Two corrections applied during review:**

- **Global Constraints** said "Task 15 handles only the cross-cutting sweep". There are fourteen
  tasks; the sweep is **Task 14**. Read that line as Task 14.
- `RefreshCookie` in Task 12 hard-codes the cookie name in a `Cookie(alias=...)`, because FastAPI
  resolves the alias at import time and cannot read a setting. That coupling is real and silent
  if broken, so Task 12 Step 6 adds a test asserting the alias equals
  `settings.refresh_cookie_name`. Flagged here so a reviewer does not read the literal as an
  oversight.

**One risk worth stating rather than solving:** Task 12's
`test_two_refreshes_inside_the_grace_window_both_succeed` depends on both requests landing inside
`refresh_rotation_grace_seconds` (10s). That is not a race in practice — two sequential `await`s
take milliseconds — but if it ever flakes on a loaded CI box, raise the setting for the test
rather than deleting the assertion. The behaviour it pins is the whole reason D12 exists.
