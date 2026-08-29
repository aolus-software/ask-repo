"""Sequencing one turn: rewrite, retrieve, generate.

Knows nothing about HTTP and nothing about the database. It receives a question, a
history snapshot, and a retrieval handle, and yields events; everything that touches
a session or a status code lives in the service and the route.

That boundary is the point of the module. M3 replaces this file with a LangGraph
state graph — if the sequencing lived in the route or the service, M3 would be a
rewrite of the API layer instead of a rewrite of one file.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.core.errors import ErrorCode
from app.models.conversation import FinishReason
from app.rag.grounding import NO_CONTEXT_ANSWER, grounding_warnings
from app.rag.prompts import ANSWER_PROMPT, REWRITE_PROMPT, Turn, format_spans, to_langchain_history
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.conversation import (
    CitationPayload,
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    TokenEvent,
)

logger = logging.getLogger(__name__)

# The rewrite is one short call, not a full answer. Its own budget, well under the
# whole-turn one, so a hung rewrite cannot consume the time the answer needs.
REWRITE_TIMEOUT_SECONDS = 20.0
# Past this the model has returned a preamble or an explanation, not a query.
MAX_REWRITE_CHARS = 512

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def cited_indexes(text: str, *, count: int) -> list[int]:
    """The span labels the answer actually referenced, in order.

    Bounded by `count`: a model that cites `[9]` when four spans were supplied has
    invented it, and reporting it would send a client looking for a citation that
    does not exist.
    """
    found = {int(match) for match in _CITATION_PATTERN.findall(text)}
    return sorted(index for index in found if 1 <= index <= count)


def _text_of(message: BaseMessage) -> str:
    """The plain text of a message, whichever content shape the provider used."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part for part in content if isinstance(part, str))


def _to_citations(chunks: list[RetrievedChunk]) -> list[CitationPayload]:
    """Number the spans as the prompt labels them: 1-based, best score first."""
    return [
        CitationPayload(
            index=index,
            file_path=chunk.file_path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            language=chunk.language,
            symbol=chunk.symbol,
            commit_sha=chunk.commit_sha,
            score=chunk.score,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


class Answerer:
    """One turn's worth of work, expressed as a stream of events."""

    def __init__(
        self,
        *,
        retriever: Retriever,
        chat_model: BaseChatModel,
        model_id: str,
        semaphore: asyncio.Semaphore,
        timeout_seconds: float,
    ) -> None:
        self.retriever = retriever
        self.chat_model = chat_model
        self.model_id = model_id
        self.semaphore = semaphore
        self.timeout_seconds = timeout_seconds

    async def answer(
        self,
        *,
        question: str,
        history: list[Turn],
        project_id: uuid.UUID,
        generation: int,
        message_id: uuid.UUID,
    ) -> AsyncGenerator[StreamEvent]:
        """Rewrite, retrieve, generate — emitting events throughout.

        `message_id` is supplied by the caller rather than generated here so the
        terminating event can name the row the caller is about to write. Deriving it
        after the stream would mean `done` could not carry it.
        """
        if self.semaphore.locked():
            # Silence for the length of someone else's answer is indistinguishable
            # from a hung request.
            yield StatusEvent(phase="queued")

        async with self.semaphore:
            search_query = question
            if history:
                yield StatusEvent(phase="rewriting")
                search_query = await self._rewrite(question, history)

            yield StatusEvent(phase="retrieving")
            spans = await self.retriever.retrieve(
                search_query, project_id=project_id, generation=generation
            )
            citations = _to_citations(spans)
            yield CitationsEvent(citations=citations)

            if not spans:
                # The guard the prompt cannot provide. With no evidence, asking the
                # model to answer anyway leaves one instruction between the user and
                # a fabrication — and spends a full generation producing it.
                logger.info(
                    "Nothing above the relevance floor for project %s; refusing to answer",
                    project_id,
                )
                yield TokenEvent(text=NO_CONTEXT_ANSWER)
                yield DoneEvent(
                    message_id=message_id,
                    model=self.model_id,
                    finish_reason=FinishReason.STOP,
                    cited_indexes=[],
                    grounding_warnings=grounding_warnings(answer="", spans=spans, cited_count=0),
                )
                return

            yield StatusEvent(phase="generating")
            messages = ANSWER_PROMPT.format_messages(
                context=format_spans(spans),
                history=to_langchain_history(history),
                question=question,
            )

            parts: list[str] = []
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    async for chunk in self.chat_model.astream(messages):
                        text = _text_of(chunk)
                        if text:
                            parts.append(text)
                            yield TokenEvent(text=text)
            except TimeoutError:
                logger.warning(
                    "The model did not finish within %ss; ending the turn",
                    self.timeout_seconds,
                )
                yield ErrorEvent(
                    message_id=message_id,
                    code=ErrorCode.LLM_UNAVAILABLE,
                    message="The model did not finish in time. The partial answer was kept.",
                    finish_reason=FinishReason.TIMEOUT,
                )
                return
            except Exception:
                logger.exception("The model failed partway through an answer")
                yield ErrorEvent(
                    message_id=message_id,
                    code=ErrorCode.LLM_UNAVAILABLE,
                    message="The model failed while answering. The partial answer was kept.",
                    finish_reason=FinishReason.ERROR,
                )
                return

            answer = "".join(parts)
            cited = cited_indexes(answer, count=len(citations))
            warnings = grounding_warnings(answer=answer, spans=spans, cited_count=len(cited))
            if warnings:
                logger.warning(
                    "Answer for project %s carries grounding warnings: %s", project_id, warnings
                )
            yield DoneEvent(
                message_id=message_id,
                model=self.model_id,
                finish_reason=FinishReason.STOP,
                cited_indexes=cited,
                grounding_warnings=warnings,
            )

    async def _rewrite(self, question: str, history: list[Turn]) -> str:
        """Condense the conversation and the question into one standalone query.

        Degrades rather than fails. On a raise, a timeout, empty output, or output
        long enough to be a preamble, the raw question is used instead — trading a
        worse answer for no answer is the wrong trade for an optimisation.

        `CancelledError` is a `BaseException` and is deliberately not caught here: a
        client that disconnected during the rewrite should stop the turn, not fall
        back and carry on answering nobody.
        """
        try:
            async with asyncio.timeout(REWRITE_TIMEOUT_SECONDS):
                result = await self.chat_model.ainvoke(
                    REWRITE_PROMPT.format_messages(
                        history=to_langchain_history(history), question=question
                    )
                )
            rewritten = _text_of(result).strip()
        except Exception:
            logger.warning("Query rewrite failed; retrieving on the raw question", exc_info=True)
            return question

        if not rewritten or len(rewritten) > MAX_REWRITE_CHARS:
            logger.warning(
                "Query rewrite returned %d characters; retrieving on the raw question",
                len(rewritten),
            )
            return question
        return rewritten
