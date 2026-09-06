"""One turn's worth of work, expressed as a stream of events.

Knows nothing about HTTP and nothing about the database. It receives a question, a
history snapshot, and a retrieval handle, and yields events; everything that touches
a session or a status code lives in the service and the route.

Since M3 the sequencing is a LangGraph state graph (`app/rag/graph/`). This module is
the adapter over it, and holds two things the graph deliberately does not: the
concurrency permit, and the construction of the single terminator. Keeping the
terminator here is what makes "exactly one per stream" structural -- no node can emit
one, so no node can emit a second.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Literal, cast

from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.core.errors import ErrorCode
from app.models.conversation import FinishReason
from app.rag.graph import build_answer_graph
from app.rag.graph.state import Intent, TurnState
from app.rag.grounding import NO_CONTEXT_ANSWER, WEAK_EVIDENCE, grounding_warnings
from app.rag.prompts import ExistingItem, ExistingRecord, Turn
from app.rag.retriever import Retriever
from app.schemas.conversation import (
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    TokenEvent,
)

logger = logging.getLogger(__name__)

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def cited_indexes(text: str, *, count: int) -> list[int]:
    """The span labels the answer actually referenced, in order.

    Bounded by `count`: a model that cites `[9]` when four spans were supplied has
    invented it, and reporting it would send a client looking for a citation that
    does not exist.
    """
    found = {int(match) for match in _CITATION_PATTERN.findall(text)}
    return sorted(index for index in found if 1 <= index <= count)


class Answerer:
    """One turn's worth of work, expressed as a stream of events."""

    def __init__(
        self,
        *,
        retriever: Retriever,
        chat_model: BaseChatModel,
        model_id: str,
        semaphore: asyncio.Semaphore,
        settings: Settings,
        propose_target: Literal["checklist", "mock_data"] | None = None,
    ) -> None:
        self.model_id = model_id
        self.semaphore = semaphore
        self.settings = settings
        self.graph = build_answer_graph(
            retriever=retriever,
            chat_model=chat_model,
            settings=settings,
            propose_target=propose_target,
        )

    async def answer(
        self,
        *,
        question: str,
        history: list[Turn],
        project_id: uuid.UUID,
        generation: int,
        message_id: uuid.UUID | None,
        existing_items: list[ExistingItem] | None = None,
        existing_records: list[ExistingRecord] | None = None,
        change_set_id: uuid.UUID | None = None,
        module_name: str = "",
    ) -> AsyncGenerator[StreamEvent]:
        """Run the graph, forwarding its events and terminating exactly once.

        `message_id` is supplied by the caller rather than generated here so the
        terminating event can name the row the caller is about to write. It is
        `None` on the re-run route, which writes a pending slot on a QA pair rather
        than a message (spec §8.1).

        The last four parameters are the two refinement paths', and default to the
        values that make either proposer a no-op -- so the Ask screen's call site is
        unchanged and cannot accidentally propose. `existing_items` is the checklist
        chat's, `existing_records` the mock-data chat's; `change_set_id` and
        `module_name` are shared, because only one proposer is ever wired into a
        given graph.
        """
        if self.semaphore.locked():
            # Silence for the length of someone else's answer is indistinguishable
            # from a hung request.
            yield StatusEvent(phase="queued")

        async with self.semaphore:
            state: TurnState = {
                "question": question,
                "history": history,
                "project_id": project_id,
                "generation": generation,
                "intent": Intent.CODEBASE_QUESTION,
                "search_query": question,
                "spans": [],
                "attempts": 0,
                "gap": None,
                "evidence_ok": False,
                "answer": "",
                "failure": None,
                "module_name": module_name,
                "existing_items": existing_items or [],
                "change_set_id": change_set_id,
                "operations": [],
                "change_summary": "",
                "existing_records": existing_records or [],
                "record_operations": [],
                "record_change_summary": "",
            }

            final: TurnState | None = None
            async for mode, chunk in self.graph.astream(state, stream_mode=["custom", "values"]):
                if mode == "custom":
                    assert isinstance(chunk, StreamEvent)
                    yield chunk
                else:
                    assert isinstance(chunk, dict)
                    final = cast(TurnState, chunk)

            if final is None:  # pragma: no cover - the graph always yields a state
                raise RuntimeError("the answer graph produced no final state")

            if (
                final["failure"] is None
                and final["intent"] is Intent.CODEBASE_QUESTION
                and not final["spans"]
            ):
                # The graph skips generation entirely on this route
                # (`route_after_retrieval` in `app/rag/graph/build.py`) rather than
                # spend a full generation on a fabrication with no evidence behind
                # it. The fixed refusal is streamed here as ordinary tokens instead,
                # so a client renders it exactly as it renders an answer.
                yield TokenEvent(text=NO_CONTEXT_ANSWER)

            yield self._terminate(final, message_id=message_id)

    def _terminate(self, final: TurnState, *, message_id: uuid.UUID | None) -> StreamEvent:
        """Build the one event that ends this stream."""
        if final["failure"] is not None:
            message = (
                "The model did not finish in time. The partial answer was kept."
                if final["failure"] is FinishReason.TIMEOUT
                else "The model failed while answering. The partial answer was kept."
            )
            return ErrorEvent(
                message_id=message_id,
                code=ErrorCode.LLM_UNAVAILABLE,
                message=message,
                finish_reason=final["failure"],
            )

        spans = final["spans"]
        answer = final["answer"]
        intent = final["intent"]

        if intent is Intent.CODEBASE_QUESTION and not spans:
            # The guard the prompt cannot provide. With no evidence, asking the
            # model to answer anyway leaves one instruction between the user and a
            # fabrication -- and spends a full generation producing it.
            logger.info(
                "Nothing above the relevance floor for project %s; refusing to answer",
                final["project_id"],
            )
            return DoneEvent(
                message_id=message_id,
                model=self.model_id,
                finish_reason=FinishReason.STOP,
                cited_indexes=[],
                grounding_warnings=grounding_warnings(answer="", spans=[], cited_count=0),
                intent=intent,
                retrieval_attempts=final["attempts"],
            )

        cited = cited_indexes(answer, count=len(spans))
        warnings = self._warnings_for(final, cited_count=len(cited))
        if warnings:
            logger.warning(
                "Answer for project %s carries grounding warnings: %s",
                final["project_id"],
                warnings,
            )
        return DoneEvent(
            message_id=message_id,
            model=self.model_id,
            finish_reason=FinishReason.STOP,
            cited_indexes=cited,
            grounding_warnings=warnings,
            intent=intent,
            retrieval_attempts=final["attempts"],
        )

    def _warnings_for(self, final: TurnState, *, cited_count: int) -> list[str]:
        """Grounding warnings for whichever route this turn took.

        The non-retrieval routes report nothing. `grounding_warnings()` returns
        `[NO_CONTEXT]` for any empty span list, which was right when retrieval was
        the only path -- but `conversational` and `out_of_scope` have empty spans
        because they never searched, and reporting "nothing in the index matched
        closely enough" would describe a search that did not happen.
        """
        if final["intent"] is not Intent.CODEBASE_QUESTION:
            return []

        warnings = grounding_warnings(
            answer=final["answer"], spans=final["spans"], cited_count=cited_count
        )
        if not final["evidence_ok"] and final["spans"]:
            warnings.append(WEAK_EVIDENCE)
        return warnings
