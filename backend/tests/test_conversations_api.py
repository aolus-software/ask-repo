"""The routes, the privacy boundary, and the shape of the stream."""

import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ingestion.chunker import Chunk
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import ProjectStatus
from tests.factories import create_conversation, create_project, create_user


def sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse an SSE body into (event name, payload) pairs, ignoring keep-alives."""
    parsed: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        parsed.append((name, json.loads(data)))
    return parsed


async def seed_ready_project(
    db_session: AsyncSession, store: InMemoryVectorStore, owner_id: uuid.UUID
) -> uuid.UUID:
    """A project whose index actually contains something to retrieve.

    `embedding_collection` is set because a project without one is deliberately
    unanswerable, and `embedding_model` must match the configured embedder or the
    turn is refused with `409` before it reaches the store.
    """
    settings = get_settings()
    project = await create_project(db_session, created_by=owner_id, status=ProjectStatus.READY)
    project.embedding_collection = "in-memory"
    project.embedding_model = settings.embedding_model
    project.active_generation = 0
    await db_session.commit()

    embedder = FakeEmbedder(dimensions=8)
    chunk = Chunk(
        file_path="app/core/repo_url.py",
        start_line=40,
        end_line=96,
        language="python",
        symbol="validate_repo_url",
        chunk_index=0,
        text="def validate_repo_url(url):\n    ...",
    )
    await store.upsert(
        project_id=project.id,
        generation=0,
        chunks=[chunk],
        vectors=await embedder.embed_documents([chunk.text]),
        commit_sha="9d12711",
    )
    return project.id


async def own_conversation(client: AsyncClient, project_id: uuid.UUID) -> str:
    response = await client.post("/conversations", json={"projectId": str(project_id)})
    assert response.status_code == 201
    return str(response.json()["id"])


async def test_creating_a_conversation_returns_camel_case(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)

    response = await authed_client.post("/conversations", json={"projectId": str(project_id)})

    assert response.status_code == 201
    assert "projectId" in response.json()
    assert "project_id" not in response.json()


async def test_asking_streams_citations_then_tokens_then_done(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """The ordering contract, asserted on the wire rather than on the answerer."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "how is the repo url validated?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in sse_events(response.text)]
    assert names.count("citations") == 1
    assert names.index("citations") < names.index("token")
    assert names[-1] == "done"


async def test_the_stream_carries_the_no_buffering_headers(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """Without these a proxy accumulates the whole stream and delivers it at once,
    which defeats the entire point of streaming."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": "q"}
    )

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


async def test_citation_payloads_are_camel_case(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """These never pass through a response_model, so nothing in FastAPI enforces it."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": "q"}
    )
    citations = next(data for name, data in sse_events(response.text) if name == "citations")
    first = citations["citations"][0]  # type: ignore[index]  # untyped SSE JSON

    assert "filePath" in first
    assert "startLine" in first
    assert "file_path" not in first


async def test_the_answer_is_readable_afterwards(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)
    await authed_client.post(f"/conversations/{conversation_id}/messages", json={"question": "q"})

    detail = await authed_client.get(f"/conversations/{conversation_id}")

    assert detail.status_code == 200
    roles = [message["role"] for message in detail.json()["messages"]]
    assert roles == ["user", "assistant"]
    assert detail.json()["messages"][1]["finishReason"] == "stop"


async def test_the_title_comes_from_the_first_question(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    await authed_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": "How does the lease work?"}
    )
    listed = await authed_client.get("/conversations")

    assert listed.json()["items"][0]["title"] == "How does the lease work?"


async def test_another_user_cannot_reach_the_conversation_at_all(
    client_for_user_a: AsyncClient,
    client_for_user_b: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """docs/PRD.md §7: user B cannot list or read user A's conversations, and gets
    404 rather than 403. All four routes, because one that returns 403 confirms
    existence and undoes the other three."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(client_for_user_a, project_id)

    assert (await client_for_user_b.get(f"/conversations/{conversation_id}")).status_code == 404
    assert (await client_for_user_b.delete(f"/conversations/{conversation_id}")).status_code == 404
    posted = await client_for_user_b.post(
        f"/conversations/{conversation_id}/messages", json={"question": "q"}
    )
    assert posted.status_code == 404
    listed = await client_for_user_b.get("/conversations")
    assert listed.json()["totalCount"] == 0


async def test_an_admin_is_not_an_exception(
    client_for_user_a: AsyncClient,
    client_for_admin: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """is_admin gates destructive operations on shared resources. Conversations are
    not shared, and §4.2 states their privacy without qualification."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(client_for_user_a, project_id)

    assert (await client_for_admin.get(f"/conversations/{conversation_id}")).status_code == 404


async def test_asking_a_project_that_is_not_ready_is_409(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id, status=ProjectStatus.INDEXING)
    await db_session.commit()
    created = await authed_client.post("/conversations", json={"projectId": str(project.id)})

    response = await authed_client.post(
        f"/conversations/{created.json()['id']}/messages", json={"question": "q"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


async def test_a_conversation_against_an_unknown_project_is_404(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.post("/conversations", json={"projectId": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


async def test_an_empty_question_is_422(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": ""}
    )

    assert response.status_code == 422
    assert "question" in response.json()["detail"]["fields"]


async def test_deleting_a_conversation_hides_it(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    assert (await authed_client.delete(f"/conversations/{conversation_id}")).status_code == 204
    assert (await authed_client.get(f"/conversations/{conversation_id}")).status_code == 404
    assert (await authed_client.get("/conversations")).json()["totalCount"] == 0


async def test_listing_filters_by_search_and_by_project(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Both filters, separately and together — and the total honours them.

    A count that ignored the filters would promise pages that do not exist, so it is
    asserted rather than assumed.
    """
    owner_id = uuid.UUID((await authed_client.get("/auth/me")).json()["id"])
    project_a = await create_project(db_session, created_by=owner_id)
    project_b = await create_project(db_session, created_by=owner_id)
    await create_conversation(
        db_session, user_id=owner_id, project_id=project_a.id, title="How does the lease work?"
    )
    await create_conversation(
        db_session,
        user_id=owner_id,
        project_id=project_b.id,
        title="How does the retry ladder work?",
    )
    await db_session.commit()

    unfiltered = await authed_client.get("/conversations")
    assert unfiltered.json()["totalCount"] == 2

    # Case-insensitive, and on a substring rather than a prefix.
    searched = await authed_client.get("/conversations", params={"search": "LEASE"})
    assert [item["title"] for item in searched.json()["items"]] == ["How does the lease work?"]
    assert searched.json()["totalCount"] == 1

    scoped = await authed_client.get("/conversations", params={"projectId": str(project_b.id)})
    assert [item["title"] for item in scoped.json()["items"]] == ["How does the retry ladder work?"]
    assert scoped.json()["totalCount"] == 1

    together = await authed_client.get(
        "/conversations", params={"search": "work", "projectId": str(project_a.id)}
    )
    assert [item["title"] for item in together.json()["items"]] == ["How does the lease work?"]


async def test_search_excludes_a_conversation_that_has_no_title_yet(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`title` is NULL until the first question derives one, and `ilike` on NULL is
    NULL rather than false — so an untitled conversation drops out of a search
    instead of matching every one of them."""
    owner_id = uuid.UUID((await authed_client.get("/auth/me")).json()["id"])
    project = await create_project(db_session, created_by=owner_id)
    await create_conversation(db_session, user_id=owner_id, project_id=project.id, title=None)
    await db_session.commit()

    assert (await authed_client.get("/conversations")).json()["totalCount"] == 1
    assert (await authed_client.get("/conversations", params={"search": "anything"})).json()[
        "totalCount"
    ] == 0


async def test_search_does_not_leak_another_users_conversation(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Ownership is applied before the search, not alongside it."""
    stranger = await create_user(db_session)
    project = await create_project(db_session, created_by=stranger.id)
    await create_conversation(
        db_session, user_id=stranger.id, project_id=project.id, title="How does the lease work?"
    )
    await db_session.commit()

    response = await authed_client.get("/conversations", params={"search": "lease"})

    assert response.json()["totalCount"] == 0
