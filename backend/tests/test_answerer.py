"""The adapter over the graph: the semaphore, and the three terminations."""

import asyncio
import uuid

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.config import Settings
from app.models.conversation import FinishReason
from app.rag.answerer import Answerer, cited_indexes
from app.rag.graph.state import Classification, EvidenceVerdict, Intent
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
from tests.fakes import ScriptedChatModel
from tests.test_retriever import _span


class RecordingRetriever:
    """Records the query it was asked for, so the classifier's rewrite is observable.

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
    settings: Settings | None = None,
) -> Answerer:
    """An answerer over fakes. Explicit parameters rather than `**kwargs`, so a
    misspelled option is a type error here instead of a silently ignored default."""
    return Answerer(
        retriever=retriever if retriever is not None else RecordingRetriever(),
        chat_model=chat_model,
        model_id="test-model",
        semaphore=asyncio.Semaphore(concurrency),
        settings=settings if settings is not None else Settings(),
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


def _codebase_question_script(search_query: str = "q") -> list[BaseModel]:
    """The two structured calls a full codebase-question turn makes, in order."""
    return [
        Classification(intent="codebase_question", search_query=search_query),
        EvidenceVerdict(sufficient=True),
    ]


async def test_citations_arrive_once_and_before_the_first_token() -> None:
    """The ordering contract. A client renders its sources panel from this event
    while the answer types, and a broken stream still has citations for its partial."""
    model = ScriptedChatModel(tokens=["a", "b"], structured_results=_codebase_question_script())
    events = await collect(build(model))

    citation_positions = [i for i, e in enumerate(events) if isinstance(e, CitationsEvent)]
    first_token = next(i for i, e in enumerate(events) if isinstance(e, TokenEvent))

    assert len(citation_positions) == 1
    assert citation_positions[0] < first_token


async def test_exactly_one_terminator() -> None:
    model = ScriptedChatModel(tokens=["a"], structured_results=_codebase_question_script())
    events = await collect(build(model))
    terminators = [e for e in events if isinstance(e, DoneEvent | ErrorEvent)]

    assert len(terminators) == 1
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason is FinishReason.STOP


async def test_the_query_is_rewritten_on_every_turn() -> None:
    """Classification runs unconditionally now, unlike the old rewrite it replaced,
    which was skipped on a first turn because there was no history to condense."""
    retriever = RecordingRetriever()
    model = ScriptedChatModel(
        tokens=["x"], structured_results=_codebase_question_script("REWRITTEN")
    )

    await collect(build(model, retriever))

    assert retriever.queries == ["REWRITTEN"]


async def test_a_follow_up_retrieves_on_the_rewritten_query() -> None:
    """Embedding "what about the error case?" verbatim produces a vector for a
    generic phrase about errors, unrelated to this repository at all — so the
    retrieved chunks are effectively random and the answer is about the wrong code."""
    retriever = RecordingRetriever()
    model = ScriptedChatModel(
        tokens=["x"],
        structured_results=_codebase_question_script("What happens when URL validation fails?"),
    )

    await collect(
        build(model, retriever),
        question="what about the error case?",
        history=[
            Turn(role="user", content="how is the url validated"),
            Turn(role="assistant", content="via validate_repo_url"),
        ],
    )

    assert retriever.queries == ["What happens when URL validation fails?"]


async def test_a_mid_stream_failure_keeps_the_tokens_already_sent() -> None:
    model = ScriptedChatModel(
        tokens=["a", "b", "c"], fail_after=2, structured_results=_codebase_question_script()
    )
    events = await collect(build(model))

    assert [e.text for e in events if isinstance(e, TokenEvent)] == ["a", "b"]
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].finish_reason is FinishReason.ERROR


async def test_a_timeout_terminates_with_its_own_finish_reason() -> None:
    """Distinct from `error` so a client can tell "retry might work" from
    "something broke". The generate node's timeout is sized from
    `settings.chat_timeout_seconds` -- there is no separate answerer-level timeout
    any more."""
    model = ScriptedChatModel(
        tokens=["a", "b"], stall_seconds=1.1, structured_results=_codebase_question_script()
    )
    events = await collect(build(model, settings=Settings(chat_timeout_seconds=1)))

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].finish_reason is FinishReason.TIMEOUT


async def test_a_contended_semaphore_announces_the_wait() -> None:
    """Silence for the length of someone else's answer is indistinguishable from a
    hung request."""
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    answerer = Answerer(
        retriever=RecordingRetriever(),
        chat_model=ScriptedChatModel(tokens=["a"], structured_results=_codebase_question_script()),
        model_id="test-model",
        semaphore=semaphore,
        settings=Settings(),
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
    model = ScriptedChatModel(
        tokens=["See [1], then app/invented/thing.py."],
        structured_results=_codebase_question_script(),
    )

    events = await collect(build(model, retriever))

    assert isinstance(events[-1], DoneEvent)
    assert UNKNOWN_PATHS in events[-1].grounding_warnings


async def test_a_clean_answer_carries_no_warnings() -> None:
    retriever = RecordingRetriever(spans=[_span("app/main.py", 0, 1, 10)])
    model = ScriptedChatModel(
        tokens=["It is set up in [1], app/main.py."], structured_results=_codebase_question_script()
    )

    events = await collect(build(model, retriever))

    assert isinstance(events[-1], DoneEvent)
    assert events[-1].grounding_warnings == []


async def test_the_done_event_reports_the_route_and_the_attempts() -> None:
    model = ScriptedChatModel(
        tokens=["Validation ", "[1]"],
        structured_results=[
            Classification(intent="codebase_question", search_query="validation"),
            EvidenceVerdict(sufficient=True),
        ],
    )

    events = await collect(build(model, settings=Settings()))
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.intent is Intent.CODEBASE_QUESTION
    assert done.retrieval_attempts == 1


async def test_a_conversational_turn_reports_no_grounding_warnings() -> None:
    """The trap. `grounding_warnings()` returns `[NO_CONTEXT]` for any empty span
    list, but this route never retrieved — reporting "nothing in the index matched"
    would describe a search that did not happen, and the frontend would show the
    user a warning about it."""
    model = ScriptedChatModel(
        tokens=["You asked about validation."],
        structured_results=[Classification(intent="conversational", search_query="thanks")],
    )

    events = await collect(build(model, settings=Settings()), question="thanks")
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.grounding_warnings == []
    assert done.intent is Intent.CONVERSATIONAL


async def test_an_out_of_scope_turn_reports_no_grounding_warnings() -> None:
    model = ScriptedChatModel(
        structured_results=[Classification(intent="out_of_scope", search_query="x")]
    )

    events = await collect(build(model, settings=Settings()), question="capital of France")
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.grounding_warnings == []
    assert done.intent is Intent.OUT_OF_SCOPE


async def test_exhausted_attempts_are_flagged_weak_evidence() -> None:
    from app.rag.grounding import WEAK_EVIDENCE

    model = ScriptedChatModel(
        tokens=["Partial ", "[1]"],
        structured_results=[
            Classification(intent="codebase_question", search_query="q1"),
            EvidenceVerdict(sufficient=False, gap="g", better_query="q2"),
            EvidenceVerdict(sufficient=False, gap="g", better_query="q3"),
        ],
    )

    events = await collect(build(model, settings=Settings(rag_max_retrieval_attempts=2)))
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert WEAK_EVIDENCE in done.grounding_warnings
    assert done.retrieval_attempts == 2


async def test_still_exactly_one_terminator_on_every_route() -> None:
    scripts: list[tuple[list[BaseModel], list[str]]] = [
        (_codebase_question_script(), ["a"]),
        ([Classification(intent="conversational", search_query="q")], ["a"]),
        ([Classification(intent="out_of_scope", search_query="q")], []),
    ]
    for scripted, tokens in scripts:
        events = await collect(
            build(
                ScriptedChatModel(tokens=tokens, structured_results=scripted),
                settings=Settings(),
            )
        )
        terminators = [e for e in events if isinstance(e, DoneEvent | ErrorEvent)]

        assert len(terminators) == 1
        assert events[-1] is terminators[0]


async def _terminator_without_a_message(model: ScriptedChatModel) -> StreamEvent:
    """Drain a turn that names no message row, and return how it ended.

    Spelled out rather than routed through `collect`, because `message_id` is the
    subject here and `collect` supplies one of its own.
    """
    events = [
        event
        async for event in build(model).answer(
            question="how does it work",
            history=[],
            project_id=uuid.uuid4(),
            generation=0,
            message_id=None,
        )
    ]
    return events[-1]


async def test_a_run_with_no_message_terminates_with_a_null_message_id() -> None:
    """A re-run writes a pending slot on a QA pair, not a message row (spec §8.1)."""
    model = ScriptedChatModel(tokens=["a"], structured_results=_codebase_question_script())

    terminator = await _terminator_without_a_message(model)

    assert isinstance(terminator, DoneEvent)
    assert terminator.message_id is None


async def test_a_failing_run_with_no_message_also_terminates() -> None:
    """The half that would otherwise be missed.

    A re-run that fails ends through `ErrorEvent`, which carries the same field.
    Widening only `DoneEvent` would leave the failure path unable to terminate at
    all — the stream would raise inside the adapter instead of reporting.
    """
    model = ScriptedChatModel(
        tokens=["a", "b", "c"], fail_after=2, structured_results=_codebase_question_script()
    )

    terminator = await _terminator_without_a_message(model)

    assert isinstance(terminator, ErrorEvent)
    assert terminator.message_id is None
