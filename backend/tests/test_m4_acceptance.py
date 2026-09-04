"""M4's success criterion, end to end: generate, review, apply, record, export.

`docs/PRD.md` §7 gets a new line at this milestone, and this is the test behind it.
Nothing here is stubbed except the three things that live outside the process -- the
broker, the vector store, and the served model. The claim, the change set, the apply,
and the export are all the real code paths.
"""

import uuid
from typing import cast

import pytest
from httpx import AsyncClient
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.generator import ChecklistGenerator
from app.checklist.model_output import (
    FileObservations,
    ObservedBehaviour,
    ProposedChangeSet,
    ProposedOperation,
)
from app.config import Settings
from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import Project, ProjectStatus
from app.queue.checklist import handle_checklist_message
from app.queue.consumer import JobOutcome
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import ChecklistJobMessage
from app.repositories.checklist_module import ChecklistModuleRepository
from tests.factories import create_project
from tests.fakes import StructuredScriptedChatModel

SOURCE_PATH = "app/auth"
INDEXED_FILE = f"{SOURCE_PATH}/login.py"


async def _ready_indexed_project(session: AsyncSession, store: InMemoryVectorStore) -> Project:
    """A project that has finished indexing, with one file in the vector store.

    The collection name is whatever the row says -- `in-memory` here -- because the
    query path reads `project.embedding_collection` verbatim and never recomputes it
    (`.claude/rules/rag.md`).
    """
    project = await create_project(session, status=ProjectStatus.READY)
    project.embedding_collection = "in-memory"
    project.embedding_model = Settings().embedding_model
    project.active_generation = 1
    await session.commit()

    await store.upsert(
        project_id=project.id,
        generation=1,
        chunks=[
            Chunk(
                file_path=INDEXED_FILE,
                start_line=1,
                end_line=3,
                language="python",
                symbol=None,
                chunk_index=0,
                text="def login(user):\n    if not user:\n        raise Unauthorized()\n",
            )
        ],
        vectors=[[0.1] * 8],
        commit_sha="abc123",
    )
    return project


def _scripted_model() -> StructuredScriptedChatModel:
    """One observation, reduced into one proposed addition."""
    return StructuredScriptedChatModel(
        {
            FileObservations: [
                FileObservations(
                    behaviours=[
                        ObservedBehaviour(
                            description="raises Unauthorized for a missing user",
                            start_line=3,
                            end_line=3,
                        )
                    ]
                )
            ],
            ProposedChangeSet: [
                ProposedChangeSet(
                    summary="1 added",
                    operations=[
                        ProposedOperation(
                            kind="positive",
                            op="add",
                            feature="Login",
                            test_name="Rejects a request with no user",
                            expected_result="401 Unauthorized",
                            rationale="The handler raises Unauthorized.",
                            citation_paths=[INDEXED_FILE],
                        )
                    ],
                )
            ],
        }
    )


async def _run_the_queued_generation(
    session: AsyncSession, queue: InMemoryIngestionQueue, store: InMemoryVectorStore
) -> None:
    """The worker's half, run inline off the job the route published.

    `handle_checklist_message` rather than the generator alone, so the acceptance test
    exercises the lease claim that is the real deduplication boundary
    (`.claude/rules/ingestion.md`) rather than a stub of it.
    """
    message = queue.messages[-1]
    assert isinstance(message, ChecklistJobMessage)

    outcome = await handle_checklist_message(
        message,
        generator=ChecklistGenerator(
            session,
            Settings(),
            store_factory=lambda _: store,
            chat_model=cast(BaseChatModel, _scripted_model()),
        ),
        repository=ChecklistModuleRepository(session),
        producer=queue,
        worker_id=f"acceptance-{uuid.uuid4().hex[:6]}",
        max_attempts=3,
        session=session,
    )

    assert outcome is JobOutcome.COMPLETED


@pytest.mark.asyncio
async def test_a_module_goes_from_empty_to_a_recorded_result(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    ingestion_queue: InMemoryIngestionQueue,
    vector_store: InMemoryVectorStore,
) -> None:
    """Empty -> generating -> review -> applied -> recorded -> exported."""
    project = await _ready_indexed_project(db_session, vector_store)

    module = (
        await authed_client.post(
            "/checklist-modules",
            json={"projectId": str(project.id), "name": "Auth", "sourcePath": SOURCE_PATH},
        )
    ).json()
    assert module["status"] == "empty"

    accepted = await authed_client.post(f"/checklist-modules/{module['id']}/generate")
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "generating"

    await _run_the_queued_generation(db_session, ingestion_queue, vector_store)

    detail = (await authed_client.get(f"/checklist-modules/{module['id']}")).json()
    assert detail["status"] == "review"
    assert detail["pendingChangeSetId"] is not None
    # Nothing generated enters the checklist unreviewed (spec 2.1).
    assert detail["items"] == []

    applied = (
        await authed_client.post(
            f"/checklist-change-sets/{detail['pendingChangeSetId']}/apply", json={}
        )
    ).json()
    assert applied["items"]
    assert applied["items"][0]["status"] == "untested"
    # The model never writes an observation (spec 2.3).
    assert applied["items"][0]["currentResult"] is None

    item_id = applied["items"][0]["id"]
    recorded = (
        await authed_client.put(
            f"/checklist-items/{item_id}/result",
            json={"currentResult": "Returned 401 as expected", "status": "pass"},
        )
    ).json()
    assert recorded["status"] == "pass"
    assert recorded["reviewedBy"] is not None

    export = await authed_client.get(f"/checklist-items/export?moduleId={module['id']}")
    assert export.status_code == 200
    assert export.content[:2] == b"PK"  # an .xlsx is a zip
