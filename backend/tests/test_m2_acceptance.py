"""The `docs/PRD.md` §7 success criteria that M2 is responsible for.

Deliberately end-to-end and deliberately duplicative of narrower tests: these are the
sentences in the PRD, and they should fail if the product stops satisfying them
however the internals are rearranged.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.vector_store import InMemoryVectorStore
from tests.factories import create_user
from tests.test_conversations_api import own_conversation, seed_ready_project, sse_events


async def test_a_real_question_gets_a_cited_answer(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """ "Can ask Dev Knowledge a real question about a project repository and get a
    correct, cited answer."

    The correctness half is the model's. What is testable here is that the citation
    points at a real file, at a real line range, in a real commit — the three things
    a reader would use to check the answer.
    """
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": "how is the repository url validated?"},
    )
    events = sse_events(response.text)
    citations = next(data for name, data in events if name == "citations")["citations"]
    citation = citations[0]  # type: ignore[index]  # untyped SSE JSON
    done = next(data for name, data in events if name == "done")

    assert citation["filePath"] == "app/core/repo_url.py"
    assert (citation["startLine"], citation["endLine"]) == (40, 96)
    assert citation["commitSha"] == "9d12711"
    assert done["citedIndexes"] == [1]
    assert done["groundingWarnings"] == []


async def test_conversations_stay_private(
    client_for_user_a: AsyncClient,
    client_for_user_b: AsyncClient,
    client_for_admin: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """ "User B cannot list or read user A's conversations, and gets 404 rather than
    403. Verified by an automated test." This is that test.

    The admin is included because §4.2 states the privacy guarantee without
    qualification: an administrator who could read a colleague's conversation would
    make the sentence false.
    """
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(client_for_user_a, project_id)

    for client in (client_for_user_b, client_for_admin):
        assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404
        assert (await client.get("/conversations")).json()["totalCount"] == 0


async def test_a_shared_project_is_queryable_by_someone_who_did_not_add_it(
    client_for_user_b: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """ "Sharing works as intended: user B can list and query a project user A
    created, without any grant step."

    M1 proved the listing half. This is the query half, and it is the first time the
    access resolver is exercised by a question rather than by a list.
    """
    user_a = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user_a.id)

    conversation_id = await own_conversation(client_for_user_b, project_id)
    response = await client_for_user_b.post(
        f"/conversations/{conversation_id}/messages", json={"question": "q"}
    )

    assert response.status_code == 200
    assert [name for name, _ in sse_events(response.text)][-1] == "done"


async def test_no_answer_is_produced_without_evidence(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """The guardrail, end to end: an empty index yields a refusal rather than a
    fluent invention, and says so in machine-readable form."""
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    vector_store.points.clear()
    conversation_id = await own_conversation(authed_client, project_id)

    response = await authed_client.post(
        f"/conversations/{conversation_id}/messages", json={"question": "q"}
    )
    done = next(data for name, data in sse_events(response.text) if name == "done")

    assert done["groundingWarnings"] == ["no_context"]
    assert done["citedIndexes"] == []


async def test_a_follow_up_keeps_the_thread_in_context(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """ "Multi-turn: at least a sliding-window or summarized memory so a 5+ turn
    conversation doesn't lose earlier context."

    Asserted on what is observable from outside: every turn is persisted in order,
    and each one produces a complete answer rather than degrading once history
    exists.
    """
    user = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, user.id)
    conversation_id = await own_conversation(authed_client, project_id)

    for index in range(5):
        response = await authed_client.post(
            f"/conversations/{conversation_id}/messages",
            json={"question": f"question number {index}"},
        )
        assert response.status_code == 200

    detail = await authed_client.get(f"/conversations/{conversation_id}")
    messages = detail.json()["messages"]

    assert [m["role"] for m in messages] == ["user", "assistant"] * 5
    assert [m["content"] for m in messages if m["role"] == "user"] == [
        f"question number {index}" for index in range(5)
    ]
    assert all(m["finishReason"] == "stop" for m in messages if m["role"] == "assistant")


async def test_deleting_a_project_takes_its_conversations_with_it(
    client_for_user_a: AsyncClient,
    client_for_admin: AsyncClient,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
) -> None:
    """ "Deleting a project soft-deletes conversations against it" (§4.2).

    The admin deletes and user A loses their conversation, so this also covers the
    part that is easy to miss: the sweep is not scoped to the deleter. A project is
    shared, so the conversations against it belong to people other than whoever
    presses delete.
    """
    owner = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, owner.id)
    conversation_id = await own_conversation(client_for_user_a, project_id)

    assert (await client_for_admin.delete(f"/projects/{project_id}")).status_code == 204

    assert (await client_for_user_a.get(f"/conversations/{conversation_id}")).status_code == 404
    assert (await client_for_user_a.get("/conversations")).json()["totalCount"] == 0
