"""The HTTP surface: status codes, the two gates, and the stream's content type."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.checklist import ChangeSetStatus
from app.models.project import Project, ProjectStatus
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_module,
    create_project,
)
from tests.helpers import seed_indexed_paths


async def _ready_project(session: AsyncSession) -> Project:
    """An indexed project: the pre-condition for creating a module or chatting."""
    project = await create_project(session, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    project.active_generation = 1
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_list_modules_returns_a_paginated_envelope(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Never a bare array for a paginated resource (`.claude/rules/router.md`)."""
    await create_checklist_module(db_session)
    await db_session.commit()

    response = await authed_client.get("/checklist-modules")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "page", "limit", "totalCount", "totalPages"}


@pytest.mark.asyncio
async def test_module_response_is_camel_case(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await create_checklist_module(db_session)
    await db_session.commit()

    body = (await authed_client.get(f"/checklist-modules/{module.id}")).json()

    assert "sourcePath" in body
    assert "pendingChangeSetId" in body
    assert "source_path" not in body


@pytest.mark.asyncio
async def test_creating_a_module_on_an_unindexed_path_is_400(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """Phase 1.1: rejected at creation, on the field the user just filled in, rather
    than accepted with a `201` that fails in a background job an hour later."""
    project = await _ready_project(db_session)
    seed_indexed_paths(vector_store, project.id, "backend/app/config.py")
    await db_session.commit()

    response = await authed_client.post(
        "/checklist-modules",
        json={"projectId": str(project.id), "name": "Auth", "sourcePath": "backend/app/authz"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MODULE_PATH_NOT_INDEXED"


@pytest.mark.asyncio
async def test_an_unknown_module_is_404(authed_client: AsyncClient) -> None:
    response = await authed_client.get(f"/checklist-modules/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CHECKLIST_MODULE_NOT_FOUND"


@pytest.mark.asyncio
async def test_editing_another_users_item_is_403(
    client_for_user_a: AsyncClient,
    client_for_user_b: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """403, not 404: module and item existence is deliberately public."""
    project = await _ready_project(db_session)
    # `POST /checklist-modules` refuses a path that matches nothing in the index
    # (phase 1.1), so the tree has to exist before a module can be created against it.
    seed_indexed_paths(vector_store, project.id, "app/auth/routes.py")
    await db_session.commit()
    created = (
        await client_for_user_a.post(
            "/checklist-modules",
            json={
                "projectId": str(project.id),
                "name": "Auth",
                "sourcePath": "app/auth",
            },
        )
    ).json()
    item = (
        await client_for_user_a.post(
            "/checklist-items",
            json={
                "moduleId": created["id"],
                "feature": "Login",
                "testName": "t",
                "expectedResult": "e",
            },
        )
    ).json()

    response = await client_for_user_b.patch(
        f"/checklist-items/{item['id']}", json={"expectedResult": "anything"}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_CHECKLIST_OWNER"


@pytest.mark.asyncio
async def test_recording_a_result_is_open_to_anyone(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole point of the split (spec 2.5): user B authored none of this."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(db_session, module_id=module.id)
    await db_session.commit()

    response = await client_for_user_b.put(
        f"/checklist-items/{item.id}/result",
        json={"currentResult": "Returned 500", "status": "fail"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "fail"


@pytest.mark.asyncio
async def test_export_returns_a_spreadsheet(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await create_checklist_module(db_session)
    await create_checklist_item(db_session, module_id=module.id)
    await db_session.commit()

    response = await authed_client.get("/checklist-items/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert "checklist.xlsx" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_is_matched_before_the_id_route(authed_client: AsyncClient) -> None:
    """FastAPI matches in declaration order: a literal path declared after a
    parameterised one is swallowed as an id and 422s every request."""
    assert (await authed_client.get("/checklist-items/export")).status_code != 422


@pytest.mark.asyncio
async def test_a_chat_turn_streams_server_sent_events(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await create_checklist_module(
        db_session, project_id=(await _ready_project(db_session)).id
    )
    await db_session.commit()

    async with authed_client.stream(
        "POST", f"/checklist-modules/{module.id}/messages", json={"question": "Add a test."}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join([chunk async for chunk in response.aiter_text()])

    assert body.count("event: done") + body.count("event: error") == 1


@pytest.mark.asyncio
async def test_generate_publishes_a_job_and_returns_202(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Fire-and-forget: the result is a change set to review, not a response body."""
    module = await create_checklist_module(
        db_session, project_id=(await _ready_project(db_session)).id
    )
    await db_session.commit()

    response = await authed_client.post(f"/checklist-modules/{module.id}/generate")

    assert response.status_code == 202
    assert response.json()["status"] == "generating"


@pytest.mark.asyncio
async def test_applying_a_resolved_change_set_is_409(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    change_set = await create_checklist_change_set(db_session, status=ChangeSetStatus.APPLIED)
    await db_session.commit()

    response = await authed_client.post(f"/checklist-change-sets/{change_set.id}/apply", json={})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CHANGE_SET_ALREADY_RESOLVED"


@pytest.mark.asyncio
async def test_discarding_a_pending_change_set_resolves_it(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Open to any authenticated user: reviewing a shared document (spec 5.4)."""
    change_set = await create_checklist_change_set(db_session)
    await db_session.commit()

    response = await authed_client.post(f"/checklist-change-sets/{change_set.id}/discard")

    assert response.status_code == 200
    assert response.json()["status"] == "discarded"
