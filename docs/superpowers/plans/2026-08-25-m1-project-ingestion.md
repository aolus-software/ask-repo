# M1 Project Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user pastes a repository URL; the app clones it, chunks it, embeds it, writes it to Qdrant, deletes the working copy, and tracks the whole thing as a `Project` with a visible status.

**Architecture:** `POST /projects` writes a row and produces one Kafka message. A worker process — the backend image with a different entrypoint — consumes it, claims the project with a database lease, and runs a staged pipeline: clone → walk → chunk → embed → upsert. Delivery is at-least-once, so the lease (not the message) is the deduplication boundary. Reindex writes a new vector generation and swaps a pointer, so a project stays queryable throughout and a failed reindex never destroys a working index.

**Tech Stack:** FastAPI, Python 3.13, uv, SQLAlchemy 2.0 + Alembic, Postgres, Kafka (single-node KRaft) via `aiokafka`, Qdrant, LangChain text splitters, Fernet (`cryptography`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-m1-project-ingestion-design.md`

**Branch:** `docs/m1-ingestion-design`

## Global Constraints

- **Wire naming:** every request/response schema inherits `ApiModel` (`app/schemas/base.py`). A schema on plain `BaseModel` ships `snake_case` keys and is a defect.
- **Error shape:** every client-visible error is raised as `AppError(status, ErrorCode.X, "message")`. Never `HTTPException` directly, never a bare `raise`.
- **Read scoping:** project reads go through `resolve_project_scope` (`app/core/access.py`) only. A route, service, or query that filters projects itself is a defect even when its output is correct today.
- **Repositories own SQLAlchemy:** `select`/`insert`/`update`/`delete` are imported in `app/repositories/**` and nowhere else. Every read starts from `active_select()`.
- **Bulk updates set `updated_at` explicitly** in `values()` — `TimestampMixin.onupdate` does not fire on Core `UPDATE`.
- **Migrations, never `create_all`** — including in tests. Every revision has a working `downgrade()`.
- **Routers are thin:** accept input, resolve dependencies, call exactly one service method, return a typed response. No `if`, no `try`, no data reshaping.
- **Timestamps:** `timestamptz`, timezone-aware, UTC. **IDs:** application-generated `uuid4`.
- **Lint gates:** `ANN` (type hints everywhere), `T20` (no `print()`), `LOG`/`G` (no f-strings in log calls — use `%s` args). `# noqa` and `# type: ignore` need a reason on the same line.
- **Secrets never surface:** no PAT or password in a log, traceback, response, or `Project.error`.
- **Tests need real infrastructure:** `make infra` must be running. Postgres and Redis are real in the suite; Kafka and Qdrant are faked except in `@pytest.mark.integration` tests.
- **Every new `Settings` field gets a `backend/.env.example` entry** in the same task.

**Fixed values from the spec — copy verbatim, do not invent:**

| Constant | Value |
| --- | --- |
| Lease duration | 5 minutes |
| Lease renewal interval | 60 seconds |
| Reconcile sweep interval | 60 seconds |
| Stranded-`pending` threshold | 2 minutes |
| Ingest topic | `askrepo.ingest.requested` |
| Retry topics | `askrepo.ingest.retry.1m`, `askrepo.ingest.retry.10m` |
| DLQ topic | `askrepo.ingest.dlq` |
| Ingest partitions | 2 |
| Max attempts | 3 |
| Clone timeout | 120 seconds |
| Repo size cap | 500 MB |
| Default host allowlist | `github.com`, `gitlab.com` |
| Chunk size / overlap | 1200 / 150 characters |
| Max indexed file size | 1048576 bytes (1 MiB) |
| Embedding batch size | 64 |
| Collection name format | `code_chunks__{provider}__{model}__{dimensions}` |

---

## Phase Overview

| Phase | Tasks | Deliverable |
| --- | --- | --- |
| 1 — Foundations | 1–5 | Config, crypto, URL validation, model, repository. No network, no queue. |
| 2 — API surface | 6–9 | Project routes working end to end against an in-memory queue. |
| 3 — Pipeline | 10–15 | Clone → walk → chunk → embed → Qdrant, driven directly. |
| 4 — Kafka | 16–20 | Real broker, consumer loop, retries, worker process. |
| 5 — Docs | 21 | The 14 documentation amendments the spec's §12 requires. |

Phases 1–2 leave the repository in a coherent state (projects can be created and listed; nothing indexes them yet). Phase 3 leaves the pipeline callable and tested but only reachable from tests. Phase 4 connects them.

---

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `app/core/crypto.py` | Fernet PAT encryption; secret scrubbing for error text |
| `app/core/repo_url.py` | SSRF validation, DNS resolution and pinning, host allowlist |
| `app/models/project.py` | `Project` ORM model, `ProjectStatus` enum |
| `app/repositories/project.py` | Project queries, the lease claim, stranded-row lookup |
| `app/schemas/project.py` | `ProjectCreateRequest`, `ProjectResponse`, `ReindexResponse` |
| `app/services/project.py` | Create/list/get/delete/reindex; the `created_by`-or-admin gate |
| `app/api/routes/projects.py` | The five routes |
| `app/queue/topics.py` | Topic names, `IngestionMessage` and its serialisation |
| `app/queue/protocol.py` | `IngestionQueue` protocol + `InMemoryIngestionQueue` fake |
| `app/queue/producer.py` | `KafkaIngestionQueue` |
| `app/queue/consumer.py` | The pause/claim/commit loop |
| `app/queue/retry.py` | Retry-topic consumer and DLQ routing |
| `app/ingestion/errors.py` | `TerminalIngestionError` / `RetryableIngestionError` |
| `app/ingestion/cloner.py` | `git clone` subprocess, size and timeout enforcement |
| `app/ingestion/walker.py` | File discovery and filtering |
| `app/ingestion/chunker.py` | `Chunker` protocol, LangChain implementation, context header |
| `app/ingestion/embedder/` | `Embedder` protocol, Ollama/OpenAI/Voyage implementations, factory |
| `app/ingestion/vector_store.py` | Collection naming, upsert, generation and project deletion |
| `app/ingestion/pipeline.py` | Stage orchestration and status transitions |
| `app/worker.py` | Worker entrypoint: consumer loop + reconcile sweep |
| `alembic/versions/*_add_projects.py` | The `projects` table |

**Modified:** `app/config.py`, `app/core/errors.py` (new `ErrorCode` members), `app/main.py` (router + producer lifespan), `app/models/__init__.py`, `backend/pyproject.toml`, `backend/.env.example`, `infra/docker-compose.yml`, `Makefile`, plus the documentation set in Task 21.

---

# Phase 1 — Foundations

### Task 1: Configuration for M1

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/pyproject.toml` (dependencies)
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: existing `Settings`, `get_settings()`
- Produces: `Settings.kafka_bootstrap_servers`, `.kafka_ingest_topic`, `.kafka_consumer_group`, `.kafka_ingest_partitions`, `.kafka_max_attempts`, `.embedding_provider`, `.embedding_model`, `.embedding_base_url`, `.embedding_api_key`, `.embedding_batch_size`, `.repo_host_allowlist`, `.clone_timeout_seconds`, `.repo_max_size_mb`, `.repo_scratch_dir`, `.chunk_size`, `.chunk_overlap`, `.max_indexed_file_bytes`, `.pat_encryption_key`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_config.py`:

```python
def test_production_refuses_placeholder_pat_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """PATs encrypted with a known key are not encrypted."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret-key-value")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    monkeypatch.delenv("PAT_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValidationError, match="PAT_ENCRYPTION_KEY"):
        Settings()


def test_ingestion_defaults_match_the_prd() -> None:
    settings = Settings()
    assert settings.clone_timeout_seconds == 120
    assert settings.repo_max_size_mb == 500
    assert settings.repo_host_allowlist == ["github.com", "gitlab.com"]
    assert settings.kafka_ingest_partitions == 2
    assert settings.embedding_batch_size == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -k "pat_key or ingestion_defaults" -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'clone_timeout_seconds'`, and no `ValidationError` raised for the missing PAT key.

- [ ] **Step 3: Add the dependencies**

```bash
cd backend
uv add "aiokafka>=0.12.0" "qdrant-client>=1.12.0" "cryptography>=44.0.0" \
       "langchain-text-splitters>=0.3.0" "httpx>=0.28.0" "pathspec>=0.12.0"
```

`httpx` moves from the dev group to runtime — the embedder implementations call HTTP APIs.

- [ ] **Step 4: Add the settings fields**

In `app/config.py`, add a `PLACEHOLDER_PAT_KEY` constant beside the existing `PLACEHOLDER_SECRET_KEY`, then add to `Settings`:

```python
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
    embedding_batch_size: int = 64

    # Ingestion
    repo_host_allowlist: list[str] = ["github.com", "gitlab.com"]
    clone_timeout_seconds: int = 120
    repo_max_size_mb: int = 500
    repo_scratch_dir: Path = Path("/data/repos")
    chunk_size: int = 1200
    chunk_overlap: int = 150
    max_indexed_file_bytes: int = 1_048_576

    # Encrypts stored PATs at rest (docs/PRD.md §9). Backed up separately from
    # the database — a backup holding both is plaintext storage with extra steps.
    pat_encryption_key: str = PLACEHOLDER_PAT_KEY
```

Extend `_reject_development_defaults_in_production`:

```python
        if self.pat_encryption_key == PLACEHOLDER_PAT_KEY:
            raise ValueError(
                "PAT_ENCRYPTION_KEY must be set to a real Fernet key when "
                "APP_ENV=production — PATs encrypted with a known key are not encrypted. "
                "Generate: python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Document every field in `.env.example`**

Append to `backend/.env.example`, and correct the existing `REDIS_URL` comment, which currently promises the ARQ queue:

```bash
# Rate limiting (M0). The job queue moved to Kafka at M1 — see KAFKA_* below.
REDIS_URL=redis://localhost:6379/0

# --- Kafka (ingestion job queue, M1) ---
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_INGEST_TOPIC=askrepo.ingest.requested
KAFKA_CONSUMER_GROUP=askrepo-ingest
# Concurrency cap for ingestion is partition count, not a separate setting.
# Raising this raises the number of repos that can index at once.
KAFKA_INGEST_PARTITIONS=2
# Attempts before a job lands in askrepo.ingest.dlq.
KAFKA_MAX_ATTEMPTS=3

# --- Embedding ---
# ollama | openai | voyage. Switching provider targets a DIFFERENT Qdrant
# collection (named for provider+model+dimensions), so existing projects are not
# corrupted — they report as needing a reindex.
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_API_KEY=
EMBEDDING_BATCH_SIZE=64

# --- Ingestion ---
# Must be a JSON array. Any host not listed is rejected before DNS resolution.
REPO_HOST_ALLOWLIST=["github.com","gitlab.com"]
CLONE_TIMEOUT_SECONDS=120
REPO_MAX_SIZE_MB=500
# Scratch space, not a persistent volume: the working copy is deleted after
# indexing, and reindex re-clones rather than pulling.
REPO_SCRATCH_DIR=/data/repos
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
MAX_INDEXED_FILE_BYTES=1048576

# --- PAT encryption ---
# Fernet key encrypting stored PATs. The app refuses to boot with the placeholder
# when APP_ENV=production. Back this up SEPARATELY from the database.
# Generate: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
PAT_ENCRYPTION_KEY=dev-insecure-change-me
```

- [ ] **Step 7: Verify lint and full suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/pyproject.toml \
        backend/uv.lock backend/tests/test_config.py
git commit -m "feat(config): add M1 ingestion, Kafka, and embedding settings"
```

---

### Task 2: PAT encryption and secret scrubbing

**Files:**
- Create: `backend/app/core/crypto.py`
- Test: `backend/tests/test_crypto.py`

**Interfaces:**
- Consumes: `Settings.pat_encryption_key`
- Produces: `SecretBox(key: str)` with `.encrypt(plaintext: str) -> bytes` and `.decrypt(token: bytes) -> str`; `scrub(text: str, *secrets: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_crypto.py`:

```python
"""PAT encryption at rest, and keeping secrets out of stored error text."""

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import SecretBox, scrub


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(Fernet.generate_key().decode())


def test_round_trip(box: SecretBox) -> None:
    token = box.encrypt("ghp_realtokenvalue")
    assert box.decrypt(token) == "ghp_realtokenvalue"


def test_ciphertext_does_not_contain_the_plaintext(box: SecretBox) -> None:
    """Guards against a 'null' implementation that stores the value verbatim."""
    assert b"ghp_realtokenvalue" not in box.encrypt("ghp_realtokenvalue")


def test_a_different_key_cannot_decrypt(box: SecretBox) -> None:
    other = SecretBox(Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="could not be decrypted"):
        other.decrypt(box.encrypt("ghp_realtokenvalue"))


def test_scrub_replaces_every_occurrence() -> None:
    message = "fatal: auth failed for https://x:ghp_secret@github.com (ghp_secret)"
    assert scrub(message, "ghp_secret") == (
        "fatal: auth failed for https://x:***@github.com (***)"
    )


def test_scrub_ignores_empty_secrets() -> None:
    """A None PAT must not turn every character boundary into ***."""
    assert scrub("plain message", "", None) == "plain message"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.crypto'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/crypto.py`:

```python
"""Encryption for stored PATs, and scrubbing for text that may quote one.

`docs/PRD.md` §9 requires PATs encrypted at rest with an env-provided key, never
logged and never returned. §4.0 extends that to logs and tracebacks. Clone stderr
is the most likely place a token surfaces, and it lands in `Project.error`, so
`scrub` runs on the way in rather than being remembered at each call site.
"""

from cryptography.fernet import Fernet, InvalidToken

REDACTION = "***"


class SecretBox:
    """Symmetric encryption for values that must survive a database read.

    Fernet rather than raw AES-GCM: it carries its own IV and authentication tag,
    so there is no nonce-reuse footgun for a caller to step on.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a secret for storage."""
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        """Decrypt a stored secret.

        Raises `ValueError` rather than propagating `InvalidToken`, so a rotated or
        wrong key reads as a configuration problem at the call site instead of a
        cryptography-library detail.
        """
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken as error:
            raise ValueError(
                "stored secret could not be decrypted — the encryption key may have changed"
            ) from error


def scrub(text: str, *secrets: str | None) -> str:
    """Replace every occurrence of each secret with `***`.

    Empty and `None` secrets are skipped: `str.replace` with an empty needle inserts
    the replacement at every character boundary, so a project with no PAT would
    otherwise have its error text destroyed.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTION)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_crypto.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/crypto.py backend/tests/test_crypto.py
git commit -m "feat(crypto): add PAT encryption and secret scrubbing"
```

---

### Task 3: Repository URL validation (SSRF)

`docs/PRD.md` §9 calls this "the sharpest risk, and worse on an internal network than a public one." This task carries the most security weight in the milestone.

**Files:**
- Create: `backend/app/core/repo_url.py`
- Test: `backend/tests/test_repo_url.py`

**Interfaces:**
- Consumes: `Settings.repo_host_allowlist`
- Produces: `ValidatedRepoUrl` (frozen dataclass: `.url`, `.host`, `.port`, `.pinned_ip`); `RepoUrlRejected(Exception)` with `.reason: str`; `async def validate_repo_url(url: str, *, allowlist: Iterable[str], resolve: Resolver | None = None) -> ValidatedRepoUrl`; type alias `Resolver = Callable[[str, int], Awaitable[list[str]]]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_repo_url.py`:

```python
"""Clone-URL validation.

The rebinding test is the reason this module exists: validating an address and then
letting git resolve the name again validates one thing and clones another.
"""

import pytest

from app.core.repo_url import RepoUrlRejected, validate_repo_url

ALLOWLIST = ["github.com", "gitlab.com"]


def resolver(*addresses: str):
    """A resolver returning fixed addresses, so no test touches real DNS."""

    async def _resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return _resolve


async def test_accepts_an_allowlisted_public_host() -> None:
    result = await validate_repo_url(
        "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=resolver("140.82.121.4")
    )
    assert result.host == "github.com"
    assert result.pinned_ip == "140.82.121.4"
    assert result.port == 443


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/acme/repo.git",
        "git://github.com/acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "file:///etc/passwd",
    ],
)
async def test_rejects_non_https_schemes(url: str) -> None:
    with pytest.raises(RepoUrlRejected, match="https"):
        await validate_repo_url(url, allowlist=ALLOWLIST, resolve=resolver("140.82.121.4"))


async def test_rejects_a_host_not_on_the_allowlist() -> None:
    with pytest.raises(RepoUrlRejected, match="not allowed"):
        await validate_repo_url(
            "https://evil.example/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("140.82.121.4"),
        )


async def test_userinfo_cannot_smuggle_a_host() -> None:
    """`https://github.com@10.0.0.1/` has hostname 10.0.0.1, not github.com."""
    with pytest.raises(RepoUrlRejected, match="not allowed"):
        await validate_repo_url(
            "https://github.com@10.0.0.1/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("10.0.0.1"),
        )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # RFC1918
        "172.16.4.2",      # RFC1918
        "192.168.1.10",    # RFC1918
        "169.254.169.254", # link-local — the cloud metadata endpoint
        "100.64.0.1",      # carrier-grade NAT
        "0.0.0.0",         # unspecified
        "::1",             # IPv6 loopback
        "fc00::1",         # IPv6 unique-local
        "fe80::1",         # IPv6 link-local
    ],
)
async def test_rejects_private_and_reserved_addresses(address: str) -> None:
    with pytest.raises(RepoUrlRejected, match="private"):
        await validate_repo_url(
            "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=resolver(address)
        )


async def test_rejects_when_any_record_is_private() -> None:
    """A host resolving to one public and one private address is rejected, not raced."""
    with pytest.raises(RepoUrlRejected, match="private"):
        await validate_repo_url(
            "https://github.com/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("140.82.121.4", "10.0.0.5"),
        )


async def test_rejects_when_the_host_does_not_resolve() -> None:
    async def _fails(host: str, port: int) -> list[str]:
        raise OSError("Name or service not known")

    with pytest.raises(RepoUrlRejected, match="did not resolve"):
        await validate_repo_url(
            "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=_fails
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_repo_url.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.repo_url'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/core/repo_url.py`:

```python
"""Clone-URL validation — the control `docs/PRD.md` §9 calls the sharpest risk.

`repo_url` is user-supplied and handed to a network client running *inside* the
corporate network, where `10.0.x.x`, `169.254.169.254`, and internal service names
resolve. This is a security control, not input hygiene.

The subtle part is DNS rebinding. Validating an address and then invoking
`git clone` lets git perform its own lookup, so an attacker controlling DNS can
return a public address for the check and a private one a moment later. This module
therefore returns the address it validated, and the cloner pins git to it via
`http.curloptResolve` — see `app/ingestion/cloner.py`.
"""

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str, int], Awaitable[list[str]]]

HTTPS_PORT = 443


class RepoUrlRejected(Exception):
    """A repository URL failed validation. The reason is safe to show a caller."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedRepoUrl:
    """A URL cleared for cloning, plus the address it was cleared against.

    `pinned_ip` is the whole point: the cloner must use this address rather than
    resolving the host again, or the validation above it means nothing.
    """

    url: str
    host: str
    port: int
    pinned_ip: str


def _is_public(address: str) -> bool:
    """Whether an address is globally routable.

    `is_global` covers loopback, private, link-local, unspecified, reserved, and
    multicast in one check for both address families — enumerating ranges by hand
    is how `100.64.0.0/10` gets forgotten.
    """
    return ipaddress.ip_address(address).is_global


async def _system_resolver(host: str, port: int) -> list[str]:
    """Resolve a host to every A/AAAA address the system returns."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


async def validate_repo_url(
    url: str, *, allowlist: Iterable[str], resolve: Resolver | None = None
) -> ValidatedRepoUrl:
    """Clear a repository URL for cloning, or raise `RepoUrlRejected`.

    `resolve` is injected so tests never touch real DNS and can simulate a host
    that returns mixed public and private records.
    """
    resolve = resolve or _system_resolver
    parts = urlsplit(url)

    if parts.scheme != "https":
        raise RepoUrlRejected("Only https:// repository URLs are accepted.")

    # `.hostname` rather than `.netloc`: it strips userinfo, so
    # `https://github.com@10.0.0.1/` reads as 10.0.0.1 and not as github.com.
    host = parts.hostname
    if not host:
        raise RepoUrlRejected("The repository URL has no host.")

    allowed = {entry.strip().lower() for entry in allowlist}
    if host.lower() not in allowed:
        raise RepoUrlRejected(
            f"Host {host!r} is not allowed. Allowed hosts: {', '.join(sorted(allowed))}."
        )

    port = parts.port or HTTPS_PORT

    try:
        addresses = await resolve(host, port)
    except OSError as error:
        raise RepoUrlRejected(f"Host {host!r} did not resolve.") from error

    if not addresses:
        raise RepoUrlRejected(f"Host {host!r} did not resolve.")

    # Every record, not just the one that will be used: a host answering with one
    # public and one private address must be rejected rather than raced.
    for address in addresses:
        if not _is_public(address):
            raise RepoUrlRejected(
                f"Host {host!r} resolves to a private or reserved address and cannot be cloned."
            )

    return ValidatedRepoUrl(url=url, host=host, port=port, pinned_ip=addresses[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_repo_url.py -v`
Expected: PASS (all parametrised cases)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/repo_url.py backend/tests/test_repo_url.py
git commit -m "feat(ingestion): add SSRF-hardened repository URL validation"
```

---

### Task 4: The `Project` model and migration

**Files:**
- Create: `backend/app/models/project.py`
- Create: `backend/alembic/versions/<rev>_add_projects.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/errors.py` (new `ErrorCode` members)
- Test: `backend/tests/test_schema.py`

**Interfaces:**
- Consumes: `Base`, `TimestampMixin`, `SoftDeleteMixin` from `app.models.base`
- Produces: `ProjectStatus` (StrEnum: `PENDING`, `CLONING`, `INDEXING`, `READY`, `FAILED`); `Project` model with `id`, `created_by`, `name`, `repo_url`, `branch`, `status`, `error`, `last_indexed_commit`, `file_count`, `chunk_count`, `encrypted_pat`, `lease_owner`, `lease_expires_at`, `last_job_id`, `reindex_in_progress`, `active_generation`, `embedding_collection`, `embedding_model`; `ErrorCode.PROJECT_NOT_FOUND`, `.NOT_PROJECT_OWNER`, `.INVALID_REPO_URL`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_schema.py`:

```python
async def test_projects_table_has_the_ingestion_columns(db_session: AsyncSession) -> None:
    """The seven columns beyond docs/PRD.md §4.1's original schema (spec §8)."""
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'projects'"
        )
    )
    columns = {row[0] for row in result}
    assert {
        "lease_owner",
        "lease_expires_at",
        "last_job_id",
        "reindex_in_progress",
        "active_generation",
        "embedding_collection",
        "embedding_model",
    } <= columns


async def test_projects_soft_delete_column_exists(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'projects' AND column_name = 'deleted_at'"
        )
    )
    assert result.scalar_one() == "timestamp with time zone"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_schema.py -k projects -v`
Expected: FAIL — the `projects` table does not exist, so both assertions fail on an empty result.

- [ ] **Step 3: Write the model**

Create `backend/app/models/project.py`:

```python
"""The `projects` table.

`created_by` is attribution and a destructive-operation gate. It does **not** scope
reads — that is `resolve_project_scope`'s job and nowhere else
(`docs/PRD.md` §5.1, `.claude/rules/router.md`).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ProjectStatus(StrEnum):
    """Lifecycle of an indexing run. Stored as text, not a Postgres enum:
    adding a value to a native enum needs a migration and a table lock."""

    PENDING = "pending"
    CLONING = "cloning"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class Project(Base, TimestampMixin, SoftDeleteMixin):
    """A repository that has been, or is being, indexed."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.PENDING.value, index=True
    )
    error: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    last_indexed_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Never serialized, in any response, not even masked (docs/PRD.md §4.1).
    encrypted_pat: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Delivery is at-least-once, so the lease — not the message — decides who runs
    # a job. See the spec's §4.2.
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Distinguishes "a new reindex was requested" from "an old message arrived
    # twice". The lease alone cannot tell those apart.
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # A reindex leaves `status` at `ready` so the project stays queryable, which
    # means status cannot express "a run is in progress". This flag does.
    reindex_in_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Which Qdrant generation serves queries. New points are written under
    # generation+1 and the pointer flips only once they are all in.
    active_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Which collection holds this project's points — needed in order to delete
    # them after the embedding provider has been switched.
    embedding_collection: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

Export it from `app/models/__init__.py` alongside the existing models so Alembic autogenerate sees it.

- [ ] **Step 4: Add the new error codes**

In `app/core/errors.py`, add to `ErrorCode` (append — never rename an existing member, the values are a wire contract):

```python
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    NOT_PROJECT_OWNER = "NOT_PROJECT_OWNER"
    INVALID_REPO_URL = "INVALID_REPO_URL"
```

- [ ] **Step 5: Generate and review the migration**

```bash
cd backend
uv run alembic revision --autogenerate -m "add projects"
```

Open the generated file. Confirm `downgrade()` contains `op.drop_table("projects")` and that the `created_by` foreign key is named by the convention (`fk_projects_created_by_users`). Add an index used by the reconcile sweep, which scans by status and lease expiry:

```python
    op.create_index(
        "ix_projects_status_lease_expires_at",
        "projects",
        ["status", "lease_expires_at"],
    )
```

and its `op.drop_index("ix_projects_status_lease_expires_at", table_name="projects")` in `downgrade()`.

- [ ] **Step 6: Run the migration up and down**

```bash
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```
Expected: all three succeed. A migration that cannot be reversed cannot be iterated on.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/project.py backend/app/models/__init__.py \
        backend/app/core/errors.py backend/alembic/versions/ backend/tests/test_schema.py
git commit -m "feat(projects): add the Project model, migration, and error codes"
```

---

### Task 5: The project repository and the lease claim

The claim is the correctness centre of the whole milestone. Its test is the one that proves duplicate delivery cannot double-index a project.

**Files:**
- Create: `backend/app/repositories/project.py`
- Test: `backend/tests/test_project_repository.py`

**Interfaces:**
- Consumes: `BaseRepository`, `Project`, `ProjectStatus`, `ProjectScope`
- Produces: `ProjectRepository` with `SORTABLE_FIELDS`; `async def list_page(*, scope: ProjectScope, page: int, limit: int, search: str | None, sort: str, descending: bool) -> tuple[Sequence[Project], int]`; `async def claim(*, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool`; `async def renew_lease(*, project_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool`; `async def release(*, project_id: uuid.UUID, job_id: uuid.UUID, status: ProjectStatus, error: str | None = None, **fields: object) -> None`; `async def find_stranded(*, pending_older_than_seconds: int) -> Sequence[Project]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_project_repository.py`:

```python
"""The lease claim, which is what makes at-least-once delivery safe."""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ProjectScope
from app.db.session import get_sessionmaker
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project, create_user  # added in this task


async def test_claim_succeeds_on_a_pending_project(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)

    claimed = await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    assert claimed is True
    await db_session.refresh(project)
    assert project.status == ProjectStatus.CLONING
    assert project.lease_owner == "worker-0"
    assert project.reindex_in_progress is False


async def test_claiming_a_ready_project_starts_a_reindex(db_session: AsyncSession) -> None:
    """A reindex leaves status at `ready` so the project stays queryable."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    repository = ProjectRepository(db_session)

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    await db_session.refresh(project)
    assert project.status == ProjectStatus.READY
    assert project.reindex_in_progress is True


async def test_a_live_lease_blocks_a_second_claim(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    assert not await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )


async def test_an_expired_lease_can_be_reclaimed(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    repository = ProjectRepository(db_session)
    # Expire it by claiming with a negative lease.
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="dead", lease_seconds=-1
    )
    await db_session.commit()

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )


async def test_a_completed_job_id_is_not_reclaimed(db_session: AsyncSession) -> None:
    """A redelivered message must not start an unwanted reindex."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    job_id = uuid.uuid4()

    await repository.claim(
        project_id=project.id, job_id=job_id, worker_id="worker-0", lease_seconds=300
    )
    await repository.release(
        project_id=project.id, job_id=job_id, status=ProjectStatus.READY
    )
    await db_session.commit()

    # The same message arrives again.
    assert not await repository.claim(
        project_id=project.id, job_id=job_id, worker_id="worker-1", lease_seconds=300
    )


async def test_exactly_one_of_two_concurrent_claims_wins() -> None:
    """The race the whole design rests on. Two sessions, one row, one winner."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as setup:
        project = await create_project(setup, status=ProjectStatus.PENDING)
        await setup.commit()
        project_id = project.id

    async def attempt(worker_id: str) -> bool:
        async with sessionmaker() as session:
            won = await ProjectRepository(session).claim(
                project_id=project_id,
                job_id=uuid.uuid4(),
                worker_id=worker_id,
                lease_seconds=300,
            )
            await session.commit()
            return won

    results = await asyncio.gather(attempt("worker-0"), attempt("worker-1"))
    assert sum(results) == 1


async def test_list_page_applies_a_restricted_scope(db_session: AsyncSession) -> None:
    """Phase 2's enforcement point, exercised now so it cannot silently rot."""
    user = await create_user(db_session)
    visible = await create_project(db_session, created_by=user.id)
    await create_project(db_session, created_by=user.id)
    await db_session.commit()

    rows, total = await ProjectRepository(db_session).list_page(
        scope=ProjectScope.of([visible.id]),
        page=1,
        limit=25,
        search=None,
        sort="created_at",
        descending=True,
    )
    assert total == 1
    assert [row.id for row in rows] == [visible.id]


async def test_list_page_with_an_empty_scope_returns_nothing(db_session: AsyncSession) -> None:
    """An empty id set means *no* access, never all of it."""
    await create_project(db_session)
    await db_session.commit()

    rows, total = await ProjectRepository(db_session).list_page(
        scope=ProjectScope.of([]), page=1, limit=25, search=None, sort="created_at", descending=True
    )
    assert total == 0
    assert list(rows) == []


async def test_unknown_sort_field_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unknown sort field"):
        await ProjectRepository(db_session).list_page(
            scope=ProjectScope.all(),
            page=1,
            limit=25,
            search=None,
            sort="encrypted_pat",
            descending=True,
        )
```

- [ ] **Step 2: Write the shared test factories**

Create `backend/tests/factories.py` — the repository tests and every later API test build the same two rows:

```python
"""Row builders shared by the project tests."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.project import Project, ProjectStatus
from app.models.user import User


async def create_user(
    session: AsyncSession, *, email: str | None = None, is_admin: bool = False
) -> User:
    """A live account that has already changed its password."""
    user = User(
        id=uuid.uuid4(),
        name="Test User",
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        # Cost 4 comes from the suite's BCRYPT_COST override; cost is not under test.
        password_hash=hash_password("correct-horse-battery", cost=4),
        is_admin=is_admin,
        must_change_password=False,
    )
    session.add(user)
    await session.flush()
    return user


async def create_project(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None = None,
    status: ProjectStatus = ProjectStatus.READY,
    repo_url: str = "https://github.com/acme/repo.git",
) -> Project:
    """A project owned by `created_by`, or by a freshly created user."""
    if created_by is None:
        created_by = (await create_user(session)).id
    project = Project(
        id=uuid.uuid4(),
        created_by=created_by,
        name="repo",
        repo_url=repo_url,
        branch="main",
        status=status.value,
    )
    session.add(project)
    await session.flush()
    return project
```

`hash_password` lives in `app/core/security.py` with a keyword-only `cost`. `app/core/passwords.py` is the *policy* module (`check_password`) and is not what you want here.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_project_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.project'`

- [ ] **Step 4: Write the repository**

Create `backend/app/repositories/project.py`:

```python
"""Queries over `projects`, including the claim that makes ingestion safe.

Kafka delivers at-least-once. The claim below — not the message — decides who runs
a job, so a redelivery, a rebalance, or a duplicate produce costs one skipped poll
rather than two workers indexing the same repository.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, update

from app.core.access import ProjectScope
from app.models.project import Project, ProjectStatus
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Reads and writes for projects. All reads exclude soft-deleted rows."""

    model = Project

    # `encrypted_pat` and `error` are deliberately absent: `sort` arrives from a
    # query parameter, and an unchecked column name is an information leak.
    SORTABLE_FIELDS = frozenset({"name", "status", "created_at", "updated_at"})

    async def list_page(
        self,
        *,
        scope: ProjectScope,
        page: int,
        limit: int,
        search: str | None,
        sort: str,
        descending: bool,
    ) -> tuple[Sequence[Project], int]:
        """One page of projects plus the total, restricted to `scope`.

        The scope arrives from `resolve_project_scope` and is applied here. In phase 1
        it is `unrestricted`, so no clause is added and the behaviour is identical to
        having none — which is the point: phase 2 changes the resolver's body only.
        """
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"unknown sort field: {sort}")

        statement = self.active_select()
        if not scope.unrestricted:
            # An empty id set means no access, not all of it — `in_(())` is false
            # for every row, which is the required fail-closed behaviour.
            statement = statement.where(Project.id.in_(scope.ids))
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(Project.name.ilike(pattern), Project.repo_url.ilike(pattern))
            )

        count_result = await self.session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        total = count_result.scalar_one()

        column = getattr(Project, sort)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * limit).limit(limit)

        rows = await self.session.execute(statement)
        return rows.scalars().all(), total

    async def claim(
        self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a project's next indexing run. True if we won it.

        Gates on two things and nothing else: no live lease, and this job has not
        already been completed.

        It cannot gate on status. A reindex leaves the project at `ready` throughout,
        so a status-based clause could never claim one. But merely permitting `ready`
        would let a redelivered message start an unwanted reindex once a finished job
        cleared its lease — `last_job_id` is what separates those two cases.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)

        statement = (
            update(Project)
            .where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
                Project.last_job_id.is_distinct_from(job_id),
                or_(Project.lease_expires_at.is_(None), Project.lease_expires_at < now),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=expires_at,
                last_job_id=job_id,
                # One statement serves both modes: a first index moves to `cloning`,
                # a reindex stays `ready` and raises the flag instead.
                status=case(
                    (Project.status == ProjectStatus.READY.value, ProjectStatus.READY.value),
                    else_=ProjectStatus.CLONING.value,
                ),
                reindex_in_progress=case(
                    (Project.status == ProjectStatus.READY.value, True), else_=False
                ),
                # Bulk UPDATE: `onupdate` does not fire on this path
                # (.claude/rules/persistence.md).
                updated_at=now,
            )
        )
        result = await self.session.execute(statement)
        return result.rowcount == 1

    async def renew_lease(
        self, *, project_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(Project)
            .where(Project.id == project_id, Project.lease_owner == worker_id)
            .values(
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
        )
        return result.rowcount == 1

    async def release(
        self,
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        status: ProjectStatus,
        error: str | None = None,
        **fields: Any,
    ) -> None:
        """Finish a run: write the outcome and drop the lease.

        `last_job_id` is set to the job just completed so a redelivery of the same
        message is recognised and skipped.
        """
        now = datetime.now(UTC)
        await self.session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(
                status=status.value,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                last_job_id=job_id,
                reindex_in_progress=False,
                updated_at=now,
                **fields,
            )
        )

    async def find_stranded(self, *, pending_older_than_seconds: int) -> Sequence[Project]:
        """Projects whose job was lost: never picked up, or held by a dead worker.

        Covers the window where `POST /projects` wrote the row but the produce failed,
        and the case where a worker died mid-run.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=pending_older_than_seconds)
        statement = self.active_select().where(
            or_(
                (Project.status == ProjectStatus.PENDING.value)
                & (Project.lease_expires_at.is_(None))
                & (Project.created_at < cutoff),
                Project.lease_expires_at < now,
            )
        )
        rows = await self.session.execute(statement)
        return rows.scalars().all()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_project_repository.py -v`
Expected: PASS (9 tests). If `test_exactly_one_of_two_concurrent_claims_wins` is flaky, that is a real finding, not a flaky test — a single `UPDATE ... WHERE` is atomic, so a second winner means the `WHERE` clause is wrong.

- [ ] **Step 6: Commit**

```bash
git add backend/app/repositories/project.py backend/tests/test_project_repository.py \
        backend/tests/factories.py
git commit -m "feat(projects): add the repository and the race-safe lease claim"
```

---

# Phase 2 — API surface

### Task 6: The queue boundary and message format

Services depend on a protocol, not on Kafka, so every route and service test in this plan runs without a broker. The Kafka implementation lands in Task 16 behind the same interface.

**Files:**
- Create: `backend/app/queue/__init__.py`, `backend/app/queue/topics.py`, `backend/app/queue/protocol.py`
- Test: `backend/tests/test_queue_message.py`

**Interfaces:**
- Consumes: `Settings.kafka_ingest_topic`, `.kafka_max_attempts`
- Produces: `IngestionMessage` (frozen dataclass: `project_id: uuid.UUID`, `job_id: uuid.UUID`, `attempt: int`, `not_before_ms: int`, `original_topic: str`) with `.to_bytes() -> bytes`, `.key() -> bytes`, classmethod `.from_bytes(raw: bytes) -> IngestionMessage`; `INGEST_TOPIC`, `RETRY_TOPICS: tuple[tuple[str, int], ...]`, `DLQ_TOPIC`, `ALL_TOPICS`; `next_destination(*, attempt: int, max_attempts: int) -> tuple[str, int]`; `IngestionQueue` protocol with `async def enqueue(message: IngestionMessage) -> None`; `InMemoryIngestionQueue` with `.messages: list[IngestionMessage]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_queue_message.py`:

```python
"""The wire format for an ingestion job."""

import uuid

from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import DLQ_TOPIC, RETRY_TOPICS, IngestionMessage, next_destination


def message(**overrides: object) -> IngestionMessage:
    defaults = {
        "project_id": uuid.uuid4(),
        "job_id": uuid.uuid4(),
        "attempt": 0,
        "not_before_ms": 0,
        "original_topic": "askrepo.ingest.requested",
    }
    return IngestionMessage(**{**defaults, **overrides})  # type: ignore[arg-type]  # test builder


def test_round_trips_through_bytes() -> None:
    original = message()
    assert IngestionMessage.from_bytes(original.to_bytes()) == original


def test_key_is_the_project_id_so_retries_share_a_partition() -> None:
    project_id = uuid.uuid4()
    assert message(project_id=project_id).key() == str(project_id).encode()


def test_first_failure_goes_to_the_one_minute_topic() -> None:
    topic, delay = next_destination(attempt=0, max_attempts=3)
    assert topic == RETRY_TOPICS[0][0]
    assert delay == 60


def test_second_failure_goes_to_the_ten_minute_topic() -> None:
    topic, delay = next_destination(attempt=1, max_attempts=3)
    assert topic == RETRY_TOPICS[1][0]
    assert delay == 600


def test_exhausted_attempts_go_to_the_dlq() -> None:
    topic, delay = next_destination(attempt=2, max_attempts=3)
    assert topic == DLQ_TOPIC
    assert delay == 0


async def test_the_in_memory_queue_records_what_it_was_given() -> None:
    queue = InMemoryIngestionQueue()
    sent = message()
    await queue.enqueue(sent)
    assert queue.messages == [sent]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_queue_message.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.queue'`

- [ ] **Step 3: Write the topics module**

Create `backend/app/queue/__init__.py` (empty) and `backend/app/queue/topics.py`:

```python
"""Topic names and the ingestion message format.

Kafka has no delayed-delivery primitive, so the delay is built from topics: a failed
job moves to a fixed-delay retry topic, and a consumer there waits until the message
is due before re-producing it. `RETRY_TOPICS` is ordered by attempt.
"""

import json
import uuid
from dataclasses import asdict, dataclass

INGEST_TOPIC = "askrepo.ingest.requested"
DLQ_TOPIC = "askrepo.ingest.dlq"

# (topic, delay_seconds), consulted in order by attempt number.
RETRY_TOPICS: tuple[tuple[str, int], ...] = (
    ("askrepo.ingest.retry.1m", 60),
    ("askrepo.ingest.retry.10m", 600),
)

ALL_TOPICS = (INGEST_TOPIC, *[topic for topic, _ in RETRY_TOPICS], DLQ_TOPIC)


@dataclass(frozen=True, slots=True)
class IngestionMessage:
    """One request to index one project.

    `job_id` is minted per enqueue and recorded on the project when the run finishes.
    It is what lets the worker tell "a new reindex was requested" from "an old message
    arrived twice" — see `ProjectRepository.claim`.
    """

    project_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int
    not_before_ms: int
    original_topic: str

    def to_bytes(self) -> bytes:
        """Serialise for the wire.

        JSON rather than a binary codec: these are a handful of messages a day, and
        someone debugging the DLQ should be able to read one.
        """
        payload = asdict(self)
        payload["project_id"] = str(self.project_id)
        payload["job_id"] = str(self.job_id)
        return json.dumps(payload).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IngestionMessage":
        """Parse a message off the wire."""
        payload = json.loads(raw)
        return cls(
            project_id=uuid.UUID(payload["project_id"]),
            job_id=uuid.UUID(payload["job_id"]),
            attempt=int(payload["attempt"]),
            not_before_ms=int(payload["not_before_ms"]),
            original_topic=str(payload["original_topic"]),
        )

    def key(self) -> bytes:
        """Partition key.

        Keying by project keeps a project's retries on one partition, so two
        attempts at the same repository never run concurrently on two workers.
        """
        return str(self.project_id).encode()


def next_destination(*, attempt: int, max_attempts: int) -> tuple[str, int]:
    """Where a job goes after failing its `attempt`-th try, and how long it waits.

    Returns the DLQ with a zero delay once the attempts are spent.
    """
    if attempt >= max_attempts - 1 or attempt >= len(RETRY_TOPICS):
        return DLQ_TOPIC, 0
    return RETRY_TOPICS[attempt]
```

- [ ] **Step 4: Write the protocol and fake**

Create `backend/app/queue/protocol.py`:

```python
"""The queue boundary.

Services depend on this protocol rather than on Kafka, so route and service tests
run without a broker. `KafkaIngestionQueue` (app/queue/producer.py) and
`InMemoryIngestionQueue` are the two implementations.
"""

from typing import Protocol

from app.queue.topics import IngestionMessage


class IngestionQueue(Protocol):
    """Somewhere to put a job so a worker picks it up."""

    async def enqueue(self, message: IngestionMessage) -> None:
        """Publish a job. Raises on failure — the caller decides what that means."""
        ...


class InMemoryIngestionQueue:
    """Test double. Records what it was handed and never fails."""

    def __init__(self) -> None:
        self.messages: list[IngestionMessage] = []

    async def enqueue(self, message: IngestionMessage) -> None:
        """Record the job."""
        self.messages.append(message)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_queue_message.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/queue/ backend/tests/test_queue_message.py
git commit -m "feat(queue): add the ingestion message format and queue protocol"
```

---

### Task 7: Project schemas and service

**Files:**
- Create: `backend/app/schemas/project.py`, `backend/app/services/project.py`
- Test: `backend/tests/test_project_service.py`

**Interfaces:**
- Consumes: `ProjectRepository`, `IngestionQueue`, `IngestionMessage`, `SecretBox`, `validate_repo_url`, `resolve_project_scope`, `AuthenticatedUser`, `ListQuery`, `PaginatedResponse`
- Produces: `ProjectCreateRequest(repo_url: str, branch: str = "main", pat: str | None = None)`; `ProjectResponse`; `ReindexResponse(enqueued: bool, project: ProjectResponse)`; `ProjectService(session, settings, queue)` with `async def create(payload, *, actor) -> ProjectResponse`, `async def list(query, *, actor) -> PaginatedResponse[ProjectResponse]`, `async def get(project_id, *, actor) -> ProjectResponse`, `async def reindex(project_id, *, actor) -> ReindexResponse`, `async def delete(project_id, *, actor) -> None`

- [ ] **Step 1: Confirm the `AuthenticatedUser` field names**

Run: `grep -n "class AuthenticatedUser" -A 12 backend/app/core/middleware.py`

The test below constructs one directly. Match the real field names and order — do not guess.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_project_service.py`:

```python
"""Project lifecycle rules: the destructive gate, the idempotent reindex, and the
fact that a PAT never leaves the service."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.project import ProjectStatus
from app.queue.protocol import InMemoryIngestionQueue
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreateRequest
from app.services.project import ProjectService
from tests.factories import create_project, create_user


def actor_for(user_id: uuid.UUID, *, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id, email="a@example.com", is_admin=is_admin, must_change_password=False
    )


def service_for(session: AsyncSession, queue: InMemoryIngestionQueue) -> ProjectService:
    return ProjectService(session, get_settings(), queue)


async def test_create_enqueues_exactly_one_job(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    response = await service_for(db_session, queue).create(
        ProjectCreateRequest(repo_url="https://github.com/acme/repo.git", branch="main"),
        actor=actor_for(user.id),
    )

    assert response.status == ProjectStatus.PENDING
    assert len(queue.messages) == 1
    assert queue.messages[0].project_id == response.id


async def test_create_rejects_a_url_that_fails_validation(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, queue).create(
            ProjectCreateRequest(repo_url="http://github.com/acme/repo.git"),
            actor=actor_for(user.id),
        )

    assert caught.value.status_code == 400
    assert caught.value.code == ErrorCode.INVALID_REPO_URL
    # Validation runs before the insert, so a rejected URL leaves nothing behind.
    assert queue.messages == []


async def test_the_pat_is_never_returned(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()

    response = await service_for(db_session, InMemoryIngestionQueue()).create(
        ProjectCreateRequest(repo_url="https://github.com/acme/repo.git", pat="ghp_secret"),
        actor=actor_for(user.id),
    )

    assert "ghp_secret" not in response.model_dump_json()


async def test_a_stranger_cannot_delete_someone_elses_project(db_session: AsyncSession) -> None:
    """docs/PRD.md §7: verified by an automated test."""
    owner = await create_user(db_session)
    stranger = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, InMemoryIngestionQueue()).delete(
            project.id, actor=actor_for(stranger.id)
        )

    # 403, not 404: project existence is deliberately public (docs/PRD.md §4.1).
    assert caught.value.status_code == 403
    assert caught.value.code == ErrorCode.NOT_PROJECT_OWNER


async def test_an_admin_can_delete_any_project(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    admin = await create_user(db_session, is_admin=True)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()

    await service_for(db_session, InMemoryIngestionQueue()).delete(
        project.id, actor=actor_for(admin.id, is_admin=True)
    )
    await db_session.commit()

    assert await ProjectRepository(db_session).get(project.id) is None


async def test_reindex_enqueues_when_the_project_is_idle(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id, status=ProjectStatus.READY)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    result = await service_for(db_session, queue).reindex(project.id, actor=actor_for(owner.id))

    assert result.enqueued is True
    assert len(queue.messages) == 1


async def test_reindex_is_a_no_op_while_a_run_is_in_flight(db_session: AsyncSession) -> None:
    """202 either way; the body says which happened (spec §2.2)."""
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id, status=ProjectStatus.INDEXING)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    result = await service_for(db_session, queue).reindex(project.id, actor=actor_for(owner.id))

    assert result.enqueued is False
    assert queue.messages == []


async def test_get_raises_404_for_a_missing_project(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, InMemoryIngestionQueue()).get(
            uuid.uuid4(), actor=actor_for(user.id)
        )
    assert caught.value.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_project_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.project'`

- [ ] **Step 4: Write the schemas**

Create `backend/app/schemas/project.py`:

```python
"""Project request and response bodies.

Every model inherits `ApiModel`, so `repo_url` arrives and leaves as `repoUrl`.
`encrypted_pat` appears in no response model at all — not masked, not optional
(`docs/PRD.md` §4.1). The safest way not to leak a field is not to declare it.
"""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.project import ProjectStatus
from app.schemas.base import ApiModel


class ProjectCreateRequest(ApiModel):
    """Create a project from a repository URL."""

    repo_url: str = Field(max_length=2048)
    branch: str = Field(default="main", max_length=255)
    # Write-only: accepted here, encrypted immediately, never echoed back.
    pat: str | None = Field(default=None, max_length=512)


class ProjectResponse(ApiModel):
    """A project as the API presents it."""

    id: uuid.UUID
    created_by: uuid.UUID
    name: str
    repo_url: str
    branch: str
    status: ProjectStatus
    error: str | None
    last_indexed_commit: str | None
    file_count: int | None
    chunk_count: int | None
    embedding_model: str | None
    reindex_in_progress: bool
    created_at: datetime
    updated_at: datetime


class ReindexResponse(ApiModel):
    """The outcome of a reindex trigger.

    Always returned with `202`. `enqueued` is false when a run was already in
    flight, so a caller can tell "I started one" from "one was already going"
    without an error branch (spec §2.2).
    """

    enqueued: bool
    project: ProjectResponse
```

- [ ] **Step 5: Write the service**

Create `backend/app/services/project.py`:

```python
"""Project lifecycle: create, list, read, reindex, delete.

The `created_by`-or-admin gate lives here rather than in the routes, so `reindex`
and `delete` cannot drift apart (`.claude/rules/router.md`).
"""

import uuid
from urllib.parse import urlsplit

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.crypto import SecretBox
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.repo_url import RepoUrlRejected, validate_repo_url
from app.models.project import Project, ProjectStatus
from app.queue.protocol import IngestionQueue
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from app.repositories.project import ProjectRepository
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ReindexResponse

DEFAULT_SORT = "created_at"

# A run is in flight in these states, so a second trigger is a no-op.
BUSY_STATUSES = frozenset(
    {ProjectStatus.PENDING.value, ProjectStatus.CLONING.value, ProjectStatus.INDEXING.value}
)


class ProjectService:
    """Business rules for projects. Owns its transactions."""

    def __init__(self, session: AsyncSession, settings: Settings, queue: IngestionQueue) -> None:
        self.session = session
        self.settings = settings
        self.queue = queue
        self._repository = ProjectRepository(session)

    async def create(
        self, payload: ProjectCreateRequest, *, actor: AuthenticatedUser
    ) -> ProjectResponse:
        """Record a project and enqueue its first indexing run.

        Any authenticated user may create one (`docs/PRD.md` §4.1, confirmed in the
        spec's §2.3). Validation runs before the row is written, so a rejected URL
        leaves nothing behind.
        """
        try:
            await validate_repo_url(payload.repo_url, allowlist=self.settings.repo_host_allowlist)
        except RepoUrlRejected as rejected:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_REPO_URL, rejected.reason
            ) from rejected

        encrypted_pat = None
        if payload.pat:
            encrypted_pat = SecretBox(self.settings.pat_encryption_key).encrypt(payload.pat)

        project = Project(
            id=uuid.uuid4(),
            created_by=actor.id,
            name=_derive_name(payload.repo_url),
            repo_url=payload.repo_url,
            branch=payload.branch,
            status=ProjectStatus.PENDING.value,
            encrypted_pat=encrypted_pat,
        )
        await self._repository.add(project)
        await self.session.commit()

        # Produced after the commit: a message referencing an uncommitted row would
        # race the worker. The reconcile sweep covers a produce that fails here.
        await self._enqueue(project.id)
        return ProjectResponse.model_validate(project)

    async def list(
        self, query: ListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[ProjectResponse]:
        """A page of projects the caller may read.

        The scope comes from the access resolver and nowhere else. In phase 1 it is
        unrestricted; phase 2 changes the resolver's body and this line stays put.
        """
        scope = access.resolve_project_scope(actor)
        try:
            rows, total = await self._repository.list_page(
                scope=scope,
                page=query.page,
                limit=query.limit,
                search=query.search,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error

        return PaginatedResponse.build(
            [ProjectResponse.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> ProjectResponse:
        """One project, by id."""
        return ProjectResponse.model_validate(await self._require_readable(project_id, actor))

    async def reindex(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> ReindexResponse:
        """Trigger a fresh indexing run. Idempotent while one is already in flight.

        The busy check here is a fast path, **not** a correctness boundary: two
        simultaneous callers both pass it and both enqueue. The worker's lease claim
        settles that (`ProjectRepository.claim`). Do not delete the lease on the
        grounds that this check exists.
        """
        project = await self._require_readable(project_id, actor)
        self._require_destructive_rights(project, actor)

        if project.status in BUSY_STATUSES or project.reindex_in_progress:
            return ReindexResponse(enqueued=False, project=ProjectResponse.model_validate(project))

        await self._enqueue(project.id)
        return ReindexResponse(enqueued=True, project=ProjectResponse.model_validate(project))

    async def delete(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete the project.

        Its Qdrant points are hard-deleted in the same operation by the vector store
        (`docs/PRD.md` §5.1) — wired in Task 15.
        """
        project = await self._require_readable(project_id, actor)
        self._require_destructive_rights(project, actor)
        await self._repository.soft_delete(project)
        await self.session.commit()

    async def _enqueue(self, project_id: uuid.UUID) -> None:
        """Publish one job for this project."""
        await self.queue.enqueue(
            IngestionMessage(
                project_id=project_id,
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=0,
                original_topic=INGEST_TOPIC,
            )
        )

    async def _require_readable(self, project_id: uuid.UUID, actor: AuthenticatedUser) -> Project:
        """Load a project the caller may see, or raise 404."""
        scope = access.resolve_project_scope(actor)
        project = await self._repository.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    def _require_destructive_rights(self, project: Project, actor: AuthenticatedUser) -> None:
        """Delete and reindex need `created_by` or admin (`docs/PRD.md` §4.1).

        403 rather than 404: project existence is deliberately public here, so
        hiding it would only confuse.
        """
        if actor.is_admin or project.created_by == actor.id:
            return
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.NOT_PROJECT_OWNER,
            "Only the person who added this project, or an administrator, can do that.",
        )


def _derive_name(repo_url: str) -> str:
    """A display name from the URL's last path segment, minus any `.git`."""
    segment = urlsplit(repo_url).path.rstrip("/").rsplit("/", 1)[-1]
    return segment.removesuffix(".git") or "project"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_project_service.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/project.py backend/app/services/project.py \
        backend/tests/test_project_service.py
git commit -m "feat(projects): add project schemas and lifecycle service"
```

---

### Task 8: The project routes

**Files:**
- Create: `backend/app/api/routes/projects.py`
- Modify: `backend/app/main.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_projects_api.py`

**Interfaces:**
- Consumes: `ProjectService`, `CurrentUser`, `SessionDep`, `ERROR_RESPONSES`, `ListQuery`, `IngestionQueue`
- Produces: `router` (prefix `/projects`, tag `Projects`); `get_ingestion_queue(request) -> IngestionQueue`; `get_project_service(...) -> ProjectService`

- [ ] **Step 1: Read how the existing tests authenticate**

Run: `grep -n "fixture" -A 15 backend/tests/test_users_api.py | head -60`

Reuse whatever fixture builds an authenticated `AsyncClient`. Do not invent a second mechanism.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_projects_api.py`:

```python
"""The project routes end to end, against an in-memory queue."""

from httpx import AsyncClient

from app.models.project import ProjectStatus


async def test_create_returns_201_and_camel_case(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git", "branch": "main"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["repoUrl"] == "https://github.com/acme/repo.git"
    assert body["status"] == ProjectStatus.PENDING
    # snake_case on the wire is the defect tests/test_api_model.py exists to catch.
    assert "repo_url" not in body
    assert "lastIndexedCommit" in body


async def test_create_never_echoes_the_pat(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git", "pat": "ghp_secret"}
    )
    assert response.status_code == 201
    assert "ghp_secret" not in response.text
    assert "pat" not in response.json()


async def test_create_rejects_a_bad_url_with_400(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "http://github.com/acme/repo.git"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REPO_URL"


async def test_list_is_paginated_not_a_bare_array(authed_client: AsyncClient) -> None:
    await authed_client.post("/projects", json={"repoUrl": "https://github.com/acme/one.git"})
    response = await authed_client.get("/projects")

    assert response.status_code == 200
    assert set(response.json()) >= {"items", "page", "limit", "totalCount", "totalPages"}


async def test_list_rejects_an_unknown_sort_field(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/projects", params={"sort": "encryptedPat"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_SORT_FIELD"


async def test_reindex_returns_202_when_a_run_is_in_flight(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    project_id = created.json()["id"]

    # The project is `pending`, so a run is already in flight.
    response = await authed_client.post(f"/projects/{project_id}/reindex")
    assert response.status_code == 202
    assert response.json()["enqueued"] is False
    assert response.json()["project"]["id"] == project_id


async def test_delete_returns_204(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    project_id = created.json()["id"]

    assert (await authed_client.delete(f"/projects/{project_id}")).status_code == 204
    assert (await authed_client.get(f"/projects/{project_id}")).status_code == 404


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/projects")).status_code == 401
```

- [ ] **Step 3: Add the queue override fixture**

In `backend/tests/conftest.py`:

```python
@pytest.fixture
def ingestion_queue() -> InMemoryIngestionQueue:
    """The queue every route test enqueues into. Assert against `.messages`."""
    return InMemoryIngestionQueue()


@pytest.fixture
def app_with_queue(ingestion_queue: InMemoryIngestionQueue) -> FastAPI:
    """The app with the broker replaced, so route tests need no Kafka."""
    from app.api.routes.projects import get_ingestion_queue

    application = create_app()
    application.dependency_overrides[get_ingestion_queue] = lambda: ingestion_queue
    return application
```

Point the existing authenticated-client fixture at `app_with_queue` so project routes resolve the fake. Import `InMemoryIngestionQueue` and `create_app` at the top of the file.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_projects_api.py -v`
Expected: FAIL — 404 on every route; the router is not mounted.

- [ ] **Step 5: Write the router**

Create `backend/app/api/routes/projects.py`:

```python
"""Project ingestion and lifecycle.

Reads are open to every authenticated user — `docs/PRD.md` §4.1 shares projects
instance-wide in phase 1. Destructive operations are gated inside the service, not
here, so `reindex` and `delete` cannot drift apart.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.queue.protocol import IngestionQueue
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ReindexResponse
from app.services.project import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


def get_ingestion_queue(request: Request) -> IngestionQueue:
    """The producer built during application startup.

    A dependency rather than a module global, so tests override it with the
    in-memory fake and never need a broker.
    """
    queue: IngestionQueue | None = getattr(request.app.state, "ingestion_queue", None)
    if queue is None:
        raise RuntimeError("ingestion queue is not configured; check the app lifespan")
    return queue


def get_project_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[IngestionQueue, Depends(get_ingestion_queue)],
) -> ProjectService:
    """Provide the service with a request-scoped session."""
    return ProjectService(session, settings, queue)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    status_code=status.HTTP_200_OK,
    summary="List all projects",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_projects(
    current_user: CurrentUser,
    service: ProjectServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[ProjectResponse]:
    return await service.list(query, actor=current_user)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one project",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def get_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> ProjectResponse:
    return await service.get(project_id, actor=current_user)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project from a repository URL",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def create_project(
    payload: ProjectCreateRequest, current_user: CurrentUser, service: ProjectServiceDep
) -> ProjectResponse:
    return await service.create(payload, actor=current_user)


@router.post(
    "/{project_id}/reindex",
    response_model=ReindexResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-clone and re-index a project",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def reindex_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> ReindexResponse:
    return await service.reindex(project_id, actor=current_user)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and its index",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def delete_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> None:
    await service.delete(project_id, actor=current_user)
```

- [ ] **Step 6: Mount the router**

In `app/main.py`, import `projects` and add `app.include_router(projects.router)` after `users`. Leave the middleware ordering untouched — `AuthContextMiddleware` must stay registered *before* `CORSMiddleware`.

`/projects` is **not** added to `GATE_EXEMPT_PREFIXES`: a user who must change their password has no business indexing a repository, and the default answer for a new prefix is no.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_projects_api.py tests/test_route_coverage.py -v`
Expected: PASS. `test_route_coverage.py` walks every registered route — a failure there means a new route is missing its `responses` block or summary.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/projects.py backend/app/main.py \
        backend/tests/test_projects_api.py backend/tests/conftest.py
git commit -m "feat(projects): add the project routes"
```

---

### Task 9: The access and gating acceptance tests

`docs/PRD.md` §7 names its criteria and says "verified by an automated test". Task 7 covered them at the service level; this task proves them over HTTP, where a future refactor is most likely to break them.

**Files:**
- Create: `backend/tests/test_m1_acceptance.py`
- Modify: `backend/tests/conftest.py`
- Test: itself

**Interfaces:**
- Consumes: everything from Tasks 1–8
- Produces: fixtures `client_for_user_a`, `client_for_user_b`, `client_for_admin` — authenticated `AsyncClient`s for three distinct accounts against `app_with_queue`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_m1_acceptance.py`:

```python
"""docs/PRD.md §7's M1 success criteria, asserted over HTTP.

These must never be quietly deleted: they encode the phase-1 sharing model and the
destructive gate, both of which look like bugs to someone who has not read §4.1.
"""

import pathlib
import re

from httpx import AsyncClient


async def test_sharing_works_as_intended(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient
) -> None:
    """User B can list and read a project user A created, with no grant step."""
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/shared.git"}
    )
    project_id = created.json()["id"]

    listed = await client_for_user_b.get("/projects")
    assert project_id in [item["id"] for item in listed.json()["items"]]

    assert (await client_for_user_b.get(f"/projects/{project_id}")).status_code == 200


async def test_destructive_gating_holds(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient
) -> None:
    """User B gets 403 on someone else's project — not 404, and not success."""
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/gated.git"}
    )
    project_id = created.json()["id"]

    delete_response = await client_for_user_b.delete(f"/projects/{project_id}")
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"]["code"] == "NOT_PROJECT_OWNER"

    assert (await client_for_user_b.post(f"/projects/{project_id}/reindex")).status_code == 403


async def test_an_admin_overrides_the_gate(
    client_for_user_a: AsyncClient, client_for_admin: AsyncClient
) -> None:
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/admin.git"}
    )
    project_id = created.json()["id"]

    assert (await client_for_admin.delete(f"/projects/{project_id}")).status_code == 204


def test_read_scoping_lives_in_exactly_one_function() -> None:
    """docs/PRD.md §7's phase-2 readiness criterion, 'confirmed by grep'.

    Only two places may compare `created_by` to a caller: the access resolver, and
    the service's destructive gate. Anything else is read scoping in the wrong
    place, which is what phase 2 would have to hunt down.
    """
    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    allowed = {"core/access.py", "services/project.py"}
    offenders: list[str] = []

    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(app_root).as_posix()
        if relative in allowed:
            continue
        if re.search(r"created_by\s*==", path.read_text()):
            offenders.append(relative)

    assert offenders == [], f"read scoping outside the resolver: {offenders}"
```

- [ ] **Step 2: Add the three client fixtures**

In `backend/tests/conftest.py`, add `client_for_user_a`, `client_for_user_b`, and `client_for_admin`, each an `AsyncClient` authenticated as a distinct account against `app_with_queue`. Model them exactly on the existing authenticated-client fixture — same login flow, same header handling — with `client_for_admin` created with `is_admin=True`.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_m1_acceptance.py -v`
Expected: FAIL — fixtures missing on the first run; after Step 2, all four should pass without touching application code. If one fails, the defect is in Tasks 7–8, not in the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_m1_acceptance.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole suite and the linter**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: PASS. Phase 2 is complete — projects can be created, listed, read, gated, and deleted. Nothing indexes them yet.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_m1_acceptance.py backend/tests/conftest.py
git commit -m "test(projects): assert PRD §7 sharing, gating, and scoping criteria"
```

---

# Phase 3 — The ingestion pipeline

Each stage is a small unit behind a narrow interface, driven directly from tests. Nothing in this phase touches Kafka.

### Task 10: Error taxonomy and the cloner

The cloner is where `docs/PRD.md` §9's SSRF control actually lands — validation in Task 3 means nothing unless git is pinned to the address that was validated.

**Files:**
- Create: `backend/app/ingestion/__init__.py`, `backend/app/ingestion/errors.py`, `backend/app/ingestion/cloner.py`
- Test: `backend/tests/test_cloner.py`

**Interfaces:**
- Consumes: `ValidatedRepoUrl`, `scrub`
- Produces: `IngestionError`, `TerminalIngestionError`, `RetryableIngestionError`; `CloneResult` (frozen dataclass: `path: Path`, `commit_sha: str`); `async def clone(validated: ValidatedRepoUrl, *, branch: str, destination: Path, pat: str | None, timeout_seconds: int, max_bytes: int) -> CloneResult`; `def build_git_command(validated, *, branch, destination) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cloner.py`:

```python
"""Clone mechanics. The command-shape tests are security tests: each flag closes a
specific hole named in docs/PRD.md §9."""

import subprocess
from pathlib import Path

import pytest

from app.core.repo_url import ValidatedRepoUrl
from app.ingestion.cloner import build_git_command, clone
from app.ingestion.errors import TerminalIngestionError

VALIDATED = ValidatedRepoUrl(
    url="https://github.com/acme/repo.git",
    host="github.com",
    port=443,
    pinned_ip="140.82.121.4",
)


def test_git_is_pinned_to_the_validated_address() -> None:
    """Without this, git resolves the host again and DNS rebinding defeats Task 3."""
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert "http.curloptResolve=github.com:443:140.82.121.4" in command


def test_redirects_are_disabled() -> None:
    """A redirect to an internal host would resolve unpinned."""
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert "http.followRedirects=false" in command


def test_the_clone_is_shallow_and_single_branch() -> None:
    command = build_git_command(VALIDATED, branch="develop", destination=Path("/tmp/x"))
    assert "--depth" in command and "1" in command
    assert "--single-branch" in command
    assert "--branch" in command
    assert "develop" in command


def test_the_pat_is_never_in_the_command_line() -> None:
    """`ps` output is world-readable; the PAT goes in the environment instead."""
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert not any("ghp_" in part for part in command)


async def test_clone_copies_a_real_repository(tmp_path: Path) -> None:
    """Against a local fixture repo, bypassing validation — that is tested separately."""
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "hello.py").write_text("def hello() -> str:\n    return 'hi'\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")
    destination = tmp_path / "clone"

    result = await clone(
        local,
        branch="main",
        destination=destination,
        pat=None,
        timeout_seconds=60,
        max_bytes=100_000_000,
    )

    assert (result.path / "hello.py").exists()
    assert len(result.commit_sha) == 40


async def test_a_missing_branch_is_terminal(tmp_path: Path) -> None:
    """Retrying will not conjure the branch, so it must not enter the retry chain."""
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    with pytest.raises(TerminalIngestionError):
        await clone(
            local,
            branch="nonexistent",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=100_000_000,
        )


async def test_a_repository_over_the_cap_is_terminal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "big.bin").write_bytes(b"0" * 2_000_000)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    with pytest.raises(TerminalIngestionError, match="too large"):
        await clone(
            local,
            branch="main",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=1_000,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_cloner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion'`

- [ ] **Step 3: Write the error taxonomy**

Create `backend/app/ingestion/__init__.py` (empty) and `backend/app/ingestion/errors.py`:

```python
"""What kind of failure this was, which decides whether the job retries.

Spending three attempts and ten minutes on a URL that failed validation is waste,
and it parks the project in a misleading non-terminal state. The consumer branches
on these two types and nothing else.
"""


class IngestionError(Exception):
    """Base for every failure the ingestion pipeline raises deliberately."""


class TerminalIngestionError(IngestionError):
    """Retrying will not help: bad URL, missing branch, rejected PAT, repo too big."""


class RetryableIngestionError(IngestionError):
    """A transient failure: network blip, provider 5xx, Qdrant unreachable."""
```

- [ ] **Step 4: Write the cloner**

Create `backend/app/ingestion/cloner.py`:

```python
"""Cloning a repository, safely.

Every flag below closes a specific hole from `docs/PRD.md` §9. Read the comments
before changing any of them — none is stylistic.
"""

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.crypto import scrub
from app.core.repo_url import ValidatedRepoUrl
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

# Fragments git prints for failures no amount of retrying will fix.
TERMINAL_MARKERS = (
    "Remote branch",
    "not found in upstream",
    "Authentication failed",
    "could not read Username",
    "Repository not found",
    "access denied",
)

SIZE_POLL_SECONDS = 1.0


def build_git_command(
    validated: ValidatedRepoUrl, *, branch: str, destination: Path
) -> list[str]:
    """The clone command, with the safety configuration baked in.

    Separated from `clone` so the flags can be asserted without running git.
    """
    return [
        "git",
        # Pin git to the address Task 3 validated. Without this git resolves the
        # host itself, and an attacker controlling DNS returns a public address
        # for the check and a private one here.
        "-c",
        f"http.curloptResolve={validated.host}:{validated.port}:{validated.pinned_ip}",
        # curl follows redirects, and a redirect to another host resolves unpinned.
        # The cost is that renamed repositories need their canonical URL.
        "-c",
        "http.followRedirects=false",
        # Never consult the host's credential store or prompt for one.
        "-c",
        "credential.helper=",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        branch,
        validated.url,
        str(destination),
    ]


@dataclass(frozen=True, slots=True)
class CloneResult:
    """Where the working copy landed, and what commit it is at."""

    path: Path
    commit_sha: str


async def _directory_size(path: Path) -> int:
    """Bytes on disk under `path`, following no symlinks."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


async def _enforce_size_cap(destination: Path, process: asyncio.subprocess.Process, max_bytes: int) -> bool:
    """Kill the clone if it outgrows the cap. True if it was killed.

    `--depth 1` bounds history but not the working tree, so a repository that is
    simply enormous at HEAD needs watching rather than trusting.
    """
    while process.returncode is None:
        await asyncio.sleep(SIZE_POLL_SECONDS)
        if destination.exists() and await _directory_size(destination) > max_bytes:
            process.kill()
            return True
    return False


async def clone(
    validated: ValidatedRepoUrl,
    *,
    branch: str,
    destination: Path,
    pat: str | None,
    timeout_seconds: int,
    max_bytes: int,
) -> CloneResult:
    """Clone a validated repository into `destination`.

    Raises `TerminalIngestionError` for anything a retry cannot fix, and
    `RetryableIngestionError` for transient trouble.
    """
    if destination.exists():
        # Re-running a job must start clean: a half-written tree from a killed
        # attempt would otherwise be indexed as if it were complete.
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    environment = {
        # Never block on a credential prompt — a hung clone holds its partition
        # and its lease until both expire.
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    command = build_git_command(validated, branch=branch, destination=destination)
    if pat:
        # The PAT goes in the environment, never on the command line: `ps` output
        # is readable by other processes and git echoes its argv in some errors.
        environment["ASKREPO_PAT"] = pat
        command[1:1] = [
            "-c",
            'credential.helper=!f() { echo "username=x-access-token"; '
            'echo "password=$ASKREPO_PAT"; }; f',
        ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    watcher = asyncio.create_task(_enforce_size_cap(destination, process, max_bytes))

    try:
        _, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as error:
        process.kill()
        raise TerminalIngestionError(
            f"Cloning timed out after {timeout_seconds}s."
        ) from error
    finally:
        watcher.cancel()

    if await watcher if not watcher.cancelled() else False:  # pragma: no cover - see note
        raise TerminalIngestionError("Repository is too large to index.")

    # Scrubbed before it goes anywhere: clone stderr is the likeliest place a
    # token surfaces, and this text lands in Project.error.
    stderr = scrub(stderr_bytes.decode(errors="replace"), pat)

    if process.returncode != 0:
        if not destination.exists() or await _directory_size(destination) > max_bytes:
            raise TerminalIngestionError("Repository is too large to index.")
        if any(marker in stderr for marker in TERMINAL_MARKERS):
            raise TerminalIngestionError(f"Clone failed: {stderr.strip()[:500]}")
        raise RetryableIngestionError(f"Clone failed: {stderr.strip()[:500]}")

    head = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=destination,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    sha_bytes, _ = await head.communicate()
    return CloneResult(path=destination, commit_sha=sha_bytes.decode().strip())
```

**Implementer's note on the size-cap check:** the `await watcher if not watcher.cancelled()` line above is awkward and you should replace it with a clean flag. Restructure `_enforce_size_cap` to set a `killed_for_size` boolean on a small mutable holder that both coroutines close over, then check that holder after `communicate()` returns. The behaviour is what matters: a clone killed for size must raise `TerminalIngestionError("Repository is too large to index.")`, and `test_a_repository_over_the_cap_is_terminal` is the gate.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_cloner.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/ backend/tests/test_cloner.py
git commit -m "feat(ingestion): add the error taxonomy and DNS-pinned cloner"
```

---

### Task 11: The file walker

**Files:**
- Create: `backend/app/ingestion/walker.py`
- Test: `backend/tests/test_walker.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `SourceFile` (frozen dataclass: `path: Path`, `relative_path: str`, `language: str`); `def walk(root: Path, *, max_file_bytes: int) -> Iterator[SourceFile]`; `def detect_language(path: Path) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_walker.py`:

```python
"""What gets indexed and what does not.

A fresh clone has already applied .gitignore — ignored files were never committed.
The filter that matters is about binaries, size, and committed-but-worthless paths.
"""

from pathlib import Path

from app.ingestion.walker import detect_language, walk


def write(root: Path, relative: str, content: bytes | str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)


def test_finds_source_files(tmp_path: Path) -> None:
    write(tmp_path, "app/main.py", "print('x')\n")
    write(tmp_path, "web/index.ts", "export const x = 1;\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"app/main.py", "web/index.ts"}


def test_skips_binaries_by_content_not_extension(tmp_path: Path) -> None:
    """A null byte in the first few KB is the signal; extensions lie."""
    write(tmp_path, "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary")
    write(tmp_path, "weird.py", b"\x00\x01\x02 not really python")
    write(tmp_path, "real.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"real.py"}


def test_skips_the_git_directory(tmp_path: Path) -> None:
    write(tmp_path, ".git/config", "[core]\n")
    write(tmp_path, "main.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"main.py"}


def test_skips_denylisted_paths(tmp_path: Path) -> None:
    """Committed, textual, and worthless to index."""
    write(tmp_path, "package-lock.json", '{"lockfileVersion": 3}\n')
    write(tmp_path, "static/app.min.js", "var a=1;\n")
    write(tmp_path, "node_modules/left-pad/index.js", "module.exports = 1;\n")
    write(tmp_path, "vendor/thing/lib.go", "package thing\n")
    write(tmp_path, "src/app.js", "const a = 1;\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"src/app.js"}


def test_skips_files_over_the_cap(tmp_path: Path) -> None:
    """One generated schema must not consume the whole indexing budget."""
    write(tmp_path, "huge.py", "x = 1\n" * 200_000)
    write(tmp_path, "small.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000)}
    assert found == {"small.py"}


def test_respects_a_gitignore_for_committed_files(tmp_path: Path) -> None:
    """The edge case: committed before the rule was added."""
    write(tmp_path, ".gitignore", "generated/\n")
    write(tmp_path, "generated/schema.py", "x = 1\n")
    write(tmp_path, "app.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"app.py", ".gitignore"} - {".gitignore"} or found == {"app.py"}


def test_detects_language_from_extension() -> None:
    assert detect_language(Path("a/b.py")) == "python"
    assert detect_language(Path("a/b.ts")) == "typescript"
    assert detect_language(Path("a/b.unknownext")) == "text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_walker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.walker'`

- [ ] **Step 3: Write the walker**

Create `backend/app/ingestion/walker.py`:

```python
"""Deciding which files in a clone are worth indexing.

`docs/PRD.md` §4.1 says "walk → .gitignore-aware filter". Worth being precise: a
fresh clone has *already* applied .gitignore, because ignored files were never
committed. `.gitignore` is still read here, but only for the genuine edge case of
files committed before a rule was added. The filtering that does the real work is
binary detection, a size cap, and a denylist of committed-but-worthless paths.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

# Directories never worth walking into at all.
SKIP_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}
)

# Committed, textual, and worthless to a code question.
DENY_SUFFIXES = (".min.js", ".min.css", ".lock", ".map")
DENY_NAMES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock"}
)

EXTENSION_LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".hpp": "cpp", ".swift": "swift", ".scala": "scala", ".sh": "bash", ".sql": "sql",
    ".html": "html", ".css": "css", ".md": "markdown", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".toml": "toml",
}

BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file cleared for chunking."""

    path: Path
    relative_path: str
    language: str


def detect_language(path: Path) -> str:
    """The chunker's language hint, from the extension. `text` when unknown."""
    return EXTENSION_LANGUAGES.get(path.suffix.lower(), "text")


def _is_binary(path: Path) -> bool:
    """Whether a file looks binary.

    Null-byte sniff rather than extension matching: an extension is a claim, and a
    `.py` full of null bytes would otherwise be fed to the embedder as text.
    """
    try:
        return b"\x00" in path.open("rb").read(BINARY_SNIFF_BYTES)
    except OSError:
        return True


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    """The repository's own ignore rules, if it has any."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", gitignore.read_text().splitlines())


def walk(root: Path, *, max_file_bytes: int) -> Iterator[SourceFile]:
    """Yield every file in `root` worth indexing."""
    spec = _load_gitignore(root)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue

        relative = path.relative_to(root).as_posix()

        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in DENY_NAMES or relative.endswith(DENY_SUFFIXES):
            continue
        if spec is not None and spec.match_file(relative):
            continue
        if path.stat().st_size > max_file_bytes:
            continue
        if _is_binary(path):
            continue

        yield SourceFile(path=path, relative_path=relative, language=detect_language(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_walker.py -v`
Expected: PASS (7 tests). Simplify `test_respects_a_gitignore_for_committed_files` once you see the real behaviour — decide deliberately whether `.gitignore` itself is indexed and assert that, rather than leaving the `or`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/walker.py backend/tests/test_walker.py
git commit -m "feat(ingestion): add the source-file walker"
```

---

### Task 12: The chunker

Chunk quality is the biggest lever on M2's answers. It ships behind a protocol because `docs/PRD.md` §7's M5 criterion — scores "meaningfully drop when chunking is deliberately made worse" — presupposes it is swappable.

**Files:**
- Create: `backend/app/ingestion/chunker.py`
- Test: `backend/tests/test_chunker.py`

**Interfaces:**
- Consumes: `SourceFile`
- Produces: `Chunk` (frozen dataclass: `file_path: str`, `start_line: int`, `end_line: int`, `language: str`, `symbol: str | None`, `chunk_index: int`, `text: str`); `Chunker` protocol with `def split(self, file: SourceFile, source: str) -> list[Chunk]`; `LanguageAwareChunker(chunk_size: int, chunk_overlap: int)`; `def embedding_text(chunk: Chunk) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chunker.py`:

```python
"""Chunk boundaries and, above all, line numbers.

Every citation at M2 and M4 is "file path + chunk id + line range" (docs/PRD.md
§4.3), so a chunker with correct text and wrong lines is worse than useless — it
cites confidently and points at the wrong code.
"""

from pathlib import Path

from app.ingestion.chunker import Chunk, LanguageAwareChunker, embedding_text
from app.ingestion.walker import SourceFile

SOURCE = '''def alpha() -> int:
    """First."""
    return 1


def beta() -> int:
    """Second."""
    return 2


def gamma() -> int:
    """Third."""
    return 3
'''


def source_file(name: str = "app/calc.py", language: str = "python") -> SourceFile:
    return SourceFile(path=Path(name), relative_path=name, language=language)


def test_produces_at_least_one_chunk() -> None:
    chunks = LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), SOURCE)
    assert len(chunks) >= 1


def test_line_numbers_locate_the_chunk_in_the_original() -> None:
    """The load-bearing assertion. Slice the file by the chunk's own line range and
    the chunk's first line must be in it."""
    lines = SOURCE.splitlines()
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)

    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)
        window = "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert chunk.text.strip().splitlines()[0] in window


def test_chunk_indexes_are_sequential_from_zero() -> None:
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_every_chunk_carries_the_file_path_and_language() -> None:
    chunks = LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), SOURCE)
    assert all(chunk.file_path == "app/calc.py" for chunk in chunks)
    assert all(chunk.language == "python" for chunk in chunks)


def test_a_symbol_is_captured_when_one_is_visible() -> None:
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)
    assert any(chunk.symbol is not None for chunk in chunks)


def test_an_unknown_language_still_chunks() -> None:
    """`text` must not crash the splitter — the walker emits it for anything unmapped."""
    chunks = LanguageAwareChunker(chunk_size=50, chunk_overlap=0).split(
        source_file("notes.rst", "text"), "line one\nline two\nline three\n"
    )
    assert len(chunks) >= 1


def test_an_empty_file_produces_no_chunks() -> None:
    assert LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), "") == []


def test_embedding_text_prepends_path_and_symbol() -> None:
    """A bare function body embeds as generic code; the header makes it *this*
    project's code. Cheap, and one of the highest-return changes in a RAG pipeline."""
    chunk = Chunk(
        file_path="backend/app/core/repo_url.py",
        start_line=10,
        end_line=20,
        language="python",
        symbol="validate_repo_url",
        chunk_index=0,
        text="return ValidatedRepoUrl(...)",
    )
    prepared = embedding_text(chunk)

    assert "backend/app/core/repo_url.py" in prepared
    assert "validate_repo_url" in prepared
    assert prepared.endswith(chunk.text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.chunker'`

- [ ] **Step 3: Write the chunker**

Create `backend/app/ingestion/chunker.py`:

```python
"""Splitting source files into embeddable chunks.

LangChain's language-aware splitter, behind a protocol. Its known weakness — the
separators have no model of nesting, so a function longer than `chunk_size` is cut
mid-body — is accepted at M1 and is the first thing M5's eval harness should be
pointed at. AST-aware chunking via tree-sitter is the identified upgrade path.

The line numbers below are not decoration: `docs/PRD.md` §4.3 defines a citation as
file path plus chunk id plus line range, so every answer M2 gives depends on them.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app.ingestion.walker import SourceFile

# LangChain's `Language` enum does not cover everything the walker detects.
LANGCHAIN_LANGUAGES = {
    "python": Language.PYTHON, "typescript": Language.TS, "javascript": Language.JS,
    "go": Language.GO, "rust": Language.RUST, "java": Language.JAVA,
    "kotlin": Language.KOTLIN, "ruby": Language.RUBY, "php": Language.PHP,
    "csharp": Language.CSHARP, "c": Language.C, "cpp": Language.CPP,
    "swift": Language.SWIFT, "scala": Language.SCALA, "html": Language.HTML,
    "markdown": Language.MARKDOWN,
}

# Best-effort enclosing-symbol capture. A miss yields None, which is fine — the
# symbol is a retrieval hint, never a correctness input.
SYMBOL_PATTERN = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|func|function|fn|type|interface|struct)\s+([A-Za-z_]\w*)",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One embeddable span of a source file."""

    file_path: str
    start_line: int
    end_line: int
    language: str
    symbol: str | None
    chunk_index: int
    text: str


class Chunker(Protocol):
    """Splits one file into chunks. Swapping this is how M5 measures chunking."""

    def split(self, file: SourceFile, source: str) -> list[Chunk]:
        """Split `source` into chunks carrying real line ranges."""
        ...


class LanguageAwareChunker:
    """LangChain's separator-based splitter, with line numbers recovered."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _splitter(self, language: str) -> RecursiveCharacterTextSplitter:
        """A splitter tuned to the language, or a generic one when unmapped."""
        mapped = LANGCHAIN_LANGUAGES.get(language)
        if mapped is None:
            return RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
            )
        return RecursiveCharacterTextSplitter.from_language(
            language=mapped, chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )

    def split(self, file: SourceFile, source: str) -> list[Chunk]:
        """Split a file, recovering each chunk's line range from its character offset.

        The splitter works in characters, so the offset is mapped back to a line by
        counting newlines before it. Searching from `cursor` rather than from zero
        keeps a repeated chunk body from resolving to the first occurrence.
        """
        if not source.strip():
            return []

        pieces = [piece for piece in self._splitter(file.language).split_text(source) if piece.strip()]

        chunks: list[Chunk] = []
        cursor = 0
        for index, piece in enumerate(pieces):
            offset = source.find(piece, cursor)
            if offset == -1:
                offset = cursor
            cursor = offset + len(piece)

            start_line = source.count("\n", 0, offset) + 1
            end_line = start_line + piece.count("\n")

            match = SYMBOL_PATTERN.search(piece)
            chunks.append(
                Chunk(
                    file_path=file.relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=file.language,
                    symbol=match.group(1) if match else None,
                    chunk_index=index,
                    text=piece,
                )
            )
        return chunks


def embedding_text(chunk: Chunk) -> str:
    """The text actually handed to the embedder.

    A bare `validate()` body embeds as generic validation code; the same chunk headed
    with its path and symbol embeds as *this* project's URL validation. A few tokens
    per chunk for a large retrieval gain.
    """
    header = f"# {chunk.file_path}"
    if chunk.symbol:
        header = f"{header} — {chunk.symbol}"
    return f"{header}\n{chunk.text}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_chunker.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/chunker.py backend/tests/test_chunker.py
git commit -m "feat(ingestion): add the language-aware chunker"
```

---

### Task 13: The embedder adapter

**Files:**
- Create: `backend/app/ingestion/embedder/__init__.py`, `ollama.py`, `openai.py`, `voyage.py`
- Test: `backend/tests/test_embedder.py`

**Interfaces:**
- Consumes: `Settings.embedding_*`
- Produces: `Embedder` protocol (`model_id: str`, `dimensions: int`, `async def embed_documents(texts: list[str]) -> list[list[float]]`, `async def embed_query(text: str) -> list[float]`); `OllamaEmbedder`, `OpenAIEmbedder`, `VoyageEmbedder`; `def build_embedder(settings: Settings) -> Embedder`; `async def probe_dimensions(embedder: Embedder) -> int`; `FakeEmbedder(dimensions: int)` for tests

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_embedder.py`:

```python
"""Provider selection, task prefixes, and error classification."""

import httpx
import pytest

from app.config import Settings
from app.ingestion.embedder import FakeEmbedder, build_embedder, probe_dimensions
from app.ingestion.embedder.ollama import OllamaEmbedder
from app.ingestion.embedder.openai import OpenAIEmbedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError


def settings_for(provider: str) -> Settings:
    return Settings(
        embedding_provider=provider,  # type: ignore[arg-type]  # narrowed by the Literal at runtime
        embedding_model="test-model",
        embedding_base_url="http://embed.test",
        embedding_api_key="key",
    )


def test_the_factory_selects_by_provider() -> None:
    assert isinstance(build_embedder(settings_for("ollama")), OllamaEmbedder)
    assert isinstance(build_embedder(settings_for("openai")), OpenAIEmbedder)


async def test_documents_and_queries_use_different_prefixes() -> None:
    """nomic and voyage require a task prefix. Using the wrong one degrades
    retrieval silently — no error, just worse answers — so it is encoded in the
    interface rather than left to a caller."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.extend(request.read().decode().split('"input"')[1:])
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    transport = httpx.MockTransport(handler)
    embedder = OllamaEmbedder(
        base_url="http://embed.test", model="nomic-embed-text", transport=transport
    )

    await embedder.embed_documents(["some code"])
    await embedder.embed_query("some question")

    assert "search_document" in seen[0]
    assert "search_query" in seen[1]


async def test_a_server_error_is_retryable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))
    embedder = OllamaEmbedder(base_url="http://e.test", model="m", transport=transport)

    with pytest.raises(RetryableIngestionError):
        await embedder.embed_documents(["x"])


async def test_an_auth_failure_is_terminal() -> None:
    """A bad API key will still be bad in ten minutes."""
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="unauthorized"))
    embedder = OpenAIEmbedder(
        base_url="http://e.test", model="m", api_key="bad", transport=transport
    )

    with pytest.raises(TerminalIngestionError):
        await embedder.embed_documents(["x"])


async def test_dimensions_are_probed_not_declared() -> None:
    """A number kept in sync by hand is a number that will eventually be wrong."""
    assert await probe_dimensions(FakeEmbedder(dimensions=768)) == 768
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_embedder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.embedder'`

- [ ] **Step 3: Write the protocol, factory, and fake**

Create `backend/app/ingestion/embedder/__init__.py`:

```python
"""Turning text into vectors, from whichever provider the instance is configured for.

Two methods rather than one, deliberately: `nomic-embed-text` and `voyage-code-*`
require task prefixes (`search_document:` versus `search_query:`), and using the
wrong one degrades retrieval with no error at all. Encoding the distinction in the
interface means an implementation cannot forget it.
"""

from typing import Protocol

from app.config import Settings


class Embedder(Protocol):
    """A source of embeddings for one configured model."""

    model_id: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content. Uses the document task prefix where required."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Uses the query task prefix where required."""
        ...


class FakeEmbedder:
    """Deterministic test double. Vectors are meaningless but correctly shaped."""

    def __init__(self, *, dimensions: int = 8, model_id: str = "fake") -> None:
        self.dimensions = dimensions
        self.model_id = model_id

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, derived from its length so results are stable."""
        return [[float((len(text) + i) % 10) / 10 for i in range(self.dimensions)] for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """A single vector, same derivation."""
        return (await self.embed_documents([text]))[0]


def build_embedder(settings: Settings) -> Embedder:
    """The embedder this instance is configured to use.

    Imports are local so an instance using a hosted provider does not import the
    others, and a broken optional dependency cannot break an unrelated deployment.
    """
    if settings.embedding_provider == "ollama":
        from app.ingestion.embedder.ollama import OllamaEmbedder

        return OllamaEmbedder(base_url=settings.embedding_base_url, model=settings.embedding_model)
    if settings.embedding_provider == "openai":
        from app.ingestion.embedder.openai import OpenAIEmbedder

        return OpenAIEmbedder(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key or "",
        )
    from app.ingestion.embedder.voyage import VoyageEmbedder

    return VoyageEmbedder(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key or "",
    )


async def probe_dimensions(embedder: Embedder) -> int:
    """Ask the model how wide its vectors are, by embedding one fixed string.

    Probed rather than configured: a declared dimension is a second source of truth
    that drifts the moment someone changes the model and forgets the number. The
    result names the Qdrant collection, so being wrong is not a small mistake.
    """
    vector = await embedder.embed_query("dimension probe")
    return len(vector)
```

- [ ] **Step 4: Write the three provider implementations**

Create `backend/app/ingestion/embedder/ollama.py`:

```python
"""Ollama's embedding endpoint."""

import httpx

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
TIMEOUT_SECONDS = 120.0


class OllamaEmbedder:
    """Embeddings from a local Ollama server."""

    def __init__(
        self, *, base_url: str, model: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.model_id = model
        self.dimensions = 0  # set by probe_dimensions at worker startup
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def _post(self, texts: list[str]) -> list[list[float]]:
        """One batched call, with failures classified for the retry chain."""
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/api/embed", json={"model": self.model_id, "input": texts}
                )
            except httpx.HTTPError as error:
                raise RetryableIngestionError(f"Embedding request failed: {error}") from error

        if response.status_code in (401, 403):
            raise TerminalIngestionError("Embedding provider rejected the credentials.")
        if response.status_code >= 400:
            raise RetryableIngestionError(
                f"Embedding provider returned {response.status_code}."
            )
        return response.json()["embeddings"]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content."""
        return await self._post([f"{DOCUMENT_PREFIX}{text}" for text in texts])

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        return (await self._post([f"{QUERY_PREFIX}{text}"]))[0]
```

Create `backend/app/ingestion/embedder/openai.py` with the same structure, posting to `{base_url}/v1/embeddings` with `{"model": ..., "input": texts}`, an `Authorization: Bearer` header, and reading `[item["embedding"] for item in response.json()["data"]]`. OpenAI models take **no** task prefix, so `embed_documents` and `embed_query` send the text unchanged — say so in a comment, because the asymmetry with Ollama is exactly the kind of thing a later reader "tidies up".

Create `backend/app/ingestion/embedder/voyage.py` posting to `{base_url}/v1/embeddings` with `{"model": ..., "input": texts, "input_type": "document"}` and `"query"` respectively — Voyage takes its task hint as a parameter rather than a text prefix.

Both classify status codes identically: 401/403 terminal, anything else ≥400 retryable, transport errors retryable.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_embedder.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/embedder/ backend/tests/test_embedder.py
git commit -m "feat(ingestion): add the pluggable embedder adapter"
```

---

### Task 14: The Qdrant vector store

**Files:**
- Create: `backend/app/ingestion/vector_store.py`
- Test: `backend/tests/test_vector_store.py`

**Interfaces:**
- Consumes: `Chunk`, `Embedder`
- Produces: `def collection_name(*, provider: str, model: str, dimensions: int) -> str`; `def point_id(project_id: uuid.UUID, file_path: str, chunk_index: int) -> str`; `VectorStore` protocol; `QdrantVectorStore(url: str, collection: str, dimensions: int)` with `async def ensure_collection() -> None`, `async def upsert(*, project_id, generation, chunks, vectors, commit_sha) -> None`, `async def delete_generation(*, project_id, generation) -> None`, `async def delete_project(project_id) -> None`; `InMemoryVectorStore` for tests

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_vector_store.py`:

```python
"""Collection naming, point identity, and payload contents."""

import uuid

from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore, collection_name, point_id


def chunk(index: int = 0, path: str = "app/main.py") -> Chunk:
    return Chunk(
        file_path=path,
        start_line=1,
        end_line=5,
        language="python",
        symbol="main",
        chunk_index=index,
        text="def main() -> None:\n    pass\n",
    )


def test_collection_name_encodes_provider_model_and_dimensions() -> None:
    """A collection's vector size is fixed at creation, so switching provider must
    target a different collection rather than corrupt the existing one."""
    assert (
        collection_name(provider="ollama", model="nomic-embed-text", dimensions=768)
        == "code_chunks__ollama__nomic_embed_text__768"
    )
    assert (
        collection_name(provider="openai", model="text-embedding-3-small", dimensions=1536)
        == "code_chunks__openai__text_embedding_3_small__1536"
    )


def test_point_ids_are_deterministic() -> None:
    """A rewrite of the same chunk overwrites rather than duplicating."""
    project = uuid.uuid4()
    assert point_id(project, "app/main.py", 0) == point_id(project, "app/main.py", 0)
    assert point_id(project, "app/main.py", 0) != point_id(project, "app/main.py", 1)
    assert point_id(project, "app/main.py", 0) != point_id(uuid.uuid4(), "app/main.py", 0)


async def test_upsert_stores_the_chunk_text_in_the_payload() -> None:
    """The working copy is deleted after indexing (docs/PRD.md §4.1), so Qdrant is
    the system of record for code content. Without the text, M2 has nothing to
    inject into a prompt."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()

    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk()],
        vectors=[[0.1, 0.2, 0.3, 0.4]],
        commit_sha="a" * 40,
    )

    payload = store.points[0]["payload"]
    assert payload["content"] == "def main() -> None:\n    pass\n"
    assert payload["project_id"] == str(project)
    assert payload["generation"] == 1
    assert payload["file_path"] == "app/main.py"
    assert payload["start_line"] == 1
    assert payload["end_line"] == 5
    assert payload["commit_sha"] == "a" * 40


async def test_delete_generation_leaves_other_generations_alone() -> None:
    """The generation swap depends on this: the old set survives until the new one
    is fully written."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()

    await store.upsert(
        project_id=project, generation=1, chunks=[chunk(0)], vectors=[[0.1] * 4], commit_sha="a" * 40
    )
    await store.upsert(
        project_id=project, generation=2, chunks=[chunk(0)], vectors=[[0.2] * 4], commit_sha="b" * 40
    )

    await store.delete_generation(project_id=project, generation=1)

    assert [point["payload"]["generation"] for point in store.points] == [2]


async def test_delete_project_removes_every_generation() -> None:
    """docs/PRD.md §5.1: the Postgres row soft-deletes, the points hard-delete."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()
    other = uuid.uuid4()

    await store.upsert(
        project_id=project, generation=1, chunks=[chunk(0)], vectors=[[0.1] * 4], commit_sha="a" * 40
    )
    await store.upsert(
        project_id=project, generation=2, chunks=[chunk(0)], vectors=[[0.2] * 4], commit_sha="b" * 40
    )
    await store.upsert(
        project_id=other, generation=1, chunks=[chunk(0)], vectors=[[0.3] * 4], commit_sha="c" * 40
    )

    await store.delete_project(project)

    assert [point["payload"]["project_id"] for point in store.points] == [str(other)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_vector_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.vector_store'`

- [ ] **Step 3: Write the vector store**

Create `backend/app/ingestion/vector_store.py`:

```python
"""Writing chunks to Qdrant.

Two things here are load-bearing and easy to get wrong:

1. **The collection name carries the model.** A collection's vector size is fixed at
   creation — nomic-embed-text is 768, text-embedding-3-small is 1536 — so a single
   fixed collection would make existing points unqueryable the moment someone flips
   EMBEDDING_PROVIDER, and Qdrant would reject the writes outright. Naming the
   collection for its contents makes a provider switch target a *different*
   collection instead.
2. **The payload holds the chunk text.** `docs/PRD.md` §4.1 deletes the working copy
   after indexing, so there is no file to re-read at query time. Qdrant is the system
   of record for code content, not merely an index over it.
"""

import re
import uuid
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models

from app.ingestion.chunker import Chunk
from app.ingestion.errors import RetryableIngestionError

COLLECTION_PREFIX = "code_chunks"
# Qdrant collection names allow a narrow character set; model ids do not respect it.
_UNSAFE = re.compile(r"[^a-z0-9]+")


def collection_name(*, provider: str, model: str, dimensions: int) -> str:
    """The collection holding vectors from this exact provider, model, and width."""
    safe_provider = _UNSAFE.sub("_", provider.lower()).strip("_")
    safe_model = _UNSAFE.sub("_", model.lower()).strip("_")
    return f"{COLLECTION_PREFIX}__{safe_provider}__{safe_model}__{dimensions}"


def point_id(project_id: uuid.UUID, file_path: str, chunk_index: int) -> str:
    """A stable id for one chunk.

    Deterministic so re-indexing the same chunk overwrites its point rather than
    accumulating a duplicate beside it.
    """
    return str(uuid.uuid5(project_id, f"{file_path}:{chunk_index}"))


def _payload(
    *, project_id: uuid.UUID, generation: int, chunk: Chunk, commit_sha: str
) -> dict[str, Any]:
    """Everything M2 needs to build a citation and a prompt, with no file on disk."""
    return {
        "project_id": str(project_id),
        "generation": generation,
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "language": chunk.language,
        "symbol": chunk.symbol,
        "chunk_index": chunk.chunk_index,
        "commit_sha": commit_sha,
        "content": chunk.text,
    }


class VectorStore(Protocol):
    """Where embedded chunks live."""

    async def ensure_collection(self) -> None:
        """Create the collection and its payload index if absent."""
        ...

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Write one batch of chunks under `generation`."""
        ...

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop one generation's points for a project."""
        ...

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Drop every point for a project, across all generations."""
        ...


class QdrantVectorStore:
    """The real store."""

    def __init__(self, *, url: str, collection: str, dimensions: int) -> None:
        self.collection = collection
        self.dimensions = dimensions
        self._client = AsyncQdrantClient(url=url)

    async def ensure_collection(self) -> None:
        """Create the collection and the `project_id` payload index if absent.

        The payload index is not optional: filtering without one degrades to a scan
        as the collection grows, and every M2 query filters by project.
        """
        try:
            if not await self._client.collection_exists(self.collection):
                await self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.dimensions, distance=models.Distance.COSINE
                    ),
                )
            await self._client.create_payload_index(
                collection_name=self.collection,
                field_name="project_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as error:  # noqa: BLE001 - any client failure is retryable here
            raise RetryableIngestionError(f"Qdrant is unavailable: {error}") from error

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Write one batch of chunks under `generation`."""
        points = [
            models.PointStruct(
                id=point_id(project_id, chunk.file_path, chunk.chunk_index),
                vector=vector,
                payload=_payload(
                    project_id=project_id, generation=generation, chunk=chunk, commit_sha=commit_sha
                ),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        except Exception as error:  # noqa: BLE001 - any client failure is retryable here
            raise RetryableIngestionError(f"Qdrant upsert failed: {error}") from error

    async def _delete_where(self, conditions: list[models.FieldCondition]) -> None:
        """Delete every point matching all conditions."""
        try:
            await self._client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=list(conditions))
                ),
                wait=True,
            )
        except Exception as error:  # noqa: BLE001 - any client failure is retryable here
            raise RetryableIngestionError(f"Qdrant delete failed: {error}") from error

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop the superseded generation once the new one is fully written."""
        await self._delete_where(
            [
                models.FieldCondition(
                    key="project_id", match=models.MatchValue(value=str(project_id))
                ),
                models.FieldCondition(
                    key="generation", match=models.MatchValue(value=generation)
                ),
            ]
        )

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Hard-delete every point for a project (`docs/PRD.md` §5.1)."""
        await self._delete_where(
            [
                models.FieldCondition(
                    key="project_id", match=models.MatchValue(value=str(project_id))
                )
            ]
        )


class InMemoryVectorStore:
    """Test double. `points` is a list of `{"id": ..., "vector": ..., "payload": ...}`."""

    def __init__(self, *, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.collection = "in-memory"
        self.points: list[dict[str, Any]] = []
        self.ensured = False

    async def ensure_collection(self) -> None:
        """Record that the caller asked."""
        self.ensured = True

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Append points, replacing any with the same id."""
        for chunk, vector in zip(chunks, vectors, strict=True):
            identifier = point_id(project_id, chunk.file_path, chunk.chunk_index)
            payload = _payload(
                project_id=project_id, generation=generation, chunk=chunk, commit_sha=commit_sha
            )
            self.points = [
                point
                for point in self.points
                if not (point["id"] == identifier and point["payload"]["generation"] == generation)
            ]
            self.points.append({"id": identifier, "vector": vector, "payload": payload})

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop one generation for one project."""
        self.points = [
            point
            for point in self.points
            if not (
                point["payload"]["project_id"] == str(project_id)
                and point["payload"]["generation"] == generation
            )
        ]

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Drop every generation for one project."""
        self.points = [
            point for point in self.points if point["payload"]["project_id"] != str(project_id)
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_vector_store.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/vector_store.py backend/tests/test_vector_store.py
git commit -m "feat(ingestion): add the Qdrant vector store with model-named collections"
```

---

### Task 15: The pipeline

Where the stages become one run, and where the generation swap and status transitions live.

**Files:**
- Create: `backend/app/ingestion/pipeline.py`
- Modify: `backend/app/services/project.py` (delete now clears vectors)
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 10–14, `ProjectRepository`, `SecretBox`
- Produces: `IngestionPipeline(session, settings, *, embedder, store, chunker, clone_fn=clone)` with `async def run(*, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pipeline.py`:

```python
"""One indexing run, end to end, with the network stubbed out."""

import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project


def make_repo(tmp_path: Path) -> Path:
    """A tiny real repository the fake cloner hands back."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def main() -> None:\n    print('hi')\n")
    (root / "util.py").write_text("def helper() -> int:\n    return 42\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def pipeline_for(
    session: AsyncSession, store: InMemoryVectorStore, repo: Path, *, fail_with: Exception | None = None
) -> IngestionPipeline:
    async def fake_clone(validated, **kwargs) -> CloneResult:  # noqa: ANN001, ANN003 - test stub
        if fail_with is not None:
            raise fail_with
        return CloneResult(path=repo, commit_sha="a" * 40)

    return IngestionPipeline(
        session,
        get_settings(),
        embedder=FakeEmbedder(dimensions=4),
        store=store,
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=fake_clone,
    )


async def test_a_successful_run_reaches_ready(db_session: AsyncSession, tmp_path: Path) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    store = InMemoryVectorStore(dimensions=4)
    job_id = uuid.uuid4()

    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w0", lease_seconds=300
    )
    await db_session.commit()

    await pipeline_for(db_session, store, make_repo(tmp_path)).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    await db_session.refresh(project)
    assert project.status == ProjectStatus.READY
    assert project.last_indexed_commit == "a" * 40
    assert project.file_count == 2
    assert project.chunk_count == len(store.points)
    assert project.lease_owner is None
    assert store.points


async def test_the_working_copy_is_deleted_after_indexing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """docs/PRD.md §4.1: /data/repos is scratch, not a persistent volume."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    repo = make_repo(tmp_path)
    job_id = uuid.uuid4()

    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w0", lease_seconds=300
    )
    await db_session.commit()

    await pipeline_for(db_session, InMemoryVectorStore(dimensions=4), repo).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    assert not repo.exists()


async def test_a_reindex_swaps_generations_without_losing_the_old_index(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The old generation survives until the new one is fully written."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    store = InMemoryVectorStore(dimensions=4)
    repository = ProjectRepository(db_session)

    for _ in range(2):
        job_id = uuid.uuid4()
        await repository.claim(
            project_id=project.id, job_id=job_id, worker_id="w0", lease_seconds=300
        )
        await db_session.commit()
        await pipeline_for(db_session, store, make_repo(tmp_path)).run(
            project_id=project.id, job_id=job_id, worker_id="w0"
        )

    await db_session.refresh(project)
    assert project.active_generation == 2
    assert project.reindex_in_progress is False
    # Only the current generation survives the swap.
    assert {point["payload"]["generation"] for point in store.points} == {2}


async def test_a_terminal_failure_marks_the_project_failed(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = uuid.uuid4()

    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w0", lease_seconds=300
    )
    await db_session.commit()

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=TerminalIngestionError("Remote branch nope not found in upstream origin"),
    )

    with pytest.raises(TerminalIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED
    assert project.error is not None
    assert project.lease_owner is None


async def test_a_retryable_failure_leaves_the_project_claimable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The consumer will re-enqueue it, so the pipeline must not mark it failed."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = uuid.uuid4()

    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w0", lease_seconds=300
    )
    await db_session.commit()

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=RetryableIngestionError("connection reset"),
    )

    with pytest.raises(RetryableIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status != ProjectStatus.FAILED
    assert project.lease_owner is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.pipeline'`

- [ ] **Step 3: Write the pipeline**

Create `backend/app/ingestion/pipeline.py`:

```python
"""One indexing run: clone → walk → chunk → embed → upsert → swap.

The generation swap is the part to read carefully. New points are written under
`active_generation + 1`, the project's pointer flips, and only then is the old
generation deleted. Two consequences, both intended: a project stays queryable
throughout a reindex, and a reindex that fails part-way leaves the working index
completely intact. Deleting first — the obvious implementation — destroys a working
index whenever embedding fails.
"""

import asyncio
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.crypto import SecretBox, scrub
from app.core.repo_url import ValidatedRepoUrl, validate_repo_url
from app.ingestion.chunker import Chunk, Chunker, embedding_text
from app.ingestion.cloner import CloneResult, clone
from app.ingestion.embedder import Embedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStore
from app.ingestion.walker import walk
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60

CloneFn = Callable[..., Awaitable[CloneResult]]


class IngestionPipeline:
    """Runs one job for one project."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        embedder: Embedder,
        store: VectorStore,
        chunker: Chunker,
        clone_fn: CloneFn = clone,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.chunker = chunker
        self.clone_fn = clone_fn
        self.repository = ProjectRepository(session)

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Index a project the caller has already claimed.

        Raises the ingestion error it failed with, so the consumer can decide
        between the retry chain and the DLQ. A terminal failure is recorded on the
        project first; a retryable one is not, because the job is coming back.
        """
        project = await self.repository.get(project_id)
        if project is None:
            logger.warning("project %s vanished before indexing", project_id)
            return

        pat = None
        if project.encrypted_pat:
            pat = SecretBox(self.settings.pat_encryption_key).decrypt(project.encrypted_pat)

        destination = self.settings.repo_scratch_dir / str(project_id)
        heartbeat = asyncio.create_task(self._renew_lease(project_id, worker_id))

        try:
            result = await self._clone(project.repo_url, project.branch, destination, pat)
            await self._set_status(project_id, ProjectStatus.INDEXING, project.status)

            generation = project.active_generation + 1
            file_count, chunk_count = await self._index(
                project_id=project_id, generation=generation, root=result.path, commit_sha=result.commit_sha
            )

            # Flip the pointer, *then* drop the superseded points.
            await self.repository.release(
                project_id=project_id,
                job_id=job_id,
                status=ProjectStatus.READY,
                error=None,
                last_indexed_commit=result.commit_sha,
                file_count=file_count,
                chunk_count=chunk_count,
                active_generation=generation,
                embedding_collection=self.store.collection,
                embedding_model=self.embedder.model_id,
            )
            await self.session.commit()

            if project.active_generation:
                await self.store.delete_generation(
                    project_id=project_id, generation=project.active_generation
                )

        except TerminalIngestionError as error:
            await self.repository.release(
                project_id=project_id,
                job_id=job_id,
                status=ProjectStatus.FAILED,
                error=scrub(str(error), pat)[:4000],
            )
            await self.session.commit()
            raise
        except RetryableIngestionError:
            # Drop the lease but leave the status alone — the job is coming back,
            # and marking it `failed` would lie to anyone reading the list.
            await self.repository.renew_lease(
                project_id=project_id, worker_id=worker_id, lease_seconds=-1
            )
            await self.session.commit()
            raise
        finally:
            heartbeat.cancel()
            # docs/PRD.md §4.1: the working copy is deleted whether we succeeded or
            # failed terminally. /data/repos is scratch space.
            shutil.rmtree(destination, ignore_errors=True)

    async def _clone(
        self, repo_url: str, branch: str, destination: Path, pat: str | None
    ) -> CloneResult:
        """Validate and clone, pinning git to the address that was validated."""
        validated: ValidatedRepoUrl = await validate_repo_url(
            repo_url, allowlist=self.settings.repo_host_allowlist
        )
        return await self.clone_fn(
            validated,
            branch=branch,
            destination=destination,
            pat=pat,
            timeout_seconds=self.settings.clone_timeout_seconds,
            max_bytes=self.settings.repo_max_size_mb * 1024 * 1024,
        )

    async def _index(
        self, *, project_id: uuid.UUID, generation: int, root: Path, commit_sha: str
    ) -> tuple[int, int]:
        """Walk, chunk, embed, and upsert. Returns (file_count, chunk_count)."""
        await self.store.ensure_collection()

        file_count = 0
        chunk_count = 0
        batch: list[Chunk] = []

        for source_file in walk(root, max_file_bytes=self.settings.max_indexed_file_bytes):
            file_count += 1
            try:
                source = source_file.path.read_text(errors="replace")
            except OSError:
                continue

            batch.extend(self.chunker.split(source_file, source))
            while len(batch) >= self.settings.embedding_batch_size:
                head, batch = batch[: self.settings.embedding_batch_size], batch[self.settings.embedding_batch_size :]
                await self._flush(project_id, generation, head, commit_sha)
                chunk_count += len(head)

        if batch:
            await self._flush(project_id, generation, batch, commit_sha)
            chunk_count += len(batch)

        return file_count, chunk_count

    async def _flush(
        self, project_id: uuid.UUID, generation: int, chunks: list[Chunk], commit_sha: str
    ) -> None:
        """Embed one batch and write it."""
        vectors = await self.embedder.embed_documents([embedding_text(chunk) for chunk in chunks])
        await self.store.upsert(
            project_id=project_id,
            generation=generation,
            chunks=chunks,
            vectors=vectors,
            commit_sha=commit_sha,
        )

    async def _set_status(
        self, project_id: uuid.UUID, new_status: ProjectStatus, current_status: str
    ) -> None:
        """Advance a first index through its states.

        A reindex is skipped deliberately: it stays `ready` so the project remains
        queryable, and `reindex_in_progress` carries the fact that a run is active.
        """
        if current_status == ProjectStatus.READY.value:
            return
        await self.repository.set_status(project_id=project_id, status=new_status)
        await self.session.commit()

    async def _renew_lease(self, project_id: uuid.UUID, worker_id: str) -> None:
        """Extend the lease while the job runs.

        This is what lets the expiry be five minutes rather than thirty: a slow but
        healthy index keeps extending, while a crashed worker releases its project
        for reclaim quickly.
        """
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with self.session.begin_nested():
                await self.repository.renew_lease(
                    project_id=project_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
```

- [ ] **Step 4: Add the missing repository method**

`_set_status` calls `ProjectRepository.set_status`, which does not exist yet. Add it beside `release`:

```python
    async def set_status(self, *, project_id: uuid.UUID, status: ProjectStatus) -> None:
        """Advance a project's status without touching its lease."""
        now = datetime.now(UTC)
        await self.session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(status=status.value, updated_at=now)
        )
```

- [ ] **Step 5: Wire vector deletion into project deletion**

`docs/PRD.md` §5.1 requires the Postgres soft delete and the Qdrant hard delete to happen in the **same operation**. In `ProjectService.delete`, after `soft_delete` and before the commit, call `await self.store.delete_project(project.id)` — which means `ProjectService` now takes a `VectorStore`. Add it as a constructor argument, build it in `get_project_service` from `Settings`, and pass `InMemoryVectorStore()` in the service tests.

Add a test to `tests/test_project_service.py` proving it:

```python
async def test_delete_hard_deletes_the_vectors(db_session: AsyncSession) -> None:
    """docs/PRD.md §5.1: vector points have no deleted_at, so they go for real."""
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()

    store = InMemoryVectorStore(dimensions=4)
    await store.upsert(
        project_id=project.id,
        generation=1,
        chunks=[Chunk("a.py", 1, 2, "python", None, 0, "x = 1")],
        vectors=[[0.1] * 4],
        commit_sha="a" * 40,
    )

    service = ProjectService(db_session, get_settings(), InMemoryIngestionQueue(), store=store)
    await service.delete(project.id, actor=actor_for(owner.id))

    assert store.points == []
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_pipeline.py tests/test_project_service.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite and the linter**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: PASS. Phase 3 is complete — the pipeline runs correctly when driven directly. Nothing calls it yet.

- [ ] **Step 8: Commit**

```bash
git add backend/app/ingestion/pipeline.py backend/app/repositories/project.py \
        backend/app/services/project.py backend/app/api/routes/projects.py \
        backend/tests/test_pipeline.py backend/tests/test_project_service.py
git commit -m "feat(ingestion): add the pipeline with generation-swap reindexing"
```

---

# Phase 4 — Kafka

### Task 16: The producer and the broker

**Files:**
- Create: `backend/app/queue/producer.py`
- Modify: `backend/app/main.py` (lifespan), `infra/docker-compose.yml`, `Makefile`
- Test: `backend/tests/test_producer.py`

**Interfaces:**
- Consumes: `IngestionMessage`, `ALL_TOPICS`, `Settings.kafka_*`
- Produces: `KafkaIngestionQueue(bootstrap_servers: str, topic: str)` with `async def start() -> None`, `async def stop() -> None`, `async def enqueue(message) -> None`, `async def produce_to(topic: str, message: IngestionMessage) -> None`; `async def ensure_topics(bootstrap_servers: str, partitions: int) -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_producer.py`:

```python
"""The producer's contract, with aiokafka stubbed.

The real broker is exercised by the integration test in Task 20.
"""

import uuid

import pytest

from app.queue.producer import KafkaIngestionQueue
from app.queue.topics import INGEST_TOPIC, IngestionMessage


class StubProducer:
    """Stands in for AIOKafkaProducer."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.sent.append((topic, value, key))


def message() -> IngestionMessage:
    return IngestionMessage(
        project_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=0,
        not_before_ms=0,
        original_topic=INGEST_TOPIC,
    )


async def test_enqueue_publishes_to_the_ingest_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubProducer()
    monkeypatch.setattr("app.queue.producer.AIOKafkaProducer", lambda **kwargs: stub)

    queue = KafkaIngestionQueue(bootstrap_servers="localhost:9092", topic=INGEST_TOPIC)
    await queue.start()
    sent = message()
    await queue.enqueue(sent)

    assert len(stub.sent) == 1
    topic, value, key = stub.sent[0]
    assert topic == INGEST_TOPIC
    assert IngestionMessage.from_bytes(value) == sent
    assert key == sent.key()


async def test_the_producer_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this a retried produce appends the message twice."""
    stub = StubProducer()
    monkeypatch.setattr("app.queue.producer.AIOKafkaProducer", lambda **kwargs: stub)

    await KafkaIngestionQueue(bootstrap_servers="localhost:9092", topic=INGEST_TOPIC).start()

    assert stub.kwargs["enable_idempotence"] is True
    assert stub.kwargs["acks"] == "all"


async def test_enqueue_before_start_is_a_programming_error() -> None:
    queue = KafkaIngestionQueue(bootstrap_servers="localhost:9092", topic=INGEST_TOPIC)
    with pytest.raises(RuntimeError, match="not started"):
        await queue.enqueue(message())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_producer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.queue.producer'`

- [ ] **Step 3: Write the producer**

Create `backend/app/queue/producer.py`:

```python
"""Publishing ingestion jobs to Kafka."""

import logging

from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from app.queue.topics import ALL_TOPICS, INGEST_TOPIC, IngestionMessage

logger = logging.getLogger(__name__)


class KafkaIngestionQueue:
    """The real queue. Started and stopped by the application lifespan."""

    def __init__(self, *, bootstrap_servers: str, topic: str = INGEST_TOPIC) -> None:
        self.topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Connect to the broker."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            # Without idempotence a retried produce appends the message twice, and
            # a duplicate job costs a wasted claim attempt on the worker side.
            enable_idempotence=True,
            acks="all",
        )
        await self._producer.start()

    async def stop(self) -> None:
        """Flush and disconnect."""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def enqueue(self, message: IngestionMessage) -> None:
        """Publish a job to the main ingest topic."""
        await self.produce_to(self.topic, message)

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        """Publish to a specific topic — used by the retry and DLQ paths."""
        if self._producer is None:
            raise RuntimeError("KafkaIngestionQueue is not started")
        await self._producer.send_and_wait(topic, value=message.to_bytes(), key=message.key())


async def ensure_topics(*, bootstrap_servers: str, partitions: int) -> None:
    """Create every topic the system uses, idempotently.

    Explicit rather than relying on broker auto-creation: auto-created topics get
    one partition, which would silently halve the ingestion concurrency cap that
    `docs/PRD.md` §4.1 sets at 2.
    """
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        topics = [
            # Replication factor 1: a single-broker cluster cannot do better, and
            # the source of truth for a project's state is Postgres regardless.
            NewTopic(name=name, num_partitions=partitions, replication_factor=1)
            for name in ALL_TOPICS
        ]
        try:
            await admin.create_topics(topics)
        except Exception as error:  # noqa: BLE001 - "already exists" is the normal path
            logger.info("topic creation skipped: %s", error)
    finally:
        await admin.close()
```

- [ ] **Step 4: Wire the producer into the app lifespan**

In `app/main.py`, add an `asynccontextmanager` lifespan that starts the producer, stashes it on `app.state.ingestion_queue`, ensures topics, and stops it on shutdown. Pass `lifespan=` to the `FastAPI(...)` constructor.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the Kafka producer's lifetime.

    On `app.state` rather than a module global so tests override the dependency
    (`get_ingestion_queue`) and never open a socket.
    """
    settings = get_settings()
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=settings.kafka_ingest_topic
    )
    await queue.start()
    app.state.ingestion_queue = queue
    try:
        yield
    finally:
        await queue.stop()
```

**Test-suite consequence:** existing tests build the app without a broker. Guard the lifespan so it is a no-op when `APP_ENV=test`, or the whole suite will hang trying to reach `localhost:9092`. Verify by running the full suite in Step 6.

- [ ] **Step 5: Add the Kafka service to Compose**

In `infra/docker-compose.yml`, add a single-broker KRaft service. It needs `KAFKA_PROCESS_ROLES=broker,controller`, a `CONTROLLER` listener in `KAFKA_LISTENERS` and `KAFKA_CONTROLLER_LISTENER_NAMES`, a `KAFKA_CONTROLLER_QUORUM_VOTERS` entry pointing at itself, a fixed `CLUSTER_ID`, and — critically — `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1`, `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1`, and `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1`. A single broker cannot satisfy the default replication factor of 3 and will fail to finish starting without these.

Give it a healthcheck along the lines of `kafka-broker-api-versions.sh --bootstrap-server localhost:9092`, a named volume for its log directory, and make `backend` depend on it with `condition: service_healthy`. Add the published port to the header comment's URL list — the header must match the services below.

Then validate: `cd infra && docker compose config --quiet`.

Add `docker-start-kafka` / `docker-stop-kafka` targets to the `Makefile` beside the existing per-service targets, and add `kafka` to whatever `make infra` starts.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_producer.py -v && uv run pytest`
Expected: PASS, and the full suite must not hang. If it hangs, the lifespan guard from Step 4 is missing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/queue/producer.py backend/app/main.py backend/tests/test_producer.py \
        infra/docker-compose.yml Makefile
git commit -m "feat(queue): add the Kafka producer, topic creation, and broker service"
```

---

### Task 17: The consumer loop

The pause-the-partition pattern is what makes long jobs survivable. Without it a rebalance fires mid-index and a second worker starts the same job.

**Files:**
- Create: `backend/app/queue/consumer.py`
- Test: `backend/tests/test_consumer.py`

**Interfaces:**
- Consumes: `IngestionMessage`, `next_destination`, `KafkaIngestionQueue`, `IngestionPipeline`, `TerminalIngestionError`, `RetryableIngestionError`
- Produces: `JobOutcome` (StrEnum: `COMPLETED`, `SKIPPED`, `RETRY_SCHEDULED`, `DEAD_LETTERED`); `async def handle_message(message, *, pipeline, repository, producer, worker_id, max_attempts, session) -> JobOutcome`; `IngestionConsumer(...)` with `async def run() -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_consumer.py`:

```python
"""Message handling: claim, run, and route the failure.

`handle_message` is separated from the polling loop precisely so it can be tested
without a broker — the loop itself is covered by the integration test in Task 20.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.project import ProjectStatus
from app.queue.consumer import JobOutcome, handle_message
from app.queue.topics import DLQ_TOPIC, INGEST_TOPIC, RETRY_TOPICS, IngestionMessage
from app.repositories.project import ProjectRepository
from tests.factories import create_project


class RecordingProducer:
    """Captures where a failed job was routed."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, IngestionMessage]] = []

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        self.sent.append((topic, message))


class StubPipeline:
    """Runs, or raises whatever it was handed."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.runs = 0

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        self.runs += 1
        if self.raises is not None:
            raise self.raises


def message_for(project_id: uuid.UUID, *, attempt: int = 0) -> IngestionMessage:
    return IngestionMessage(
        project_id=project_id,
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=0,
        original_topic=INGEST_TOPIC,
    )


async def test_a_claimed_job_runs(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    pipeline = StubPipeline()

    outcome = await handle_message(
        message_for(project.id),
        pipeline=pipeline,
        repository=ProjectRepository(db_session),
        producer=RecordingProducer(),
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.COMPLETED
    assert pipeline.runs == 1


async def test_a_job_held_by_another_worker_is_skipped(db_session: AsyncSession) -> None:
    """At-least-once delivery means duplicates. The lease, not the message, decides."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="other", lease_seconds=300
    )
    await db_session.commit()
    pipeline = StubPipeline()

    outcome = await handle_message(
        message_for(project.id),
        pipeline=pipeline,
        repository=repository,
        producer=RecordingProducer(),
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.SKIPPED
    assert pipeline.runs == 0


async def test_a_retryable_failure_goes_to_the_one_minute_topic(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    outcome = await handle_message(
        message_for(project.id, attempt=0),
        pipeline=StubPipeline(RetryableIngestionError("network")),
        repository=ProjectRepository(db_session),
        producer=producer,
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    topic, routed = producer.sent[0]
    assert topic == RETRY_TOPICS[0][0]
    assert routed.attempt == 1
    assert routed.not_before_ms > 0


async def test_a_terminal_failure_never_retries(db_session: AsyncSession) -> None:
    """Three attempts on a rejected URL is waste, and parks the project misleadingly."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    outcome = await handle_message(
        message_for(project.id),
        pipeline=StubPipeline(TerminalIngestionError("branch not found")),
        repository=ProjectRepository(db_session),
        producer=producer,
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.COMPLETED
    assert producer.sent == []


async def test_exhausted_attempts_go_to_the_dlq(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    outcome = await handle_message(
        message_for(project.id, attempt=2),
        pipeline=StubPipeline(RetryableIngestionError("still failing")),
        repository=ProjectRepository(db_session),
        producer=producer,
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.sent[0][0] == DLQ_TOPIC

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED


async def test_an_unexpected_error_retries_once_then_stops(db_session: AsyncSession) -> None:
    """A bug should not silently eat jobs, nor loop forever."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    first = await handle_message(
        message_for(project.id, attempt=0),
        pipeline=StubPipeline(ValueError("unexpected")),
        repository=ProjectRepository(db_session),
        producer=producer,
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )
    assert first is JobOutcome.RETRY_SCHEDULED

    second = await handle_message(
        message_for(project.id, attempt=1),
        pipeline=StubPipeline(ValueError("unexpected")),
        repository=ProjectRepository(db_session),
        producer=producer,
        worker_id="w0",
        max_attempts=3,
        session=db_session,
    )
    assert second is JobOutcome.DEAD_LETTERED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_consumer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.queue.consumer'`

- [ ] **Step 3: Write the consumer**

Create `backend/app/queue/consumer.py`:

```python
"""Consuming ingestion jobs.

Two things here are the difference between working and quietly corrupting a project.

**Pausing.** Kafka's group protocol treats a consumer that stops calling `poll()` as
dead, and `max.poll.interval.ms` defaults to five minutes — far less than indexing a
real repository takes. So the loop pauses the partition, runs the job as a task, and
keeps polling: a paused partition returns no records, the member stays alive, and no
rebalance fires. Raising `max.poll.interval.ms` instead would mean guessing at the
slowest repository anyone will ever index.

**Claiming.** Even with pausing, delivery is at-least-once. The claim in
`ProjectRepository` is the actual deduplication boundary; this module trusts it and
not the message.
"""

import asyncio
import logging
import time
import uuid
from enum import StrEnum
from typing import Protocol

from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.project import ProjectStatus
from app.queue.topics import DLQ_TOPIC, IngestionMessage, next_destination
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300
POLL_TIMEOUT_MS = 1000


class JobOutcome(StrEnum):
    """What happened to one message. Every value means "commit the offset"."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTERED = "dead_lettered"


class Pipeline(Protocol):
    """The unit of work a message triggers."""

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Index one project."""
        ...


class Producer(Protocol):
    """Somewhere to route a failed job."""

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        """Publish to a specific topic."""
        ...


async def handle_message(
    message: IngestionMessage,
    *,
    pipeline: Pipeline,
    repository: ProjectRepository,
    producer: Producer,
    worker_id: str,
    max_attempts: int,
    session: AsyncSession,
) -> JobOutcome:
    """Claim, run, and route one job.

    Separated from the polling loop so it is testable without a broker. Every return
    value means the offset should be committed — a message is never left uncommitted
    to be redelivered, because redelivery is exactly what the retry topics are for.
    """
    claimed = await repository.claim(
        project_id=message.project_id,
        job_id=message.job_id,
        worker_id=worker_id,
        lease_seconds=LEASE_SECONDS,
    )
    await session.commit()

    if not claimed:
        # Another worker holds a live lease, or this job already completed.
        logger.info("skipping project %s: not claimable", message.project_id)
        return JobOutcome.SKIPPED

    try:
        await pipeline.run(
            project_id=message.project_id, job_id=message.job_id, worker_id=worker_id
        )
    except TerminalIngestionError:
        # The pipeline already recorded `failed` and the reason on the project.
        logger.warning("project %s failed terminally", message.project_id)
        return JobOutcome.COMPLETED
    except RetryableIngestionError as error:
        return await _route_failure(
            message, producer=producer, repository=repository, session=session,
            max_attempts=max_attempts, reason=str(error),
        )
    except Exception as error:  # noqa: BLE001 - an unexpected bug still needs routing
        logger.exception("project %s raised an unexpected error", message.project_id)
        return await _route_failure(
            message, producer=producer, repository=repository, session=session,
            max_attempts=max_attempts, reason=f"Unexpected error: {error}",
        )

    return JobOutcome.COMPLETED


async def _route_failure(
    message: IngestionMessage,
    *,
    producer: Producer,
    repository: ProjectRepository,
    session: AsyncSession,
    max_attempts: int,
    reason: str,
) -> JobOutcome:
    """Send a failed job to the next retry topic, or to the DLQ if spent."""
    topic, delay_seconds = next_destination(attempt=message.attempt, max_attempts=max_attempts)
    forwarded = IngestionMessage(
        project_id=message.project_id,
        job_id=message.job_id,
        attempt=message.attempt + 1,
        not_before_ms=int(time.time() * 1000) + delay_seconds * 1000,
        original_topic=message.original_topic,
    )
    await producer.produce_to(topic, forwarded)

    if topic == DLQ_TOPIC:
        # Nothing else will pick this up, so the project must stop looking busy.
        await repository.release(
            project_id=message.project_id,
            job_id=message.job_id,
            status=ProjectStatus.FAILED,
            error=reason[:4000],
        )
        await session.commit()
        return JobOutcome.DEAD_LETTERED

    return JobOutcome.RETRY_SCHEDULED


class IngestionConsumer:
    """The polling loop for one worker."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: Producer,
        build_pipeline,  # noqa: ANN001 - a factory taking a session, typed at the call site
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.producer = producer
        self.build_pipeline = build_pipeline
        self.worker_id = worker_id

    async def run(self) -> None:
        """Poll, pause, process, commit, resume — forever."""
        consumer = AIOKafkaConsumer(
            self.settings.kafka_ingest_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_consumer_group,
            # The offset moves only after the work is done and durable.
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            while True:
                batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
                for partition, records in batches.items():
                    for record in records:
                        await self._process(consumer, partition, record)
        finally:
            await consumer.stop()

    async def _process(self, consumer: AIOKafkaConsumer, partition, record) -> None:  # noqa: ANN001 - aiokafka types
        """Run one record with its partition paused.

        Pausing is what keeps the member alive across a job far longer than
        `max.poll.interval.ms`: the loop keeps calling `getmany`, which returns
        nothing for a paused partition, so the broker never concludes we died.
        """
        message = IngestionMessage.from_bytes(record.value)
        consumer.pause(partition)
        try:
            job = asyncio.create_task(self._run_job(message))
            while not job.done():
                # Keep polling so the group protocol stays satisfied.
                await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS)
            await job
            await consumer.commit()
        finally:
            consumer.resume(partition)

    async def _run_job(self, message: IngestionMessage) -> JobOutcome:
        """One job, in its own session."""
        async with self.sessionmaker() as session:
            return await handle_message(
                message,
                pipeline=self.build_pipeline(session),
                repository=ProjectRepository(session),
                producer=self.producer,
                worker_id=self.worker_id,
                max_attempts=self.settings.kafka_max_attempts,
                session=session,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_consumer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/queue/consumer.py backend/tests/test_consumer.py
git commit -m "feat(queue): add the consumer with partition pausing and failure routing"
```

---

### Task 18: The retry consumer

**Files:**
- Create: `backend/app/queue/retry.py`
- Test: `backend/tests/test_retry.py`

**Interfaces:**
- Consumes: `IngestionMessage`, `RETRY_TOPICS`, `Producer`
- Produces: `def seconds_until_due(message: IngestionMessage, *, now_ms: int) -> float`; `RetryConsumer(settings, producer, topic)` with `async def run() -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_retry.py`:

```python
"""Waiting out a delay in a log that has no delay primitive."""

import uuid

from app.queue.retry import seconds_until_due
from app.queue.topics import INGEST_TOPIC, IngestionMessage


def message(not_before_ms: int) -> IngestionMessage:
    return IngestionMessage(
        project_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=1,
        not_before_ms=not_before_ms,
        original_topic=INGEST_TOPIC,
    )


def test_a_future_message_reports_the_remaining_wait() -> None:
    assert seconds_until_due(message(60_000), now_ms=0) == 60.0


def test_a_due_message_reports_zero() -> None:
    assert seconds_until_due(message(1_000), now_ms=5_000) == 0.0


def test_an_exactly_due_message_reports_zero() -> None:
    assert seconds_until_due(message(5_000), now_ms=5_000) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.queue.retry'`

- [ ] **Step 3: Write the retry consumer**

Create `backend/app/queue/retry.py`:

```python
"""Turning a fixed-delay topic into a delayed delivery.

Kafka has no delay primitive. The trick is that every message in a fixed-delay topic
was appended in time order, so the partition head is always the earliest-due message.
A consumer therefore reads the head, and if it is not yet due, **pauses the partition
and sleeps until it is** — it does not commit, does not seek past, and does not spin.

Getting this wrong is expensive in a specific way: a consumer that re-polls without
pausing burns a core doing nothing, and one that seeks past the message loses the job.
"""

import asyncio
import logging
import time

from aiokafka import AIOKafkaConsumer

from app.config import Settings
from app.queue.consumer import Producer
from app.queue.topics import IngestionMessage

logger = logging.getLogger(__name__)

POLL_TIMEOUT_MS = 1000


def seconds_until_due(message: IngestionMessage, *, now_ms: int) -> float:
    """How long to wait before this message may be re-produced. Never negative."""
    return max(0.0, (message.not_before_ms - now_ms) / 1000)


class RetryConsumer:
    """Drains one retry topic back into the main ingest topic, on schedule."""

    def __init__(self, *, settings: Settings, producer: Producer, topic: str) -> None:
        self.settings = settings
        self.producer = producer
        self.topic = topic

    async def run(self) -> None:
        """Poll, wait until due, re-produce, commit."""
        consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.settings.kafka_consumer_group}-{self.topic}",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            while True:
                batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
                for partition, records in batches.items():
                    for record in records:
                        await self._release(consumer, partition, record)
        finally:
            await consumer.stop()

    async def _release(self, consumer: AIOKafkaConsumer, partition, record) -> None:  # noqa: ANN001 - aiokafka types
        """Hold the message until it is due, then send it back to the main topic."""
        message = IngestionMessage.from_bytes(record.value)
        wait = seconds_until_due(message, now_ms=int(time.time() * 1000))

        if wait > 0:
            # Pause rather than spin: this partition has nothing runnable until the
            # head is due, and the head is always the earliest-due message.
            consumer.pause(partition)
            try:
                await asyncio.sleep(wait)
            finally:
                consumer.resume(partition)

        logger.info("re-queueing project %s (attempt %d)", message.project_id, message.attempt)
        await self.producer.produce_to(self.settings.kafka_ingest_topic, message)
        await consumer.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_retry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/queue/retry.py backend/tests/test_retry.py
git commit -m "feat(queue): add the delayed-retry topic consumer"
```

---

### Task 19: The worker entrypoint and the reconcile sweep

**Files:**
- Create: `backend/app/worker.py`
- Modify: `backend/app/repositories/refresh_token.py` (cleanup method)
- Test: `backend/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `IngestionConsumer`, `RetryConsumer`, `KafkaIngestionQueue`, `ProjectRepository.find_stranded`, `build_embedder`, `probe_dimensions`, `collection_name`, `QdrantVectorStore`, `LanguageAwareChunker`
- Produces: `async def reconcile_once(*, repository, producer, topic) -> int`; `async def reconcile_loop(...) -> None`; `async def main() -> None`; `RefreshTokenRepository.delete_expired_and_revoked() -> int`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_reconcile.py`:

```python
"""Recovering jobs that Kafka never got, or that a dead worker was holding."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ProjectStatus
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from app.repositories.project import ProjectRepository
from app.worker import reconcile_once
from tests.factories import create_project


class RecordingProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, IngestionMessage]] = []

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        self.sent.append((topic, message))


async def test_a_stranded_pending_project_is_re_enqueued(db_session: AsyncSession) -> None:
    """POST /projects wrote the row but the produce failed. Nothing else recovers it."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    count = await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    )

    assert count == 1
    assert producer.sent[0][1].project_id == project.id


async def test_a_freshly_created_project_is_left_alone(db_session: AsyncSession) -> None:
    """Its message is probably in flight; two minutes is the grace period."""
    await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    ) == 0
    assert producer.sent == []


async def test_a_project_held_by_a_dead_worker_is_re_enqueued(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="dead", lease_seconds=-1
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=repository, producer=producer, topic=INGEST_TOPIC
    ) == 1


async def test_a_healthy_running_job_is_left_alone(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="alive", lease_seconds=300
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=repository, producer=producer, topic=INGEST_TOPIC
    ) == 0


async def test_re_enqueued_jobs_get_a_fresh_job_id(db_session: AsyncSession) -> None:
    """The old job_id may already be recorded on the row, which would make the
    replacement message unclaimable."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    )

    assert producer.sent[0][1].job_id != project.last_job_id
    assert producer.sent[0][1].attempt == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 3: Write the worker**

Create `backend/app/worker.py`:

```python
"""The ingestion worker process.

Runs the backend image with a different entrypoint, so it shares `Settings`, the ORM
models, the repositories, and the access resolver rather than growing a parallel copy
of any of them.

Three things run concurrently: the main ingest consumer, one consumer per retry
topic, and a sweep that recovers jobs Kafka never received.
"""

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.embedder import build_embedder, probe_dimensions
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import QdrantVectorStore, collection_name
from app.queue.consumer import IngestionConsumer, Producer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.retry import RetryConsumer
from app.queue.topics import RETRY_TOPICS, IngestionMessage
from app.repositories.project import ProjectRepository
from app.repositories.refresh_token import RefreshTokenRepository

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 60
STRANDED_AFTER_SECONDS = 120


async def reconcile_once(
    *, repository: ProjectRepository, producer: Producer, topic: str
) -> int:
    """Re-enqueue every job that was lost. Returns how many.

    Covers two gaps the queue cannot close on its own: `POST /projects` committed the
    row but the produce failed, and a worker died holding a lease. Safe to run on
    every worker concurrently — the lease claim deduplicates, so a duplicate message
    costs one skipped poll.
    """
    stranded = await repository.find_stranded(
        pending_older_than_seconds=STRANDED_AFTER_SECONDS
    )
    for project in stranded:
        logger.info("re-enqueueing stranded project %s (status=%s)", project.id, project.status)
        await producer.produce_to(
            topic,
            IngestionMessage(
                project_id=project.id,
                # A fresh job id: reusing the old one could match `last_job_id` on
                # the row, and the claim would refuse the replacement message.
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=0,
                original_topic=topic,
            ),
        )
    return len(stranded)


async def reconcile_loop(*, producer: Producer, topic: str) -> None:
    """The 60-second tick: recover lost jobs and prune dead refresh tokens.

    `docs/PRD.md` §5.1 schedules the `refresh_tokens` cleanup for "M1, with the job
    scheduler". This loop is that scheduler.
    """
    sessionmaker = get_sessionmaker()
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
        try:
            async with sessionmaker() as session:
                await reconcile_once(
                    repository=ProjectRepository(session), producer=producer, topic=topic
                )
                pruned = await RefreshTokenRepository(session).delete_expired_and_revoked()
                await session.commit()
                if pruned:
                    logger.info("pruned %d dead refresh tokens", pruned)
        except Exception:  # noqa: BLE001 - the loop must outlive any single failure
            logger.exception("reconcile tick failed")


async def main() -> None:
    """Start the consumers and the sweep, and run until cancelled."""
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )

    producer = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=settings.kafka_ingest_topic
    )
    await producer.start()

    # Probed once at startup: the width names the collection, so guessing it wrong
    # is not a small mistake.
    embedder = build_embedder(settings)
    embedder.dimensions = await probe_dimensions(embedder)
    collection = collection_name(
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=embedder.dimensions,
    )
    logger.info("worker %s using collection %s", worker_id, collection)

    def build_pipeline(session: AsyncSession) -> IngestionPipeline:
        """A pipeline bound to one job's session."""
        return IngestionPipeline(
            session,
            settings,
            embedder=embedder,
            store=QdrantVectorStore(
                url=settings.qdrant_url, collection=collection, dimensions=embedder.dimensions
            ),
            chunker=LanguageAwareChunker(
                chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
            ),
        )

    consumer = IngestionConsumer(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=build_pipeline,
        worker_id=worker_id,
    )

    tasks = [
        asyncio.create_task(consumer.run()),
        asyncio.create_task(
            reconcile_loop(producer=producer, topic=settings.kafka_ingest_topic)
        ),
        *[
            asyncio.create_task(
                RetryConsumer(settings=settings, producer=producer, topic=topic).run()
            )
            for topic, _ in RETRY_TOPICS
        ],
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Add the refresh-token cleanup**

In `backend/app/repositories/refresh_token.py`:

```python
    async def delete_expired_and_revoked(self) -> int:
        """Hard-delete dead refresh tokens. Returns how many went.

        `refresh_tokens` is the documented exception to soft delete
        (`docs/PRD.md` §5.1): its lifecycle is `revoked_at` / `expires_at`, and these
        rows are genuinely finished.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            delete(RefreshToken).where(
                or_(RefreshToken.expires_at < now, RefreshToken.revoked_at.is_not(None))
            )
        )
        return result.rowcount
```

Import `delete` and `or_` there. Confirm the model's real attribute names first: `grep -n "Mapped" backend/app/models/refresh_token.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_reconcile.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker.py backend/app/repositories/refresh_token.py \
        backend/tests/test_reconcile.py
git commit -m "feat(worker): add the worker entrypoint and reconcile sweep"
```

---

### Task 20: Compose wiring and the integration test

The pause-during-a-long-job path cannot be verified any other way, so this is the one place a real broker is required.

**Files:**
- Modify: `infra/docker-compose.yml`, `backend/pyproject.toml`, `Makefile`, `backend/tests/conftest.py`
- Create: `backend/tests/test_ingestion_integration.py`

**Interfaces:**
- Consumes: everything
- Produces: the `integration` pytest marker; `make test-integration`

- [ ] **Step 1: Register the marker and keep it out of `make check`**

In `backend/pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "integration: needs a real Kafka broker and Qdrant; excluded from `make check`",
]
# Integration tests are opt-in: otherwise CI needs a broker in order to lint a docstring.
addopts = "-m 'not integration'"
```

Add to the `Makefile`:

```make
test-integration:  ## Run integration tests (needs `make infra`)
	cd backend && uv run pytest -m integration -v
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_ingestion_integration.py`:

```python
"""End to end against a real broker.

Everything else in this suite fakes the queue. This file exists for the one property
that cannot be faked: that a job taking longer than `max.poll.interval.ms` does not
trigger a rebalance and get run twice.
"""

import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import ProjectStatus
from app.queue.consumer import IngestionConsumer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from tests.factories import create_project

pytestmark = pytest.mark.integration


@pytest.fixture
async def producer() -> KafkaIngestionQueue:
    settings = get_settings()
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers, partitions=settings.kafka_ingest_partitions
    )
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=INGEST_TOPIC
    )
    await queue.start()
    yield queue
    await queue.stop()


async def test_a_produced_job_is_consumed_and_indexed(
    db_session: AsyncSession, producer: KafkaIngestionQueue, tmp_path: Path
) -> None:
    """The whole loop: produce → consume → claim → index → ready."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main() -> None:\n    pass\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    store = InMemoryVectorStore(dimensions=4)

    async def fake_clone(validated, **kwargs) -> CloneResult:  # noqa: ANN001, ANN003 - test stub
        return CloneResult(path=repo, commit_sha="a" * 40)

    def build_pipeline(session: AsyncSession) -> IngestionPipeline:
        return IngestionPipeline(
            session,
            get_settings(),
            embedder=FakeEmbedder(dimensions=4),
            store=store,
            chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
            clone_fn=fake_clone,
        )

    consumer = IngestionConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=build_pipeline,
        worker_id="integration-worker",
    )

    await producer.enqueue(
        IngestionMessage(
            project_id=project.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic=INGEST_TOPIC,
        )
    )

    task = asyncio.create_task(consumer.run())
    try:
        for _ in range(60):
            await asyncio.sleep(1)
            await db_session.refresh(project)
            if project.status == ProjectStatus.READY:
                break
    finally:
        task.cancel()

    assert project.status == ProjectStatus.READY
    assert store.points


async def test_a_long_job_does_not_trigger_a_rebalance(
    db_session: AsyncSession, producer: KafkaIngestionQueue, tmp_path: Path
) -> None:
    """The property the pause pattern exists for.

    A job that outlasts the poll interval must run exactly once. Without pausing,
    the broker evicts the member mid-job and a second consumer starts the same work.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    runs = 0

    class SlowPipeline:
        async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
            nonlocal runs
            runs += 1
            # Comfortably past the default 5s poll timeout used in this test setup.
            await asyncio.sleep(15)

    consumer = IngestionConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=lambda session: SlowPipeline(),
        worker_id="slow-worker",
    )

    await producer.enqueue(
        IngestionMessage(
            project_id=project.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic=INGEST_TOPIC,
        )
    )

    task = asyncio.create_task(consumer.run())
    await asyncio.sleep(25)
    task.cancel()

    assert runs == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest -m integration -v`
Expected: FAIL — no broker reachable, until Step 4 brings one up.

- [ ] **Step 4: Add the worker and Ollama services to Compose**

In `infra/docker-compose.yml`:

- **`worker`**: the same `build` context as `backend`, `command: ["uv", "run", "python", "-m", "app.worker"]`, the same environment block, `deploy: { replicas: 2 }`, depending on `kafka`, `postgres`, and `qdrant` being healthy. Two replicas against two partitions is what makes §4.1's concurrency cap of 2 structural rather than a setting.
- **`ollama`**: `image: ollama/ollama`, a named volume for models, `profiles: ["ollama"]`. The profile must be **on by default** in `make up` and `make infra`, because §9's shipped default is `EMBEDDING_PROVIDER=ollama` — a default pointing at a service nobody started is a broken out-of-box experience. An instance using a hosted provider drops the profile.

Update the header comment's service and port list to match, then validate:

```bash
cd infra && docker compose config --quiet
```

- [ ] **Step 5: Run test to verify it passes**

```bash
make infra
cd backend && uv run pytest -m integration -v
```
Expected: PASS (2 tests). The second takes ~25 seconds by design — it is waiting out a poll interval on purpose.

- [ ] **Step 6: Run the full non-integration suite**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest`
Expected: PASS, with integration tests deselected.

- [ ] **Step 7: Commit**

```bash
git add infra/docker-compose.yml Makefile backend/pyproject.toml \
        backend/tests/test_ingestion_integration.py backend/tests/conftest.py
git commit -m "feat(infra): add worker and ollama services, and the integration suite"
```

---

# Phase 5 — Documentation

### Task 21: The documentation amendments

`.claude/rules/documentation.md` requires these in the same change as the code, and `contradiction-halt.md` step 4 is explicit that a decision leaving the PRD saying the old thing has only relocated the contradiction rather than settled it. **This task is not optional and does not get deferred.**

**Files:** `docs/PRD.md`, `CLAUDE.md`, `README.md`, `backend/README.md`, `backend/.env.example`, `infra/docker-compose.yml`, `SECURITY.md`, `CONTRIBUTING.md`, `.claude/rules/ingestion.md` (new)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Amend `docs/PRD.md`**

Work through every row. The PRD is the source of truth, so it is wrong last, not first.

| Section | Change |
| --- | --- |
| §1 | Add event streaming to the stated learning goals — Kafka is currently absent from the list, which is what made §5's rejection of it consistent |
| §4.1 | `Project` schema gains the seven columns: `lease_owner`, `lease_expires_at`, `last_job_id`, `reindex_in_progress`, `active_generation`, `embedding_collection`, `embedding_model` |
| §4.1 | Clarify the walk: a fresh clone has already applied `.gitignore`, so the filter that matters is binary detection, a per-file size cap, and a path denylist |
| §4.1 | Reindex is a generation swap: the project stays `ready` and queryable, and a failed reindex leaves the old index intact |
| §5 | Stack table, "Background jobs" row: Kafka, not `BackgroundTasks` → ARQ |
| §5 | Stack table, "Rate limiting" row: drop "reused for job-queue backing at M1" — Redis no longer backs the queue |
| §5 | **Rewrite the "On the job queue" note.** It currently argues against Kafka by name at `docs/PRD.md:370`. Replace it with the decision as taken: the technical argument stands, it was overridden for the learning goal in §1, and each cost is mitigated as described in the spec's §2.1. Do not delete the reasoning — a future reader needs to know the trade was made knowingly |
| §5.1 | Record that idempotent action endpoints return `202` with an outcome flag rather than `409` |
| §6 | M1 no longer "moves jobs to Redis + ARQ" |
| §8 | Mark "who can add projects" (any user) and the PAT question (full support, caveat intact) as decided |

- [ ] **Step 2: Amend `CLAUDE.md`**

- Status banner: M1 backend shipped. Postgres, Redis, **Kafka, and Qdrant** are read.
- Replace "Jobs move from `BackgroundTasks` to Redis + ARQ at M1" with the Kafka topology.
- Remove "`qdrant_url` remains declared and unread until M1" — it is read now.
- Add the ingestion architecture notes a reader cannot infer from one file: the lease is the deduplication boundary; the collection name carries the embedding model; reindex is a generation swap.
- **Keep counts exact** — the rules table gains a row for the new `ingestion.md`, so the "Ten rule files" sentence becomes eleven.

- [ ] **Step 3: Amend the remaining docs**

- **`backend/README.md`**: the route table must be exhaustive — add all five project routes. Document the new config values and the `python -m app.worker` command.
- **`README.md`**: tick M1 in the roadmap; add Kafka, the worker, and Ollama to the service/port table.
- **`backend/.env.example`**: verify every field from Task 1 is present and that the `REDIS_URL` comment no longer promises the ARQ queue.
- **`infra/docker-compose.yml`**: the header comment's URL list must match the services below.
- **`SECURITY.md`**: add `PAT_ENCRYPTION_KEY` as an operator responsibility, **backed up separately from the database** — a backup holding both is plaintext storage with extra steps. Note the new services and that Kafka must not be exposed beyond the internal network.
- **`CONTRIBUTING.md`**: document `make test-integration` and that it needs `make infra`.

- [ ] **Step 4: Write the new ingestion rule**

Create `.claude/rules/ingestion.md`, with a `paths:` frontmatter block covering `backend/app/ingestion/**/*.py` and `backend/app/queue/**/*.py`. M1 establishes patterns that currently have no rule, and the point is that the next person cannot unknowingly undo them:

- The lease is the deduplication boundary. The service-level busy check is a fast path; removing the lease because "the service already checks" is a defect.
- Long jobs pause their partition and commit after the work. Raising `max.poll.interval.ms` instead is not an acceptable substitute.
- Every failure is classified `TerminalIngestionError` or `RetryableIngestionError`. An unclassified raise defaults to retryable-once and is a gap to close, not a style choice.
- Chunk line ranges are load-bearing — every citation depends on them.
- The collection name carries provider, model, and dimensions. Never hardcode a collection name.
- Anything derived from clone output passes through `scrub` before it is stored or logged.

- [ ] **Step 5: Verify every claim**

```bash
cd backend && uv run pytest && cd ../infra && docker compose config --quiet
grep -rn "ARQ\|BackgroundTasks" ../docs/PRD.md ../CLAUDE.md ../README.md ../backend/README.md
```
Expected: the suite passes, Compose validates, and the only remaining ARQ mentions are deliberate historical references in the rewritten §5 note. Anything else is stale documentation.

Then check the README's examples actually work — `.claude/rules/documentation.md` requires that a documented `curl` runs against the code as committed.

- [ ] **Step 6: Commit**

```bash
git add docs/PRD.md CLAUDE.md README.md backend/README.md backend/.env.example \
        infra/docker-compose.yml SECURITY.md CONTRIBUTING.md .claude/rules/ingestion.md
git commit -m "docs: bring the docs in line with M1 and the Kafka decision"
```

---

## Done criteria

M1 is complete when all of these hold:

- [ ] `make check` passes.
- [ ] `make test-integration` passes with `make infra` running.
- [ ] `docs/PRD.md` §7's M1 criteria pass as automated tests: sharing works without a grant step, destructive gating returns `403`, an admin overrides it, and read scoping greps to one function.
- [ ] A real repository can be indexed end to end via `POST /projects`, reaching `ready` with non-zero file and chunk counts.
- [ ] Killing a worker mid-index leaves the project reclaimable within five minutes, and it completes on the next attempt.
- [ ] A reindex leaves the project queryable throughout, and a reindex failed part-way leaves the previous index intact.
- [ ] No PAT appears in any log, traceback, API response, or `Project.error`.
- [ ] `grep -rn "ARQ" docs/ CLAUDE.md README.md` returns only the deliberate historical reference in the rewritten §5 note.
