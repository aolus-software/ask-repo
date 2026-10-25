"""Generating an eval set: scroll and sample the index, or translate an English set.

The generator scrolls; it does not search -- top-k cannot report what it left out
(`CLAUDE.md`). A per-pair model failure drops that pair rather than failing the job,
the same degrade-don't-fail stance as the checklist's map step; a terminal provider
error fails the job and the consumer records it.

No question, reference or answer text reaches a log line: a pair that is dropped is
logged by the error's class alone (`.claude/rules/call-log.md`).

A translated set (`source_set_id` set) reads no index: each source pair is translated
with one call, retried once, and a pair whose translation drops a backticked span or a
path is written excluded with its reason, never dropped (spec §3.4).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.language import Language
from app.core.notifications import NotificationType
from app.db.session import get_sessionmaker
from app.eval.model_output import GeneratedPair, TranslatedQuestion
from app.eval.notifications import announce_set
from app.eval.sampling import SampledChunk, assign_types, names_its_file, sample_chunks
from app.eval.translation import translate_question
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.models.eval import (
    EvalExclusionReason,
    EvalMix,
    EvalPair,
    EvalQuestionType,
    EvalSet,
    EvalSetStatus,
)
from app.observability.features import CallFeature, call_config
from app.rag.errors import classify_chat_error
from app.rag.prompts import build_eval_pair_prompt
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_set import LEASE_RENEWAL_SECONDS, LEASE_SECONDS, EvalSetRepository
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

NO_PAIRS_ERROR = "No usable pairs could be generated from this path."
NO_FAITHFUL_TRANSLATION_ERROR = "No question could be translated with its code kept intact."


class EvalSetGenerator:
    """One `generate` job, bound to one session."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        store_factory: VectorStoreFactory,
        chat_model: BaseChatModel,
    ) -> None:
        """Bind this run to `session`.

        `_renew` deliberately does not use `session`: it opens its own short-lived
        session per tick, because an `AsyncSession` is not safe for concurrent use.
        """
        self.session = session
        self.settings = settings
        self.store_factory = store_factory
        self.chat_model = chat_model
        self.sets = EvalSetRepository(session)
        self.pairs = EvalPairRepository(session)
        self.projects = ProjectRepository(session)

    async def run(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, attempt: int = 0
    ) -> None:
        """Generate and write the set's pairs, then release it `ready` or `failed`.

        `target_id` is the set id -- the keyword the eval consumer's runner protocol
        uses for both job kinds. The caller has already claimed the set; failures
        propagate so the consumer routes them onto the ladder.
        """
        set_id = target_id
        eval_set = await self.sets.get(set_id)
        if eval_set is None:
            raise TerminalIngestionError(f"eval set {set_id} is gone")
        project = await self.projects.get(eval_set.project_id)
        if project is None:
            raise TerminalIngestionError(f"project {eval_set.project_id} is gone")
        scope: dict[str, Any] = {
            "trace_seed": str(set_id),
            "project_id": project.id,
            "attempt": attempt,
        }

        renewal = asyncio.create_task(self._renew(set_id=set_id, worker_id=worker_id))
        try:
            if eval_set.source_set_id is not None:
                pairs = await self._translate(eval_set, scope, renewal)
                usable = any(pair.exclusion_reason is None for pair in pairs)
                failure, generation = NO_FAITHFUL_TRANSLATION_ERROR, eval_set.indexed_generation
            else:
                if not project.embedding_collection:
                    raise TerminalIngestionError(f"project {project.id} has no index to scroll")
                generation = project.active_generation
                pairs = await self._sample(
                    eval_set, project.id, project.embedding_collection, generation, scope, renewal
                )
                usable = bool(pairs)
                failure = NO_PAIRS_ERROR
        finally:
            await self._stop_renewal(renewal, set_id=set_id)

        if usable:
            await self.pairs.add_many(pairs)
            released = await self.sets.release(
                set_id=set_id,
                job_id=job_id,
                worker_id=worker_id,
                status=EvalSetStatus.READY,
                pair_count=len(pairs),
                indexed_generation=generation,
            )
        else:
            released = await self.sets.release(
                set_id=set_id,
                job_id=job_id,
                worker_id=worker_id,
                status=EvalSetStatus.FAILED,
                error=failure,
            )
        if not released:
            # A worker that lost its lease leaves both the set and its pairs alone.
            await self.session.rollback()
            logger.warning("eval generation for set %s lost its lease; discarding", set_id)
            return
        # Before the commit, deliberately -- the outcome and the notification of it
        # are one transaction (`.claude/rules/notifications.md` rule 2).
        await announce_set(
            self.session,
            set_id=set_id,
            event_type=(
                NotificationType.EVAL_SET_READY if usable else NotificationType.EVAL_SET_FAILED
            ),
            mail_enabled=self.settings.mail_enabled,
            pair_count=len(pairs) if usable else None,
        )
        await self.session.commit()

    async def _sample(
        self,
        eval_set: EvalSet,
        project_id: uuid.UUID,
        collection: str,
        generation: int,
        scope: dict[str, Any],
        renewal: "asyncio.Task[None]",
    ) -> list[EvalPair]:
        """Scroll the index, sample chunks and write one generated pair per usable chunk."""
        payloads = await self._scroll(
            # Verbatim from the row, never recomputed from current settings.
            collection=collection,
            project_id=project_id,
            generation=generation,
            path_prefix=eval_set.source_path or "",
        )
        chunks = sample_chunks(payloads, count=eval_set.requested_count, seed=eval_set.id)
        types = assign_types(len(chunks), EvalMix(eval_set.mix))
        model = self.chat_model.with_structured_output(GeneratedPair)
        pairs: list[EvalPair] = []
        for chunk, question_type in zip(chunks, types, strict=True):
            self._require_lease(renewal, eval_set.id)
            generated = await self._generate_one(model, chunk, question_type, scope)
            if generated is None:
                continue
            pairs.append(
                EvalPair(
                    id=uuid.uuid4(),
                    set_id=eval_set.id,
                    position=len(pairs),
                    question_type=question_type.value,
                    question=generated.question.strip(),
                    reference_answer=generated.reference_answer.strip(),
                    source_file=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
            )
        return pairs

    async def _translate(
        self, eval_set: EvalSet, scope: dict[str, Any], renewal: "asyncio.Task[None]"
    ) -> list[EvalPair]:
        """One pair per source pair, in source order, with the source's current exclusions.

        An unfaithful pair is written excluded with `translation_unfaithful` and keeps the
        last attempt's text, or the English question when no attempt returned any (ruling
        R6). A copied hand exclusion keeps `exclusion_reason` `NULL`, so it can be
        included again; from here the two sets' exclusions are independent.
        """
        if eval_set.source_set_id is None:
            raise AssertionError("_translate needs a translated set")
        sources = await self.pairs.list_for_set(eval_set.source_set_id, include_excluded=True)
        model = self.chat_model.with_structured_output(TranslatedQuestion)
        language = Language(eval_set.language)
        now = datetime.now(UTC)
        pairs: list[EvalPair] = []
        for source in sources:
            self._require_lease(renewal, eval_set.id)
            outcome = await translate_question(
                model, question=source.question, language=language, scope=scope
            )
            unfaithful = not outcome.faithful
            pairs.append(
                EvalPair(
                    id=uuid.uuid4(),
                    set_id=eval_set.id,
                    position=source.position,
                    question_type=source.question_type,
                    question=outcome.question or source.question,
                    reference_answer=source.reference_answer,
                    source_file=source.source_file,
                    start_line=source.start_line,
                    end_line=source.end_line,
                    excluded_at=now if unfaithful or source.excluded_at is not None else None,
                    exclusion_reason=(
                        EvalExclusionReason.TRANSLATION_UNFAITHFUL.value if unfaithful else None
                    ),
                    source_pair_id=source.id,
                )
            )
        return pairs

    @staticmethod
    def _require_lease(renewal: "asyncio.Task[None]", set_id: uuid.UUID) -> None:
        """Stop spending model calls once the heartbeat has stopped: the lease was lost.

        The set was deleted or another worker owns it, and either way this run's
        release would match no row and discard everything (audit finding §8.4).
        Mirrors `EvalRunner._require_lease`.
        """
        if renewal.done():
            raise RetryableIngestionError(f"eval set {set_id} lost its lease mid-run")

    async def _renew(self, *, set_id: uuid.UUID, worker_id: str) -> None:
        """Hold the lease for the length of the run. Mirrors `MockDataGenerator._renew`."""
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with get_sessionmaker()() as session:
                held = await EvalSetRepository(session).renew_lease(
                    set_id=set_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
                await session.commit()
            if not held:
                logger.warning("lost the lease on eval set %s mid-run", set_id)
                return

    async def _stop_renewal(self, renewal: asyncio.Task[None], *, set_id: uuid.UUID) -> None:
        """Cancel the heartbeat and collect it."""
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("lease renewal for eval set %s failed", set_id, exc_info=True)

    async def _scroll(
        self, *, collection: str, project_id: uuid.UUID, generation: int, path_prefix: str
    ) -> list[dict[str, Any]]:
        """Every chunk under the path at this generation."""
        store = self.store_factory(collection)
        payloads: list[dict[str, Any]] = []
        try:
            async for page in store.scroll(
                project_id=project_id,
                generation=generation,
                path_prefix=path_prefix,
                page_size=self.settings.eval_scroll_page_size,
            ):
                payloads.extend(page)
        except TerminalIngestionError:
            raise
        except Exception as error:
            raise RetryableIngestionError(
                f"scrolling the index failed ({type(error).__name__})."
            ) from error
        return payloads

    async def _generate_one(
        self,
        model: Runnable[list[BaseMessage], Any],
        chunk: SampledChunk,
        question_type: EvalQuestionType,
        scope: dict[str, Any],
    ) -> GeneratedPair | None:
        """One pair, or `None` when the response is unusable. Terminal errors raise."""
        config: RunnableConfig = call_config(CallFeature.EVAL_GENERATE, **scope)
        try:
            result = await model.ainvoke(
                build_eval_pair_prompt(chunk=chunk, question_type=question_type), config=config
            )
        except Exception as error:
            classified = classify_chat_error(error)
            if classified is not None:
                # Terminal fails the job; retryable defers the lease up the ladder. Only
                # an unclassified failure (a malformed response) drops this one pair.
                raise classified from error
            logger.warning("an eval pair could not be generated: %s", type(error).__name__)
            return None
        if not isinstance(result, GeneratedPair):
            return None
        if not result.question.strip() or not result.reference_answer.strip():
            return None
        if names_its_file(result.question, chunk.file_path):
            return None
        return result
