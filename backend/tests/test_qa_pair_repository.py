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

from app.core.access import ProjectScope
from app.repositories.qa_pair import QAPairRepository
from tests.factories import create_qa_pair


async def test_list_page_filters_by_tag_and_counts_unpaginated(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    for index in range(3):
        await create_qa_pair(
            db_session,
            project_id=project.id,
            created_by=user.id,
            question=f"q{index}",
            tags=["auth"] if index < 2 else ["billing"],
        )
    await db_session.commit()

    repo = QAPairRepository(db_session)
    rows, total = await repo.list_page(
        scope=ProjectScope.all(),
        page=1,
        limit=1,
        sort="created_at",
        descending=True,
        tag="auth",
    )

    assert len(rows) == 1
    # The count applies the same filters as the page, so the pager never promises
    # a page that does not exist.
    assert total == 2


async def test_list_page_intersects_the_scope(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    mine = await create_project(db_session, created_by=user.id)
    theirs = await create_project(db_session, created_by=user.id)
    await create_qa_pair(db_session, project_id=mine.id, created_by=user.id)
    await create_qa_pair(db_session, project_id=theirs.id, created_by=user.id)
    await db_session.commit()

    repo = QAPairRepository(db_session)
    rows, total = await repo.list_page(
        scope=ProjectScope.of([mine.id]),
        page=1,
        limit=25,
        sort="created_at",
        descending=True,
    )

    assert total == 1
    assert rows[0].project_id == mine.id


async def test_an_empty_scope_returns_nothing_not_everything(
    db_session: AsyncSession,
) -> None:
    """`ProjectScope.of([])` means no access. Fail-open here would be a phase-2 leak."""
    user = await create_user(db_session)
    await create_qa_pair(db_session, created_by=user.id)
    await db_session.commit()

    repo = QAPairRepository(db_session)
    _, total = await repo.list_page(
        scope=ProjectScope.of([]), page=1, limit=25, sort="created_at", descending=True
    )

    assert total == 0


async def test_list_page_rejects_an_unlisted_sort_field(db_session: AsyncSession) -> None:
    repo = QAPairRepository(db_session)
    try:
        await repo.list_page(
            scope=ProjectScope.all(),
            page=1,
            limit=25,
            sort="password_hash",
            descending=True,
        )
    except ValueError as error:
        assert "password_hash" in str(error)
    else:
        raise AssertionError("expected ValueError for an unlisted sort field")

async def test_distinct_tags_are_sorted_and_deduplicated(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    await create_qa_pair(db_session, project_id=project.id, created_by=user.id, tags=["auth"])
    await create_qa_pair(
        db_session, project_id=project.id, created_by=user.id, tags=["billing", "auth"]
    )
    await db_session.commit()

    repo = QAPairRepository(db_session)
    assert await repo.distinct_tags(scope=ProjectScope.all()) == ["auth", "billing"]


async def test_soft_delete_for_project_sweeps_every_owner(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    other = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    await create_qa_pair(db_session, project_id=project.id, created_by=owner.id)
    await create_qa_pair(db_session, project_id=project.id, created_by=other.id)
    await db_session.commit()

    repo = QAPairRepository(db_session)
    swept = await repo.soft_delete_for_project(project.id)
    await db_session.commit()

    assert swept == 2
    _, total = await repo.list_page(
        scope=ProjectScope.all(), page=1, limit=25, sort="created_at", descending=True
    )
    assert total == 0

