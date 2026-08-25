# M0 — Auth & Accounts (backend) — design

**Date:** 2026-08-23
**Milestone:** M0 (`docs/PRD.md` §6)
**Scope:** backend only — persistence foundation, auth API, login rate limiting
**Status:** approved for planning

---

## 1. Scope

This spec covers three of the four things `docs/PRD.md` and `docs/design.md` jointly place at M0:

1. **Persistence foundation** — SQLAlchemy 2.0 (async), Alembic, session lifecycle, the
   repository layer, the soft-delete guarantee.
2. **Auth API** — `users` and `refresh_tokens` tables, bcrypt password hashing, JWT access
   tokens, opaque rotating refresh tokens, the `must_change_password` gate, admin-driven
   reset, bootstrap seeding.
3. **Login rate limiting** — the first Redis consumer.

### Explicitly out of scope

- **Frontend auth and the app shell.** `docs/design.md:110-111` places two component rows at
  M0 (an auth set and a shell set). Those get their own spec, written against this API once it
  exists. `docs/PRD.md` §7's criterion — "log in as a seeded admin, change the initial
  password, and create an account for a colleague, with no manual database work" — is satisfied
  by this API alone.
- Anything touching projects, Qdrant, ingestion, or RAG. The one exception is the access
  resolver (§10), which ships as a real, tested function so that M1 has a seam to fill rather
  than a convention to remember.
- CI workflows. `.github/` currently holds templates only, and `Makefile:109` describes `check`
  as "everything CI would run" against a CI that does not exist. Adding one is not this
  milestone's job; the new `make infra` prerequisite is documented in `CONTRIBUTING.md` instead.

---

## 2. Decisions and rationale

Each row is a decision taken during design, with the reason it went that way. Where a decision
departs from a ground-truth document, the amendment is listed in §13.

| # | Decision | Why |
| --- | --- | --- |
| D1 | **Async SQLAlchemy** — asyncpg, `AsyncSession`, `async def` handlers | `docs/PRD.md:316` picks ARQ over Celery because the indexing pipeline is already async. M1's worker and M2–M3's LangGraph nodes need DB access from async code; converting later is worse than paying the test-setup cost now. |
| D2 | **Three layers** — route → service → repository | `deleted_at IS NULL` must never be forgotten (`docs/PRD.md:323`). A `BaseRepository` whose query helper carries the filter makes the guarantee structural rather than remembered. Only repositories import `select`. |
| D3 | **Access token in the response body; refresh token in an httpOnly cookie** | A 30-day credential in `localStorage` is readable by any script on the page. `backend/app/main.py:20-26` already sets `allow_credentials=True` with an explicit origin list — the CORS shape cookies require. API calls use the `Authorization` header, so no normal route has a CSRF surface. |
| D4 | **Structured error `detail`, decided API-wide** | `docs/PRD.md:107` requires a machine-readable reason; `.claude/rules/router.md:152-156` forbids inventing an error shape in one router. Deciding it once here satisfies both. |
| D5 | **The whole `/auth` surface stays reachable while `must_change_password` is set** | Read literally, "every route except `POST /auth/change-password`" (`docs/PRD.md:107`) is a dead end: the access token expires in 15 minutes, `/auth/refresh` would be blocked, and the user has no way forward. |
| D6 | **Seeding is a CLI command run by the container entrypoint** | Keeps DB side effects out of the request-serving app and out of every `TestClient(create_app())`. Idempotent and re-runnable by an operator. |
| D7 | **Rate limiting is per-route via an explicit dependency, not app-wide middleware** | `docs/PRD.md:115` specifies only a login limit. `SECURITY.md:42` puts authenticated-user DoS out of the threat model, so a global limiter would guard a threat the project has declined to defend against. |
| D8 | **Tests run against the `make infra` Postgres, in a separate `askrepo_test` database** | `timestamptz`, the partial unique index on `email`, and asyncpg itself all diverge on SQLite. A suite that passes on SQLite and fails on Postgres is worse than none. |
| D9 | **The access resolver ships in M0** | `docs/PRD.md:359` makes single-point read scoping a success criterion. Shipping the function and its contract test before the first route that could bypass it. |
| D10 | **Common-password check against a vendored wordlist** | No network. `SECURITY.md:51` says keep the instance off the public internet, which rules out the HIBP range API. |
| D11 | **The gate is HTTP middleware, and it owns the authoritative decode and user load** | Fail-closed: a route added at M2 is gated with no action taken. Owning the load means one decode and one DB read per request. Costs are named in §6 and §11. |
| D12 | **10-second grace window on refresh rotation**, satisfied by minting a sibling token | Strict rotation logs out any client that refreshes twice concurrently — two browser tabs is enough. Genuine replay (anything older than the window) still revokes the family. The cost is stated precisely in §5. |
| D13 | **Refresh tokens are hashed with SHA-256, not bcrypt** | They are 256-bit values from `secrets.token_urlsafe(32)`, so a password hash's reason to exist (slowing brute force against low-entropy secrets) does not apply — and bcrypt's per-row salt would force a full-table scan to look a token up, instead of a unique-index hit. |
| D14 | **`refresh_tokens` carries no `deleted_at`** | Its lifecycle is `revoked_at` / `expires_at`. A third overlapping state column that nothing sets is worse than a documented exception. |
| D15 | **`/users` mutations are admin-only; reads are open to any authenticated user** | From M1 every project and QA pair shows `created_by`, and `docs/design.md` wants "I can see who saved a pair". Making reads admin-only now forces a second parallel directory endpoint later. |
| D16 | **Admin-supplied password on reset, not server-generated** | A generated password would have to appear in the response, which `.claude/rules/response-api.md:152-156` forbids outright. |
| D17 | **Last-admin guard** | A sole admin demoting or deleting themselves leaves an instance recoverable only by manual SQL — exactly what §7's "no manual database work" exists to prevent. |
| D18 | **Redis unavailable fails open, logged at `error`** | A Redis outage degrades brute-force protection; failing closed would lock the whole team out of their own tool. bcrypt at cost 12 still makes each guess expensive, and the network is private. |
| D19 | **mypy is added to `make typecheck` for the backend** | `pyproject.toml` selects `ANN` for annotation *coverage* with nothing verifying annotation *correctness*. M0 introduces `Mapped[...]` models and a generic `BaseRepository` — the code where a checker pays for itself. |
| D20 | **Partial unique index on `email`, scoped to non-deleted rows** | `docs/PRD.md:323` requires the constraint to account for soft delete without saying how. Partial lets a rehired colleague's address be reused, and forces every lookup to filter `deleted_at IS NULL` anyway. |
| D21 | **Explicitly sized `varchar(n)` on every string column, not `text`** | A stated length bound is a data-integrity constraint the schema enforces rather than a rule the service is trusted to remember. Sizes are chosen per column, not a blanket 255 — see §4. |
| D22 | **Re-hash on successful login when the bcrypt cost factor has changed** | The cost is embedded in the stored hash (`$2b$12$…`), so raising it later applies to existing accounts instead of only new ones. One `UPDATE` on a path that already does an expensive hash. |
| D23 | **bcrypt, not argon2id** | argon2id's 64 MiB of memory per hash is a real cost on the single shared VPS `docs/PRD.md:297` targets. bcrypt is still a proper password hash — deliberately slow, salted, self-describing — so the security property that matters is retained. Contradicts `docs/PRD.md` in four places; amended per §13. |
| D24 | **Passwords are capped at 72 bytes, validated as bytes** | bcrypt silently truncates its input at 72 bytes: without an explicit cap, two different long passwords can both authenticate and nobody finds out. Rejecting is chosen over SHA-256 pre-hashing — see §5. |

---

## 3. Module layout

```
backend/
├── alembic.ini
├── alembic/
│   ├── env.py                          # async engine; target_metadata = Base.metadata
│   └── versions/
│       └── <rev>_initial_auth_tables.py
└── app/
    ├── main.py                         # + AuthContextMiddleware, exception handlers, 2 routers
    ├── config.py                       # + §11 settings, + production validation
    ├── cli.py                          # `python -m app.cli seed-admins`
    ├── core/
    │   ├── security.py                 # bcrypt hash/verify/needs-rehash, JWT encode/decode, token mint, sha256
    │   ├── passwords.py                # policy: length bounds + wordlist membership
    │   ├── data/common-passwords.txt   # vendored wordlist
    │   ├── errors.py                   # ErrorCode, AppError, exception handlers
    │   ├── middleware.py               # AuthContextMiddleware, AuthContext, AuthenticatedUser
    │   ├── rate_limit.py               # Redis fixed-window limiter dependency
    │   └── access.py                   # ProjectScope, resolve_project_scope — the phase-2 seam
    ├── db/
    │   └── session.py                  # lazy async engine, sessionmaker, get_session
    ├── models/
    │   ├── base.py                     # DeclarativeBase, naming_convention, TimestampMixin, SoftDeleteMixin
    │   ├── user.py
    │   └── refresh_token.py
    ├── repositories/
    │   ├── base.py                     # BaseRepository — owns the soft-delete filter
    │   ├── user.py
    │   └── refresh_token.py
    ├── services/
    │   ├── auth.py
    │   └── user.py
    ├── schemas/
    │   ├── base.py                     # unchanged — ApiModel
    │   ├── pagination.py               # ListQuery, PaginatedResponse[T]
    │   ├── errors.py                   # ErrorResponse, ValidationErrorResponse (for OpenAPI)
    │   ├── auth.py
    │   └── user.py
    └── api/
        ├── deps.py                     # CurrentUser / AdminUser aliases, session, services
        └── routes/
            ├── index.py                # unchanged
            ├── health.py               # unchanged
            ├── auth.py                 # new
            └── users.py                # new
```

`app/models/` mirrors the existing `app/schemas/`, keeping the technical-role layout the repo
already uses and that `.claude/rules/router.md:18-26` assumes.

### Layer contract

- **Routes** accept validated input, resolve dependencies, call exactly one service method,
  return a typed response (`.claude/rules/router.md:53-68`). No conditionals.
- **Services** own business rules, transactions, and orchestration across repositories. They
  never import `select`, `insert`, or `update` from SQLAlchemy.
- **Repositories** own every statement. All reads go through `BaseRepository._active_select()`,
  which pre-applies `deleted_at IS NULL` for models carrying `SoftDeleteMixin`. A repository
  that needs deleted rows calls a distinctly named method (`get_including_deleted`) so the
  intent is visible at the call site and greppable.

---

## 4. Data model

`app/models/base.py` defines `Base` with an explicit `MetaData(naming_convention=...)` so
constraint and index names are deterministic and Alembic autogenerate produces stable diffs.

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `uuid` PK | application-generated `uuid4` (`docs/PRD.md:322`) |
| `name` | `varchar(255)` NOT NULL | |
| `email` | `varchar(255)` NOT NULL | normalized to lowercase at the schema boundary; RFC 5321's practical maximum is 254 |
| `password_hash` | `varchar(255)` NOT NULL | bcrypt encoded string, always exactly 60 chars. Sized at 255 rather than 60 deliberately: a future move to argon2id needs ~97, and headroom here costs nothing while a too-tight column would force a migration |
| `is_admin` | `boolean` NOT NULL DEFAULT `false` | |
| `must_change_password` | `boolean` NOT NULL DEFAULT `true` | |
| `last_login_at` | `timestamptz` NULL | |
| `created_at` | `timestamptz` NOT NULL | server default `now()` |
| `updated_at` | `timestamptz` NOT NULL | server default `now()`, SQLAlchemy `onupdate` |
| `deleted_at` | `timestamptz` NULL | soft delete |

Indexes: `UNIQUE (email) WHERE deleted_at IS NULL` — partial (D20), and it doubles as the lookup
index for login. No standalone index on `deleted_at`: it has two distinct values in practice, so
it would not be selective, and the table holds one row per developer in the organization.

Not `citext`: lowercase normalization happens in the request schema, so a Postgres extension
buys nothing.

**On `varchar(n)` versus `text`.** Every string column above is explicitly sized. Worth knowing
what that does and does not buy in Postgres: the two types are stored identically and perform
identically — `varchar(n)` is `text` plus a length check constraint. So the sizes here are a
data-integrity statement, not an optimization, and each number is chosen to mean something rather
than being a blanket 255 (which is a MySQL row-format artifact with no significance in Postgres).
Raising a limit later is a metadata-only `ALTER TABLE` and cheap; lowering one rewrites the
table.

### `refresh_tokens`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `uuid` PK | |
| `user_id` | `uuid` NOT NULL | FK → `users.id`, `ON DELETE NO ACTION` (users are never hard-deleted), indexed |
| `family_id` | `uuid` NOT NULL | the rotation chain; indexed |
| `token_hash` | `varchar(64)` NOT NULL | SHA-256 hex is always exactly 64 characters, **UNIQUE** |
| `issued_at` | `timestamptz` NOT NULL | |
| `expires_at` | `timestamptz` NOT NULL | `issued_at + refresh_token_ttl_days` |
| `used_at` | `timestamptz` NULL | set when rotated normally |
| `revoked_at` | `timestamptz` NULL | |
| `revoked_reason` | `varchar(32)` NULL | `Literal["rotated", "replay", "logout", "logout_all", "password_change", "admin_reset", "user_deactivated"]` — longest value is 18 chars |

No `deleted_at` (D14). No `user_agent` / `ip` columns — `docs/PRD.md:118` puts
session-activity history out of scope, and unread columns are debt.

### Migrations

One initial revision creating both tables. `alembic/env.py` uses
`async_engine_from_config` + `connection.run_sync(...)` for the async driver. `Base.metadata`
is the autogenerate target; `create_all` is used nowhere, including in tests (§11), so the
migrations themselves are exercised on every run.

`updated_at` uses SQLAlchemy's `onupdate`, which does **not** fire on bulk `UPDATE` statements.
Every bulk path — revoking a token family, revoking all of a user's tokens — sets `updated_at`
explicitly. Where a table has no `updated_at` (`refresh_tokens`), this does not apply.

---

## 5. Auth mechanics

### Primitives (`app/core/security.py`)

- **Passwords:** the `bcrypt` package directly, cost factor 12 — `docs/PRD.md:110`'s "sensible
  cost parameters". Not `passlib`: its last release predates bcrypt 4.x and it misdetects the
  backend version, producing spurious warnings for no benefit here.

  Chosen over argon2id (D23) because argon2id wants 64 MiB of memory per hash, and
  `docs/PRD.md:297` targets a single shared VPS also running Postgres, Qdrant, Redis, and
  possibly a local Ollama model. bcrypt keeps the property that actually matters — each guess
  costs real time — without the memory footprint.

  bcrypt and the SHA-256 used for refresh tokens are both hashes, but they are not
  interchangeable, and mixing them up is the single easiest way to get this milestone wrong.
  SHA-256 is a *fast* digest; that is its design goal. bcrypt is a *deliberately slow, salted*
  password hash whose purpose is to make guessing expensive. A password is low-entropy and
  guessable, so it needs bcrypt; a refresh token is 256 random bits, so there is nothing to guess
  and the fast digest is correct (D13).

  Two practical consequences of bcrypt's encoded format, `$2b$12$<22-char salt><31-char hash>`:

  - **There is no separate salt column.** Scheme, cost, and per-row salt all live in that one
    60-character string. Verification is `bcrypt.checkpw(candidate, stored)`, never
    `hash(candidate) == stored` — the latter cannot work, because each row's salt differs.
  - **The cost factor is visible, so it can be raised.** On a successful login, if the cost
    parsed from the stored prefix is below the configured `bcrypt_cost`, the service re-hashes the
    plaintext it already has in hand and updates the row (D22). Raising the cost later therefore
    reaches existing accounts, not just new ones.

  **The 72-byte truncation, and why the cap is a rejection (D24).** bcrypt ignores input past 72
  bytes, silently. Left unhandled, a 200-character password and a different 200-character
  password sharing their first 72 bytes would both authenticate — a correctness bug that produces
  no error and no log line. Two ways out:

  1. **Reject anything over 72 bytes** — chosen. One check, no subtlety, and the limit is
     generous against a 12-character minimum.
  2. Pre-hash with SHA-256 and feed bcrypt the base64 digest (the `bcrypt_sha256` scheme),
     supporting arbitrary length. Rejected: it reintroduces a construction whose security
     argument needs explaining (an attacker holding SHA-256 password hashes from an unrelated
     breach can test them against these bcrypt hashes directly — "password shucking"), which is
     the opposite of why bcrypt was chosen here.

  The cap is measured in **bytes after UTF-8 encoding, not characters** — a passphrase of CJK or
  emoji characters reaches 72 bytes at roughly 18–24 characters, so a character-based check would
  let truncation through for exactly the users least likely to notice.

  Note that `password_max_bytes` (§11) bounds the *plaintext in the request*, not the column: the
  stored value is always 60 characters.
- **Access tokens:** `PyJWT`, HS256, key from `SECRET_KEY`. Claims: `sub` (user id as string),
  `iat`, `exp`, `jti`, `typ="access"`. **Not** `is_admin` and **not** `must_change_password` —
  both would go stale for up to 15 minutes, and `docs/PRD.md:101` requires deactivation to end
  sessions *immediately*, which is only true if every request re-reads the row.
- **Refresh tokens:** `secrets.token_urlsafe(32)` for the raw value; SHA-256 hex stored (D13).
- **Uniform login failure:** an unknown email is verified against a module-level dummy bcrypt
  hash so timing matches a wrong password, and both return `INVALID_CREDENTIALS`
  (`docs/PRD.md:114`).

### Password policy (`app/core/passwords.py`)

Policy lives entirely in the service layer, not in Pydantic constraints, so every rejection is
one code (`WEAK_PASSWORD`, `400`) rather than "sometimes `422` for length, sometimes `400` for
the wordlist".

- Minimum 12 characters (`docs/PRD.md:110`).
- Rejected if present in the vendored wordlist, compared case-insensitively after stripping.
- **Maximum 72 bytes** once UTF-8 encoded — enforced in the request schema as the one exception,
  because it is a correctness requirement rather than a policy preference (D24). Rejection message
  names bytes, not characters, so a user hitting it with a non-ASCII passphrase is not left
  counting letters.

### Rotation and replay (`POST /auth/refresh`)

One transaction, in order:

1. SHA-256 the cookie value; look it up on the unique index.
2. Not found → `401 INVALID_TOKEN`.
3. `expires_at` in the past → `401 TOKEN_EXPIRED`.
4. `revoked_at` set → **replay**: revoke the whole `family_id` with reason `replay`, clear the
   cookie, `401 REFRESH_TOKEN_REUSED`.
5. `used_at` set:
   - within `refresh_rotation_grace_seconds` → **not a replay** (D12): mint a *sibling* token in
     the same `family_id`, return a new access token, set the new cookie. The consumed row stays
     consumed and is not revoked.
   - older → **replay**, as step 4.
6. Owner missing or soft-deleted → revoke the family, `401 INVALID_TOKEN`.
7. Otherwise valid → set `used_at`, insert a successor row sharing `family_id`, return a new
   access token, set the new cookie.

**Why a sibling and not the original successor.** Only the successor's SHA-256 hash is stored,
so its raw value cannot be re-sent to a second caller. The alternatives are worse: caching the
raw token in Redis puts a live credential in a store that ships without a password in
development (`SECURITY.md:64`), and deriving the successor deterministically from its parent
(`HMAC(secret, parent)`) would mean that stealing any single token yields the entire future
chain, silently — destroying the property rotation exists to provide.

Minting a sibling means a family can briefly hold more than one live token. The cost is precise
and bounded: for `refresh_rotation_grace_seconds` after a legitimate rotation, a token stolen
and replayed inside that window produces a second live token without tripping detection.
Anything outside the window still revokes the whole family. That is the trade being made against
guaranteed logouts for anyone with two tabs open, and it is why the window is 10 seconds rather
than minutes.

### Revocation matrix

| Trigger | Scope | `revoked_reason` |
| --- | --- | --- |
| `POST /auth/logout` | the presented token only | `logout` |
| `POST /auth/logout-all` | every token for the user | `logout_all` |
| `POST /auth/change-password` | every token for the user **except** the presented one | `password_change` |
| `POST /users/{id}/reset-password` | every token for that user | `admin_reset` |
| `DELETE /users/{id}` | every token for that user | `user_deactivated` |
| replay detected | every token in the `family_id` | `replay` |
| normal rotation | the consumed token | `rotated` |

`change-password` sparing the caller's own token is `docs/PRD.md:108` ("revokes all *other*
refresh tokens"), and the caller's token is identifiable because it arrived in the cookie.

`change-password` returns no new access token: `must_change_password` is not a claim, so the
existing token starts working everywhere the instant the row changes.

---

## 6. `AuthContextMiddleware` and dependencies

### The middleware

Registered in `create_app()` **inside** `CORSMiddleware`, so its `403` carries CORS headers —
otherwise the browser reports an opaque network failure and the frontend never sees the code it
is supposed to branch on. This property is asserted by a test (§11), not by reasoning about
Starlette's registration order.

The middleware always establishes identity; only the `403` check is path-scoped. Getting this
backwards is an easy mistake with a sharp edge — if the middleware short-circuited on `/auth`,
`request.state.auth` would never be populated there and `GET /auth/me` would fail with a
`RuntimeError` instead of returning the caller.

Flow:

1. No `Authorization: Bearer` header → set `request.state.auth = AuthContext(None, None)` and
   pass through. The route's own dependency owns the `401`, so unauthenticated access to a
   public route is unaffected.
2. Decode the token. Failure → `AuthContext(None, INVALID_TOKEN | TOKEN_EXPIRED)`, pass through.
3. Load the user in a short-lived session built from the sessionmaker directly (middleware
   cannot use `Depends`). Missing or soft-deleted → `AuthContext(None, INVALID_TOKEN)`, pass
   through. This is what makes deactivation immediate.
4. Set `AuthContext(user, None)`.
5. If `must_change_password` is set **and** the path is not gate-exempt — exact `/`, or prefixed
   by `/health`, `/docs`, `/redoc`, `/openapi.json`, or `auth.router.prefix` — return
   `403 PASSWORD_CHANGE_REQUIRED` immediately. The auth prefix is read from the router object,
   not typed as a literal, so renaming it cannot desynchronize the gate.

A request carrying a bearer token to `/health` therefore costs one primary-key lookup it does not
need. That is accepted rather than special-cased: a path allowlist governing whether identity is
resolved at all is the version of this middleware that produces the bug described above.

The middleware's session closes before the handler runs, so identity crosses the boundary as a
frozen dataclass, never a detached ORM row:

```python
@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    name: str
    email: str
    is_admin: bool
    must_change_password: bool
```

`must_change_password` is carried because `/auth` routes run with the gate bypassed and may
legitimately observe it as true — `POST /auth/change-password` is the obvious case. For every
route outside `/auth`, the gate has already established that it is false.

This is a deliberate deviation from `.claude/rules/router.md:75`'s
`Annotated[User, Depends(get_current_user)]`: the annotated type is `AuthenticatedUser`, not the
ORM `User`. It removes a whole class of `DetachedInstanceError` and makes it impossible for a
handler to lazily load a relationship off the request-scoped identity. Services load the full
ORM row when they need to mutate it. `router.md` is updated to match (§13).

### Dependencies (`app/api/deps.py`)

```python
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser   = Annotated[AuthenticatedUser, Depends(require_admin)]
```

- `get_current_user` reads `request.state.auth`. User present → return it. Error present →
  raise `AppError(401, error)`. Attribute missing entirely → `RuntimeError`, because that means
  the middleware is not installed; that is a programming error and must surface as a `500`, not
  as a `401` that looks like a credential problem.
- `require_admin` builds on it and raises `AppError(403, ADMIN_REQUIRED)`.

There is no `require_active_user` — the gate is structural, which is the whole point of D11.

A test walks `app.routes` and asserts every mounted path is either in the open set or reachable
only through `CurrentUser`/`AdminUser`. This does not enforce the gate (the middleware does);
it asserts the open-prefix list still matches the routers actually mounted, so an M2 route
group added under a new prefix cannot land outside the allowlist's intent unnoticed.

---

## 7. Error contract

`app/core/errors.py`:

```python
class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
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
```

`AppError(HTTPException)` takes `(status_code, code, message)` and builds
`detail={"code": ..., "message": ...}`. Every raise site in the app uses it; bare
`HTTPException` is not used.

Wire shape, for every error the application raises:

```json
{ "detail": { "code": "PASSWORD_CHANGE_REQUIRED", "message": "You must change your password before continuing." } }
```

`RequestValidationError` gets a handler reshaping it into the same envelope plus a field map, so
there is genuinely **one** error shape rather than two:

```json
{ "detail": { "code": "VALIDATION_ERROR", "message": "Request validation failed.",
              "fields": { "newPassword": "String should have at least 12 characters" } } }
```

Field keys are the aliases as they arrived — `camelCase` — which is what
`docs/design.md:161-163` needs to render a `FieldError` per field without the frontend mapping
`loc` arrays itself.

A catch-all `Exception` handler logs with `exc_info=True` and returns
`500 {"code": "INTERNAL_ERROR", "message": "Internal server error."}` with no internals
(`.claude/rules/response-api.md:56`).

`app/schemas/errors.py` declares `ErrorResponse` / `ValidationErrorResponse` purely so route
`responses` blocks reference a real schema in `/docs`.

---

## 8. Routes

### `/auth` — `APIRouter(prefix="/auth", tags=["Auth"])`, no router-level dependency

| Route | Status | Request | Response | `responses` |
| --- | --- | --- | --- | --- |
| `POST /auth/login` | 200 | `LoginRequest{email, password}` | `LoginResponse` + `Set-Cookie` | 401, 422, 429 |
| `POST /auth/refresh` | 200 | refresh cookie | `LoginResponse` + rotated cookie | 401, 429 |
| `POST /auth/change-password` | 200 | `ChangePasswordRequest{currentPassword, newPassword}` | `UserResponse` | 400, 401, 422, 429 |
| `POST /auth/logout` | 204 | refresh cookie | — | 401 |
| `POST /auth/logout-all` | 204 | — | — | 401 |
| `GET /auth/me` | 200 | — | `UserResponse` | 401 |

`LoginResponse`: `accessToken`, `tokenType` (`"bearer"`), `expiresIn` (seconds), `user`
(`UserResponse`).

`POST /auth/login` is the only route where a `401` means bad credentials rather than a bad
token, hence the distinct `INVALID_CREDENTIALS` code.

`POST /auth/logout` is idempotent: an absent or already-revoked cookie still clears the cookie
and returns `204`. Logging out twice is not an error condition.

### `/users` — `APIRouter(prefix="/users", tags=["Users"])`

Per-route dependencies, not router-level (D15): reads take `CurrentUser`, mutations take
`AdminUser`.

| Route | Status | Dep | Request | Response | `responses` |
| --- | --- | --- | --- | --- | --- |
| `GET /users` | 200 | `CurrentUser` | `ListQuery` | `PaginatedResponse[UserResponse]` | 400, 401, 422 |
| `GET /users/{id}` | 200 | `CurrentUser` | — | `UserResponse` | 401, 404 |
| `POST /users` | 201 | `AdminUser` | `UserCreateRequest{name, email, password, isAdmin?}` | `UserResponse` | 400, 401, 403, 409, 422 |
| `PATCH /users/{id}` | 200 | `AdminUser` | `UserUpdateRequest{name?, isAdmin?}` | `UserResponse` | 401, 403, 404, 409, 422 |
| `DELETE /users/{id}` | 204 | `AdminUser` | — | — | 401, 403, 404, 409 |
| `POST /users/{id}/reset-password` | 200 | `AdminUser` | `ResetPasswordRequest{newPassword}` | `UserResponse` | 400, 401, 403, 404, 422 |

`UserResponse`: `id`, `name`, `email`, `isAdmin`, `mustChangePassword`, `lastLoginAt`,
`createdAt`, `updatedAt`. `passwordHash` is not a declared field on any response model
(`.claude/rules/response-api.md:152-156`) — absent, not excluded.

Non-admins see the same shape on `GET /users`, including other users' `isAdmin` and
`mustChangePassword`. Inside one organization's instance that is acceptable; if it later isn't,
the reduced shape belongs in the service, not a branch in the route.

`PATCH` cannot change `email` or `password` — `docs/PRD.md:105` scopes it to name and the admin
flag, and password changes have their own two routes with their own audit semantics.

`409 LAST_ADMIN` on `PATCH` (clearing `isAdmin`) and `DELETE` when the operation would leave
zero active admins (D17).

`404 USER_NOT_FOUND`, not `403`: a user id is not a resource whose existence is public in the
way a project's is, and `.claude/rules/response-api.md:58-69` reserves `403` for "may see it,
may not do this to it" — which does not apply, since these routes are admin-gated already.

### Shared list contract (`app/schemas/pagination.py`)

`ListQuery` per `.claude/rules/router.md:128-146`: `page`, `limit`, `search`, `sort`,
`sortDirection`. Sortable fields on `/users` are allowlisted (`name`, `email`, `created_at`,
`last_login_at`); anything else is `400 INVALID_SORT_FIELD`. `search` matches `name` or `email`
case-insensitively. `PaginatedResponse[T]` returns `items`, `page`, `limit`, `totalCount`,
`totalPages` — never a bare array.

---

## 9. Rate limiting

`app/core/rate_limit.py` — Redis fixed-window counters (`INCR` + `EXPIRE`), applied as an
explicit dependency.

| Limit | Key | Applied to |
| --- | --- | --- |
| 5 / minute / client IP | `rl:login:ip:{ip}:{minute}` | `POST /auth/login` |
| 10 / hour / email, **failures only** | `rl:login:email:{email}:{hour}` | `POST /auth/login` |
| 5 / minute / client IP | `rl:pwchange:ip:{ip}:{minute}` | `POST /auth/change-password` |

Exceeding either returns `429 RATE_LIMITED`.

**Failures only, and success resets the email counter.** A raw per-email counter is a lockout
weapon — anyone who knows a colleague's address can spend ten bad guesses an hour to keep them
out. Counting only failures does not eliminate that, but it stops legitimate logins from
consuming the budget. The email counter is incremented *after* a failed credential check and
deleted on success. The IP counter is incremented *before*, so it also bounds attempts against
unknown addresses (which is what makes it the enumeration-resistant half of the pair).

**`change-password` is limited too**, beyond what `docs/PRD.md:115` specifies: it verifies
`currentPassword`, so leaving it uncapped while login is capped just moves the target.

**Client IP.** `docs/PRD.md:304` puts Caddy in front, so `request.client.host` is Caddy for
every request; without correction, "5/min/IP" silently becomes "5/min for the entire instance"
and two mistyped passwords lock everybody out. A `trusted_proxy_hops: int = 0` setting selects
the entry that many hops from the **right** of `X-Forwarded-For`, so a client cannot spoof past
the limit by sending its own header. `0` means use `request.client.host` and ignore the header
entirely.

**Redis unreachable** → log with `exc_info=True` at `error` and allow the request (D18).

---

## 10. Access resolver — the phase-2 seam

`app/core/access.py`:

```python
@dataclass(frozen=True, slots=True)
class ProjectScope:
    """Which projects a caller may read."""
    unrestricted: bool
    ids: frozenset[UUID]

    @classmethod
    def all(cls) -> "ProjectScope": ...
    @classmethod
    def of(cls, ids: Iterable[UUID]) -> "ProjectScope": ...


def resolve_project_scope(user: AuthenticatedUser) -> ProjectScope:
    """Phase 1: every project on the instance. Phase 2 replaces this body."""
    return ProjectScope.all()
```

An explicit type rather than `list[UUID] | None`, because a sentinel `None` meaning
"unrestricted" is fail-open — any accidental `None` would read as full access. `ProjectScope`
forces the caller to branch on `unrestricted` deliberately, and at M1 the Qdrant filter builder
is the single place that does so.

`.claude/rules/router.md:100-102` currently writes the resolver as returning a plain list; it is
updated to this signature in the same change (§13).

Shipped with a test asserting the phase-1 contract — any user, admin or not, gets
`unrestricted` — so `docs/PRD.md:359`'s "read scoping happens in exactly one function, confirmed
by grep" has something to point at from M0 onward, and the phase-2 change is a visible diff to
one function and one test.

---

## 11. Configuration

New `Settings` fields in `app/config.py`, each with a matching `backend/.env.example` entry:

| Setting | Default | Notes |
| --- | --- | --- |
| `secret_key` | `"dev-insecure-change-me"` | JWT signing. Rejected at startup when `app_env == "production"` |
| `access_token_ttl_minutes` | `15` | `docs/PRD.md:106` |
| `refresh_token_ttl_days` | `30` | `docs/PRD.md:106` |
| `refresh_cookie_name` | `"askrepo_refresh"` | |
| `refresh_cookie_path` | `"/auth"` | the cookie is only ever sent to auth routes |
| `refresh_cookie_secure` | `True` | must be `True` in production; makes TLS a hard requirement |
| `refresh_cookie_samesite` | `"lax"` | `lax` covers same-site deployments including `localhost:3000` → `localhost:8000`; a genuinely cross-site deployment needs `none` (which requires `secure=True`) |
| `refresh_rotation_grace_seconds` | `10` | D12 |
| `bootstrap_admin_emails` | `["superuser@example.com", "admin@example.com"]` | `docs/PRD.md:62` |
| `bootstrap_admin_password` | `None` | `seed-admins` exits non-zero if unset |
| `password_min_length` | `12` | |
| `password_max_bytes` | `72` | bcrypt's truncation boundary (D24) — not tunable upward without changing algorithm |
| `bcrypt_cost` | `12` | raising it later re-hashes existing accounts on their next login (D22) |
| `login_rate_per_minute_ip` | `5` | |
| `login_rate_per_hour_email` | `10` | |
| `trusted_proxy_hops` | `0` | §9 |

`database_url`'s default changes from `postgresql://…` to `postgresql+asyncpg://…` in both
`config.py` and `.env.example`.

`refresh_cookie_secure` defaults to `True` even in development: modern browsers treat
`http://localhost` as a secure context, so a `Secure` cookie is still set there. Defaulting to
`False` would make the development path diverge from production in exactly the mechanism hardest
to notice is broken.

Startup validation (in `create_app`, so it fails fast and loudly): when
`app_env == "production"`, reject the placeholder `secret_key` and reject
`refresh_cookie_secure=False`. `bootstrap_admin_password` is not validated at startup — it is
only needed by the seed command, which does its own checking (§8), so an instance that has
already been seeded does not need the variable present to boot.

### Session lifecycle (`app/db/session.py`)

The engine and sessionmaker are built **lazily** from `get_settings()`, not at import time. This
is not stylistic: the middleware builds its own session from the sessionmaker rather than
through `Depends` (D11), so a test that only overrides the `get_session` dependency would leave
the middleware talking to the development database. Lazy construction means a settings override
reaches both paths.

`get_session` yields an `AsyncSession` per request and closes it; services own commits.

---

## 12. Testing

### Fixtures

- **Session-scoped:** create `askrepo_test` on the `make infra` Postgres if absent, run
  `alembic upgrade head` against it. Never `create_all` — the migrations are the thing under
  test, and the partial unique index has to be exercised exactly as shipped.
- **Function-scoped:** `TRUNCATE <all tables> CASCADE` before each test. Not a rolled-back outer
  transaction: services commit, and the savepoint-restart recipe required to make rollback
  survive a commit is the fragile kind of clever.
- **Redis:** DB index 15, flushed per test.
- Settings overridden so `database_url` points at `askrepo_test`, reaching both `get_session`
  and the middleware (§11).

### Cases that must exist

Auth flow:

1. Seeded admin logs in → `200`, `mustChangePassword` true in the response user.
2. That admin calls `GET /users` → `403 PASSWORD_CHANGE_REQUIRED`.
3. Same admin calls `GET /auth/me` → `200`. And `POST /auth/refresh` → `200`. (D5)
4. Change password → `200`; `GET /users` now `200` with the *same* access token.
5. Weak password (short, and in the wordlist) → `400 WEAK_PASSWORD` for both.
6. Unknown email and wrong password both return `401 INVALID_CREDENTIALS`, identical bodies.
6a. A row stored at a lower bcrypt cost is transparently re-hashed on successful login, and the
    old hash still verifies before that happens. (D22)
6b. A password of 73 bytes → `400 WEAK_PASSWORD`. A 24-character CJK passphrase exceeding 72
    bytes → also rejected, proving the check counts bytes rather than characters. And two
    distinct 80-byte passwords sharing their first 72 bytes must **not** both authenticate —
    that is the truncation bug D24 exists to prevent, so it is asserted directly rather than
    inferred from the length check.

Refresh chain:

7. Rotate once, then replay the consumed token after the grace window → `401
   REFRESH_TOKEN_REUSED`, and every row in the family has `revoked_at` set.
8. Two refreshes with the same token inside the grace window → both `200`, two live sibling
   tokens in the family, family not revoked. A third use of that same token *after* the window
   → `401 REFRESH_TOKEN_REUSED` and the family revoked. (D12)
9. Refresh after `logout-all` → `401`.

Access control:

10. Non-admin `POST /users` → `403 ADMIN_REQUIRED`.
11. Non-admin `GET /users` → `200`. (D15)
12. Soft-delete a user, then use their still-unexpired access token → `401`. (Immediate
    deactivation; the reason D11 loads the row per request.)
13. Deleting or demoting the only admin → `409 LAST_ADMIN`.

Contract:

14. The gate's `403` carries `access-control-allow-origin`. (§6 — asserts the property, not the
    middleware ordering.)
15. `RequestValidationError` produces `{detail: {code, message, fields}}` with `camelCase` field
    keys.
16. No response body in any test contains `password_hash`, `passwordHash`, a bcrypt prefix
    (`$2b$`), or a raw refresh token.
17. Route-coverage walk: every mounted path is open-by-declaration or behind
    `CurrentUser`/`AdminUser`.
18. `resolve_project_scope` returns `unrestricted` for an admin and a non-admin alike.

Rate limiting:

19. Sixth login attempt within a minute → `429 RATE_LIMITED`.
20. Successful login resets the per-email failure counter.
21. Redis unavailable → login still succeeds. (D18)

Seeding:

22. `seed-admins` twice → two users, not four, and the second run reports skips.
23. `seed-admins` with `BOOTSTRAP_ADMIN_PASSWORD` unset → non-zero exit, no rows written.
24. `seed-admins` with a password failing policy → non-zero exit, no rows written.

### Tooling

`mypy` added as a dev dependency with a backend config block; `Makefile:131`'s `typecheck`
target gains `cd backend && uv run mypy .` alongside the existing `tsc` run (D19). SQLAlchemy 2.0
ships PEP 484 typing natively, so no mypy plugin and no `sqlalchemy2-stubs` are involved — the
deprecated plugin approach belongs to 1.4.

---

## 13. Documentation and rules changed in the same commit

`.claude/rules/documentation.md` makes these part of this change, not a follow-up.

### `docs/PRD.md` (source of truth — amended, not silently diverged from)

- **Passwords are hashed with bcrypt, not argon2id** (D23). Four locations, all of which name
  argon2id explicitly and must change together, or the PRD contradicts the code in the section a
  reader would check first: `docs/PRD.md:73` (the `User` schema comment), `:110` (the password
  policy), `:301` (the tech-stack table's Auth row), `:382` (§9's brute-force mitigation). §4.0's
  policy line also gains the 72-byte maximum (D24), which is a new constraint the PRD does not
  currently state at all.
- §4.0: refresh token travels as an httpOnly cookie, access token in the body (D3).
- §4.0: the gate covers "every route outside `/auth`" rather than "every route except
  `POST /auth/change-password`" (D5).
- §4.0: reset-password takes an admin-supplied password (D16).
- §4.0: the login limiter also covers `change-password`; the per-email limit counts failures
  only (§9).
- §4.0: new acceptance criterion — the last active admin cannot be demoted or deleted (D17).
- §4.0/§3: `GET /users` and `GET /users/{id}` are open to any authenticated user; mutations are
  admin-only (D15).
- §5.1: the structured error `detail` contract (D4).
- §5.1: `refresh_tokens` is an explicit exception to "every table carries `deleted_at`" (D14);
  the convention is scoped to user-facing resources.
- §5.1/§4.1: the access resolver returns `ProjectScope`, not a list (D9, §10).
- §5: `BackgroundTasks` row unaffected; the ORM row gains `refresh_tokens` (already listed).

### Rules

- **`.claude/rules/router.md`** — handler examples become `async def`; the `CurrentUser` alias
  annotates `AuthenticatedUser`; the resolver example uses `ProjectScope`; a note that `/users`
  splits dependencies per route rather than router-level.
- **`.claude/rules/response-api.md`** — the structured `detail` shape and `ErrorCode`; the
  reshaped `422`; `429` is declared on routes carrying a limiter dependency rather than
  universally (D7).
- **New `.claude/rules/persistence.md`** — models/repositories/services layering, the
  `BaseRepository` soft-delete guarantee, `select` only in repositories, migration conventions,
  bulk-update `updated_at`, lazy engine construction.

### Other docs

- **`CLAUDE.md`** — "Nine rule files" becomes **ten** and the table gains a row; "Status: pre-M0"
  is corrected; the "Datastores are wired but unread" section is rewritten (Postgres and Redis
  are now read); the commands section gains `make seed`; the architecture notes gain the
  layering and error-contract facts.
- **`README.md`** — status banner, M0 roadmap checkbox, quick-start including `make seed`,
  service table if ports change (they do not).
- **`backend/README.md`** — exhaustive route table for `/auth` and `/users`, the new config
  values, the new layout, the new dev commands (`alembic`, `python -m app.cli`, the `make infra`
  test prerequisite).
- **`backend/.env.example`** — every setting in §11, plus the `+asyncpg` driver change.
- **`SECURITY.md`** — `BOOTSTRAP_ADMIN_PASSWORD` as an operator secret; the `Secure` cookie flag
  makes TLS a hard requirement rather than a nicety; the Redis fail-open behaviour stated
  plainly so an operator knows what a Redis outage costs them.
- **`CONTRIBUTING.md`** — `make check` now requires `make infra` first; `typecheck` covers the
  backend.
- **`infra/docker-compose.yml`** — backend entrypoint becomes
  `alembic upgrade head && python -m app.cli seed-admins && uvicorn …`; new environment
  variables; header comment updated if the service list changes (it does not).
- **`Makefile`** — `seed` target; `typecheck` gains mypy.

---

## 14. M0 done means

Traceable to `docs/PRD.md` §7:

- A fresh instance comes up, a seeded admin logs in, is forced to change the initial password,
  and creates an account for a colleague — no manual database work. (Automated, §12 cases 1–4.)
- No password, hash, or token appears in any response body. (§12 case 16.)
- Deactivating a user ends their session immediately, not in 15 minutes. (§12 case 12.)
- Replay of a consumed refresh token revokes that device's chain. (§12 case 7.)
- Login brute force is capped, and a Redis outage does not lock the team out. (§12 cases 19–21.)
- Read scoping exists in exactly one function, with a test pinning its phase-1 contract. (§12
  case 18.)
- Every doc in §13 matches the code as committed.

## 15. Known debt carried forward

- **No CI workflow.** Tests now require Postgres and Redis; that prerequisite lives only in
  `CONTRIBUTING.md` until a workflow exists.
- **Expired `refresh_tokens` rows are never pruned.** Harmless at this scale; a cleanup path
  belongs with the ARQ worker at M1, which is the first time the project has a scheduler.
- **The vendored wordlist ages.** Acceptable — the 12-character minimum does most of the work.
- **Frontend auth and the app shell** are unbuilt; `docs/design.md`'s M0 component rows stay
  uninstalled until that spec lands.
