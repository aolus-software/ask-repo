"""The two content bans, as tests.

An audit trail is by definition something an operator reads, so it is a destination
on the scrub path rather than an exception to it (`docs/PRD.md` §9).
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEventType, repo_url_host
from app.core.permissions import EDITOR_NAME, VIEWER_NAME
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.checklist import ChecklistItemStatus
from app.models.user import User
from tests.conftest import AuditRows, GrantMembership
from tests.factories import create_checklist_item, create_checklist_module, create_user
from tests.test_conversations_api import seed_ready_project

PAT = "ghp_exampletokenvalue0123456789"


def test_repo_url_host_drops_userinfo() -> None:
    """A PAT is embedded in the clone URL, so the host is derived, never trimmed.

    String-trimming is what goes wrong under a URL shape nobody anticipated; parsing
    and keeping only the hostname cannot carry credentials through by construction.
    """
    assert repo_url_host(f"https://{PAT}@github.com/acme/private.git") == "github.com"
    assert repo_url_host("https://github.com/acme/private.git") == "github.com"
    assert repo_url_host("not-a-url") is None


async def test_project_create_stores_the_host_not_the_credentialed_url(
    authed_client: AsyncClient, audit_rows: AuditRows
) -> None:
    response = await authed_client.post(
        "/projects",
        json={"repoUrl": "https://github.com/acme/private.git", "pat": PAT},
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.PROJECT_CREATED)
    assert len(rows) == 1
    serialised = str(rows[0].details)
    assert PAT not in serialised
    assert "github.com/acme/private" not in serialised
    assert rows[0].details["changed"]["repoUrlHost"]["after"] == "github.com"
    assert rows[0].details["patSupplied"] is True


async def test_clearing_results_records_the_count_not_the_rows(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """The highest-value row in the table, and the one the 18-event draft missed.

    This erases a week of a tester's observations without deleting a single row, and
    PRD §4.3's promise that a regeneration cannot destroy a recorded result does not
    cover it, because it is not a regeneration.

    The rows are what was destroyed, and copying them in would put generated test
    content in the trail against the content ban. The count plus the filter says what
    was lost and to whom to talk -- never the test bodies themselves.
    """
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        test_name="first",
        expected_result="Something expected to happen",
        status=ChecklistItemStatus.PASS,
        current_result="It happened",
    )
    await create_checklist_item(
        db_session,
        module_id=module.id,
        test_name="second",
        status=ChecklistItemStatus.FAIL,
        current_result="Returned 500",
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(
        "/checklist-items/clear-results", json={"moduleId": str(module.id)}
    )
    assert response.status_code == 200
    assert response.json()["clearedCount"] == 2

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_RESULTS_CLEARED)
    assert len(rows) == 1
    assert rows[0].details["clearedCount"] == 2
    assert rows[0].details["filter"] == {"moduleId": str(module.id)}
    # No test-case text anywhere in the row.
    assert "expected" not in str(rows[0].details).lower()
    assert "500" not in str(rows[0].details)


async def test_conversation_events_carry_no_label_and_no_content(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
    audit_rows: AuditRows,
) -> None:
    """The amendment to PRD §4.2, held to exactly what was conceded.

    An administrator can see who, which project and when. Never what about: a
    conversation's title derives from the user's first question, and §2.5's ban on
    storing a prompt applies to it verbatim.
    """
    owner = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, owner.id)
    await grant_membership(authed_user.id, project_id, VIEWER_NAME)

    created = await authed_client.post("/conversations", json={"projectId": str(project_id)})
    assert created.status_code == 201

    rows = await audit_rows(AuditEventType.CONVERSATION_CREATED)
    assert len(rows) == 1
    assert rows[0].project_id == project_id
    assert str(rows[0].target_id) == created.json()["id"]
    assert rows[0].target_label is None
    assert rows[0].details == {}

    deleted = await authed_client.delete(f"/conversations/{created.json()['id']}")
    assert deleted.status_code == 204

    delete_rows = await audit_rows(AuditEventType.CONVERSATION_DELETED)
    assert len(delete_rows) == 1
    assert delete_rows[0].target_label is None
    assert delete_rows[0].details == {"messageCount": 0}


async def test_asking_a_question_records_nothing(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
    audit_rows: AuditRows,
) -> None:
    """PRD §2.5 keeps per-model-call records out of this table by name.

    One table would bury "an admin deactivated an account" under two hundred map
    calls, and the tokens-and-timing record is Phase 2.5's, not this one's.
    """
    owner = await create_user(db_session)
    project_id = await seed_ready_project(db_session, vector_store, owner.id)
    await grant_membership(authed_user.id, project_id, VIEWER_NAME)

    created = await authed_client.post("/conversations", json={"projectId": str(project_id)})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    before = len(await audit_rows())

    async with authed_client.stream(
        "POST",
        f"/conversations/{conversation_id}/messages",
        json={"question": "what is this?"},
    ) as response:
        assert response.status_code == 200
        async for _ in response.aiter_lines():
            pass

    assert len(await audit_rows()) == before
