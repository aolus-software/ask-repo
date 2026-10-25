"""The eval set HTTP surface: generate, list, read, delete, exclude a pair."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
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

    by_project = [
        await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY),
        await authed_client.get(f"/projects/{project.id}/eval-sets"),
    ]
    # Reached by the set's or pair's own id: the same code a random id gets, so a
    # former member holding an id cannot tell whether it still exists.
    by_set_id = [
        await authed_client.get(f"/eval-sets/{eval_set.id}"),
        await authed_client.delete(f"/eval-sets/{eval_set.id}"),
        await authed_client.put(f"/eval-pairs/{pair.id}/excluded", json={"excluded": True}),
    ]

    for response in by_project:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"
    for response in by_set_id:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "EVAL_SET_NOT_FOUND"


@pytest.mark.asyncio
async def test_an_unknown_set_in_a_visible_project_is_404_eval_set_not_found(
    authed_client: AsyncClient,
) -> None:
    """A random id answers exactly as a real set in a hidden project does
    (`test_a_non_member_gets_404_on_every_set_route`), so the code cannot tell them apart."""
    response = await authed_client.get(f"/eval-sets/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EVAL_SET_NOT_FOUND"


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
async def test_deleting_a_project_soft_deletes_all_four_eval_tables(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
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
    ids: list[tuple[type[EvalSet | EvalPair | EvalRun | EvalResult], uuid.UUID]] = [
        (EvalSet, eval_set.id),
        (EvalPair, pair.id),
        (EvalRun, run.id),
        (EvalResult, result.id),
    ]

    response = await authed_client.delete(f"/projects/{project.id}")

    assert response.status_code == 204
    db_session.expire_all()
    for model, row_id in ids:
        stamped = await db_session.scalar(
            select(model.id).where(model.id == row_id, model.deleted_at.is_not(None))
        )
        assert stamped == row_id, model.__name__


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


async def _runnable_set(
    db_session: AsyncSession, *, pairs: int = 2, excluded: int = 0
) -> tuple[Project, EvalSet]:
    """A ready project holding a ready set with `pairs` pairs, `excluded` of them excluded."""
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(
        db_session, project_id=project.id, status=EvalSetStatus.READY, pair_count=pairs
    )
    for position in range(pairs):
        await create_eval_pair(
            db_session, set_id=eval_set.id, position=position, excluded=position < excluded
        )
    return project, eval_set


@pytest.mark.asyncio
async def test_starting_a_run_returns_202_and_publishes_a_run_job(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    audit_rows: AuditRows,
) -> None:
    project, eval_set = await _runnable_set(db_session, pairs=3, excluded=1)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert body["setId"] == str(eval_set.id)
    topic, message = ingestion_queue.produced[-1]
    assert topic == "askrepo.eval.jobs"
    assert isinstance(message, EvalJobMessage)
    assert message.kind == "run"
    assert str(message.target_id) == body["id"]
    (row,) = await audit_rows("eval_run.requested")
    assert row.target_label == eval_set.name
    assert row.target_id == uuid.UUID(body["id"])
    assert row.details["pairCount"] == 2


@pytest.mark.asyncio
async def test_a_run_on_a_generating_set_is_409_not_ready(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(
        db_session, project_id=project.id, status=EvalSetStatus.GENERATING
    )
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVAL_SET_NOT_READY"


@pytest.mark.asyncio
async def test_a_run_with_every_pair_excluded_is_409_not_ready(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session, pairs=2, excluded=2)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVAL_SET_NOT_READY"


@pytest.mark.asyncio
async def test_a_second_run_while_one_runs_is_409_in_progress(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    first = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")
    second = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "EVAL_RUN_IN_PROGRESS"


@pytest.mark.asyncio
async def test_a_run_during_a_reindex_is_409(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session)
    project.reindex_in_progress = True
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


@pytest.mark.asyncio
async def test_a_run_after_an_embedding_model_change_is_409(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session)
    project.embedding_model = "other"
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMBEDDING_MODEL_CHANGED"


@pytest.mark.asyncio
async def test_runs_list_newest_first_and_a_run_reads_with_its_results(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session, pairs=1)
    pair = (await db_session.scalars(select(EvalPair).where(EvalPair.set_id == eval_set.id))).one()
    older = await create_eval_run(
        db_session, set_id=eval_set.id, project_id=project.id, created_by=authed_user.id
    )
    newer = await create_eval_run(
        db_session, set_id=eval_set.id, project_id=project.id, created_by=authed_user.id
    )
    # One transaction means one `now()`; pin the order the assertion depends on.
    older.created_at = newer.created_at - timedelta(minutes=5)
    db_session.add(
        EvalResult(
            id=uuid.uuid4(),
            run_id=newer.id,
            pair_id=pair.id,
            retrieval_hit=True,
            verdict="correct",
            judge_reason="Matches.",
            answer="It does thing 0.",
            grounding_warnings=["uncited_answer"],
            retrieval_attempts=2,
        )
    )
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    listed = await authed_client.get(f"/eval-sets/{eval_set.id}/runs")
    detail = await authed_client.get(f"/eval-runs/{newer.id}")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [str(newer.id), str(older.id)]
    assert detail.status_code == 200
    (result,) = detail.json()["results"]
    assert set(result) == {
        "id",
        "pairId",
        "retrievalHit",
        "verdict",
        "judgeReason",
        "answer",
        "groundingWarnings",
        "retrievalAttempts",
    }
    assert result["pairId"] == str(pair.id)
    assert result["groundingWarnings"] == ["uncited_answer"]


@pytest.mark.asyncio
async def test_a_viewer_may_read_runs_but_not_start_one(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project, eval_set = await _runnable_set(db_session)
    run = await create_eval_run(
        db_session,
        set_id=eval_set.id,
        project_id=project.id,
        created_by=authed_user.id,
        status="done",
    )
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    listed = await authed_client.get(f"/eval-sets/{eval_set.id}/runs")
    read = await authed_client.get(f"/eval-runs/{run.id}")
    started = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert listed.status_code == 200
    assert read.status_code == 200
    assert started.status_code == 403
    assert started.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_a_non_member_gets_404_on_every_run_route(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    project, eval_set = await _runnable_set(db_session)
    run = await create_eval_run(
        db_session, set_id=eval_set.id, project_id=project.id, created_by=authed_user.id
    )
    await db_session.commit()

    by_set_id = [
        await authed_client.post(f"/eval-sets/{eval_set.id}/runs"),
        await authed_client.get(f"/eval-sets/{eval_set.id}/runs"),
    ]
    by_run_id = await authed_client.get(f"/eval-runs/{run.id}")

    for response in by_set_id:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "EVAL_SET_NOT_FOUND"
    assert by_run_id.status_code == 404
    assert by_run_id.json()["detail"]["code"] == "EVAL_RUN_NOT_FOUND"


@pytest.mark.asyncio
async def test_an_unknown_run_is_404_eval_run_not_found(authed_client: AsyncClient) -> None:
    response = await authed_client.get(f"/eval-runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EVAL_RUN_NOT_FOUND"


async def _owned_ready_project(
    authed_user: User, grant_membership: GrantMembership, db_session: AsyncSession
) -> tuple[Project, EvalSet]:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, status=EvalSetStatus.READY)
    await grant_membership(authed_user.id, project.id, OWNER_NAME)
    return project, eval_set


@pytest.mark.asyncio
async def test_reindex_during_a_running_eval_run_is_409_and_changes_nothing(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project, eval_set = await _owned_ready_project(authed_user, grant_membership, db_session)
    await create_eval_run(
        db_session,
        set_id=eval_set.id,
        project_id=project.id,
        created_by=authed_user.id,
        status="running",
    )
    await db_session.commit()

    response = await authed_client.post(f"/projects/{project.id}/reindex")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVAL_RUN_IN_PROGRESS"
    await db_session.refresh(project)
    assert project.reindex_in_progress is False
    assert await audit_rows("project.reindex.requested") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["done", "failed", "deleted"])
async def test_reindex_ignores_runs_that_are_finished_or_deleted(
    state: str,
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    project, eval_set = await _owned_ready_project(authed_user, grant_membership, db_session)
    run = await create_eval_run(
        db_session,
        set_id=eval_set.id,
        project_id=project.id,
        created_by=authed_user.id,
        status="running" if state == "deleted" else state,
    )
    if state == "deleted":
        run.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await authed_client.post(f"/projects/{project.id}/reindex")

    assert response.status_code == 202
    assert response.json()["enqueued"] is True


@pytest.mark.asyncio
async def test_deleting_a_set_takes_the_set_lock_first(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.repositories.eval_set import EvalSetRepository

    project, eval_set = await _runnable_set(db_session)
    await grant_membership(authed_user.id, project.id, OWNER_NAME)
    await db_session.commit()
    locked: list[uuid.UUID] = []
    original = EvalSetRepository.lock

    async def spy(self: EvalSetRepository, set_id: uuid.UUID) -> EvalSet | None:
        locked.append(set_id)
        return await original(self, set_id)

    monkeypatch.setattr(EvalSetRepository, "lock", spy)

    assert (await authed_client.delete(f"/eval-sets/{eval_set.id}")).status_code == 204
    assert locked == [eval_set.id]


@pytest.mark.asyncio
async def test_starting_a_run_locks_the_project_before_the_set(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Project deletion updates the project row and then the set rows; taking the
    # locks in the other order here would let the two deadlock each other.
    from app.repositories.eval_set import EvalSetRepository
    from app.repositories.project import ProjectRepository

    project, eval_set = await _runnable_set(db_session)
    await grant_membership(authed_user.id, project.id, OWNER_NAME)
    await db_session.commit()
    order: list[str] = []
    set_lock = EvalSetRepository.lock
    project_lock = ProjectRepository.lock

    async def spy_set(self: EvalSetRepository, set_id: uuid.UUID) -> EvalSet | None:
        order.append("set")
        return await set_lock(self, set_id)

    async def spy_project(self: ProjectRepository, project_id: uuid.UUID) -> Project | None:
        order.append("project")
        return await project_lock(self, project_id)

    monkeypatch.setattr(EvalSetRepository, "lock", spy_set)
    monkeypatch.setattr(ProjectRepository, "lock", spy_project)

    response = await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert response.status_code == 202, response.text
    assert order == ["project", "set"]


@pytest.mark.asyncio
async def test_reads_carry_language_and_lineage(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(db_session, project_id=project.id, pair_count=1)
    await create_eval_pair(db_session, set_id=eval_set.id)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    listed = (await authed_client.get(f"/projects/{project.id}/eval-sets")).json()
    detail = (await authed_client.get(f"/eval-sets/{eval_set.id}")).json()

    assert listed["items"][0]["language"] == "en"
    assert listed["items"][0]["sourceSetId"] is None
    assert detail["pairs"][0]["sourcePairId"] is None
    assert detail["pairs"][0]["exclusionReason"] is None


async def _english_source(session: AsyncSession, project: Project) -> EvalSet:
    """A ready, natively generated English set with one pair, as a translation's source."""
    source = await create_eval_set(session, project_id=project.id, name="Auth", pair_count=1)
    source.source_path = "backend/app/"
    source.requested_count = 25
    source.mix = "locate"
    source.indexed_generation = 1
    await create_eval_pair(session, set_id=source.id)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_translating_a_set_copies_its_scope_and_publishes_a_generate_job(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets",
        json={"sourceSetId": str(source.id), "language": "id"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "generating"
    assert body["language"] == "id"
    assert body["sourceSetId"] == str(source.id)
    assert body["name"] == "Auth · id"
    assert (body["sourcePath"], body["requestedCount"], body["mix"]) == (
        "backend/app/",
        25,
        "locate",
    )
    assert body["indexedGeneration"] == 1
    _, message = ingestion_queue.produced[-1]
    assert isinstance(message, EvalJobMessage)
    assert message.kind == "generate"
    assert str(message.target_id) == body["id"]
    (row,) = await audit_rows("eval_set.generation.requested")
    assert row.details["language"] == "id"
    assert row.details["sourceSetId"] == str(source.id)


@pytest.mark.asyncio
async def test_a_native_set_records_english_and_no_source(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    body = (await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY)).json()

    assert body["language"] == "en"
    assert body["sourceSetId"] is None
    (row,) = await audit_rows("eval_set.generation.requested")
    assert row.details["language"] == "en"
    assert "sourceSetId" not in row.details


@pytest.mark.asyncio
async def test_a_second_live_translation_into_one_language_is_409(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)
    body = {"sourceSetId": str(source.id), "language": "ko"}

    first = await authed_client.post(f"/projects/{project.id}/eval-sets", json=body)
    second = await authed_client.post(f"/projects/{project.id}/eval-sets", json=body)
    other_language = await authed_client.post(
        f"/projects/{project.id}/eval-sets", json={**body, "language": "ja"}
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "EVAL_TRANSLATION_EXISTS"
    assert other_language.status_code == 202


@pytest.mark.asyncio
async def test_a_deleted_translation_frees_its_language(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)
    body = {"sourceSetId": str(source.id), "language": "ms"}

    first = (await authed_client.post(f"/projects/{project.id}/eval-sets", json=body)).json()
    # A set that is still generating cannot be deleted (EVAL_SET_GENERATING); let it finish.
    await db_session.execute(
        update(EvalSet).where(EvalSet.id == uuid.UUID(first["id"])).values(status="ready")
    )
    await db_session.commit()
    assert (await authed_client.delete(f"/eval-sets/{first['id']}")).status_code == 204
    again = await authed_client.post(f"/projects/{project.id}/eval-sets", json=body)

    assert again.status_code == 202


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["unknown", "not_ready", "a_translation", "other_project", "deleted"]
)
async def test_an_unusable_source_is_one_422(
    case: str,
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    source_id = source.id
    if case == "unknown":
        source_id = uuid.uuid4()
    elif case == "not_ready":
        source.status = EvalSetStatus.GENERATING.value
    elif case == "a_translation":
        translated = await create_eval_set(
            db_session, project_id=project.id, language="id", source_set_id=source.id
        )
        source_id = translated.id
    elif case == "other_project":
        elsewhere = await _ready_project(db_session)
        source_id = (await create_eval_set(db_session, project_id=elsewhere.id)).id
    elif case == "deleted":
        source.deleted_at = datetime.now(UTC)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets",
        json={"sourceSetId": str(source_id), "language": "id"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["fieldTypes"] == {"sourceSetId": "eval_source_invalid"}
    assert set(detail["fields"]) == {"sourceSetId"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"sourceSetId": "00000000-0000-0000-0000-000000000000", "language": "en"},
        {"sourceSetId": "00000000-0000-0000-0000-000000000000", "language": "fr"},
        {"sourceSetId": "00000000-0000-0000-0000-000000000000"},
        {"sourceSetId": "00000000-0000-0000-0000-000000000000", "language": "id", "count": 10},
        {**BODY, "language": "id"},
        {"count": 10, "mix": "balanced"},
    ],
)
async def test_a_mixed_or_incomplete_body_is_422(
    body: dict[str, object],
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/projects/{project.id}/eval-sets", json=body)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translating_needs_eval_run(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets",
        json={"sourceSetId": str(source.id), "language": "id"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_translating_needs_a_stable_index(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await _english_source(db_session, project)
    project.reindex_in_progress = True
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        f"/projects/{project.id}/eval-sets",
        json={"sourceSetId": str(source.id), "language": "id"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


async def test_deleting_a_generating_set_is_409(
    authed_client: AsyncClient,
    grant_membership: GrantMembership,
    authed_user: User,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(
        db_session, project_id=project.id, status=EvalSetStatus.GENERATING
    )
    set_id = eval_set.id
    await grant_membership(authed_user.id, project.id, OWNER_NAME)

    response = await authed_client.delete(f"/eval-sets/{set_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVAL_SET_GENERATING"
    db_session.expire_all()
    row = await db_session.get(EvalSet, set_id)
    assert row is not None
    assert row.deleted_at is None


async def test_deleting_a_set_whose_translation_is_generating_is_409_until_it_finishes(
    authed_client: AsyncClient,
    grant_membership: GrantMembership,
    authed_user: User,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await create_eval_set(db_session, project_id=project.id)
    translation = await create_eval_set(
        db_session,
        project_id=project.id,
        status=EvalSetStatus.GENERATING,
        language="id",
        source_set_id=source.id,
    )
    await grant_membership(authed_user.id, project.id, OWNER_NAME)

    refused = await authed_client.delete(f"/eval-sets/{source.id}")

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "EVAL_SET_GENERATING"

    translation.status = EvalSetStatus.READY.value
    await db_session.commit()

    assert (await authed_client.delete(f"/eval-sets/{source.id}")).status_code == 204
    assert (await authed_client.delete(f"/eval-sets/{translation.id}")).status_code == 204


async def test_a_deleted_generating_translation_does_not_block_its_source(
    authed_client: AsyncClient,
    grant_membership: GrantMembership,
    authed_user: User,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    source = await create_eval_set(db_session, project_id=project.id)
    translation = await create_eval_set(
        db_session,
        project_id=project.id,
        status=EvalSetStatus.GENERATING,
        language="id",
        source_set_id=source.id,
    )
    translation.deleted_at = datetime.now(UTC)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, OWNER_NAME)

    assert (await authed_client.delete(f"/eval-sets/{source.id}")).status_code == 204


async def test_the_generating_refusal_comes_after_the_404_and_403(
    authed_client: AsyncClient,
    grant_membership: GrantMembership,
    authed_user: User,
    db_session: AsyncSession,
) -> None:
    project = await _ready_project(db_session)
    eval_set = await create_eval_set(
        db_session, project_id=project.id, status=EvalSetStatus.GENERATING
    )
    await db_session.commit()

    not_a_member = await authed_client.delete(f"/eval-sets/{eval_set.id}")
    await grant_membership(authed_user.id, project.id, VIEWER_NAME)
    without_permission = await authed_client.delete(f"/eval-sets/{eval_set.id}")

    assert not_a_member.status_code == 404
    assert not_a_member.json()["detail"]["code"] == "EVAL_SET_NOT_FOUND"
    assert without_permission.status_code == 403
    assert without_permission.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


class _BrokerDown(Exception):
    """Stands in for any failure of the Kafka produce."""


async def _refuse_to_publish(*args: object, **kwargs: object) -> None:
    raise _BrokerDown


async def test_a_failed_publish_still_leaves_the_set_request_on_the_trail(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await _ready_project(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)
    monkeypatch.setattr(ingestion_queue, "enqueue_eval", _refuse_to_publish)

    with pytest.raises(_BrokerDown):
        await authed_client.post(f"/projects/{project.id}/eval-sets", json=BODY)

    assert len(await audit_rows("eval_set.generation.requested")) == 1


async def test_a_failed_publish_still_leaves_the_run_request_on_the_trail(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, eval_set = await _runnable_set(db_session, pairs=2)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)
    monkeypatch.setattr(ingestion_queue, "enqueue_eval", _refuse_to_publish)

    with pytest.raises(_BrokerDown):
        await authed_client.post(f"/eval-sets/{eval_set.id}/runs")

    assert len(await audit_rows("eval_run.requested")) == 1
