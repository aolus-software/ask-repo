"""Re-running a saved question: the pre-flight codes and the ordering contract."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import Project, ProjectStatus
from app.models.qa_pair import QAPair, QAStatus
from tests.factories import create_project, create_qa_pair, create_user
from tests.test_conversations_api import seed_ready_project, sse_events


async def caller_id(client: AsyncClient) -> uuid.UUID:
    """The user this client is authenticated as.

    The client fixtures create their user internally and never expose it, and other
    suites sidestep that by creating the resource through the API so `created_by`
    lands on the caller. A QA pair cannot be created that way without first seeding
    a whole answered conversation, so the id is read back off `/auth/me` instead.

    It matters here because re-running is gated on `created_by`: a pair owned by a
    freshly-made stranger returns `403` before the route reaches anything this file
    is trying to test.
    """
    response = await client.get("/auth/me")
    return uuid.UUID(response.json()["id"])


async def test_rerun_streams_citations_once_before_the_first_token(
    client_for_user_a: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """`.claude/rules/rag.md`'s ordering contract holds on this route too."""
    owner_id = await caller_id(client_for_user_a)
    project_id = await seed_ready_project(db_session, vector_store, owner_id)
    pair = await create_qa_pair(db_session, project_id=project_id, created_by=owner_id)
    await db_session.commit()

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    names = [name for name, _ in events]
    assert names.count("citations") == 1
    assert names.index("citations") < names.index("token")
    # Exactly one terminator, and it carries a finishReason.
    terminators = [(name, data) for name, data in events if name in {"done", "error"}]
    assert len(terminators) == 1
    assert terminators[0][1]["finishReason"] is not None
    # No message row to name on this route (spec §8.1).
    assert terminators[0][1]["messageId"] is None


async def test_a_completed_rerun_lands_in_the_pending_slot(
    client_for_user_a: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    owner_id = await caller_id(client_for_user_a)
    project_id = await seed_ready_project(db_session, vector_store, owner_id)
    pair = await create_qa_pair(db_session, project_id=project_id, created_by=owner_id)
    # Captured before `expire_all` below: the route writes through its own session,
    # so this one's identity map holds a stale row and has to be expired to see the
    # pending slot — after which even reading `pair.id` off the instance would
    # trigger a refresh, and that is IO outside an awaited context.
    pair_id = pair.id
    original = pair.answer
    await db_session.commit()

    await client_for_user_a.post(f"/qa-pairs/{pair_id}/rerun")

    db_session.expire_all()
    stored = (await db_session.execute(select(QAPair).where(QAPair.id == pair_id))).scalar_one()
    assert stored.pending_run_at is not None
    assert stored.pending_answer
    assert stored.pending_finish_reason == "stop"
    # The stored answer is untouched until a human accepts (`docs/PRD.md:339`).
    assert stored.answer == original


async def test_a_non_owner_cannot_rerun(
    client_for_user_b: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """Re-running mutates the pending slot, so it is a write and is gated as one."""
    owner = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, owner.id)
    pair = await create_qa_pair(db_session, project_id=project_id, created_by=owner.id)
    await db_session.commit()

    response = await client_for_user_b.post(f"/qa-pairs/{pair.id}/rerun")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_QA_PAIR_OWNER"


async def test_rerun_against_an_unindexed_project_is_409_before_any_bytes(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    owner_id = await caller_id(client_for_user_a)
    project = await create_project(db_session, created_by=owner_id, status=ProjectStatus.PENDING)
    pair = await create_qa_pair(db_session, project_id=project.id, created_by=owner_id)
    await db_session.commit()

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


async def test_rerun_after_an_embedding_model_switch_is_409(
    client_for_user_a: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """The guard that would otherwise fail silently.

    Swap one 768-wide model for another and Qdrant accepts the query, returns its
    nearest neighbours in a space the collection was never built in, and the model
    writes a fluent cited answer about noise — with no error anywhere. A regression
    set whose re-runs quietly degrade is worse than no regression set.
    """
    owner_id = await caller_id(client_for_user_a)
    project_id = await seed_ready_project(db_session, vector_store, owner_id)
    # Move the project to a model this instance no longer runs.
    row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    row.embedding_model = "some-other-model"
    pair = await create_qa_pair(db_session, project_id=project_id, created_by=owner_id)
    await db_session.commit()

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMBEDDING_MODEL_CHANGED"


async def test_rerun_of_an_unknown_pair_is_404(client_for_user_a: AsyncClient) -> None:
    response = await client_for_user_a.post(f"/qa-pairs/{uuid.uuid4()}/rerun")

    assert response.status_code == 404


async def stage_pending_run(
    session: AsyncSession, pair_id: uuid.UUID, *, finish_reason: str = "stop"
) -> None:
    """Put a completed re-run in the slot without running the model."""
    row = (await session.execute(select(QAPair).where(QAPair.id == pair_id))).scalar_one()
    row.pending_answer = "A newer answer."
    row.pending_citations = None
    row.pending_model = "test-model"
    row.pending_finish_reason = finish_reason
    row.pending_run_at = datetime.now(UTC)
    await session.commit()


async def test_accept_promotes_the_run_and_resets_the_verdict(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    """A human verified *that text*. Replace the text and the verdict must go.

    A stale green badge on a shared regression set is worse than no badge, because
    it is trusted (spec §5.4).
    """
    owner_id = await caller_id(client_for_user_a)
    project = await create_project(db_session, created_by=owner_id)
    pair = await create_qa_pair(
        db_session, project_id=project.id, created_by=owner_id, status=QAStatus.PASS
    )
    await db_session.commit()
    await stage_pending_run(db_session, pair.id)

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun/accept")

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "A newer answer."
    assert body["status"] == "unreviewed"
    assert body["reviewedBy"] is None
    assert body["reviewedAt"] is None
    assert body["hasPendingRun"] is False
    assert body["lastRunAt"] is not None


async def test_accept_refuses_a_run_that_never_finished(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    """A partial run may be read. It may never be published to the team."""
    owner_id = await caller_id(client_for_user_a)
    project = await create_project(db_session, created_by=owner_id)
    pair = await create_qa_pair(db_session, project_id=project.id, created_by=owner_id)
    await db_session.commit()
    await stage_pending_run(db_session, pair.id, finish_reason="disconnected")

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun/accept")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ANSWER_INCOMPLETE"


async def test_accept_with_an_empty_slot_is_409(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    owner_id = await caller_id(client_for_user_a)
    project = await create_project(db_session, created_by=owner_id)
    pair = await create_qa_pair(db_session, project_id=project.id, created_by=owner_id)
    await db_session.commit()

    response = await client_for_user_a.post(f"/qa-pairs/{pair.id}/rerun/accept")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "NO_PENDING_RUN"


async def test_discard_clears_the_slot_and_leaves_the_answer(
    client_for_user_a: AsyncClient, db_session: AsyncSession
) -> None:
    owner_id = await caller_id(client_for_user_a)
    project = await create_project(db_session, created_by=owner_id)
    pair = await create_qa_pair(db_session, project_id=project.id, created_by=owner_id)
    original = pair.answer
    await db_session.commit()
    await stage_pending_run(db_session, pair.id)

    response = await client_for_user_a.delete(f"/qa-pairs/{pair.id}/rerun")

    assert response.status_code == 204
    detail = (await client_for_user_a.get(f"/qa-pairs/{pair.id}")).json()
    assert detail["hasPendingRun"] is False
    assert detail["answer"] == original


async def test_a_non_owner_cannot_accept(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    pair = await create_qa_pair(db_session, project_id=project.id, created_by=owner.id)
    await db_session.commit()
    await stage_pending_run(db_session, pair.id)

    response = await client_for_user_b.post(f"/qa-pairs/{pair.id}/rerun/accept")

    assert response.status_code == 403
