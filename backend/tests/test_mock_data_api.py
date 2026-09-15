"""End-to-end route tests, mirroring test_checklist_api.py's non-streaming coverage."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.permissions import VIEWER_NAME
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import GrantMembership
from tests.factories import create_checklist_module, create_mock_data_record, create_project


async def _ready_project(session: AsyncSession) -> Project:
    """An indexed project: the pre-condition for creating a module or generating
    mock data against it."""
    project = await create_project(session, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    project.active_generation = 1
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_get_mock_data_before_any_generation_returns_empty(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    await db_session.commit()

    response = await client_for_admin.get(f"/checklist-modules/{module.id}/mock-data")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["records"] == []


@pytest.mark.asyncio
async def test_generate_returns_202_and_queues_a_job(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    await db_session.commit()

    response = await client_for_admin.post(
        f"/checklist-modules/{module.id}/mock-data-generations",
        json={"count": 5},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "generating"


@pytest.mark.asyncio
async def test_generate_twice_conflicts(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    await db_session.commit()
    await client_for_admin.post(f"/checklist-modules/{module.id}/mock-data-generations")

    response = await client_for_admin.post(f"/checklist-modules/{module.id}/mock-data-generations")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MOCK_DATA_GENERATION_IN_PROGRESS"


@pytest.mark.asyncio
async def test_delete_record_requires_ownership(
    client_for_user_b: AsyncClient,
    user_b: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    """A record created by someone else cannot be deleted by a non-admin caller who
    is not its owner -- `403`, not `404`, because user B holds a role on the project
    and therefore already sees the module, the dataset and the record. A caller with
    no membership gets `404` instead; that is the row below."""
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    record = await create_mock_data_record(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(user_b.id, project.id, VIEWER_NAME)

    response = await client_for_user_b.delete(f"/mock-data-records/{record.id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_MOCK_DATA_RECORD_OWNER"


async def test_delete_record_is_404_for_a_non_member(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    """The counterpart of the row above: with no membership the record must not be
    distinguishable from one that does not exist."""
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    record = await create_mock_data_record(db_session, module_id=module.id)
    await db_session.commit()

    response = await client_for_user_b.delete(f"/mock-data-records/{record.id}")

    assert response.status_code == 404
