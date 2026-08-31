"""The QA routes: the wire shape, the gate, and the one write that is not gated."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_qa_pair, create_user


async def test_list_returns_a_page_in_camel_case(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    await create_qa_pair(db_session, created_by=user.id, module="auth")
    await db_session.commit()

    response = await client_for_user_a.get("/qa-pairs")

    assert response.status_code == 200
    body = response.json()
    assert body["totalCount"] == 1
    assert body["items"][0]["module"] == "auth"
    assert "referenceAnswer" in body["items"][0]
    assert "reference_answer" not in body["items"][0]


async def test_every_user_sees_every_pair(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    """Phase-1 sharing, and it is intended (`docs/PRD.md` §4.1)."""
    stranger = await create_user(db_session)
    await create_qa_pair(db_session, created_by=stranger.id)
    await db_session.commit()

    response = await client_for_user_b.get("/qa-pairs")

    assert response.json()["totalCount"] == 1


async def test_filters_flatten_into_query_parameters(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    """The regression guard for `QAPairListQuery` being a ListQuery subclass.

    If a filter is ever moved to a sibling `Query(...)` parameter, FastAPI stops
    flattening the model and this returns 422 with `{"request": "Field required"}`.
    """
    user = await create_user(db_session)
    await create_qa_pair(db_session, created_by=user.id, tags=["auth"])
    await create_qa_pair(db_session, created_by=user.id, tags=["billing"])
    await db_session.commit()

    response = await client_for_user_a.get("/qa-pairs?tag=auth&status=unreviewed&limit=5")

    assert response.status_code == 200
    assert response.json()["totalCount"] == 1


async def test_unlisted_sort_field_is_400(client_for_user_a: AsyncClient) -> None:
    response = await client_for_user_a.get("/qa-pairs?sort=password_hash")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_SORT_FIELD"


async def test_tags_route_is_not_swallowed_by_the_detail_route(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    """`/qa-pairs/tags` must be declared before `/qa-pairs/{id}`.

    Declared after, FastAPI matches it as an id and the request dies on a malformed
    UUID with a 422 that names nothing useful.
    """
    user = await create_user(db_session)
    await create_qa_pair(db_session, created_by=user.id, tags=["billing", "auth"])
    await db_session.commit()

    response = await client_for_user_a.get("/qa-pairs/tags")

    assert response.status_code == 200
    assert response.json() == ["auth", "billing"]


async def test_a_non_owner_cannot_edit_or_delete(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await create_user(db_session)
    pair = await create_qa_pair(db_session, created_by=owner.id)
    await db_session.commit()

    patched = await client_for_user_b.patch(f"/qa-pairs/{pair.id}", json={"module": "hijacked"})
    deleted = await client_for_user_b.delete(f"/qa-pairs/{pair.id}")

    assert patched.status_code == 403
    assert patched.json()["detail"]["code"] == "NOT_QA_PAIR_OWNER"
    assert deleted.status_code == 403


async def test_a_non_owner_CAN_set_the_status(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    """Asserted explicitly, and it is not a mistake.

    `docs/PRD.md:338`: "Any user may create and verify a pair. Editing or deleting a
    pair requires `created_by` or admin." Anyone tightening this to 403 is changing
    documented behaviour, not fixing an oversight.
    """
    owner = await create_user(db_session)
    pair = await create_qa_pair(db_session, created_by=owner.id)
    await db_session.commit()

    response = await client_for_user_b.put(f"/qa-pairs/{pair.id}/status", json={"status": "fail"})

    assert response.status_code == 200
    assert response.json()["status"] == "fail"


async def test_an_unknown_pair_is_404(client_for_user_a: AsyncClient) -> None:
    response = await client_for_user_a.get(f"/qa-pairs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "QA_PAIR_NOT_FOUND"


async def test_the_routes_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/qa-pairs")).status_code == 401
