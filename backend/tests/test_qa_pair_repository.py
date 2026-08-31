"""The `qa_pairs` table: defaults, soft delete, and the tag array."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qa_pair import QAPair, QASource, QAStatus
from app.repositories.base import BaseRepository
from tests.factories import create_project, create_user


class _Repo(BaseRepository[QAPair]):
    model = QAPair


async def test_defaults_are_unreviewed_manual_and_untagged(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    pair = QAPair(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by=user.id,
        question="How does login work?",
        answer="It hashes with bcrypt.",
        reference_answer="It hashes with bcrypt.",
        source=QASource.MANUAL.value,
        status=QAStatus.UNREVIEWED.value,
    )
    db_session.add(pair)
    await db_session.commit()
    await db_session.refresh(pair)

    assert pair.tags == []
    assert pair.status == "unreviewed"
    assert pair.source == "manual"
    assert pair.deleted_at is None
    assert pair.eval_score is None
    assert pair.pending_run_at is None
    assert pair.created_at is not None


async def test_active_select_excludes_soft_deleted(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    repo = _Repo(db_session)
    pair = QAPair(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by=user.id,
        question="q",
        source=QASource.MANUAL.value,
        status=QAStatus.UNREVIEWED.value,
    )
    db_session.add(pair)
    await db_session.commit()

    await repo.soft_delete(pair)
    await db_session.commit()

    assert await repo.get(pair.id) is None
    assert await repo.get_including_deleted(pair.id) is not None


async def test_tags_round_trip_as_a_list(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    pair = QAPair(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by=user.id,
        question="q",
        tags=["auth", "billing"],
        source=QASource.MANUAL.value,
        status=QAStatus.UNREVIEWED.value,
    )
    db_session.add(pair)
    await db_session.commit()
    await db_session.refresh(pair)

    assert pair.tags == ["auth", "billing"]
