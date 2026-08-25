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
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password
from app.models import User
from app.schemas.user import UserCreateRequest
from app.services.user import UserService

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

    # Not a bare `"password" not in text` check: the response legitimately carries
    # `mustChangePassword`, whose lowercased form contains "password" as a substring.
    # What must be absent is the secret itself — a `password`/`passwordHash` field,
    # or a bcrypt hash.
    assert '"password"' not in response.text
    assert '"passwordHash"' not in response.text
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


async def test_a_racing_duplicate_email_is_409_not_500(db_session: AsyncSession) -> None:
    """Two admins creating the same address in one flush window both pass the
    check-then-insert pre-check; the second commit hits the partial unique index and
    must still surface `409 EMAIL_ALREADY_EXISTS`, not a bare `500`.
    """
    await _make_user(db_session, email="race@example.com")
    service = UserService(db_session, get_settings())

    async def _pretend_available(email: str) -> bool:
        """Simulate the pre-check having run before the colliding row existed."""
        return False

    service.users.email_exists = _pretend_available  # type: ignore[method-assign]

    with pytest.raises(AppError) as caught:
        await service.create(
            UserCreateRequest(
                name="Racer", email="race@example.com", password=GOOD_PASSWORD, is_admin=False
            )
        )

    assert caught.value.status_code == 409
    assert caught.value.code == "EMAIL_ALREADY_EXISTS"


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


async def test_an_unknown_sort_field_is_400(client: AsyncClient, db_session: AsyncSession) -> None:
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


async def test_patch_cannot_change_the_email(client: AsyncClient, db_session: AsyncSession) -> None:
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
