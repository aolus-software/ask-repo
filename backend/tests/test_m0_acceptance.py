"""The §7 success criterion, end to end.

Every other test asserts a part. This one asserts the whole sentence: "An admin can
bring up a fresh instance, log in as a seeded admin, change the initial password, and
create an account for a colleague — with no manual database work."
"""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import seed_admins
from app.config import get_settings

SEEDED_PASSWORD = "a-perfectly-fine-passphrase"
CHOSEN_PASSWORD = "an-entirely-different-passphrase"


@pytest.fixture(autouse=True)
def _bootstrap_password() -> Iterator[None]:
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
    assert login.json()["user"]["mustChangePassword"] is True

    headers = {"Authorization": f"Bearer {access}"}

    # The rest of the API is closed until the password changes.
    blocked = await client.get("/users", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    # Change the initial password, using the token issued before the change. The
    # refresh cookie login set is already on the client's jar; setting it again via a
    # per-request kwarg would trigger httpx's cookie-persistence deprecation warning.
    changed = await client.post(
        "/auth/change-password",
        headers=headers,
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
