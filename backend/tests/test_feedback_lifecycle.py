"""Feedback follows its subject: notes go with a conversation, rows with a project."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.feedback import Feedback
from app.models.user import User
from tests.factories import create_conversation, create_feedback, create_message

# No `pytestmark = pytest.mark.asyncio`: this repo runs pytest-asyncio in "auto" mode
# (`asyncio_mode = "auto"` in pyproject.toml), so an `async def test_...` needs no
# marker, and a module-level mark would wrongly apply to the sync test below too.


async def test_deleting_a_conversation_nulls_its_notes_and_keeps_the_votes(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    answer = await create_message(db_session, conversation_id=conversation.id)
    await create_feedback(
        db_session,
        user_id=authed_user.id,
        project_id=conversation.project_id,
        target_id=answer.id,
        note="It invented a helper.",
        reason_codes=("invented_something",),
    )
    await db_session.commit()

    response = await authed_client.delete(f"/conversations/{conversation.id}")

    assert response.status_code == 204
    db_session.expire_all()
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.note is None
    assert row.reason_codes == ["invented_something"]
    assert row.deleted_at is None


def test_feedback_retention_defaults_to_keep_forever() -> None:
    assert Settings().feedback_retention_days == 0
