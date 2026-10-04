"""The eval tables round-trip, and a result is unique per (run, pair)."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval import (
    EvalPair,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalSet,
    EvalSetStatus,
    EvalVerdict,
)
from tests.factories import create_project, create_user


async def _set(db_session: AsyncSession) -> EvalSet:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    eval_set = EvalSet(
        id=uuid.uuid4(),
        project_id=project.id,
        name="routes",
        source_path=None,
        requested_count=10,
        mix="balanced",
        status=EvalSetStatus.READY.value,
        pair_count=0,
        created_by=user.id,
    )
    db_session.add(eval_set)
    await db_session.flush()
    return eval_set


async def test_a_set_its_pair_run_and_result_round_trip(db_session: AsyncSession) -> None:
    eval_set = await _set(db_session)
    pair = EvalPair(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        position=0,
        question_type="explain",
        question="What does the login handler check?",
        reference_answer="It checks the password hash.",
        source_file="app/auth/login.py",
        start_line=1,
        end_line=20,
    )
    run = EvalRun(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        project_id=eval_set.project_id,
        status=EvalRunStatus.RUNNING.value,
        created_by=eval_set.created_by,
    )
    db_session.add_all([pair, run])
    await db_session.flush()
    db_session.add(
        EvalResult(
            id=uuid.uuid4(),
            run_id=run.id,
            pair_id=pair.id,
            retrieval_hit=True,
            verdict=EvalVerdict.CORRECT.value,
            judge_reason="Matches.",
            answer="It checks the hash [1].",
            grounding_warnings=[],
            retrieval_attempts=1,
        )
    )
    await db_session.commit()

    assert (await db_session.get(EvalResult, (await _only_result_id(db_session)))) is not None


async def _only_result_id(db_session: AsyncSession) -> uuid.UUID:
    from sqlalchemy import select

    return (await db_session.execute(select(EvalResult.id))).scalar_one()


async def test_a_result_is_unique_per_run_and_pair(db_session: AsyncSession) -> None:
    eval_set = await _set(db_session)
    pair = EvalPair(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        position=0,
        question_type="locate",
        question="Where is login?",
        reference_answer="app/auth/login.py",
        source_file="app/auth/login.py",
        start_line=1,
        end_line=2,
    )
    run = EvalRun(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        project_id=eval_set.project_id,
        status=EvalRunStatus.RUNNING.value,
        created_by=eval_set.created_by,
    )
    db_session.add_all([pair, run])
    await db_session.flush()
    run_id, pair_id = run.id, pair.id
    for _ in range(2):
        db_session.add(
            EvalResult(
                id=uuid.uuid4(),
                run_id=run_id,
                pair_id=pair_id,
                retrieval_hit=False,
                verdict="error",
                answer="",
                grounding_warnings=[],
                retrieval_attempts=0,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    assert eval_set.id
