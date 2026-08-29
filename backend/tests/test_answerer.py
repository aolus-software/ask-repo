"""The sequence, the fallbacks, and the three terminations."""

import asyncio
import uuid

from langchain_core.language_models import BaseChatModel

from app.models.conversation import FinishReason
from app.rag.answerer import Answerer, cited_indexes
from app.rag.grounding import NO_CONTEXT, NO_CONTEXT_ANSWER, UNKNOWN_PATHS
from app.rag.prompts import Turn
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.conversation import (
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    TokenEvent,
)
from tests.fakes import FailingChatModel, ScriptedChatModel
from tests.test_retriever import _span


class RecordingRetriever:
    """Records the query it was asked for, so rewrite behaviour is observable.

    Satisfies the `Retriever` protocol structurally — no base class and no cast.
    """

    def __init__(self, spans: list[RetrievedChunk] | None = None) -> None:
        self.spans = spans if spans is not None else [_span("app/a.py", 0, 1, 10)]
        self.queries: list[str] = []

    async def retrieve(
        self, query: str, *, project_id: uuid.UUID, generation: int
    ) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self.spans


def build(
    chat_model: BaseChatModel,
    retriever: Retriever | None = None,
    *,
    concurrency: int = 2,
    timeout_seconds: float = 30,
) -> Answerer:
    """An answerer over fakes. Explicit parameters rather than `**kwargs`, so a
    misspelled option is a type error here instead of a silently ignored default."""
    return Answerer(
        retriever=retriever if retriever is not None else RecordingRetriever(),
        chat_model=chat_model,
        model_id="test-model",
        semaphore=asyncio.Semaphore(concurrency),
        timeout_seconds=timeout_seconds,
    )


async def collect(
    answerer: Answerer,
    *,
    question: str = "how does it work",
    history: list[Turn] | None = None,
) -> list[StreamEvent]:
    """Drain a whole turn into a list, so ordering can be asserted on positions."""
    return [
        event
        async for event in answerer.answer(
            question=question,
            history=history if history is not None else [],
            project_id=uuid.uuid4(),
            generation=0,
            message_id=uuid.uuid4(),
        )
    ]


async def test_citations_arrive_once_and_before_the_first_token() -> None:
    """The ordering contract. A client renders its sources panel from this event
    while the answer types, and a broken stream still has citations for its partial."""
    events = await collect(build(ScriptedChatModel(tokens=["a", "b"])))

    citation_positions = [i for i, e in enumerate(events) if isinstance(e, CitationsEvent)]
    first_token = next(i for i, e in enumerate(events) if isinstance(e, TokenEvent))

    assert len(citation_positions) == 1
    assert citation_positions[0] < first_token


async def test_exactly_one_terminator() -> None:
    events = await collect(build(ScriptedChatModel(tokens=["a"])))
    terminators = [e for e in events if isinstance(e, DoneEvent | ErrorEvent)]

    assert len(terminators) == 1
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason is FinishReason.STOP


async def test_the_first_turn_is_not_rewritten() -> None:
    """There is no history to condense, and the raw question is already standalone."""
    retriever = RecordingRetriever()
    await collect(build(ScriptedChatModel(tokens=["x"], invoke_result="REWRITTEN"), retriever))

    assert retriever.queries == ["how does it work"]


async def test_a_follow_up_retrieves_on_the_rewritten_query() -> None:
    """Embedding "what about the error case?" verbatim produces a vector for a
    generic phrase about errors, unrelated to this repository at all — so the
    retrieved chunks are effectively random and the answer is about the wrong code."""
    retriever = RecordingRetriever()
    model = ScriptedChatModel(tokens=["x"], invoke_result="What happens when URL validation fails?")

    await collect(
        build(model, retriever),
        question="what about the error case?",
        history=[
            Turn(role="user", content="how is the url validated"),
            Turn(role="assistant", content="via validate_repo_url"),
        ],
    )

    assert retriever.queries == ["What happens when URL validation fails?"]


async def test_a_failed_rewrite_falls_back_to_the_raw_question() -> None:
    """Failing the whole turn because an optimisation failed trades a worse answer
    for no answer, which is the wrong trade."""
    retriever = RecordingRetriever()

    await collect(
        build(FailingChatModel(tokens=["x"]), retriever),
        question="what about the error case?",
        history=[Turn(role="user", content="earlier")],
    )

    assert retriever.queries == ["what about the error case?"]


async def test_an_overlong_rewrite_falls_back_to_the_raw_question() -> None:
    """A model that returns a preamble instead of a query would otherwise have its
    explanation embedded as though it were the search text."""
    retriever = RecordingRetriever()
    model = ScriptedChatModel(tokens=["x"], invoke_result="x" * 600)

    await collect(
        build(model, retriever),
        question="what about the error case?",
        history=[Turn(role="user", content="earlier")],
    )

    assert retriever.queries == ["what about the error case?"]


async def test_an_empty_rewrite_falls_back_to_the_raw_question() -> None:
    retriever = RecordingRetriever()
    model = ScriptedChatModel(tokens=["x"], invoke_result="   ")

    await collect(
        build(model, retriever),
        question="what about the error case?",
        history=[Turn(role="user", content="earlier")],
    )

    assert retriever.queries == ["what about the error case?"]


async def test_a_mid_stream_failure_keeps_the_tokens_already_sent() -> None:
    events = await collect(build(ScriptedChatModel(tokens=["a", "b", "c"], fail_after=2)))

    assert [e.text for e in events if isinstance(e, TokenEvent)] == ["a", "b"]
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].finish_reason is FinishReason.ERROR


async def test_a_timeout_terminates_with_its_own_finish_reason() -> None:
    """Distinct from `error` so a client can tell "retry might work" from
    "something broke"."""
    model = ScriptedChatModel(tokens=["a", "b"], stall_seconds=0.05)
    events = await collect(build(model, timeout_seconds=0.01))

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].finish_reason is FinishReason.TIMEOUT


async def test_a_contended_semaphore_announces_the_wait() -> None:
    """Silence for the length of someone else's answer is indistinguishable from a
    hung request."""
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    answerer = Answerer(
        retriever=RecordingRetriever(),
        chat_model=ScriptedChatModel(tokens=["a"]),
        model_id="test-model",
        semaphore=semaphore,
        timeout_seconds=30,
    )

    events: list[StreamEvent] = []
    task = asyncio.create_task(_drain(answerer, events))
    await asyncio.sleep(0)
    semaphore.release()
    await task

    assert isinstance(events[0], StatusEvent)
    assert events[0].phase == "queued"


async def _drain(answerer: Answerer, sink: list[StreamEvent]) -> None:
    async for event in answerer.answer(
        question="q", history=[], project_id=uuid.uuid4(), generation=0, message_id=uuid.uuid4()
    ):
        sink.append(event)


def test_cited_indexes_ignores_labels_that_do_not_exist() -> None:
    """A model that cites `[9]` when four spans were supplied has invented one.
    Reporting it would send a client looking for a citation that is not there."""
    assert cited_indexes("see [1] and [3], also [9]", count=4) == [1, 3]


async def test_nothing_retrieved_refuses_without_calling_the_model() -> None:
    """The guard that matters most. With no evidence, asking the model to answer
    anyway leaves one prompt instruction between the user and a fabrication — and
    burns a full generation to produce it."""
    retriever = RecordingRetriever(spans=[])
    model = ScriptedChatModel(tokens=["this should never be streamed"])

    events = await collect(build(model, retriever))

    assert not any(isinstance(e, TokenEvent) and "never be streamed" in e.text for e in events)
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].grounding_warnings == [NO_CONTEXT]
    assert events[-1].cited_indexes == []


async def test_the_refusal_reaches_the_client_as_ordinary_tokens() -> None:
    """A refusal renders like an answer, so clients need no special case. The
    machine-readable distinction is in groundingWarnings."""
    events = await collect(build(ScriptedChatModel(tokens=["x"]), RecordingRetriever(spans=[])))
    streamed = "".join(e.text for e in events if isinstance(e, TokenEvent))

    assert streamed == NO_CONTEXT_ANSWER


async def test_an_answer_naming_an_unretrieved_file_is_flagged() -> None:
    retriever = RecordingRetriever(spans=[_span("app/main.py", 0, 1, 10)])
    model = ScriptedChatModel(tokens=["See [1], then app/invented/thing.py."])

    events = await collect(build(model, retriever))

    assert isinstance(events[-1], DoneEvent)
    assert UNKNOWN_PATHS in events[-1].grounding_warnings


async def test_a_clean_answer_carries_no_warnings() -> None:
    retriever = RecordingRetriever(spans=[_span("app/main.py", 0, 1, 10)])
    model = ScriptedChatModel(tokens=["It is set up in [1], app/main.py."])

    events = await collect(build(model, retriever))

    assert isinstance(events[-1], DoneEvent)
    assert events[-1].grounding_warnings == []
