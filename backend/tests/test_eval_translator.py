"""A `generate` job on a translated set: one translation per source pair, never a scroll."""

import uuid
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.notifications import NotificationType
from app.eval import generator as generator_module
from app.eval.generator import NO_FAITHFUL_TRANSLATION_ERROR, EvalSetGenerator
from app.eval.model_output import TranslatedQuestion
from app.models.eval import EvalPair, EvalSet, EvalSetStatus
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_set import EvalSetRepository
from tests.factories import create_eval_pair, create_eval_set, create_project, create_user
from tests.fakes import StructuredScriptedChatModel


class _NoStore:
    """A translation must never scroll the index; any use of the store is a failure."""

    def __call__(self, collection: str) -> object:
        raise AssertionError("a translation read the vector store")


async def _setup(
    session: AsyncSession, questions: list[str], *, excluded: set[int] | None = None
) -> tuple[EvalSet, list[EvalPair], uuid.UUID]:
    user = await create_user(session)
    project = await create_project(session, created_by=user.id)
    source = await create_eval_set(
        session, project_id=project.id, created_by=user.id, pair_count=len(questions)
    )
    source_pairs: list[EvalPair] = []
    for position, question in enumerate(questions):
        pair = await create_eval_pair(
            session,
            set_id=source.id,
            position=position,
            excluded=position in (excluded or set()),
        )
        pair.question = question
        source_pairs.append(pair)
    translated = await create_eval_set(
        session,
        project_id=project.id,
        created_by=user.id,
        status=EvalSetStatus.GENERATING,
        language="id",
        source_set_id=source.id,
    )
    translated.indexed_generation = 4
    await session.commit()
    job = uuid.uuid4()
    await EvalSetRepository(session).claim(
        set_id=translated.id, job_id=job, worker_id="w", lease_seconds=300
    )
    await session.commit()
    return translated, source_pairs, job


def _generator(session: AsyncSession, chat: object) -> EvalSetGenerator:
    return EvalSetGenerator(
        session,
        Settings(),
        store_factory=cast("generator_module.VectorStoreFactory", _NoStore()),
        chat_model=cast(BaseChatModel, chat),
    )


async def _pairs(session: AsyncSession, set_id: uuid.UUID) -> list[EvalPair]:
    session.expire_all()
    return await EvalPairRepository(session).list_for_set(set_id, include_excluded=True)


async def _reload(session: AsyncSession, set_id: uuid.UUID) -> EvalSet:
    session.expire_all()
    row = await EvalSetRepository(session).get(set_id)
    assert row is not None
    return row


async def test_each_source_pair_is_translated_and_linked(db_session: AsyncSession) -> None:
    translated, sources, job = await _setup(
        db_session, ["What does `claim` do?", "Where is a login rate limited?"]
    )
    chat = StructuredScriptedChatModel(
        {
            TranslatedQuestion: [
                TranslatedQuestion(question="Apa yang dilakukan `claim`?"),
                TranslatedQuestion(question="Di mana login dibatasi?"),
            ]
        }
    )

    await _generator(db_session, chat).run(target_id=translated.id, job_id=job, worker_id="w")

    row = await _reload(db_session, translated.id)
    assert row.status == EvalSetStatus.READY.value
    assert row.pair_count == 2
    assert row.indexed_generation == 4
    pairs = await _pairs(db_session, translated.id)
    assert [p.question for p in pairs] == ["Apa yang dilakukan `claim`?", "Di mana login dibatasi?"]
    for pair, source in zip(pairs, sources, strict=True):
        await db_session.refresh(source)  # `_pairs` expired it
        assert pair.source_pair_id == source.id
        assert (pair.position, pair.question_type, pair.reference_answer) == (
            source.position,
            source.question_type,
            source.reference_answer,
        )
        assert (pair.source_file, pair.start_line, pair.end_line) == (
            source.source_file,
            source.start_line,
            source.end_line,
        )
        assert pair.excluded_at is None
        assert pair.exclusion_reason is None


async def test_an_unfaithful_pair_is_written_excluded_with_its_reason(
    db_session: AsyncSession,
) -> None:
    translated, _, job = await _setup(db_session, ["What does `claim` do?", "How is it limited?"])
    set_id = translated.id
    chat = StructuredScriptedChatModel(
        {
            TranslatedQuestion: [
                TranslatedQuestion(question="Apa fungsi klaim?"),
                TranslatedQuestion(question="Apa fungsi klaim lagi?"),
                TranslatedQuestion(question="Bagaimana dibatasi?"),
            ]
        }
    )

    await _generator(db_session, chat).run(target_id=translated.id, job_id=job, worker_id="w")

    first, second = await _pairs(db_session, set_id)
    assert first.excluded_at is not None
    assert first.exclusion_reason == "translation_unfaithful"
    assert first.question == "Apa fungsi klaim lagi?"
    assert second.excluded_at is None
    assert (await _reload(db_session, set_id)).status == EvalSetStatus.READY.value


async def test_source_exclusions_are_copied_without_a_reason(db_session: AsyncSession) -> None:
    translated, _, job = await _setup(db_session, ["One?", "Two?"], excluded={1})
    chat = StructuredScriptedChatModel(
        {
            TranslatedQuestion: [
                TranslatedQuestion(question="Satu?"),
                TranslatedQuestion(question="Dua?"),
            ]
        }
    )

    await _generator(db_session, chat).run(target_id=translated.id, job_id=job, worker_id="w")

    first, second = await _pairs(db_session, translated.id)
    assert first.excluded_at is None
    assert second.excluded_at is not None
    assert second.exclusion_reason is None


async def test_no_faithful_pair_fails_the_set_and_announces_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[NotificationType] = []

    async def record(session: AsyncSession, **kwargs: object) -> None:
        announced.append(cast(NotificationType, kwargs["event_type"]))

    monkeypatch.setattr(generator_module, "announce_set", record)
    translated, _, job = await _setup(db_session, ["What does `claim` do?"])
    chat = StructuredScriptedChatModel(
        {TranslatedQuestion: [TranslatedQuestion(question="x"), TranslatedQuestion(question="y")]}
    )

    await _generator(db_session, chat).run(target_id=translated.id, job_id=job, worker_id="w")

    row = await _reload(db_session, translated.id)
    assert row.status == EvalSetStatus.FAILED.value
    assert row.error == NO_FAITHFUL_TRANSLATION_ERROR
    assert announced == [NotificationType.EVAL_SET_FAILED]
