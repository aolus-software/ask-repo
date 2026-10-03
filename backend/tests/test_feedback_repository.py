"""FeedbackRepository: upsert, the lifecycle sweeps, and the aggregates."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feedback import FeedbackFeature, FeedbackRating, FeedbackTarget
from app.models.feedback import Feedback
from app.models.project import Project
from app.repositories.feedback import FeedbackRepository
from tests.factories import (
    create_conversation,
    create_feedback,
    create_message,
    create_project,
    create_user,
)

pytestmark = pytest.mark.asyncio


async def _upsert(
    repo: FeedbackRepository,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    target_id: uuid.UUID,
    rating: str = "down",
    reason_codes: list[str] | None = None,
    note: str | None = None,
) -> Feedback:
    return await repo.upsert(
        user_id=user_id,
        project_id=project_id,
        target_type=FeedbackTarget.MESSAGE.value,
        target_id=target_id,
        feature=FeedbackFeature.ANSWER.value,
        rating=rating,
        reason_codes=reason_codes if reason_codes is not None else ["other"],
        note=note,
        prompt_version="abcdefabcdef",
    )


async def test_upsert_updates_in_place(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    repo = FeedbackRepository(db_session)
    target = uuid.uuid4()

    first = await _upsert(repo, user_id=user.id, project_id=project.id, target_id=target)
    second = await _upsert(
        repo, user_id=user.id, project_id=project.id, target_id=target, rating="up", reason_codes=[]
    )

    assert second.id == first.id
    rows = (await db_session.execute(select(Feedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].rating == "up"
    assert rows[0].reason_codes == []


async def test_delete_mine_removes_only_the_callers_vote(db_session: AsyncSession) -> None:
    me = await create_user(db_session)
    other = await create_user(db_session)
    project = await create_project(db_session)
    repo = FeedbackRepository(db_session)
    target = uuid.uuid4()
    await _upsert(repo, user_id=me.id, project_id=project.id, target_id=target)
    await _upsert(repo, user_id=other.id, project_id=project.id, target_id=target)

    deleted = await repo.delete_mine(
        user_id=me.id, target_type=FeedbackTarget.MESSAGE.value, target_id=target
    )

    assert deleted == 1
    remaining = (await db_session.execute(select(Feedback.user_id))).scalars().all()
    assert remaining == [other.id]


async def test_mine_for_targets_returns_only_the_callers_rows(db_session: AsyncSession) -> None:
    me = await create_user(db_session)
    other = await create_user(db_session)
    project = await create_project(db_session)
    a, b = uuid.uuid4(), uuid.uuid4()
    await create_feedback(db_session, user_id=me.id, project_id=project.id, target_id=a)
    await create_feedback(db_session, user_id=other.id, project_id=project.id, target_id=b)

    mine = await FeedbackRepository(db_session).mine_for_targets(
        user_id=me.id, target_type=FeedbackTarget.MESSAGE.value, target_ids=[a, b]
    )

    assert set(mine) == {a}


async def test_clear_notes_for_conversation_keeps_the_counts(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=user.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await create_feedback(
        db_session,
        user_id=user.id,
        project_id=conversation.project_id,
        target_id=message.id,
        note="It cited the wrong router.",
        reason_codes=("wrong_file_cited",),
    )

    cleared = await FeedbackRepository(db_session).clear_notes_for_conversation(conversation.id)

    assert cleared == 1
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.note is None
    assert row.reason_codes == ["wrong_file_cited"]
    assert row.deleted_at is None


async def test_soft_delete_for_project_hides_that_project_only(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    doomed = await create_project(db_session)
    kept = await create_project(db_session)
    await create_feedback(db_session, user_id=user.id, project_id=doomed.id)
    await create_feedback(db_session, user_id=user.id, project_id=kept.id)

    swept = await FeedbackRepository(db_session).soft_delete_for_project(doomed.id)

    assert swept == 1
    live = (
        (await db_session.execute(select(Feedback.project_id).where(Feedback.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    assert live == [kept.id]


async def test_delete_older_than_prunes_by_cutoff(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    old = await create_feedback(db_session, user_id=user.id, project_id=project.id)
    await create_feedback(db_session, user_id=user.id, project_id=project.id)
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=40))
    )

    pruned = await FeedbackRepository(db_session).delete_older_than(
        datetime.now(UTC) - timedelta(days=30)
    )

    assert pruned == 1


async def test_aggregates_count_by_feature_reason_and_prompt_version(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    other = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session,
        user_id=user.id,
        project_id=project.id,
        reason_codes=("wrong_file_cited", "missed_something"),
        prompt_version="aaaaaaaaaaaa",
    )
    await create_feedback(
        db_session,
        user_id=other.id,
        project_id=project.id,
        rating=FeedbackRating.UP,
        reason_codes=(),
        prompt_version="bbbbbbbbbbbb",
    )
    repo = FeedbackRepository(db_session)

    by_feature = await repo.counts_by_feature({})
    by_reason = await repo.counts_by_reason({})
    by_version = await repo.counts_by_prompt_version({})

    assert sorted(by_feature) == [("answer", "down", 1), ("answer", "up", 1)]
    assert sorted(by_reason) == [
        ("answer", "missed_something", 1),
        ("answer", "wrong_file_cited", 1),
    ]
    assert sorted(by_version) == [("aaaaaaaaaaaa", "down", 1), ("bbbbbbbbbbbb", "up", 1)]


async def test_page_joins_the_project_name_and_filters(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    alpha = await create_project(db_session, name="alpha")
    beta = await create_project(db_session, name="beta")
    await create_feedback(db_session, user_id=user.id, project_id=alpha.id)
    await create_feedback(db_session, user_id=user.id, project_id=beta.id)

    rows, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"project_ids": frozenset({alpha.id})}
    )

    assert total == 1
    assert [name for _, name in rows] == ["alpha"]


async def test_page_excludes_rows_whose_project_was_soft_deleted(db_session: AsyncSession) -> None:
    """A PUT racing a project delete must not surface that project's row afterwards."""
    user = await create_user(db_session)
    live = await create_project(db_session, name="live")
    doomed = await create_project(db_session, name="doomed")
    await create_feedback(db_session, user_id=user.id, project_id=live.id)
    await create_feedback(db_session, user_id=user.id, project_id=doomed.id)
    await db_session.execute(
        update(Project).where(Project.id == doomed.id).values(deleted_at=datetime.now(UTC))
    )

    rows, total = await FeedbackRepository(db_session).page(limit=10, offset=0, filters={})

    assert total == 1
    assert [name for _, name in rows] == ["live"]


async def test_page_filters_by_feature(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, feature=FeedbackFeature.ANSWER
    )
    await create_feedback(
        db_session,
        user_id=user.id,
        project_id=project.id,
        feature=FeedbackFeature.PROPOSE_CHECKLIST,
        reason_codes=("wrong_scope",),
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"feature": FeedbackFeature.ANSWER.value}
    )

    assert total == 1


async def test_page_filters_by_rating(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session,
        user_id=user.id,
        project_id=project.id,
        rating=FeedbackRating.UP,
        reason_codes=(),
    )
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, rating=FeedbackRating.DOWN
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"rating": "up"}
    )

    assert total == 1


async def test_page_filters_by_reason_code(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, reason_codes=("wrong_file_cited",)
    )
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, reason_codes=("missed_something",)
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"reason_code": "wrong_file_cited"}
    )

    assert total == 1


async def test_page_filters_by_prompt_version(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, prompt_version="aaaaaaaaaaaa"
    )
    await create_feedback(
        db_session, user_id=user.id, project_id=project.id, prompt_version="bbbbbbbbbbbb"
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"prompt_version": "aaaaaaaaaaaa"}
    )

    assert total == 1


async def test_page_filters_by_created_from(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session)
    old = await create_feedback(db_session, user_id=user.id, project_id=project.id)
    await create_feedback(db_session, user_id=user.id, project_id=project.id)
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=10))
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10, offset=0, filters={"created_from": datetime.now(UTC) - timedelta(days=1)}
    )

    assert total == 1


async def test_page_filters_by_created_to_includes_the_whole_selected_day(
    db_session: AsyncSession,
) -> None:
    """A bare calendar day (from `<input type="date">`) must not exclude votes cast
    that same day — the same fix `AuditEventRepository` already applies."""
    user = await create_user(db_session)
    project = await create_project(db_session)
    today = await create_feedback(db_session, user_id=user.id, project_id=project.id)
    tomorrow = await create_feedback(db_session, user_id=user.id, project_id=project.id)
    now = datetime.now(UTC)
    today_midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == today.id)
        .values(created_at=today_midnight + timedelta(hours=12))
    )
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == tomorrow.id)
        .values(created_at=today_midnight + timedelta(days=1, hours=1))
    )

    _, total = await FeedbackRepository(db_session).page(
        limit=10,
        offset=0,
        filters={"created_from": today_midnight, "created_to": today_midnight},
    )

    assert total == 1


async def test_page_orders_within_a_day_by_id_not_time(db_session: AsyncSession) -> None:
    """Two votes cast the same UTC day must not come back ordered by the time of
    day they were cast — that would leak the sequence back to an admin as page
    position instead of a printed clock time, which is exactly what dropping the
    time from `FeedbackAdminRead` was for."""
    user = await create_user(db_session)
    project = await create_project(db_session)
    early = await create_feedback(db_session, user_id=user.id, project_id=project.id, note="early")
    late = await create_feedback(db_session, user_id=user.id, project_id=project.id, note="late")
    now = datetime.now(UTC)
    today_midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
    # Give the row cast earlier in the day the *larger* id, and the row cast later
    # the *smaller* id, so ordering by id vs. ordering by timestamp disagree.
    smaller_id, larger_id = sorted((uuid.uuid4(), uuid.uuid4()))
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == early.id)
        .values(id=larger_id, created_at=today_midnight + timedelta(hours=1))
    )
    await db_session.execute(
        update(Feedback)
        .where(Feedback.id == late.id)
        .values(id=smaller_id, created_at=today_midnight + timedelta(hours=20))
    )

    rows, total = await FeedbackRepository(db_session).page(limit=10, offset=0, filters={})

    assert total == 2
    assert [row.note for row, _ in rows] == ["early", "late"]
