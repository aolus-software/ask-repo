"""Generating an eval set: scroll the index, sample chunks, write one pair per chunk.

The generator scrolls; it does not search -- top-k cannot report what it left out
(`CLAUDE.md`). A per-pair model failure drops that pair rather than failing the job,
the same degrade-don't-fail stance as the checklist's map step; a terminal provider
error fails the job and the consumer records it.

No question, reference or answer text reaches a log line: a pair that is dropped is
logged by the error's class alone (`.claude/rules/call-log.md`).
"""

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import get_sessionmaker
from app.eval.model_output import GeneratedPair
from app.eval.sampling import SampledChunk, assign_types, names_its_file, sample_chunks
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.models.eval import EvalMix, EvalPair, EvalQuestionType, EvalSetStatus
from app.observability.features import CallFeature, call_config
from app.rag.errors import classify_chat_error
from app.rag.prompts import build_eval_pair_prompt
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_set import LEASE_RENEWAL_SECONDS, LEASE_SECONDS, EvalSetRepository
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

NO_PAIRS_ERROR = "No usable pairs could be generated from this path."


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
        if project is None or not project.embedding_collection:
            raise TerminalIngestionError(f"project {eval_set.project_id} has no index to scroll")
        generation = project.active_generation
        scope: dict[str, Any] = {
            "trace_seed": str(set_id),
            "project_id": project.id,
            "attempt": attempt,
        }

        renewal = asyncio.create_task(self._renew(set_id=set_id, worker_id=worker_id))
        try:
            payloads = await self._scroll(
                # Verbatim from the row, never recomputed from current settings.
                collection=project.embedding_collection,
                project_id=project.id,
                generation=generation,
                path_prefix=eval_set.source_path or "",
            )
            chunks = sample_chunks(payloads, count=eval_set.requested_count, seed=set_id)
            types = assign_types(len(chunks), EvalMix(eval_set.mix))
            model = self.chat_model.with_structured_output(GeneratedPair)
            pairs: list[EvalPair] = []
            for chunk, question_type in zip(chunks, types, strict=True):
                generated = await self._generate_one(model, chunk, question_type, scope)
                if generated is None:
                    continue
                pairs.append(
                    EvalPair(
                        id=uuid.uuid4(),
                        set_id=set_id,
                        position=len(pairs),
                        question_type=question_type.value,
                        question=generated.question.strip(),
                        reference_answer=generated.reference_answer.strip(),
                        source_file=chunk.file_path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                    )
                )
        finally:
            await self._stop_renewal(renewal, set_id=set_id)

        if pairs:
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
                error=NO_PAIRS_ERROR,
            )
        if not released:
            # A worker that lost its lease leaves both the set and its pairs alone.
            await self.session.rollback()
            logger.warning("eval generation for set %s lost its lease; discarding", set_id)
            return
        await self.session.commit()

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
            raise RetryableIngestionError(f"scrolling the index failed: {error}") from error
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
