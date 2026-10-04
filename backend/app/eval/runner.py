"""Running an eval set through the real answer graph.

No answer style: `Answerer.answer` without one renders the default prompt byte-for-byte
(persona spec §6), which is what makes two runs comparable. No conversation is written;
an eval answer is nobody's conversation. `retrieval_hit` reads the one `citations`
event -- first-pass retrieval, which is what chunking and embedding change.

Two kinds of failure, kept apart. A failure inside one pair's answer (an `error` event)
or judge call degrades: that pair records `verdict = error` and the run goes on, so a
run whose every pair errored is still `done`. Anything else is infrastructure -- the
store unreachable, a chat error classified retryable or terminal, the lease lost -- and
propagates, so the consumer defers and retries, or fails the run when it is terminal.

No question, reference, answer or judge reason reaches a log line: a failure is logged
by the error's class alone (`.claude/rules/call-log.md`).
"""

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import get_sessionmaker
from app.eval.model_output import JudgeVerdict
from app.ingestion.embedder import Embedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.models.eval import EvalResult, EvalRunStatus, EvalVerdict
from app.models.project import Project
from app.observability.features import CallFeature, call_config
from app.rag.answerer import Answerer
from app.rag.errors import classify_chat_error
from app.rag.prompt_version import PROMPT_VERSION
from app.rag.prompts import build_eval_judge_prompt
from app.rag.retriever import CodeRetriever
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_result import EvalResultRepository
from app.repositories.eval_run import LEASE_RENEWAL_SECONDS, LEASE_SECONDS, EvalRunRepository
from app.repositories.project import ProjectRepository
from app.schemas.conversation import (
    CitationPayload,
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
)

logger = logging.getLogger(__name__)

RESULT_BATCH = 10
MAX_REASON_CHARS = 500


def retrieval_hit(citations: list[CitationPayload], source_file: str) -> bool:
    """Whether retrieval brought the pair's own file back on the first pass."""
    return any(citation.file_path == source_file for citation in citations)


@dataclass(frozen=True)
class _PairSpec:
    """What a pair needs while answering, copied out so no ORM row crosses a commit."""

    id: uuid.UUID
    question: str
    reference: str
    source_file: str


class EvalRunner:
    """One `run` job, bound to one session."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        store_factory: VectorStoreFactory,
        embedder: Embedder,
        chat_model: BaseChatModel,
    ) -> None:
        """Bind this job to `session`.

        `_renew` deliberately does not use `session`: it opens its own short-lived
        session per tick, because an `AsyncSession` is not safe for concurrent use.
        """
        self.session = session
        self.settings = settings
        self.store_factory = store_factory
        self.embedder = embedder
        self.chat_model = chat_model
        self.runs = EvalRunRepository(session)
        self.pairs = EvalPairRepository(session)
        self.results = EvalResultRepository(session)
        self.projects = ProjectRepository(session)

    async def run(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, attempt: int = 0
    ) -> None:
        """Answer and judge every pair not yet answered, then release the run `done`.

        `target_id` is the run id. The caller has already claimed the run; failures
        propagate so the consumer routes them onto the ladder.
        """
        run_id = target_id
        run = await self.runs.get(run_id)
        if run is None:
            raise TerminalIngestionError(f"eval run {run_id} is gone")
        project = await self.projects.get(run.project_id)
        if project is None or not project.embedding_collection:
            raise TerminalIngestionError(f"project {run.project_id} has no index to query")
        if project.embedding_model != self.embedder.model_id:
            # The guard `.claude/rules/rag.md` asks of every retrieval: another model's
            # vectors would return noise that still looks like answers.
            raise TerminalIngestionError(
                f"project {project.id} was indexed with a different embedding model"
            )

        # Plain locals before the first commit: it expires every ORM attribute, and a
        # lazy reload inside a gathered coroutine is an unawaited IO attempt.
        project_id = project.id
        generation = project.active_generation
        set_id = run.set_id
        answerer = self._answerer(project)

        run.prompt_version = PROMPT_VERSION
        run.chat_provider = self.settings.chat_provider
        run.chat_model = self.settings.chat_model
        run.judge_model = self.settings.chat_model
        run.embedding_model = project.embedding_model
        run.project_generation = project.active_generation
        await self.session.commit()

        done_ids = await self.results.pair_ids_for_run(run_id)
        pending = [
            _PairSpec(pair.id, pair.question, pair.reference_answer, pair.source_file)
            for pair in await self.pairs.list_for_set(set_id, include_excluded=False)
            if pair.id not in done_ids
        ]
        width = self.settings.eval_answer_concurrency

        renewal = asyncio.create_task(self._renew(run_id=run_id, worker_id=worker_id))
        try:
            unsaved = 0
            for start in range(0, len(pending), width):
                chunk = pending[start : start + width]
                finished = await self._gather(
                    [
                        self._answer_and_judge(
                            answerer,
                            pair,
                            project_id=project_id,
                            generation=generation,
                            attempt=attempt,
                            run_id=run_id,
                        )
                        for pair in chunk
                    ]
                )
                self.session.add_all(finished)
                unsaved += len(finished)
                if unsaved >= RESULT_BATCH:
                    self._require_lease(renewal, run_id)
                    await self.session.commit()
                    unsaved = 0
            self._require_lease(renewal, run_id)
        except Exception:
            # Uncommitted results are dropped: a redelivery re-answers them.
            await self.session.rollback()
            raise
        finally:
            await self._stop_renewal(renewal, run_id=run_id)

        await self.session.flush()
        rows = await self.results.list_for_run(run_id)
        released = await self.runs.release(
            run_id=run_id,
            job_id=job_id,
            worker_id=worker_id,
            status=EvalRunStatus.DONE,
            finished_at=datetime.now(UTC),
            pairs_answered=len(rows),
            hits=sum(1 for row in rows if row.retrieval_hit),
            correct=_count(rows, EvalVerdict.CORRECT),
            partial=_count(rows, EvalVerdict.PARTIAL),
            wrong=_count(rows, EvalVerdict.WRONG),
            errors=_count(rows, EvalVerdict.ERROR),
        )
        if not released:
            await self.session.rollback()
            logger.warning("eval run %s lost its lease before release", run_id)
            raise RetryableIngestionError(f"eval run {run_id} lost its lease")
        await self.session.commit()

    def _answerer(self, project: Project) -> Answerer:
        """One answerer for the run: no `propose_target`, so it cannot propose."""
        assert project.embedding_collection is not None
        settings = self.settings
        return Answerer(
            retriever=CodeRetriever(
                # Verbatim from the row, never recomputed from current settings.
                store=self.store_factory(project.embedding_collection),
                embedder=self.embedder,
                top_k=settings.rag_top_k,
                max_chars=settings.rag_context_max_chars,
                min_score=settings.rag_min_score,
            ),
            chat_model=self.chat_model,
            model_id=settings.chat_model,
            semaphore=asyncio.Semaphore(settings.eval_answer_concurrency),
            settings=settings,
        )

    async def _gather(self, work: list[Coroutine[Any, Any, EvalResult]]) -> list[EvalResult]:
        """Run one chunk of pairs together; if one raises, stop the rest."""
        tasks = [asyncio.ensure_future(item) for item in work]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    def _require_lease(self, renewal: "asyncio.Task[None]", run_id: uuid.UUID) -> None:
        """Refuse to commit once the heartbeat has stopped: the lease was lost.

        Another worker may now own the run, and its rows would collide with ours on
        the unique `(run_id, pair_id)` index.
        """
        if renewal.done():
            raise RetryableIngestionError(f"eval run {run_id} lost its lease mid-run")

    async def _answer_and_judge(
        self,
        answerer: Answerer,
        pair: _PairSpec,
        *,
        project_id: uuid.UUID,
        generation: int,
        attempt: int,
        run_id: uuid.UUID,
    ) -> EvalResult:
        """One pair: drain the answer, then grade it.

        A model failure inside the answer (an `error` event) or the judge records
        `verdict = error`. A failure of the retrieval path -- the store, the embedder --
        is infrastructure and propagates, classified when it is a chat error.
        """
        result_id = uuid.uuid4()
        citations: list[CitationPayload] = []
        parts: list[str] = []
        done: DoneEvent | None = None
        failed = False
        try:
            # `message_id` is the result's id: the answerer derives its trace seed from
            # it, so the answer's calls and the judge's share one trace (spec §3.3).
            async for event in answerer.answer(
                question=pair.question,
                history=[],
                project_id=project_id,
                generation=generation,
                message_id=result_id,
            ):
                if isinstance(event, CitationsEvent):
                    citations = list(event.citations)
                elif isinstance(event, TokenEvent):
                    parts.append(event.text)
                elif isinstance(event, DoneEvent):
                    done = event
                elif isinstance(event, ErrorEvent):
                    failed = True
        except Exception as error:
            classified = classify_chat_error(error)
            if classified is not None:
                raise classified from error
            raise RetryableIngestionError(
                f"answering an eval pair failed: {type(error).__name__}"
            ) from error
        answer = "".join(parts)
        verdict, reason = EvalVerdict.ERROR, None
        if not failed and done is not None:
            verdict, reason = await self._judge(
                pair, answer, result_id=result_id, project_id=project_id, attempt=attempt
            )
        return EvalResult(
            id=result_id,
            run_id=run_id,
            pair_id=pair.id,
            retrieval_hit=retrieval_hit(citations, pair.source_file),
            verdict=verdict.value,
            judge_reason=reason,
            answer=answer,
            grounding_warnings=list(done.grounding_warnings) if done else [],
            retrieval_attempts=done.retrieval_attempts if done else 0,
        )

    async def _judge(
        self,
        pair: _PairSpec,
        answer: str,
        *,
        result_id: uuid.UUID,
        project_id: uuid.UUID,
        attempt: int,
    ) -> tuple[EvalVerdict, str | None]:
        """Grade one answer. Any failure is `error` for this pair, never for the run."""
        try:
            result = await self.chat_model.with_structured_output(JudgeVerdict).ainvoke(
                build_eval_judge_prompt(
                    question=pair.question, reference=pair.reference, answer=answer
                ),
                config=call_config(
                    CallFeature.EVAL_JUDGE,
                    trace_seed=str(result_id),
                    project_id=project_id,
                    attempt=attempt,
                ),
            )
            verdict = JudgeVerdict.model_validate(result)
            return EvalVerdict(verdict.verdict), verdict.reason[:MAX_REASON_CHARS]
        except Exception as error:
            logger.warning("an eval answer could not be judged: %s", type(error).__name__)
            return EvalVerdict.ERROR, None

    async def _renew(self, *, run_id: uuid.UUID, worker_id: str) -> None:
        """Hold the lease for the length of the run. Mirrors `EvalSetGenerator._renew`.

        Returns when the lease is lost; `_require_lease` reads that as the task being
        done.
        """
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with get_sessionmaker()() as session:
                held = await EvalRunRepository(session).renew_lease(
                    run_id=run_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
                await session.commit()
            if not held:
                logger.warning("lost the lease on eval run %s mid-run", run_id)
                return

    async def _stop_renewal(self, renewal: "asyncio.Task[None]", *, run_id: uuid.UUID) -> None:
        """Cancel the heartbeat and collect it."""
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("lease renewal for eval run %s failed", run_id, exc_info=True)


def _count(rows: list[EvalResult], verdict: EvalVerdict) -> int:
    return sum(1 for row in rows if row.verdict == verdict.value)
