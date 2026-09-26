# Profile Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user gets a `/profile` page — account and memberships, their own
sessions with per-session revoke, their own audit activity, notification preferences, and
password change — and a password change stops signing them out of the session they changed
it from.

**Architecture:** The access JWT gains a `sid` claim carrying the refresh-token family id,
which is how the backend identifies "this session" without the refresh cookie the BFF proxy
strips. Four caller-scoped routes under a new, gated `/me` prefix serve the page;
membership is read through `app/core/access.py` only. The frontend adds one page in the app
shell, reached from the account menu, and moves notification preferences onto it.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest (backend, `uv`); Next.js 16 +
React 19 + TanStack Query + Vitest + Testing Library (frontend, `bun`).

**Spec:** `docs/superpowers/specs/2026-09-26-profile-page-design.md` — read it before any
task. Where this plan and the spec disagree, the spec wins; stop and report.

## Global Constraints

- Every JSON body is camelCase: every request/response model inherits `ApiModel` (`app/schemas/base.py`). `tests/test_api_model.py` walks only the SSE models, so the camelCase key assertions in `tests/test_me_api.py` are what check the `/me` shapes.
- Nothing outside `app/core/access.py` (and the allowlist in `tests/test_scoping_is_single_point.py`) may name `ProjectMembership`.
- `/me` is **not** added to `GATE_EXEMPT_PREFIXES`.
- No `/me` route takes a user id. Another user's session id is `404 SESSION_NOT_FOUND`, never `403`.
- Audit events are recorded **after** the commit, from plain locals (`.claude/rules/audit-trail.md`).
- `ErrorCode` and `AuditEventType` members are added, never renamed.
- One service call per route (`.claude/rules/router.md`).
- Frontend: design tokens only — no `dark:` colour utility, no palette utility (`bg-zinc-50`), no raw hex. shadcn/Base UI composed with `render={...}`, never `asChild`.
- `# noqa` / `# type: ignore` need a reason on the same line.
- Backend commands run from `backend/`, frontend commands from `frontend/`.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Never push. Never commit to `main` — work is on `feat/profile-page`.

## File map

**Backend — modified:** `app/core/security.py`, `app/core/middleware.py`,
`app/core/access.py`, `app/core/audit.py`, `app/core/errors.py`, `app/models/refresh_token.py`,
`app/repositories/refresh_token.py`, `app/repositories/audit_event.py`,
`app/services/auth.py`, `app/api/routes/auth.py`, `app/main.py`.

**Backend — created:** `alembic/versions/d4a9e6b27c15_add_refresh_token_device.py`,
`app/schemas/me.py`, `app/services/me.py`, `app/api/routes/me.py`, `tests/test_me_api.py`.

**Backend tests — modified:** `tests/test_security.py`, `tests/test_auth_api.py`,
`tests/test_client_address.py`, `tests/test_audit_coverage.py`,
`tests/test_audit_write_sites.py`, `tests/test_access.py`.

**Frontend — created:** `lib/user-agent.ts` (+ test), `lib/auth/user-agent-header.ts`
(+ test), `hooks/use-profile.ts`, `app/(app)/profile/page.tsx`,
`components/profile/profile-screen.tsx`, `components/profile/account-section.tsx`,
`components/profile/sessions-section.tsx` (+ test), `components/profile/activity-section.tsx`,
`components/profile/password-section.tsx` (+ test).

**Frontend — modified:** `app/api/auth/login/route.ts`, `lib/api/types.ts`,
`lib/api/endpoints.ts`, `lib/query/keys.ts`, `lib/audit.ts`, `lib/nav.ts`, `lib/nav.test.ts`,
`lib/settings-nav.ts`, `hooks/use-change-password.ts`,
`app/(app)/settings/notifications/page.tsx`, `app/(app)/settings/page.tsx` (comment only),
`components/notifications/preferences-screen.tsx`, `components/layout/account-menu.tsx`.

**Frontend — deleted:** `components/users/change-password-dialog.tsx`.

**Docs:** `docs/PRD.md`, `.claude/rules/audit-trail.md`, `.claude/rules/navigation.md`,
`docs/data.md`, `docs/notifications.md`, `backend/README.md`, `frontend/README.md`,
`CLAUDE.md`, `CHANGELOG.md`.

---

### Task 1: The `sid` claim, and password change keeps the caller's session

Reproduce the defect first. **If Step 2's test passes against unchanged code, stop and
report** — the spec's premise (§1.10) would be wrong.

**Files:**
- Modify: `backend/app/core/security.py:99-131`
- Modify: `backend/app/core/middleware.py` (`AuthenticatedUser`, `_resolve`)
- Modify: `backend/app/repositories/refresh_token.py:87-107`
- Modify: `backend/app/services/auth.py` (`_issue`, `change_password`)
- Modify: `backend/app/api/routes/auth.py:194-214`
- Test: `backend/tests/test_auth_api.py`, `backend/tests/test_security.py`
- Docs: `CHANGELOG.md`

**Interfaces:**
- Produces: `AccessClaims(user_id: uuid.UUID, session_id: uuid.UUID | None)` and
  `decode_access_claims(token: str, *, secret: str) -> AccessClaims` in `app/core/security.py`;
  `create_access_token(user_id, *, secret, ttl_minutes, session_id: uuid.UUID | None = None)`;
  `AuthenticatedUser.session_id: uuid.UUID | None` (default `None`);
  `RefreshTokenRepository.revoke_all_for_user(user_id, *, reason, except_family_id: uuid.UUID | None = None) -> int`;
  `AuthService.change_password(user_id, payload, session_id: uuid.UUID | None) -> UserResponse`.

- [ ] **Step 1: Write the failing reproduction test**

Append to `backend/tests/test_auth_api.py`:

```python
async def test_change_password_without_the_cookie_spares_the_callers_own_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The BFF proxy strips `cookie` from every forwarded request
    (`frontend/app/api/[...path]/route.ts`), so this is how a real browser's change
    arrives. The caller's session must survive it; every other session must not."""
    await _make_user(db_session)
    access, own_cookie = await _login(client)
    _, other_cookie = await _login(client)

    client.cookies.clear()
    response = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    _present_cookie(client, own_cookie)
    own_session = await client.post("/auth/refresh")
    _present_cookie(client, other_cookie)
    other_session = await client.post("/auth/refresh")

    assert own_session.status_code == 200
    assert other_session.status_code == 401
```

- [ ] **Step 2: Run it and confirm it fails for the stated reason**

Run: `uv run pytest tests/test_auth_api.py::test_change_password_without_the_cookie_spares_the_callers_own_session -v`
Expected: FAIL at `assert own_session.status_code == 200` (actual `401`). Any other
failure, or a pass, means stop and report.

- [ ] **Step 3: Write the security tests for the claim**

Append to `backend/tests/test_security.py` (add `AccessClaims, decode_access_claims` to the
existing `from app.core.security import (...)` block):

```python
def test_access_token_carries_the_session_id_when_given() -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(
        user_id, secret=SECRET, ttl_minutes=15, session_id=session_id
    )

    assert jwt.decode(token, SECRET, algorithms=["HS256"])["sid"] == str(session_id)
    assert decode_access_claims(token, secret=SECRET) == AccessClaims(
        user_id=user_id, session_id=session_id
    )


def test_a_token_without_sid_decodes_to_no_session() -> None:
    """Tokens minted before `sid` existed stay valid until they expire."""
    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id, secret=SECRET, ttl_minutes=15)

    assert decode_access_claims(token, secret=SECRET) == AccessClaims(
        user_id=user_id, session_id=None
    )


def test_decoding_rejects_a_non_uuid_session() -> None:
    claims = {
        "sub": str(uuid.uuid4()),
        "sid": "not-a-uuid",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalidError):
        decode_access_claims(token, secret=SECRET)
```

Leave `test_access_token_carries_no_authorisation_claims` untouched: with no
`session_id`, the claim set must stay exactly `{"sub", "iat", "exp", "jti", "typ"}`.

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL — `ImportError: cannot import name 'AccessClaims'`.

- [ ] **Step 5: Implement the claim in `app/core/security.py`**

Add `from dataclasses import dataclass` to the imports if absent. Replace
`create_access_token` and `decode_access_token` with:

```python
@dataclass(frozen=True, slots=True)
class AccessClaims:
    """What an access token asserts: who, and which sign-in it belongs to.

    `session_id` is the refresh-token `family_id`. It is how the backend tells one of a
    user's sessions from another without the refresh cookie, which the BFF proxy never
    forwards. `None` only for a token minted before the claim existed.
    """

    user_id: uuid.UUID
    session_id: uuid.UUID | None


def create_access_token(
    user_id: uuid.UUID,
    *,
    secret: str,
    ttl_minutes: int,
    session_id: uuid.UUID | None = None,
) -> tuple[str, int]:
    """Mint a signed access token. Returns the token and its lifetime in seconds.

    Deliberately carries no `is_admin` or `must_change_password` claim: both would go
    stale for up to `ttl_minutes`, and `docs/PRD.md:101` requires deactivation to end
    a session immediately. `sid` is safe to carry because it never changes for the
    life of a session.
    """
    issued_at = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl_minutes),
        "jti": str(uuid.uuid4()),
        "typ": _ACCESS_TOKEN_TYPE,
    }
    if session_id is not None:
        claims["sid"] = str(session_id)
    token = jwt.encode(claims, secret, algorithm=_ACCESS_TOKEN_ALGORITHM)
    return token, ttl_minutes * 60


def decode_access_claims(token: str, *, secret: str) -> AccessClaims:
    """Verify an access token and return what it asserts."""
    try:
        claims = jwt.decode(token, secret, algorithms=[_ACCESS_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenExpiredError(str(error)) from error
    except jwt.PyJWTError as error:
        raise TokenInvalidError(str(error)) from error

    if claims.get("typ") != _ACCESS_TOKEN_TYPE:
        raise TokenInvalidError("token is not an access token")
    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as error:
        raise TokenInvalidError("token subject is not a UUID") from error
    raw_session = claims.get("sid")
    try:
        session_id = uuid.UUID(raw_session) if raw_session is not None else None
    except ValueError as error:
        raise TokenInvalidError("token session is not a UUID") from error
    return AccessClaims(user_id=user_id, session_id=session_id)


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    """Verify an access token and return the user id it identifies."""
    return decode_access_claims(token, secret=secret).user_id
```

- [ ] **Step 6: Run the security tests**

Run: `uv run pytest tests/test_security.py -v`
Expected: PASS (all, including the untouched claim-set test).

- [ ] **Step 7: Carry the session on `AuthenticatedUser`**

In `backend/app/core/middleware.py`:

1. Change the import to
   `from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_claims`.
2. Add this field as the **last** field of `AuthenticatedUser`, after `grants`:

```python
    # The refresh-token family this request's access token was minted for — which of
    # the user's sessions is calling. `None` for a token minted before the `sid` claim.
    session_id: uuid.UUID | None = None
```

3. In `_resolve`, replace the `decode_access_token(...)` call and its use:

```python
        try:
            claims = decode_access_claims(
                header.removeprefix(_BEARER_PREFIX), secret=settings.secret_key
            )
        except TokenExpiredError:
            return AuthContext(user=None, error=ErrorCode.TOKEN_EXPIRED)
        except TokenInvalidError:
            return AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)
```

   then `UserRepository(session).get(claims.user_id)`, and pass
   `session_id=claims.session_id` to the `AuthenticatedUser(...)` constructor.

- [ ] **Step 8: Spare a family, not a token id**

In `backend/app/repositories/refresh_token.py`, replace `revoke_all_for_user` with:

```python
    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        reason: RevokedReason,
        except_family_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every unrevoked token for one user. Returns the count.

        `except_family_id` spares the caller's own session — every token in it, not one
        row — which is what `docs/PRD.md:108` means by revoking all *other* refresh
        tokens on a password change. A family is the session; sparing one token id was
        only ever right for the family's newest token.
        """
        statement = update(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        if except_family_id is not None:
            statement = statement.where(RefreshToken.family_id != except_family_id)
        result = await self.session.execute(
            statement.values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return cast(CursorResult[Any], result).rowcount
```

Run: `grep -rn "except_token_id" app tests` — expected: only the docstring in
`tests/test_auth_api.py::test_change_password_revokes_other_sessions_with_reason`. Change
that docstring's `except_token_id` to `except_family_id`.

- [ ] **Step 9: Mint `sid` and use it in `change_password`**

In `backend/app/services/auth.py`, in `_issue`, compute the family once and pass it to both
tokens:

```python
        family = family_id or uuid.uuid4()
        access_token, expires_in = create_access_token(
            user.id,
            secret=self.settings.secret_key,
            ttl_minutes=self.settings.access_token_ttl_minutes,
            session_id=family,
        )
        raw_refresh = generate_opaque_token()
        await self.tokens.create(
            user_id=user.id,
            family_id=family,
            token_hash=sha256_hex(raw_refresh),
            expires_at=expires_at
            or datetime.now(UTC) + timedelta(days=self.settings.refresh_token_ttl_days),
        )
```

Replace `change_password`'s signature and revocation block:

```python
    async def change_password(
        self,
        user_id: uuid.UUID,
        payload: ChangePasswordRequest,
        session_id: uuid.UUID | None,
    ) -> UserResponse:
        """Change the caller's own password, keeping their current session alive."""
```

```python
        # Revoke all *other* sessions (docs/PRD.md:108). The caller's session is the one
        # their access token names: the refresh cookie never reaches this route through
        # the BFF proxy. A token minted before `sid` names none, so every session goes —
        # the old behaviour, for at most one access-token lifetime after deploy.
        await self.tokens.revoke_all_for_user(
            user.id, reason="password_change", except_family_id=session_id
        )
```

Remove the now-unused `current = await self.tokens.get_by_hash(...)` line.

- [ ] **Step 10: Stop reading the cookie in the route**

In `backend/app/api/routes/auth.py`, replace the `change_password` route with:

```python
@router.post(
    "/change-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change your own password",
    description=(
        "Revokes every other session. The caller's own session — the one its access "
        "token names — stays signed in."
    ),
    dependencies=[Depends(enforce_password_change_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422, 429)},
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    service: AuthServiceDep,
) -> UserResponse:
    return await service.change_password(current_user.id, payload, current_user.session_id)
```

Leave `_read_refresh_cookie` in place — refresh and logout still use it.

- [ ] **Step 11: Add the remaining auth tests**

Append to `backend/tests/test_auth_api.py` (add `import jwt` and
`from app.core.security import create_access_token` to the imports):

```python
async def test_change_password_with_a_pre_sid_token_revokes_every_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A token minted before the claim names no session, so none is spared."""
    user = await _make_user(db_session)
    _, own_cookie = await _login(client)
    legacy, _ = create_access_token(
        user.id, secret=get_settings().secret_key, ttl_minutes=15
    )

    client.cookies.clear()
    await client.post(
        "/auth/change-password",
        headers=_bearer(legacy),
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    _present_cookie(client, own_cookie)

    assert (await client.post("/auth/refresh")).status_code == 401


async def test_the_forced_change_keeps_its_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The first-login flow goes through the same proxy, so it had the same defect."""
    await _make_user(db_session, must_change_password=True)
    access, cookie = await _login(client)

    client.cookies.clear()
    await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    _present_cookie(client, cookie)

    assert (await client.post("/auth/refresh")).status_code == 200


async def test_the_access_token_names_its_refresh_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, cookie = await _login(client)
    row = await db_session.execute(
        text("SELECT family_id FROM refresh_tokens WHERE token_hash = :hash"),
        {"hash": sha256_hex(cookie)},
    )
    family_id = row.scalar_one()
    secret = get_settings().secret_key

    assert jwt.decode(access, secret, algorithms=["HS256"])["sid"] == str(family_id)

    _present_cookie(client, cookie)
    refreshed = (await client.post("/auth/refresh")).json()["accessToken"]
    assert jwt.decode(refreshed, secret, algorithms=["HS256"])["sid"] == str(family_id)
```

- [ ] **Step 12: Run the auth, security and middleware suites**

Run: `uv run pytest tests/test_auth_api.py tests/test_security.py tests/test_auth_middleware.py tests/test_middleware_grants.py tests/test_access.py -v`
Expected: PASS, including Step 1's reproduction test.

- [ ] **Step 13: Record the fix in the CHANGELOG**

In `CHANGELOG.md`, under `## [Unreleased]`, add a `### Fixed` heading after the existing
`### Changed` section of that release (create it; it does not exist yet) with:

```markdown
- **Changing your password no longer signs you out of the session you changed it from.**
  The backend looked for the caller's session in the refresh cookie, which the frontend's
  API proxy never forwards, so every session was revoked — the caller's included — and they
  were sent to the sign-in page within 15 minutes. Access tokens now carry a `sid` claim
  naming their session, and the change spares that one. This affected the forced
  first-login change too.
```

- [ ] **Step 14: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors.

```bash
git add backend/app/core/security.py backend/app/core/middleware.py \
  backend/app/repositories/refresh_token.py backend/app/services/auth.py \
  backend/app/api/routes/auth.py backend/tests/test_auth_api.py \
  backend/tests/test_security.py CHANGELOG.md
git commit -m "fix(auth): keep the caller's session through a password change

The backend spared the caller's session by reading the refresh cookie,
which the BFF proxy strips, so every session was revoked. Access tokens
now carry a sid claim naming their refresh family, and change_password
spares that family.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Device information on refresh tokens

**Files:**
- Create: `backend/alembic/versions/d4a9e6b27c15_add_refresh_token_device.py`
- Modify: `backend/app/models/refresh_token.py`
- Modify: `backend/app/repositories/refresh_token.py` (`create`)
- Modify: `backend/app/services/auth.py` (`__init__`, `_issue`, three call sites)
- Modify: `backend/app/api/routes/auth.py` (`get_auth_service`)
- Create: `frontend/lib/auth/user-agent-header.ts`, `frontend/lib/auth/user-agent-header.test.ts`
- Modify: `frontend/app/api/auth/login/route.ts`
- Test: `backend/tests/test_client_address.py`

**Interfaces:**
- Consumes: Task 1's `_issue` (family computed once, `session_id=family`).
- Produces: `RefreshToken.user_agent: str | None`, `RefreshToken.ip_address: str | None`;
  `RefreshTokenRepository.create(..., user_agent: str | None = None, ip_address: str | None = None)`;
  `AuthService(..., user_agent: str | None = None)`;
  `AuthService._issue(user, *, parent: RefreshToken | None = None, expires_at: datetime | None = None)`;
  `userAgentHeader(request: Request): Record<string, string>` in `frontend/lib/auth/user-agent-header.ts`.

- [ ] **Step 1: Write the failing backend tests**

Append to `backend/tests/test_client_address.py` (add `from sqlalchemy import text` and
`from app.core.security import sha256_hex` to its imports):

```python
async def _device_of(session: AsyncSession, cookie: str) -> tuple[str | None, str | None]:
    row = await session.execute(
        text("SELECT user_agent, ip_address FROM refresh_tokens WHERE token_hash = :hash"),
        {"hash": sha256_hex(cookie)},
    )
    return tuple(row.one())


async def test_a_session_records_the_device_it_started_on(
    behind_a_proxy: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    response = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.9", "user-agent": "Mozilla/5.0 (Test)"},
    )
    cookie = response.cookies[get_settings().refresh_cookie_name]

    assert await _device_of(db_session, cookie) == ("Mozilla/5.0 (Test)", "203.0.113.9")


async def test_rotation_keeps_the_device_the_session_started_on(
    behind_a_proxy: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """A refresh arrives from the Next server, not the browser — copying the parent's
    values is what keeps the session describing the browser that signed in."""
    await _make_user(db_session)
    login = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.9", "user-agent": "Mozilla/5.0 (Test)"},
    )
    name = get_settings().refresh_cookie_name
    client.cookies.set(name, login.cookies[name])
    refreshed = await client.post(
        "/auth/refresh", headers={"x-forwarded-for": "198.51.100.1", "user-agent": "node"}
    )

    assert await _device_of(db_session, refreshed.cookies[name]) == (
        "Mozilla/5.0 (Test)",
        "203.0.113.9",
    )


async def test_an_overlong_user_agent_is_truncated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    response = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"user-agent": "x" * 1000},
    )
    cookie = response.cookies[get_settings().refresh_cookie_name]

    user_agent, _ = await _device_of(db_session, cookie)
    assert user_agent == "x" * 255
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_client_address.py -k "device or rotation_keeps or overlong" -v`
Expected: FAIL — `column "user_agent" does not exist`.

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/d4a9e6b27c15_add_refresh_token_device.py`:

```python
"""add refresh token device

Revision ID: d4a9e6b27c15
Revises: c3f8a1d05e72
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a9e6b27c15"
down_revision: str | Sequence[str] | None = "c3f8a1d05e72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens", sa.Column("user_agent", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "refresh_tokens", sa.Column("ip_address", sa.String(length=45), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "ip_address")
    op.drop_column("refresh_tokens", "user_agent")
```

Verify `c3f8a1d05e72` is still the head: `uv run alembic heads` — expected output names
`c3f8a1d05e72` before this file exists. If another head appears, set `down_revision` to it.

- [ ] **Step 4: Add the columns to the model and the repository**

In `backend/app/models/refresh_token.py`, after `revoked_reason`:

```python
    # The browser a session started on, captured at login and copied forward on every
    # rotation — a refresh arrives from the Next server, not the browser. Shown to the
    # user on their profile so they can tell one session from another. `ip_address`
    # matches `audit_events.ip_address`: 45 characters fits any IPv6 textual form.
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
```

In `backend/app/repositories/refresh_token.py`, extend `create`:

```python
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        """Insert a token. A rotation successor reuses the parent's `family_id`."""
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return await self.add(token)
```

- [ ] **Step 5: Thread the device through `AuthService`**

In `backend/app/services/auth.py`:

1. Add a module constant below `logger`:

```python
# `refresh_tokens.user_agent` is `String(255)`. A header is client-controlled and
# unbounded, so it is cut rather than rejected — a long agent is not an attack worth
# refusing a login over.
MAX_USER_AGENT_LENGTH = 255
```

2. Add `user_agent: str | None = None` as a keyword parameter to `__init__` and store
   `self._user_agent = user_agent[:MAX_USER_AGENT_LENGTH] if user_agent else None`.

3. Replace `_issue`'s `family_id` parameter with `parent`:

```python
    async def _issue(
        self,
        user: User,
        *,
        parent: RefreshToken | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[AccessTokenResponse, str]:
        """Mint an access token and a refresh token, storing only the latter's digest.

        With no `parent` this starts a session: a new family, and the device this
        request came from. With one it continues that session: the parent's family,
        and the parent's device — a rotation arrives from the Next server, so its own
        agent and address describe the proxy, not the person.

        `expires_at` defaults to a fresh `now + refresh_token_ttl_days`. The grace-window
        sibling path (see `refresh`) passes the *parent's* `expires_at` instead, so a
        hijacked chain is capped at the original token's remaining lifetime rather than
        renewing itself indefinitely on every rotation.
        """
        family = parent.family_id if parent else uuid.uuid4()
        access_token, expires_in = create_access_token(
            user.id,
            secret=self.settings.secret_key,
            ttl_minutes=self.settings.access_token_ttl_minutes,
            session_id=family,
        )
        raw_refresh = generate_opaque_token()
        await self.tokens.create(
            user_id=user.id,
            family_id=family,
            token_hash=sha256_hex(raw_refresh),
            expires_at=expires_at
            or datetime.now(UTC) + timedelta(days=self.settings.refresh_token_ttl_days),
            user_agent=parent.user_agent if parent else self._user_agent,
            ip_address=parent.ip_address if parent else self._client_ip,
        )
        response = AccessTokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )
        return response, raw_refresh
```

4. Update the two rotation call sites in `refresh`:
   - `self._issue(user, family_id=token.family_id, expires_at=token.expires_at)` →
     `self._issue(user, parent=token, expires_at=token.expires_at)`
   - `self._issue(user, family_id=token.family_id)` → `self._issue(user, parent=token)`

   `_authenticate_and_issue`'s `self._issue(user)` is unchanged.
   Run `grep -rn "_issue(" app` — expected: exactly those three call sites.

5. In `backend/app/api/routes/auth.py`, add `Header` to the `fastapi` import and extend
   `get_auth_service`:

```python
def get_auth_service(
    session: SessionDep,
    settings: SettingsDep,
    attempts: LoginAttemptLimiterDep,
    recorder: AuditRecorderDep,
    client_ip: ClientIpDep,
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthService:
```

   and pass `user_agent=user_agent` to `AuthService(...)`. Add one sentence to its
   docstring: "The user agent arrives the same way, and only `login` stores it."

- [ ] **Step 6: Run the backend tests**

Run: `uv run pytest tests/test_client_address.py tests/test_auth_api.py -v`
Expected: PASS. (The session-scoped fixture migrates the test database to head.)

Then check the migration round-trips against the dev database (needs `make infra`):
`uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors.

- [ ] **Step 7: Write the failing frontend test**

Create `frontend/lib/auth/user-agent-header.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { userAgentHeader } from "@/lib/auth/user-agent-header";

function request(headers: Record<string, string>): Request {
  return new Request("http://localhost:3000/api/auth/login", { headers });
}

describe("userAgentHeader", () => {
  it("relays the browser's agent", () => {
    expect(userAgentHeader(request({ "user-agent": "Mozilla/5.0 (Test)" }))).toEqual({
      "user-agent": "Mozilla/5.0 (Test)",
    });
  });

  it("sends nothing when the browser sent none", () => {
    expect(userAgentHeader(request({}))).toEqual({});
  });
});
```

Run: `bun run vitest run lib/auth/user-agent-header.test.ts`
Expected: FAIL — cannot resolve `@/lib/auth/user-agent-header`.

- [ ] **Step 8: Implement and wire the helper**

Create `frontend/lib/auth/user-agent-header.ts`:

```ts
/**
 * Relaying the browser's user agent to the backend, on login only.
 *
 * The login call leaves from the Next server, so without this every session records
 * Node's own agent string and the profile's session list cannot tell a phone from a
 * laptop. Only login needs it: the backend copies a session's device forward on every
 * rotation, because a refresh arrives from here and not from the browser.
 */
export function userAgentHeader(request: Request): Record<string, string> {
  const userAgent = request.headers.get("user-agent");
  return userAgent ? { "user-agent": userAgent } : {};
}
```

In `frontend/app/api/auth/login/route.ts`, import it and extend the upstream headers:

```ts
    headers: {
      "content-type": "application/json",
      ...forwardedHeaders(request),
      ...userAgentHeader(request),
    },
```

Update the comment above that line to: "The caller's address and browser go with it: this
route is rate-limited per caller, and the session records the device it started on."

Run: `bun run vitest run lib/auth/user-agent-header.test.ts`
Expected: PASS.

- [ ] **Step 9: Lint and commit**

Run (backend): `uv run ruff check . && uv run ruff format --check .`
Run (frontend): `bun lint`
Expected: no errors.

```bash
git add backend/alembic/versions/d4a9e6b27c15_add_refresh_token_device.py \
  backend/app/models/refresh_token.py backend/app/repositories/refresh_token.py \
  backend/app/services/auth.py backend/app/api/routes/auth.py \
  backend/tests/test_client_address.py frontend/lib/auth/user-agent-header.ts \
  frontend/lib/auth/user-agent-header.test.ts frontend/app/api/auth/login/route.ts
git commit -m "feat(auth): record the device a session started on

Stores user_agent and ip_address on refresh_tokens at login and copies
them forward on rotation, so a session describes the browser that signed
in rather than the Next server that refreshes it. The login handler now
relays the browser's User-Agent.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `memberships_for` and `GET /me/memberships`

**Files:**
- Modify: `backend/app/core/access.py` (add `memberships_for` beside `role_for`)
- Create: `backend/app/schemas/me.py`, `backend/app/services/me.py`, `backend/app/api/routes/me.py`
- Modify: `backend/app/main.py:161-163` (register the router)
- Test: `backend/tests/test_access.py`, create `backend/tests/test_me_api.py`
- Docs: `backend/README.md` (route table)

**Interfaces:**
- Consumes: `AuthenticatedUser.grants: Mapping[uuid.UUID, ProjectGrant]`;
  `ProjectRepository.names_and_generations(project_ids) -> dict[uuid.UUID, ProjectSummary]`.
- Produces: `memberships_for(user: AuthenticatedUser) -> list[ProjectGrant]`;
  `MembershipSummary(project_id, project_name, role)`; `MeService(session)` with
  `async memberships(user) -> list[MembershipSummary]`; `router = APIRouter(prefix="/me", tags=["Me"])`;
  `MeServiceDep`; test helper `_login(client, email) -> tuple[str, str]` in `tests/test_me_api.py`.

- [ ] **Step 1: Write the failing access test**

Open `backend/tests/test_access.py`, find its existing helper that builds an
`AuthenticatedUser` with `grants=` (line ~29), and append a test in the file's style:

```python
def test_memberships_for_returns_real_grants_even_for_an_admin() -> None:
    """Unlike `resolve_project_scope`, this answers "where am I a member" — an admin's
    unrestricted read does not make them a member of anything."""
    project_id = uuid.uuid4()
    grant = ProjectGrant(project_id=project_id, role="editor", permissions=frozenset())
    admin = AuthenticatedUser(
        id=uuid.uuid4(),
        name="Admin",
        email="admin@example.com",
        is_admin=True,
        must_change_password=False,
        grants={project_id: grant},
    )
    nobody = AuthenticatedUser(
        id=uuid.uuid4(),
        name="Admin",
        email="other@example.com",
        is_admin=True,
        must_change_password=False,
    )

    assert memberships_for(admin) == [grant]
    assert memberships_for(nobody) == []
```

Add `memberships_for` to its `from app.core.access import ...` line and `ProjectGrant` to
its middleware import. Run:
`uv run pytest tests/test_access.py -k memberships_for -v` → FAIL (`ImportError`).

- [ ] **Step 2: Implement `memberships_for`**

In `backend/app/core/access.py`, change the middleware import to
`from app.core.middleware import AuthenticatedUser, ProjectGrant` and add after `role_for`:

```python
def memberships_for(user: AuthenticatedUser) -> list[ProjectGrant]:
    """The projects this caller actually holds a membership on, with the role on each.

    A different question from `resolve_project_scope`: that one answers "what may I
    read", and an administrator may read everything. This answers "where am I a
    member", and an administrator is a member only where someone granted it. Read from
    the snapshot the middleware already loaded — no I/O, and the only membership read
    the profile makes (`tests/test_scoping_is_single_point.py`).
    """
    return list(user.grants.values())
```

Run: `uv run pytest tests/test_access.py -v` → PASS.

- [ ] **Step 3: Write the failing route tests**

Create `backend/tests/test_me_api.py`:

```python
"""The `/me` surface: the caller's own memberships, sessions and activity.

Every route here is scoped to the caller by construction — none takes a user id — so
the tests that matter are the ones proving one user never reaches another's rows.
Clients sign in through `/auth/login` rather than minting a token, because the session
routes need a real refresh family and the `sid` claim that names it.
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User
from tests.conftest import TEST_PASSWORD, GrantMembership
from tests.factories import create_project

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"


async def _login(client: AsyncClient, email: str) -> tuple[str, str]:
    """Sign in and return (access token, raw refresh cookie)."""
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers={"user-agent": UA},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"], response.cookies[get_settings().refresh_cookie_name]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_memberships_lists_the_callers_grants_with_role_names(
    client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    grant_membership: GrantMembership,
) -> None:
    alpha = await create_project(db_session, grant_owner=False, name="alpha")
    beta = await create_project(db_session, grant_owner=False, name="beta")
    await create_project(db_session, grant_owner=False, name="not-mine")
    await db_session.commit()
    await grant_membership(authed_user.id, beta.id, "viewer")
    await grant_membership(authed_user.id, alpha.id, "editor")
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.status_code == 200
    assert response.json() == [
        {"projectId": str(alpha.id), "projectName": "alpha", "role": "editor"},
        {"projectId": str(beta.id), "projectName": "beta", "role": "viewer"},
    ]


async def test_memberships_drops_a_deleted_project(
    client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    grant_membership: GrantMembership,
) -> None:
    project = await create_project(db_session, grant_owner=False, name="gone")
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, "owner")
    project.deleted_at = datetime.now(UTC)
    await db_session.commit()
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.json() == []


async def test_an_admin_sees_only_real_memberships(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await create_project(db_session, grant_owner=False)
    await db_session.commit()
    access, _ = await _login(client, admin_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.json() == []


async def test_me_routes_require_a_token(client: AsyncClient) -> None:
    for path in ("/me/memberships", "/me/sessions", "/me/activity"):
        assert (await client.get(path)).status_code == 401, path
    assert (await client.delete(f"/me/sessions/{uuid.uuid4()}")).status_code == 401


async def test_me_routes_are_behind_the_password_change_gate(
    client: AsyncClient, db_session: AsyncSession, authed_user: User
) -> None:
    """`/me` is not gate-exempt: a user holding a temporary password reaches nothing
    here until they change it."""
    authed_user.must_change_password = True
    await db_session.commit()
    access, _ = await _login(client, authed_user.email)

    for path in ("/me/memberships", "/me/sessions", "/me/activity"):
        response = await client.get(path, headers=_bearer(access))
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    response = await client.delete(f"/me/sessions/{uuid.uuid4()}", headers=_bearer(access))
    assert response.status_code == 403
```

Run: `uv run pytest tests/test_me_api.py -v`
Expected: FAIL — `404` on `/me/memberships` (no router). The token and gate tests fail too
until Tasks 4–5 add the other routes; that is expected. They must pass by the end of Task 5.

- [ ] **Step 4: Write the schema**

Create `backend/app/schemas/me.py`:

```python
"""Wire shapes for `/me` — the caller's own account surface.

Each model inherits `ApiModel`, so every key ships camelCase.
"""

import uuid

from app.schemas.base import ApiModel


class MembershipSummary(ApiModel):
    """One project the caller is a member of, and their role on it."""

    project_id: uuid.UUID
    project_name: str
    role: str
```

- [ ] **Step 5: Write the service**

Create `backend/app/services/me.py`:

```python
"""The caller's own account surface: memberships, sessions and activity.

Every method takes the caller and nothing that names another user. Membership comes
from `app/core/access.py`, never a query of its own
(`tests/test_scoping_is_single_point.py`).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import memberships_for
from app.core.middleware import AuthenticatedUser
from app.repositories.project import ProjectRepository
from app.schemas.me import MembershipSummary


class MeService:
    """Backs the routes under `/me`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)

    async def memberships(self, user: AuthenticatedUser) -> list[MembershipSummary]:
        """The caller's memberships, named, soft-deleted projects dropped, by name."""
        grants = memberships_for(user)
        names = await self.projects.names_and_generations([g.project_id for g in grants])
        summaries = [
            MembershipSummary(
                project_id=grant.project_id,
                project_name=names[grant.project_id].name,
                role=grant.role,
            )
            for grant in grants
            if grant.project_id in names
        ]
        return sorted(summaries, key=lambda summary: summary.project_name.lower())
```

- [ ] **Step 6: Write the router and register it**

Create `backend/app/api/routes/me.py`:

```python
"""The caller's own account surface.

Deliberately **not** under `/auth`: that prefix is exempt from the forced-password-change
gate, and nothing here should be readable before a temporary password is replaced. No
route takes a user id — there is no `/me/{id}`, and an administrator's view of other
people stays on `/users`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.me import MembershipSummary
from app.services.me import MeService

router = APIRouter(prefix="/me", tags=["Me"])


def get_me_service(session: SessionDep) -> MeService:
    """Provide the service with a request-scoped session."""
    return MeService(session)


MeServiceDep = Annotated[MeService, Depends(get_me_service)]


@router.get(
    "/memberships",
    response_model=list[MembershipSummary],
    status_code=status.HTTP_200_OK,
    summary="The projects you are a member of",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_memberships(
    current_user: CurrentUser, service: MeServiceDep
) -> list[MembershipSummary]:
    return await service.memberships(current_user)
```

In `backend/app/main.py`, add `me` to the routes import and
`app.include_router(me.router)` after `app.include_router(auth.router)`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_me_api.py -k "memberships or admin_sees" tests/test_access.py tests/test_scoping_is_single_point.py -v`
Expected: PASS. `test_scoping_is_single_point.py` passing is the proof `MeService` reads
membership only through `access.py`.

- [ ] **Step 8: Add the route to the README**

In `backend/README.md`, find the exhaustive route table and add a row for
`GET /me/memberships` — "The caller's project memberships and role on each" — in the
table's existing column format, in a new `/me` group after the `/auth` rows.

- [ ] **Step 9: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add backend/app/core/access.py backend/app/schemas/me.py backend/app/services/me.py \
  backend/app/api/routes/me.py backend/app/main.py backend/tests/test_access.py \
  backend/tests/test_me_api.py backend/README.md
git commit -m "feat(me): list the caller's own memberships

Adds memberships_for to access.py, which answers where a user is a
member rather than what they may read, and the gated /me router with
its first route.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Sessions — list and revoke

**Files:**
- Modify: `backend/app/models/refresh_token.py` (`RevokedReason`)
- Modify: `backend/app/repositories/refresh_token.py` (two methods)
- Modify: `backend/app/core/errors.py` (`SESSION_NOT_FOUND`)
- Modify: `backend/app/core/audit.py` (`AUTH_SESSION_REVOKED` + context keys)
- Modify: `backend/app/schemas/me.py`, `backend/app/services/me.py`, `backend/app/api/routes/me.py`
- Test: `backend/tests/test_me_api.py`, `backend/tests/test_audit_coverage.py`, `backend/tests/test_audit_write_sites.py`
- Docs: `backend/README.md`

**Interfaces:**
- Consumes: Task 1's `AuthenticatedUser.session_id`; Task 2's `RefreshToken.user_agent` / `ip_address`; Task 3's `MeService`, `router`, `_login`, `_bearer`, `UA`.
- Produces: `SessionResponse(id, user_agent, ip_address, started_at, last_active_at, expires_at, current)`;
  `RefreshTokenRepository.live_families_for(user_id) -> list[SessionRow]`;
  `RefreshTokenRepository.family_belongs_to(family_id, user_id) -> bool`;
  `MeService(session, *, recorder: AuditRecorder, client_ip: str | None)`,
  `async sessions(user) -> list[SessionResponse]`, `async revoke_session(user, session_id) -> None`;
  `ErrorCode.SESSION_NOT_FOUND`; `AuditEventType.AUTH_SESSION_REVOKED = "auth.session.revoked"`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_me_api.py` (add `from sqlalchemy import text`,
`from app.core.audit import AuditEventType`, `from app.core.security import sha256_hex`
and `from tests.conftest import AuditRows` — merge into the existing conftest import):

```python
async def test_sessions_lists_each_live_sign_in_and_marks_this_one(
    client: AsyncClient, authed_user: User
) -> None:
    first, _ = await _login(client, authed_user.email)
    await _login(client, authed_user.email)

    response = await client.get("/me/sessions", headers=_bearer(first))

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert [s["current"] for s in sessions].count(True) == 1
    assert all(s["userAgent"] == UA for s in sessions)
    assert set(sessions[0]) == {
        "id", "userAgent", "ipAddress", "startedAt", "lastActiveAt", "expiresAt", "current",
    }


async def test_sessions_omits_a_logged_out_sign_in(
    client: AsyncClient, authed_user: User
) -> None:
    """`logout` revokes only the presented token, leaving used ancestors unrevoked —
    a family is live only while it has an unused, unrevoked, unexpired head."""
    access, _ = await _login(client, authed_user.email)
    await _login(client, authed_user.email)
    await client.post("/auth/logout")  # the jar holds the second sign-in's cookie

    response = await client.get("/me/sessions", headers=_bearer(access))

    assert len(response.json()) == 1


async def test_sessions_never_shows_another_users(
    client: AsyncClient, user_a: User, user_b: User
) -> None:
    access_a, _ = await _login(client, user_a.email)
    await _login(client, user_b.email)

    response = await client.get("/me/sessions", headers=_bearer(access_a))

    assert len(response.json()) == 1


async def test_revoking_a_session_ends_it(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    access, _ = await _login(client, authed_user.email)
    _, other_cookie = await _login(client, authed_user.email)
    other = next(
        s for s in (await client.get("/me/sessions", headers=_bearer(access))).json()
        if not s["current"]
    )

    response = await client.delete(f"/me/sessions/{other['id']}", headers=_bearer(access))

    assert response.status_code == 204
    client.cookies.set(get_settings().refresh_cookie_name, other_cookie)
    assert (await client.post("/auth/refresh")).status_code == 401
    [row] = await audit_rows(AuditEventType.AUTH_SESSION_REVOKED)
    assert row.actor_user_id == authed_user.id
    assert row.details["familyId"] == other["id"]
    assert row.details["current"] is False
    assert row.details["revokedCount"] >= 1


async def test_revoking_the_current_session_is_allowed(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    access, cookie = await _login(client, authed_user.email)
    current = (await client.get("/me/sessions", headers=_bearer(access))).json()[0]

    response = await client.delete(f"/me/sessions/{current['id']}", headers=_bearer(access))

    assert response.status_code == 204
    client.cookies.set(get_settings().refresh_cookie_name, cookie)
    assert (await client.post("/auth/refresh")).status_code == 401
    [row] = await audit_rows(AuditEventType.AUTH_SESSION_REVOKED)
    assert row.details["current"] is True


async def test_another_users_session_is_not_found(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """`404`, not `403`: the answer must not confirm that someone else's id exists."""
    access_a, _ = await _login(client, user_a.email)
    _, cookie_b = await _login(client, user_b.email)
    row = await db_session.execute(
        text("SELECT family_id FROM refresh_tokens WHERE token_hash = :hash"),
        {"hash": sha256_hex(cookie_b)},
    )
    family_b = row.scalar_one()

    response = await client.delete(f"/me/sessions/{family_b}", headers=_bearer(access_a))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"
    client.cookies.set(get_settings().refresh_cookie_name, cookie_b)
    assert (await client.post("/auth/refresh")).status_code == 200


async def test_an_unknown_session_is_not_found(client: AsyncClient, authed_user: User) -> None:
    access, _ = await _login(client, authed_user.email)

    response = await client.delete(f"/me/sessions/{uuid.uuid4()}", headers=_bearer(access))

    assert response.status_code == 404
```

Run: `uv run pytest tests/test_me_api.py -k "session" -v`
Expected: FAIL — `404`/`405` from routes that do not exist yet.

- [ ] **Step 2: Add the reason, the error code and the audit event**

- `backend/app/models/refresh_token.py`: add `"user_revoked",` as the last member of
  `RevokedReason`. The column is `String(32)` with no check constraint, so no migration.
- `backend/app/core/errors.py`: add `SESSION_NOT_FOUND = "SESSION_NOT_FOUND"` beside the
  other `*_NOT_FOUND` members.
- `backend/app/core/audit.py`: add
  `AUTH_SESSION_REVOKED = "auth.session.revoked"` after `AUTH_PASSWORD_RESET_COMPLETED`
  in the auth block, and to `CONTEXT_KEYS`, after the `AUTH_PASSWORD_RESET_COMPLETED`
  entry:

```python
    # A user ending one of their own sessions from the profile. `current` separates
    # "signed this device out" from "signed another device out" — the second is the one
    # worth a responder's attention. No `changed` block: the event is its name.
    AuditEventType.AUTH_SESSION_REVOKED: frozenset({"familyId", "current", "revokedCount"}),
```

- [ ] **Step 3: Add the repository methods**

In `backend/app/repositories/refresh_token.py`, add `from typing import NamedTuple` (merge
into the existing `typing` import) and `func, select` to the `sqlalchemy` import. Above the
class:

```python
class SessionRow(NamedTuple):
    """One live sign-in, aggregated over its rotation chain."""

    family_id: uuid.UUID
    user_agent: str | None
    ip_address: str | None
    started_at: datetime
    last_active_at: datetime
    expires_at: datetime
```

Methods on the class:

```python
    async def live_families_for(self, user_id: uuid.UUID) -> list[SessionRow]:
        """The user's live sessions, most recently active first.

        A family is live while its chain head — an unused, unrevoked, unexpired token —
        exists. `revoked_at` alone is not the test: `mark_used` leaves a rotated token's
        `revoked_at` unset, and `logout` revokes only the presented token, so a
        signed-out family still holds unrevoked ancestors. The head also carries the
        freshest `issued_at` (the last refresh) and the session's device, copied forward
        from login.
        """
        now = datetime.now(UTC)
        started = (
            select(
                RefreshToken.family_id,
                func.min(RefreshToken.issued_at).label("started_at"),
            )
            .where(RefreshToken.user_id == user_id)
            .group_by(RefreshToken.family_id)
            .subquery()
        )
        statement = (
            select(
                RefreshToken.family_id,
                RefreshToken.user_agent,
                RefreshToken.ip_address,
                started.c.started_at,
                RefreshToken.issued_at,
                RefreshToken.expires_at,
            )
            .join(started, started.c.family_id == RefreshToken.family_id)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.used_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.issued_at.desc())
        )
        rows = (await self.session.execute(statement)).all()
        # Inside the rotation grace window a family can briefly hold two heads (D12).
        # Keep the newest: rows arrive newest first, so the first seen wins.
        seen: dict[uuid.UUID, SessionRow] = {}
        for family_id, user_agent, ip_address, started_at, issued_at, expires_at in rows:
            seen.setdefault(
                family_id,
                SessionRow(family_id, user_agent, ip_address, started_at, issued_at, expires_at),
            )
        return list(seen.values())

    async def family_belongs_to(self, family_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether this family is one of this user's. One answer for "not yours" and
        "does not exist", so the caller cannot tell them apart."""
        result = await self.session.execute(
            select(RefreshToken.id)
            .where(RefreshToken.family_id == family_id, RefreshToken.user_id == user_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
```

- [ ] **Step 4: Add the schema**

Append to `backend/app/schemas/me.py` (add `from datetime import datetime`):

```python
class SessionResponse(ApiModel):
    """One of the caller's live sign-ins. `id` is the refresh-token family."""

    id: uuid.UUID
    user_agent: str | None
    ip_address: str | None
    started_at: datetime
    last_active_at: datetime
    expires_at: datetime
    current: bool
```

- [ ] **Step 5: Extend the service**

In `backend/app/services/me.py`, add imports (`import uuid`, `from fastapi import status`,
`from app.core.audit import AuditEntry, AuditEventType, AuditRecorder`,
`from app.core.errors import AppError, ErrorCode`,
`from app.repositories.refresh_token import RefreshTokenRepository`, `SessionResponse`), then
change the constructor and add two methods:

```python
    def __init__(
        self,
        session: AsyncSession,
        *,
        recorder: AuditRecorder,
        client_ip: str | None = None,
    ) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self._recorder = recorder
        self._client_ip = client_ip

    async def sessions(self, user: AuthenticatedUser) -> list[SessionResponse]:
        """The caller's live sessions, the one making this request marked `current`."""
        rows = await self.tokens.live_families_for(user.id)
        return [
            SessionResponse(
                id=row.family_id,
                user_agent=row.user_agent,
                ip_address=row.ip_address,
                started_at=row.started_at,
                last_active_at=row.last_active_at,
                expires_at=row.expires_at,
                current=row.family_id == user.session_id,
            )
            for row in rows
        ]

    async def revoke_session(self, user: AuthenticatedUser, session_id: uuid.UUID) -> None:
        """End one of the caller's sessions.

        `404` for a family that is not theirs as well as one that does not exist — the
        same answer, so this cannot confirm another user's session id. The access token
        of a revoked session keeps working until it expires; that window is the same one
        Log out everywhere has, and the frontend says so.
        """
        if not await self.tokens.family_belongs_to(session_id, user.id):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.SESSION_NOT_FOUND, "Session not found."
            )
        revoked_count = await self.tokens.revoke_family(session_id, reason="user_revoked")
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_SESSION_REVOKED,
                actor_user_id=user.id,
                actor_email=user.email,
                ip_address=self._client_ip,
                context={
                    "familyId": str(session_id),
                    "current": session_id == user.session_id,
                    "revokedCount": revoked_count,
                },
            )
        )
```

- [ ] **Step 6: Add the routes**

In `backend/app/api/routes/me.py`: import `uuid`, `AuditRecorderDep, ClientIpDep` from
`app.api.deps`, and `SessionResponse`. Update the factory and add two routes:

```python
def get_me_service(
    session: SessionDep, recorder: AuditRecorderDep, client_ip: ClientIpDep
) -> MeService:
    """Provide the service with a request-scoped session, the recorder and the caller's
    address — only `revoke_session` uses the last two."""
    return MeService(session, recorder=recorder, client_ip=client_ip)
```

```python
@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    status_code=status.HTTP_200_OK,
    summary="Your signed-in sessions",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_sessions(
    current_user: CurrentUser, service: MeServiceDep
) -> list[SessionResponse]:
    return await service.sessions(current_user)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign one of your sessions out",
    description=(
        "Its refresh token stops working at once; an access token it already holds "
        "keeps working until it expires, at most the access-token lifetime."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def revoke_session(
    session_id: uuid.UUID, current_user: CurrentUser, service: MeServiceDep
) -> None:
    await service.revoke_session(current_user, session_id)
```

- [ ] **Step 7: Classify the route in the coverage test**

In `backend/tests/test_audit_coverage.py`, add to `ROUTE_EVENTS` after the Task 4 auth
block:

```python
    # --- profile ---
    ("DELETE", "/me/sessions/{session_id}"): AuditEventType.AUTH_SESSION_REVOKED,
```

In `backend/tests/test_audit_write_sites.py`, add a write-site test following the file's
existing `auth.logout` test (line ~128) as the pattern, asserting one
`AUTH_SESSION_REVOKED` row with `outcome == "success"` and the three context keys after a
`DELETE /me/sessions/{id}` on the caller's own session. Use `/auth/login` to obtain a
session, as `tests/test_me_api.py::_login` does.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_me_api.py tests/test_audit_coverage.py tests/test_audit_write_sites.py -v`
Expected: PASS except the activity cases in `test_me_routes_require_a_token` and
`test_me_routes_are_behind_the_password_change_gate` (Task 5).

- [ ] **Step 9: README, lint, commit**

Add `GET /me/sessions` and `DELETE /me/sessions/{session_id}` rows to `backend/README.md`'s
route table under the `/me` group.

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add backend/app backend/tests backend/README.md
git commit -m "feat(me): list and revoke your own sessions

A session is a refresh family with a live chain head; the one the
caller's sid names is marked current. Revoking one is audited as
auth.session.revoked, and another user's session id is a 404.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Activity — the caller's own audit events

**Files:**
- Modify: `backend/app/repositories/audit_event.py` (`_PageFilters`, `_filtered`, `page`)
- Modify: `backend/app/schemas/me.py`, `backend/app/services/me.py`, `backend/app/api/routes/me.py`
- Test: `backend/tests/test_me_api.py`, `backend/tests/test_audit_events_api.py`
- Docs: `backend/README.md`

**Interfaces:**
- Consumes: `resolve_project_scope(user) -> ProjectScope`; Task 3–4's `MeService`, router, test helpers.
- Produces: `AuditEventRepository.page(..., visible_project_ids: frozenset[uuid.UUID] | None = None)`;
  `ActivityEntry(id, created_at, event_type, outcome, target_label, project_id, ip_address)`;
  `MeService.activity(user, query: ListQuery) -> PaginatedResponse[ActivityEntry]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_me_api.py` (add `from datetime import timedelta` and
`from app.models import AuditEvent`):

```python
async def _audit(
    session: AsyncSession,
    *,
    actor: uuid.UUID | None,
    event_type: str,
    project_id: uuid.UUID | None = None,
    minutes_ago: int = 0,
) -> None:
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            event_type=event_type,
            outcome="success",
            actor_user_id=actor,
            project_id=project_id,
            target_label="label",
            ip_address="203.0.113.9",
            details={},
        )
    )
    await session.commit()


async def test_activity_shows_only_the_callers_own_rows(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    access, _ = await _login(client, user_a.email)  # writes auth.login.succeeded for A
    await _audit(db_session, actor=user_b.id, event_type="user.updated")

    response = await client.get("/me/activity", headers=_bearer(access))

    assert response.status_code == 200
    body = response.json()
    assert [item["eventType"] for item in body["items"]] == ["auth.login.succeeded"]
    assert set(body["items"][0]) == {
        "id", "createdAt", "eventType", "outcome", "targetLabel", "projectId", "ipAddress",
    }
    assert body["totalCount"] == 1


async def test_activity_includes_failed_sign_ins_against_the_account(
    client: AsyncClient, authed_user: User
) -> None:
    """Recorded with the account as actor, though someone else typed the password."""
    await client.post(
        "/auth/login", json={"email": authed_user.email, "password": "wrong-password-here"}
    )
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/activity", headers=_bearer(access))

    assert "auth.login.failed" in [item["eventType"] for item in response.json()["items"]]


async def test_activity_hides_rows_on_projects_the_caller_cannot_see(
    client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    grant_membership: GrantMembership,
) -> None:
    """A removed member stops seeing their own past rows there: the row carries the
    project's name, and project existence is private."""
    visible = await create_project(db_session, grant_owner=False)
    hidden = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, visible.id, "viewer")
    await _audit(db_session, actor=authed_user.id, event_type="project.created",
                 project_id=visible.id, minutes_ago=3)
    await _audit(db_session, actor=authed_user.id, event_type="project.deleted",
                 project_id=hidden.id, minutes_ago=2)
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/activity", headers=_bearer(access))

    types = [item["eventType"] for item in response.json()["items"]]
    assert "project.created" in types
    assert "project.deleted" not in types
    assert "auth.login.succeeded" in types  # project-less rows always show


async def test_an_admins_activity_is_not_narrowed(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await _audit(db_session, actor=admin_user.id, event_type="project.deleted",
                 project_id=project.id, minutes_ago=1)
    access, _ = await _login(client, admin_user.email)

    response = await client.get("/me/activity", headers=_bearer(access))

    assert "project.deleted" in [item["eventType"] for item in response.json()["items"]]


async def test_activity_is_paged(client: AsyncClient, db_session: AsyncSession, authed_user: User) -> None:
    for minutes in range(3):
        await _audit(db_session, actor=authed_user.id, event_type="user.updated",
                     minutes_ago=minutes + 10)
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/activity?limit=2&page=2", headers=_bearer(access))

    body = response.json()
    assert body["page"] == 2
    assert body["totalCount"] == 4
    assert len(body["items"]) == 2
```

Also add to `backend/tests/test_audit_events_api.py` a test in its style asserting an admin's
`GET /audit-events` still returns rows on a project the admin holds no membership on, and a
non-admin still gets `403` — the admin read must be unchanged by the new parameter.

Run: `uv run pytest tests/test_me_api.py -k activity -v` → FAIL (`404`).

- [ ] **Step 2: Narrow the repository query**

In `backend/app/repositories/audit_event.py`:

1. Add `visible_project_ids: frozenset[uuid.UUID] | None` to `_PageFilters`.
2. Add the same keyword to `_filtered`, and after the `project_id` clause:

```python
        if visible_project_ids is not None:
            # A narrowing applied on top of the access resolver's answer, never instead of
            # it: the caller passes `resolve_project_scope`'s ids. Rows with no project —
            # sign-ins, account events — are always visible to their own actor.
            statement = statement.where(
                or_(
                    AuditEvent.project_id.is_(None),
                    AuditEvent.project_id.in_(visible_project_ids),
                )
            )
```

3. Add `visible_project_ids: frozenset[uuid.UUID] | None = None` to `page` and put it in
   the `filters` dict.

- [ ] **Step 3: Add the schema, service method and route**

Append to `backend/app/schemas/me.py`:

```python
class ActivityEntry(ApiModel):
    """One audit row the caller is the actor of.

    Slimmer than the admin models on purpose: no `details`, no actor (always the
    caller), and none of `AuditEventResponse`'s live lookups, which cost a query a row.
    """

    id: uuid.UUID
    created_at: datetime
    event_type: str
    outcome: str
    target_label: str | None
    project_id: uuid.UUID | None
    ip_address: str | None
```

In `backend/app/services/me.py` (imports: `resolve_project_scope` from `app.core.access`,
`AuditEventRepository`, `ActivityEntry`, `ListQuery`, `PaginatedResponse` from
`app.schemas.pagination`; add `self.audit = AuditEventRepository(session)` to `__init__`):

```python
    async def activity(
        self, user: AuthenticatedUser, query: ListQuery
    ) -> PaginatedResponse[ActivityEntry]:
        """The caller's own audit rows, newest first.

        Project-scoped rows are narrowed through `resolve_project_scope`, so a member
        removed from a project stops seeing its name here. An administrator's scope is
        unrestricted, so nothing is narrowed.
        """
        scope = resolve_project_scope(user)
        rows, total = await self.audit.page(
            limit=query.limit,
            offset=(query.page - 1) * query.limit,
            actor_user_id=user.id,
            visible_project_ids=None if scope.unrestricted else scope.ids,
        )
        items = [
            ActivityEntry(
                id=row.id,
                created_at=row.created_at,
                event_type=row.event_type,
                outcome=row.outcome,
                target_label=row.target_label,
                project_id=row.project_id,
                ip_address=row.ip_address,
            )
            for row in rows
        ]
        return PaginatedResponse.build(
            items, page=query.page, limit=query.limit, total_count=total
        )
```

In `backend/app/api/routes/me.py` (imports: `Query` from fastapi, `ActivityEntry`,
`ListQuery`, `PaginatedResponse`):

```python
@router.get(
    "/activity",
    response_model=PaginatedResponse[ActivityEntry],
    status_code=status.HTTP_200_OK,
    summary="What you have done, from the audit trail",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 422)},
)
async def list_activity(
    current_user: CurrentUser,
    service: MeServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[ActivityEntry]:
    return await service.activity(current_user, query)
```

`query` is the route's only query parameter — keep it that way (`rag.md`: a query model
stops flattening once a scalar sits beside it).

- [ ] **Step 4: Run the whole backend suite**

Run: `uv run pytest -v`
Expected: PASS, including every test in `tests/test_me_api.py`,
`tests/test_scoping_is_single_point.py` and `tests/test_audit_coverage.py`.

- [ ] **Step 5: README, lint, commit**

Add `GET /me/activity` to `backend/README.md`'s `/me` group.

Run: `uv run ruff check . && uv run ruff format --check .`

```bash
git add backend/app backend/tests backend/README.md
git commit -m "feat(me): show the caller their own audit activity

A second, narrow reader of the audit trail: rows where the caller is the
actor, project-scoped rows narrowed through resolve_project_scope. The
admin read is unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Frontend data layer — types, endpoints, hooks, device labels

**Files:**
- Modify: `frontend/lib/api/types.ts`, `frontend/lib/api/endpoints.ts`, `frontend/lib/query/keys.ts`, `frontend/lib/audit.ts`, `frontend/hooks/use-change-password.ts`
- Create: `frontend/hooks/use-profile.ts`, `frontend/lib/user-agent.ts`, `frontend/lib/user-agent.test.ts`

**Interfaces:**
- Consumes: the three `/me` response shapes from Tasks 3–5.
- Produces: types `MembershipSummary`, `SessionSummary`, `ActivityEntry`;
  `endpoints.me.{memberships, sessions, session(id), activity}`;
  `keys.profile.{all, memberships, sessions, activity(params)}`;
  hooks `useMemberships()`, `useSessions()`, `useRevokeSession()`, `useActivity(params: ListParams)`;
  `deviceLabel(userAgent: string | null): string`.

- [ ] **Step 1: Write the failing parser test**

Create `frontend/lib/user-agent.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { deviceLabel } from "@/lib/user-agent";

describe("deviceLabel", () => {
  it.each([
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Chrome on macOS",
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0",
      "Edge on Windows",
    ],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0", "Firefox on Linux"],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
      "Safari on iOS",
    ],
    [
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36",
      "Chrome on Android",
    ],
  ])("names %s", (userAgent, expected) => {
    expect(deviceLabel(userAgent)).toBe(expected);
  });

  it("says unknown for a missing or blank agent", () => {
    expect(deviceLabel(null)).toBe("Unknown device");
    expect(deviceLabel("   ")).toBe("Unknown device");
  });

  it("falls back to the raw string when nothing matches", () => {
    expect(deviceLabel("curl/8.4.0")).toBe("curl/8.4.0");
  });
});
```

Run: `bun run vitest run lib/user-agent.test.ts` → FAIL (module not found).

- [ ] **Step 2: Implement the parser**

Create `frontend/lib/user-agent.ts`:

```ts
/**
 * "Chrome on macOS" from a user-agent string, for the profile's session list.
 *
 * Order matters in both tables. Edge and Opera carry "Chrome/", and Chrome carries
 * "Safari/", so the more specific name is tested first. An iPad's agent says
 * "Mac OS X" and Android's says "Linux", so iOS and Android come before them. A small
 * table instead of a dependency: this only has to tell a person's own devices apart,
 * and the raw string is always one hover away.
 */
const BROWSERS: [RegExp, string][] = [
  [/Edg\//, "Edge"],
  [/OPR\/|Opera/, "Opera"],
  [/Firefox\//, "Firefox"],
  [/Chrome\//, "Chrome"],
  [/Safari\//, "Safari"],
];

const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad|iPod/, "iOS"],
  [/Android/, "Android"],
  [/Windows/, "Windows"],
  [/CrOS/, "ChromeOS"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/Linux/, "Linux"],
];

export function deviceLabel(userAgent: string | null): string {
  if (!userAgent?.trim()) return "Unknown device";
  const browser = BROWSERS.find(([pattern]) => pattern.test(userAgent))?.[1];
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent))?.[1];
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? userAgent;
}
```

Run: `bun run vitest run lib/user-agent.test.ts` → PASS.

- [ ] **Step 3: Types, endpoints, keys, audit vocabulary**

Append to `frontend/lib/api/types.ts` (`AuditOutcome` already exists there):

```ts
/** `GET /me/memberships` — a project the caller belongs to, and their role on it. */
export interface MembershipSummary {
  projectId: string;
  projectName: string;
  role: string;
}

/** `GET /me/sessions` — one live sign-in. `id` is the refresh-token family. */
export interface SessionSummary {
  id: string;
  userAgent: string | null;
  ipAddress: string | null;
  startedAt: string;
  lastActiveAt: string;
  expiresAt: string;
  current: boolean;
}

/** `GET /me/activity` — one audit row the caller is the actor of. */
export interface ActivityEntry {
  id: string;
  createdAt: string;
  eventType: string;
  outcome: AuditOutcome;
  targetLabel: string | null;
  projectId: string | null;
  ipAddress: string | null;
}
```

In `frontend/lib/api/endpoints.ts`, add after the `auth` block:

```ts
  me: {
    memberships: "/me/memberships",
    sessions: "/me/sessions",
    session: (id: string) => `/me/sessions/${id}`,
    activity: "/me/activity",
  },
```

In `frontend/lib/query/keys.ts`, add after `passwordPolicy`:

```ts
  profile: {
    all: ["profile"] as const,
    memberships: ["profile", "memberships"] as const,
    sessions: ["profile", "sessions"] as const,
    activity: (params: ListParams) => ["profile", "activity", params] as const,
  },
```

In `frontend/lib/audit.ts`, add `"auth.session.revoked",` after `"auth.refresh.replayed",`
in `AUDIT_EVENT_TYPES`.

- [ ] **Step 4: Write the hooks**

Create `frontend/hooks/use-profile.ts`:

```ts
"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type {
  ActivityEntry,
  ListParams,
  MembershipSummary,
  PaginatedResponse,
  SessionSummary,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** None of these poll: a profile is read when opened, and refetched after a change. */
export function useMemberships() {
  return useQuery({
    queryKey: keys.profile.memberships,
    queryFn: () => apiFetch<MembershipSummary[]>(endpoints.me.memberships),
  });
}

export function useSessions() {
  return useQuery({
    queryKey: keys.profile.sessions,
    queryFn: () => apiFetch<SessionSummary[]>(endpoints.me.sessions),
  });
}

export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(endpoints.me.session(id), { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.profile.sessions }),
  });
}

export function useActivity(params: ListParams) {
  return useQuery({
    queryKey: keys.profile.activity(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<ActivityEntry>>(
        `${endpoints.me.activity}${listQueryString(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}
```

In `frontend/hooks/use-change-password.ts`, replace `onSuccess` so the session list reflects
the backend revoking every other session:

```ts
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.me });
      void queryClient.invalidateQueries({ queryKey: keys.profile.sessions });
    },
```

- [ ] **Step 5: Typecheck, test, commit**

Run: `bun run vitest run lib/user-agent.test.ts && bun lint && bunx tsc --noEmit`
Expected: no errors.

```bash
git add frontend/lib frontend/hooks
git commit -m "feat(profile): add the profile data layer and device labels

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Navigation — `/profile` in the menu, preferences move, Settings admin-only

**Files:**
- Modify: `frontend/lib/settings-nav.ts`, `frontend/lib/nav.ts`, `frontend/lib/nav.test.ts`
- Modify: `frontend/app/(app)/settings/notifications/page.tsx`, `frontend/app/(app)/settings/page.tsx` (comment only)
- Modify: `frontend/components/notifications/preferences-screen.tsx`
- Modify: `frontend/components/layout/account-menu.tsx`

**Interfaces:**
- Produces: `/profile` as a breadcrumb-only destination; `PreferencesScreen` rendering
  without its own page header, for embedding.

- [ ] **Step 1: Update the nav tests to the new shape**

In `frontend/lib/nav.test.ts`:

1. Rename "keeps a group visible when at least one child is reachable" to
   "hides Settings from a non-admin, whose group has no reachable child" and change its
   expected list to `["/", "/projects", "/ask", "/checklist"]`.
2. In "resolves the settings children for an admin", remove `"/settings/notifications"`.
3. Delete the two tests "resolves /settings to notifications for a non-admin" and
   "shows only notifications to a non-admin under settings". Remove the now-unused
   `settingsNav` import if nothing else uses it.
4. In "hides Roles from a non-admin", the `settings` lookup is now `undefined`; keep the
   assertion (`?? []` already handles it).
5. Add, inside the breadcrumbs `describe`:

```ts
  it("names the profile page, which is reached from the account menu", () => {
    expect(resolveBreadcrumbs("/profile", member)).toEqual([
      { href: "/profile", label: "Profile" },
    ]);
  });
```

Run: `bun run vitest run lib/nav.test.ts` → FAIL (member still sees `/settings`; no
Profile crumb).

- [ ] **Step 2: Change the nav**

`frontend/lib/settings-nav.ts`: remove the Notifications entry and the `Bell` import, and
replace the docstring with:

```ts
/**
 * Settings' children — all administrator-only.
 *
 * Notification preferences used to live here as the one non-admin child; they moved to
 * `/profile`, because they belong to a person rather than to the instance. With no
 * reachable child, `visibleNavTree` hides the whole group from a non-admin.
 */
```

`frontend/lib/nav.ts`: add `UserRound` to the `lucide-react` import and
`{ title: "Profile", href: "/profile", icon: UserRound },` to `breadcrumbOnlyItems`. In the
comment above it, change "which `lib/nav.test.ts` pins at exactly five top-level
destinations" to "which `lib/nav.test.ts` pins — five top-level destinations for an admin,
four for everyone else". Add one sentence: "`/profile` is here for the same reason: it
opens from the account menu."

Run: `bun run vitest run lib/nav.test.ts` → PASS.

- [ ] **Step 3: Redirect the old preferences route**

Replace `frontend/app/(app)/settings/notifications/page.tsx` with:

```tsx
import { redirect } from "next/navigation";

/** Preferences moved to the profile; old links and bookmarks land on that section. */
export default function NotificationPreferencesPage() {
  redirect("/profile#notifications");
}
```

In `frontend/app/(app)/settings/page.tsx`, replace the docstring's second and third
sentences with: "Every child is admin-only, so a non-admin falls through to `/` — the
same outcome as before Notifications briefly lived here." Code unchanged.

- [ ] **Step 4: Let `PreferencesScreen` embed**

In `frontend/components/notifications/preferences-screen.tsx`, replace

```tsx
    <div className="mx-auto w-full max-w-3xl">
      <PageHeader
        title="Notifications"
        description="Choose what AskRepo notifies you about, and how."
      />
```

with `<div>`, remove the `PageHeader` import, and add one sentence to the component
docstring: "Rendered inside the profile's Notifications section, which supplies the
heading."

- [ ] **Step 5: The account menu**

In `frontend/components/layout/account-menu.tsx`:

1. Import `Link` from `next/link`, `UserRound` from `lucide-react`, and
   `DropdownMenuGroup, DropdownMenuLabel, DropdownMenuSeparator` from the dropdown module.
2. Replace the component docstring with: "Who is signed in, the way to their profile, and
   the two sign-out actions. Everything else about the account lives on `/profile`."
3. Replace the `DropdownMenuContent` body:

```tsx
      <DropdownMenuContent align="end" className="w-56">
        {/* Base UI requires a group label inside a Group, or it throws at render. */}
        <DropdownMenuGroup>
          <DropdownMenuLabel>
            <span className="text-foreground block truncate text-sm font-medium">
              {user.name}
            </span>
            <span className="text-muted-foreground block truncate text-xs font-normal">
              {user.email}
            </span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/profile" />}>
          <UserRound className="size-4" />
          Profile
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void logout(false)}>
          <LogOut className="size-4" />
          Log out
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void logout(true)}>
          <MonitorSmartphone className="size-4" />
          Log out everywhere
        </DropdownMenuItem>
      </DropdownMenuContent>
```

- [ ] **Step 6: Verify and commit**

Run: `bun run vitest run && bun lint && bunx tsc --noEmit`
Expected: PASS. (The `/profile` link 404s until Task 8.)

```bash
git add frontend/lib frontend/app frontend/components
git commit -m "feat(profile): route to the profile from the account menu

Notification preferences move off Settings, which is admin-only again;
/settings/notifications redirects to the profile's section.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The profile page

**Files:**
- Create: `frontend/app/(app)/profile/page.tsx`
- Create: `frontend/components/profile/profile-screen.tsx`, `account-section.tsx`, `sessions-section.tsx`, `sessions-section.test.tsx`, `activity-section.tsx`, `password-section.tsx`, `password-section.test.tsx`
- Delete: `frontend/components/users/change-password-dialog.tsx`

**Interfaces:**
- Consumes: Task 6's hooks, types and `deviceLabel`; Task 7's embeddable `PreferencesScreen`;
  `useSession()`; `ChangePasswordFields`; `useChangePassword()`; `FormPage`; `ConfirmDialog`;
  `StatusBadge`; `UserRoleBadge`; `EmptyState`; `ListError`; `TableSkeleton`;
  `PaginationFooter`; `auditEventLabel`; `formatRelative` / `formatAbsolute`.
- Produces: `ProfileScreen({ resetEnabled }: { resetEnabled: boolean })`;
  `SessionsSection()`; `PasswordSection({ resetEnabled }: { resetEnabled: boolean })`.

- [ ] **Step 1: Write the failing component tests**

Create `frontend/components/profile/sessions-section.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionsSection } from "@/components/profile/sessions-section";
import { SessionProvider } from "@/components/layout/session-context";
import type { SessionSummary, UserResponse } from "@/lib/api/types";

const user: UserResponse = {
  id: "u1",
  name: "Dev",
  email: "dev@example.com",
  isAdmin: false,
  mustChangePassword: false,
  lastLoginAt: new Date().toISOString(),
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
};

function session(id: string, current: boolean): SessionSummary {
  const now = new Date().toISOString();
  return {
    id,
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Chrome/129.0 Safari/537.36",
    ipAddress: "203.0.113.9",
    startedAt: now,
    lastActiveAt: now,
    expiresAt: now,
    current,
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider user={user}>
        <SessionsSection />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("SessionsSection", () => {
  it("marks the current session and names the device", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json([session("a", true)])));
    renderSection();
    expect(await screen.findByText("This device")).toBeInTheDocument();
    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
  });

  it("revokes another session in place, after confirming", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : Response.json([session("a", true), session("b", false)]),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderSection();

    const buttons = await screen.findAllByRole("button", { name: /^log out$/i });
    fireEvent.click(buttons[1]);
    fireEvent.click(await screen.findByRole("button", { name: /sign it out/i }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/me/sessions/b"),
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });
});
```

`SessionProvider` is the app shell's own provider (`components/layout/session-context.tsx`),
so the section reads the user exactly as it does in the app. If `apiFetch` prefixes paths with `/api`, `stringContaining("/me/sessions/b")` still matches.

Create `frontend/components/profile/password-section.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PasswordSection } from "@/components/profile/password-section";
import { SessionProvider } from "@/components/layout/session-context";
import type { UserResponse } from "@/lib/api/types";

const user = { id: "u1", name: "Dev", email: "dev@example.com" } as UserResponse;

function renderSection(resetEnabled: boolean) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SessionProvider user={user}>
        <PasswordSection resetEnabled={resetEnabled} />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

describe("PasswordSection", () => {
  it("offers a reset link only when mail is on", () => {
    const { unmount } = renderSection(true);
    expect(screen.getByRole("button", { name: /email me a reset link/i })).toBeInTheDocument();
    unmount();

    renderSection(false);
    expect(screen.queryByRole("button", { name: /email me a reset link/i })).toBeNull();
  });

  it("keeps the change-password fields", () => {
    renderSection(false);
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();
  });
});
```

Run: `bun run vitest run components/profile` → FAIL (modules not found).

- [ ] **Step 2: Account section**

Create `frontend/components/profile/account-section.tsx`:

```tsx
"use client";

import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UserRoleBadge } from "@/components/users/user-role-badge";
import { useMemberships } from "@/hooks/use-profile";
import { useSession } from "@/hooks/use-session";

/** Who you are, and which projects you belong to — read-only (§4.0: admin-provisioned). */
export function AccountSection() {
  const user = useSession();
  const memberships = useMemberships();
  const rows = memberships.data ?? [];

  return (
    <Card className="gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <p className="text-foreground font-medium">{user.name}</p>
          <p className="text-muted-foreground text-sm">{user.email}</p>
        </div>
        <UserRoleBadge isAdmin={user.isAdmin} />
      </div>
      {user.isAdmin ? (
        <p className="text-muted-foreground text-sm">
          As an administrator you can see every project. The list below is only the ones
          you are a member of.
        </p>
      ) : null}

      {memberships.isError ? (
        <ListError error={memberships.error} onRetry={() => memberships.refetch()} />
      ) : !memberships.isLoading && rows.length === 0 ? (
        <EmptyState size="compact" description="You aren't a member of any project yet." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Role</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {memberships.isLoading ? (
                <TableSkeleton columns={2} />
              ) : (
                rows.map((row) => (
                  <TableRow key={row.projectId}>
                    <TableCell>
                      <Link
                        href={`/projects/${row.projectId}`}
                        className="text-primary underline-offset-4 hover:underline"
                      >
                        {row.projectName}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm capitalize">{row.role}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}
```

- [ ] **Step 3: Sessions section**

Create `frontend/components/profile/sessions-section.tsx`:

```tsx
"use client";

import { useState } from "react";

import { ListError } from "@/components/feedback/list-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRevokeSession, useSessions } from "@/hooks/use-profile";
import { useSession } from "@/hooks/use-session";
import type { SessionSummary } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { deviceLabel } from "@/lib/user-agent";

/**
 * A hard load to `/login`, as the account menu does: it drops the React Query cache with
 * the session, so nothing of this operator survives into the next one on a shared machine.
 */
async function signOut(all: boolean) {
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ all }),
  });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- clears the in-memory cache with the session
  window.location.assign("/login");
}

export function SessionsSection() {
  const user = useSession();
  const sessions = useSessions();
  const revoke = useRevokeSession();
  const [pending, setPending] = useState<SessionSummary | null>(null);

  function logOut(session: SessionSummary) {
    if (session.current) {
      // Revoking this device's family and signing out are the same act; the logout
      // route also clears the cookies Next holds.
      void signOut(false);
      return;
    }
    setPending(session);
  }

  return (
    <Card className="gap-4 p-6">
      <p className="text-muted-foreground text-sm">
        Last signed in{" "}
        <span className="text-foreground" title={formatAbsolute(user.lastLoginAt)}>
          {user.lastLoginAt ? formatRelative(user.lastLoginAt) : "never"}
        </span>
      </p>

      {sessions.isError ? (
        <ListError error={sessions.error} onRetry={() => sessions.refetch()} />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead>IP address</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Last active</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessions.isLoading ? (
                <TableSkeleton columns={5} />
              ) : (
                (sessions.data ?? []).map((session) => (
                  <TableRow key={session.id}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        <span title={session.userAgent ?? undefined}>
                          {deviceLabel(session.userAgent)}
                        </span>
                        {session.current ? (
                          <StatusBadge tone="info" label="This device" />
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{session.ipAddress ?? "—"}</TableCell>
                    <TableCell className="text-sm" title={formatAbsolute(session.startedAt)}>
                      {formatRelative(session.startedAt)}
                    </TableCell>
                    <TableCell
                      className="text-sm"
                      title={formatAbsolute(session.lastActiveAt)}
                    >
                      {formatRelative(session.lastActiveAt)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => logOut(session)}>
                        Log out
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="outline" onClick={() => void signOut(true)}>
          Log out everywhere
        </Button>
      </div>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Sign this session out?"
        description="It can't refresh again. It may stay signed in for up to 15 minutes, until its current access expires."
        confirmLabel="Sign it out"
        isPending={revoke.isPending}
        error={revoke.error}
        onConfirm={() =>
          pending && revoke.mutate(pending.id, { onSuccess: () => setPending(null) })
        }
      />
    </Card>
  );
}
```

If `StatusBadge`'s `tone` does not accept `"info"`, use the tone `lib/status.ts`'s
`StatusTone` declares for neutral emphasis (`"neutral"`).

- [ ] **Step 4: Activity section**

Create `frontend/components/profile/activity-section.tsx`:

```tsx
"use client";

import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActivity } from "@/hooks/use-profile";
import { auditEventLabel } from "@/lib/audit";
import { formatAbsolute, formatRelative } from "@/lib/dates";

const PAGE_SIZE = 20;

/**
 * Your own rows from the audit trail. A failed sign-in against your account appears
 * here with the address it came from — it is recorded with you as the actor.
 */
export function ActivitySection() {
  const [page, setPage] = useState(1);
  const activity = useActivity({ page, limit: PAGE_SIZE });
  const items = activity.data?.items ?? [];

  return (
    <Card className="gap-4 p-6">
      {activity.isError ? (
        <ListError error={activity.error} onRetry={() => activity.refetch()} />
      ) : !activity.isLoading && items.length === 0 ? (
        <EmptyState size="compact" description="Nothing recorded yet." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>IP address</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activity.isLoading ? (
                <TableSkeleton columns={5} />
              ) : (
                items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <StatusBadge tone="neutral" label={auditEventLabel(item.eventType)} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={item.outcome === "failure" ? "danger" : "success"}
                        label={item.outcome === "failure" ? "Failure" : "Success"}
                      />
                    </TableCell>
                    <TableCell className="text-sm">{item.targetLabel ?? "—"}</TableCell>
                    <TableCell className="text-sm">{item.ipAddress ?? "—"}</TableCell>
                    <TableCell className="text-sm" title={formatAbsolute(item.createdAt)}>
                      {formatRelative(item.createdAt)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
      {activity.data ? (
        <PaginationFooter
          page={activity.data.page}
          totalPages={activity.data.totalPages}
          totalCount={activity.data.totalCount}
          onPageChange={setPage}
        />
      ) : null}
    </Card>
  );
}
```

- [ ] **Step 5: Password section**

Create `frontend/components/profile/password-section.tsx`:

```tsx
"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { FormPage } from "@/components/form/form-page";
import { Button } from "@/components/ui/button";
import {
  ChangePasswordFields,
  type ChangePasswordValues,
} from "@/components/users/change-password-fields";
import { useChangePassword } from "@/hooks/use-change-password";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";

const EMPTY: ChangePasswordValues = { currentPassword: "", newPassword: "" };

/**
 * Change password in a page shell — the fields are the ones the forced first-login
 * screen uses (`forms.md` §2: a swap, not a rewrite). The reset link is the Phase 2.4
 * flow, sent to the caller's own address through the same public route the
 * forgot-password page uses; the confirmation is the same neutral sentence.
 */
export function PasswordSection({ resetEnabled }: { resetEnabled: boolean }) {
  const user = useSession();
  const [values, setValues] = useState<ChangePasswordValues>(EMPTY);
  const change = useChangePassword();
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.auth.passwordResetRequest, {
        method: "POST",
        body: JSON.stringify({ email: user.email }),
      }),
    onSettled: () =>
      toast.success("If mail can reach you, a reset link is on its way."),
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    change.mutate(values, {
      onSuccess: () => {
        toast.success("Password changed. Your other sessions were signed out.");
        setValues(EMPTY);
      },
    });
  }

  return (
    <div className="space-y-4">
      <FormPage
        title="Change password"
        description="Your other sessions will be signed out. This one stays signed in."
        submitLabel="Change password"
        isPending={change.isPending}
        error={change.error}
        onSubmit={handleSubmit}
      >
        <ChangePasswordFields values={values} onChange={setValues} error={change.error} />
      </FormPage>
      {resetEnabled ? (
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">
            Forgotten your current password? We can email you a link instead.
          </p>
          <Button
            variant="outline"
            disabled={reset.isPending}
            onClick={() => reset.mutate()}
          >
            Email me a reset link
          </Button>
        </div>
      ) : null}
    </div>
  );
}
```

`onSettled`, not `onSuccess`: the route answers `202` or `429` alike and the screen must not
tell them apart, exactly as `forgot-password-screen.tsx` treats them.

- [ ] **Step 6: The screen and the route**

Create `frontend/components/profile/profile-screen.tsx`:

```tsx
"use client";

import { AccountSection } from "@/components/profile/account-section";
import { ActivitySection } from "@/components/profile/activity-section";
import { PasswordSection } from "@/components/profile/password-section";
import { SessionsSection } from "@/components/profile/sessions-section";
import { PageHeader } from "@/components/layout/page-header";
import { PreferencesScreen } from "@/components/notifications/preferences-screen";

const SECTIONS = [
  { id: "account", title: "Account" },
  { id: "sessions", title: "Sessions" },
  { id: "activity", title: "Activity" },
  { id: "notifications", title: "Notifications" },
  { id: "password", title: "Password" },
] as const;

/** One column of sections; on wide screens an index of anchors sits beside it. */
export function ProfileScreen({ resetEnabled }: { resetEnabled: boolean }) {
  const body: Record<(typeof SECTIONS)[number]["id"], React.ReactNode> = {
    account: <AccountSection />,
    sessions: <SessionsSection />,
    activity: <ActivitySection />,
    notifications: <PreferencesScreen />,
    password: <PasswordSection resetEnabled={resetEnabled} />,
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader title="Profile" description="Your account, sessions and settings." />
      <div className="grid gap-8 lg:grid-cols-[10rem_1fr]">
        <nav aria-label="Profile sections" className="hidden lg:block">
          <ul className="sticky top-24 space-y-2 text-sm">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-10">
          {SECTIONS.map((section) => (
            <section key={section.id} id={section.id} className="scroll-mt-24 space-y-3">
              <h2 className="text-foreground text-lg font-semibold">{section.title}</h2>
              {body[section.id]}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
```

Create `frontend/app/(app)/profile/page.tsx`:

```tsx
import { ProfileScreen } from "@/components/profile/profile-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";

/**
 * Server-side, like the login page's check: a failed availability read hides the reset
 * button rather than failing the page.
 */
async function resetEnabled(): Promise<boolean> {
  try {
    const { enabled } = await serverFetch<{ enabled: boolean }>(
      endpoints.auth.passwordResetAvailability,
    );
    return enabled;
  } catch {
    return false;
  }
}

export default async function ProfilePage() {
  return <ProfileScreen resetEnabled={await resetEnabled()} />;
}
```

- [ ] **Step 7: Delete the orphaned dialog**

Run: `grep -rn "ChangePasswordDialog" app components hooks lib` — expected: only its own
file. Delete `frontend/components/users/change-password-dialog.tsx`. Update the docstring in
`components/users/change-password-fields.tsx`: "Mounted inside FormPage on the forced route
and on the profile's Password section."

- [ ] **Step 8: Verify and commit**

Run: `bun run vitest run && bun lint && bun run build`
Expected: PASS. `bun run build` catches type errors the dev server tolerates.

```bash
git add frontend
git commit -m "feat(profile): add the profile page

Account and memberships, sessions with per-session sign-out, your own
activity, notification preferences and password change on one page.
Removes the change-password dialog nothing imported.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Documentation, PRD amendments, and final verification

**Files:** `docs/PRD.md`, `.claude/rules/audit-trail.md`, `.claude/rules/navigation.md`,
`docs/data.md`, `docs/notifications.md`, `frontend/README.md`, `CLAUDE.md`, `CHANGELOG.md`.

Each edit states a fact about the tree; keep the surrounding register. Spec §0.2 lists the
PRD amendments — every one lands here.

- [ ] **Step 1: `docs/PRD.md`**

1. **§4.0** — add a `#### Profile` subsection at the end of §4.0 (before line 501's
   out-of-scope paragraph): the `/profile` page and its five sections; the four `/me`
   routes; no `/profile/{id}`, admins view other users only through `/settings/users`;
   editing one's own name or email stays out of scope; a revoked session's access token
   lives out its lifetime (15 minutes by default).
2. **§4.0 out of scope (line 501)** — remove "session-activity history" from the list and
   add after the paragraph: "**Amended (2026-09-26):** a user sees and may revoke their own
   sessions, with device and address captured at sign-in (§4.0 *Profile*). There is still no
   administrator view of anyone else's sessions."
3. **§2.1 Phase 2.2** — add an amendment paragraph: the audit trail has a second, narrow
   reader — a user reads the rows where they are the actor through `GET /me/activity`, with
   project-scoped rows narrowed through `resolve_project_scope`; every other read stays
   admin-only. Same register as the conversation-metadata amendment.
4. **§2.1 Phase 2.3** — one sentence: preferences moved from Settings to the profile; the
   polled count is unchanged.
5. **§6** — after the "Phase 1.1 — module path picker" paragraph, add: "**M0 amendment —
   profile page (shipped, 2026-09-26).** Not a milestone of its own: one page over what M0,
   Phase 2.2 and Phase 2.3 already shipped — account and memberships, own sessions with
   revoke, own audit activity, notification preferences, and password change. Also fixed
   password change revoking the caller's own session. See §4.0." Adjust "shipped" only
   when the PR merges; until then write "(in progress)".
6. **§9** — add: `refresh_tokens.user_agent` and `ip_address` are newly stored personal data
   with the table's existing lifecycle; a user can see the address of failed sign-in
   attempts against their own account.

- [ ] **Step 2: Rules**

- `.claude/rules/audit-trail.md` — in the *Authenticate* row of "What must record an
  event", add "session revoke" and `auth.session.revoked`. In "Who reads it", add a
  paragraph: users read their own actor rows through `GET /me/activity`, narrowed through
  `resolve_project_scope` — a read on a different axis again, still going through
  `app/core/access.py`.
- `.claude/rules/navigation.md` — record `/profile` as breadcrumb-only (reached from the
  account menu, like `/notifications`) and that every Settings child is admin-only again;
  rewrite any sentence calling Notifications Settings' first non-admin child.

- [ ] **Step 3: Reference docs**

- `docs/data.md` — `refresh_tokens` gains `user_agent` (255) and `ip_address` (45), migration
  `d4a9e6b27c15`; `RevokedReason` gains `user_revoked`; the event list gains
  `auth.session.revoked`; define a live session (unused, unrevoked, unexpired head).
- `docs/notifications.md` — preferences live at `/profile#notifications`;
  `/settings/notifications` redirects there.
- `frontend/README.md` — add `/profile` to the screens list and `components/profile/` to the
  layout tree; note `/settings/notifications` is a redirect.
- `CLAUDE.md` — add `/profile` to the frontend route list in the "Frontend" section and note
  `/settings/notifications` now redirects to it. Change no count other than what this makes
  stale.

- [ ] **Step 4: CHANGELOG**

Under `## [Unreleased]` → `### Added`:

```markdown
- **Profile page** at `/profile`, opened from the account menu: your account and project
  memberships, your signed-in sessions with the device and address each started from and a
  per-session sign-out, your own activity from the audit trail, notification preferences,
  and password change (plus "Email me a reset link" when mail is on).
- `GET /me/memberships`, `GET /me/sessions`, `DELETE /me/sessions/{sessionId}`,
  `GET /me/activity`.
- `ErrorCode.SESSION_NOT_FOUND`; audit event `auth.session.revoked`.
```

Under `### Changed`:

```markdown
- Notification preferences moved from Settings to the profile; `/settings/notifications`
  redirects there. Settings is administrator-only again, so non-admins no longer see it in
  the sidebar.
- Access tokens carry a `sid` claim naming their refresh-token family.
```

- [ ] **Step 5: Full verification**

Run from the repo root: `make check`
Expected: lint, format-check, typecheck and both test suites pass. Paste the tail of the
output into the task report; do not claim a pass without it.

Run from `frontend/`: `bun run build` → succeeds.

- [ ] **Step 6: Manual check**

Only with the user's go-ahead to start services (their Ollama must not be started — `make
dev` warns without it, which is fine for this check). With `make infra` and `make dev`:

1. Sign in from two browsers; each shows **This device** on its own row with the right
   browser name.
2. From the first, sign the second out; within 15 minutes the second's next navigation
   lands on `/login`.
3. Change the password from the profile; the page stays signed in past 15 minutes of use.
4. `/settings/notifications` redirects to `/profile#notifications`.
5. As a non-admin, the sidebar has no Settings entry.

Report each result; if a step is skipped, say so.

- [ ] **Step 7: Commit**

```bash
git add docs .claude CHANGELOG.md CLAUDE.md frontend/README.md
git commit -m "docs(profile): record the profile page and its PRD amendments

Own-session history comes off the out-of-scope list, the audit trail
gains a self-read, and preferences move to the profile.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
