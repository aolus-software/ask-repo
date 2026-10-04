"""The eval set HTTP surface: generate, list, read, delete, exclude a pair."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.permissions import EDITOR_NAME, OWNER_NAME, VIEWER_NAME
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.eval import EvalPair, EvalResult, EvalRun, EvalSet, EvalSetStatus
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import EvalJobMessage
from tests.conftest import AuditRows, GrantMembership
from tests.factories import (
    create_eval_pair,
    create_eval_run,
    create_eval_set,
    create_project,
)
from tests.helpers import changed_field, seed_indexed_paths

BODY = {"name": "Baseline", "count": 10, "mix": "balanced"}


async def _ready_project(session: AsyncSession) -> Project:
    """An indexed project: the pre-condition for generating a set."""
    project = await create_project(session, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    project.active_generation = 1
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_generating_a_set_returns_202_and_publishes_a_generate_job(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "generating"
    assert {"projectId", "sourcePath", "requestedCount", "pairCount", "latestRun"} <= set(body)
    topic, message = ingestion_queue.produced[-1]
    assert topic == "askrepo.eval.jobs"
    assert isinstance(message, EvalJobMessage)
    assert message.kind == "generate"
    assert str(message.target_id) == body["id"]
    (row,) = await audit_rows("eval_set.generation.requested")
    assert row.target_label == "Baseline"
    for field in ("name", "sourcePath", "requestedCount", "mix"):
        assert changed_field(row.details, field)["before"] is None


@pytest.mark.asyncio
async def test_a_count_outside_10_25_50_is_422(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets", json={**BODY, "count": 11}
    )

    assert response.status_code == 422
    assert "count" in response.json()["detail"]["fields"]


@pytest.mark.asyncio
async def test_an_unindexed_path_is_400(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    project = await _ready_project(db_session)
    seed_indexed_paths(vector_store, project.id, "backend/app/config.py")
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets", json={**BODY, "sourcePath": "nowhere/at/all"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MODULE_PATH_NOT_INDEXED"


@pytest.mark.asyncio
async def test_generating_during_a_reindex_is_409(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    project.reindex_in_progress = True
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


@pytest.mark.asyncio
async def test_a_viewer_may_list_but_not_generate(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    listed = await authed_client.get(f"/projects/{project.id}/eval-sets")
    created = await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY)

    assert listed.status_code == 200
    assert set(listed.json()) == {"items", "page", "limit", "totalCount", "totalPages"}
    assert created.status_code == 403
    assert created.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_a_non_member_gets_404_on_every_set_route(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id)
    pair = await create_eval_pair(db_session, set_id=eval_set.id)
    await db_session.commit()

    responses = [
        await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY),
        await authed_client.get(f"/projects/{project.id}/eval-sets"),
        await authed_client.get(f"/eval-sets/{eval_set.id}"),
        await authed_client.delete(f"/eval-sets/{eval_set.id}"),
        await authed_client.put(f"/eval-pairs/{pair.id}/excluded", json={"excluded": True}),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_an_unknown_set_in_a_visible_project_is_404_eval_set_not_found(
    authed_client: AsyncClient,
) -> None:
    """A random id has no project to check, so it is `EVAL_SET_NOT_FOUND`; a real set in a
    project the caller cannot see is `PROJECT_NOT_FOUND`. Both are `404`, and neither
    confirms that a private project exists."""
    response = await authed_client.get(f"/eval-sets/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] in {"EVAL_SET_NOT_FOUND", "PROJECT_NOT_FOUND"}


@pytest.mark.asyncio
async def test_set_detail_lists_pairs_in_order_with_excluded_flag(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, pair_count=2)
    await create_eval_pair(db_session, set_id=eval_set.id, position=1, excluded=True)
    await create_eval_pair(db_session, set_id=eval_set.id, position=0)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    body = (await authed_client.get(f"/eval-sets/{eval_set.id}")).json()

    assert [pair["position"] for pair in body["pairs"]] == [0, 1]
    assert [pair["excluded"] for pair in body["pairs"]] == [False, True]
    assert body["projectGeneration"] == 1
    assert {"questionType", "referenceAnswer", "sourceFile", "startLine", "endLine"} <= set(
        body["pairs"][0]
    )


@pytest.mark.asyncio
async def test_excluding_a_pair_round_trips_and_is_audited_once(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, pair_count=1)
    pair = await create_eval_pair(db_session, set_id=eval_set.id)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    first = await authed_client.put(f"/eval-pairs/{pair.id}/excluded", json={"excluded": True})
    second = await authed_client.put(f"/eval-pairs/{pair.id}/excluded", json={"excluded": True})

    assert first.status_code == second.status_code == 200
    assert first.json()["excluded"] is True
    (row,) = await audit_rows("eval_pair.updated")
    assert changed_field(row.details, "excluded") == {"before": False, "after": True}
    assert "question" not in str(row.details)


@pytest.mark.asyncio
async def test_a_viewer_cannot_exclude_a_pair(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id)
    pair = await create_eval_pair(db_session, set_id=eval_set.id)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    response = await authed_client.put(f"/eval-pairs/{pair.id}/excluded", json={"excluded": True})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_deleting_a_set_soft_deletes_pairs_runs_and_results(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, pair_count=1)
    pair = await create_eval_pair(db_session, set_id=eval_set.id)
    run = await create_eval_run(
        db_session, set_id=eval_set.id, project_id=project.id, created_by=authed_user.id
    )
    result = EvalResult(
        id=uuid.uuid4(),
        run_id=run.id,
        pair_id=pair.id,
        retrieval_hit=True,
        verdict="correct",
        answer="a",
        grounding_warnings=[],
        retrieval_attempts=1,
    )
    db_session.add(result)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, OWNER_NAME)
    set_id, pair_id, run_id, result_id = eval_set.id, pair.id, run.id, result.id

    response = await authed_client.delete(f"/eval-sets/{set_id}")

    assert response.status_code == 204
    db_session.expire_all()
    models: list[tuple[type[EvalSet | EvalPair | EvalRun | EvalResult], uuid.UUID]] = [
        (EvalSet, set_id),
        (EvalPair, pair_id),
        (EvalRun, run_id),
        (EvalResult, result_id),
    ]
    for model, row_id in models:
        stamped = await db_session.scalar(
            select(model.id).where(model.id == row_id, model.deleted_at.is_not(None))
        )
        assert stamped == row_id, model.__name__
    (event,) = await audit_rows("eval_set.deleted")
    assert event.details["pairCount"] == 1
    assert event.details["runCount"] == 1
    assert (await authed_client.get(f"/eval-sets/{set_id}")).status_code == 404


@pytest.mark.asyncio
async def test_deleting_a_set_with_a_running_run_is_409(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, status=EvalSetStatus.READY)
    await create_eval_run(
        db_session,
        set_id=eval_set.id,
        project_id=project.id,
        created_by=authed_user.id,
        status="running",
    )
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, OWNER_NAME)

    response = await authed_client.delete(f"/eval-sets/{eval_set.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVAL_RUN_IN_PROGRESS"
