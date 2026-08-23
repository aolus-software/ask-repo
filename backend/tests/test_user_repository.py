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
