"""The graph: routing, the corrective retrieval loop, and the streaming contract."""

from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.rag.graph.state import Classification, EvidenceVerdict, Intent, TurnState


def test_intent_serialises_as_its_value() -> None:
    """`Intent` rides in `DoneEvent`, so it must serialise as a string the frontend
    matches on — the same reason `FinishReason` is a `StrEnum`."""
    assert Intent.CODEBASE_QUESTION.value == "codebase_question"
    assert Intent.CONVERSATIONAL.value == "conversational"
    assert Intent.OUT_OF_SCOPE.value == "out_of_scope"
    assert f"{Intent.CONVERSATIONAL}" == "conversational"


def test_classification_rejects_an_unknown_intent() -> None:
    """The model is constrained to these three by `with_structured_output`; this is
    the guard for a provider that ignores the constraint."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Classification(intent="something_else", search_query="q")


def test_evidence_verdict_defaults_are_empty_strings() -> None:
    """`gap` and `better_query` are empty when the evidence is sufficient, so a
    grader that omits them is valid rather than a crash mid-turn."""
    verdict = EvidenceVerdict(sufficient=True)

    assert verdict.gap == ""
    assert verdict.better_query == ""


def test_status_event_accepts_the_new_phases() -> None:
    from app.schemas.conversation import StatusEvent

    assert StatusEvent(phase="classifying").phase == "classifying"
    assert StatusEvent(phase="grading").phase == "grading"


def test_done_event_reports_the_path_the_turn_took() -> None:
    """Not recomputable from the stored message, so if it is not reported here it is
    gone — see spec §2.4."""
    import json
    import uuid

    from app.models.conversation import FinishReason
    from app.rag.graph.state import Intent
    from app.schemas.conversation import DoneEvent

    event = DoneEvent(
        message_id=uuid.uuid4(),
        model="test-model",
        finish_reason=FinishReason.STOP,
        cited_indexes=[1],
        intent=Intent.CONVERSATIONAL,
        retrieval_attempts=0,
    )
    payload = json.loads(event.model_dump_json(by_alias=True))

    assert payload["intent"] == "conversational"
    assert payload["retrievalAttempts"] == 0


async def test_the_fake_returns_scripted_structured_results_in_order() -> None:
    """Two structured calls per turn at most (classify, then grade), so the fake
    hands them out in sequence rather than repeating one."""
    from app.rag.graph.state import Classification, EvidenceVerdict
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(
        structured_results=[
            Classification(intent="codebase_question", search_query="q"),
            EvidenceVerdict(sufficient=False, gap="no tests", better_query="better"),
        ]
    )

    first = await model.with_structured_output(Classification).ainvoke("anything")
    second = await model.with_structured_output(EvidenceVerdict).ainvoke("anything")

    assert first.intent == "codebase_question"
    assert second.sufficient is False
    assert second.better_query == "better"


async def test_the_fake_raises_when_the_script_runs_out() -> None:
    """A silent default would let a test pass while exercising a path it never set
    up — the failure it is meant to catch would look like success."""
    import pytest

    from app.rag.graph.state import Classification
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(structured_results=[])

    with pytest.raises(AssertionError):
        await model.with_structured_output(Classification).ainvoke("anything")


async def test_the_failing_model_raises_on_a_structured_call() -> None:
    """The degradation path: classify and grade must both survive a model that
    raises."""
    import pytest

    from app.rag.graph.state import Classification
    from tests.fakes import FailingChatModel

    with pytest.raises(RuntimeError):
        await FailingChatModel().with_structured_output(Classification).ainvoke("x")


async def test_two_scripted_model_instances_do_not_share_a_structured_queue() -> None:
    """A queue stored on the class, or captured by closure over a shared list, would
    let one test's script bleed into another's model instance. Each `ScriptedChatModel`
    must own its own cursor."""
    from app.rag.graph.state import Classification
    from tests.fakes import ScriptedChatModel

    first_model = ScriptedChatModel(
        structured_results=[Classification(intent="codebase_question", search_query="a")]
    )
    second_model = ScriptedChatModel(
        structured_results=[Classification(intent="conversational", search_query="b")]
    )

    first_result = await first_model.with_structured_output(Classification).ainvoke("x")
    second_result = await second_model.with_structured_output(Classification).ainvoke("x")

    assert first_result.search_query == "a"
    assert second_result.search_query == "b"


async def run_node(
    node: Callable[[TurnState], Awaitable[dict]], state: TurnState
) -> tuple[list, TurnState]:
    """Run one node inside a throwaway one-node graph.

    Required, not preferred: nodes call `emit()`, which resolves LangGraph's stream
    writer from the runnable context and raises `RuntimeError` when there is none. A
    node invoked as a bare function would be tested in a state it never runs in.
    """
    graph = StateGraph(TurnState)
    graph.add_node("n", node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)
    app = graph.compile()

    events: list = []
    final: TurnState | None = None
    async for mode, chunk in app.astream(state, stream_mode=["custom", "values"]):
        if mode == "custom":
            events.append(chunk)
        else:
            final = chunk
    assert final is not None
    return events, final


def base_state(**overrides: object) -> TurnState:
    """A turn state with every key present, so a node reading one never KeyErrors."""
    import uuid

    state: TurnState = {
        "question": "how does validation work",
        "history": [],
        "project_id": uuid.uuid4(),
        "generation": 0,
        "intent": Intent.CODEBASE_QUESTION,
        "search_query": "",
        "spans": [],
        "attempts": 0,
        "gap": None,
        "evidence_ok": False,
        "answer": "",
        "failure": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]  # test helper takes arbitrary overrides
    return state


async def test_classify_routes_and_rewrites_in_one_call() -> None:
    from app.rag.graph.nodes import build_classify
    from app.rag.graph.state import Classification
    from app.schemas.conversation import StatusEvent
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(
        structured_results=[
            Classification(intent="conversational", search_query="how does it work")
        ]
    )

    events, final = await run_node(build_classify(model, enabled=True), base_state())

    assert final["intent"] is Intent.CONVERSATIONAL
    assert final["search_query"] == "how does it work"
    assert any(isinstance(e, StatusEvent) and e.phase == "classifying" for e in events)


async def test_a_failing_classifier_falls_back_to_retrieval() -> None:
    """Degrades toward evidence. Trading a worse answer for no answer is the wrong
    trade for an optimisation, and the safe default is the path that retrieves."""
    from app.rag.graph.nodes import build_classify
    from tests.fakes import FailingChatModel

    _, final = await run_node(
        build_classify(FailingChatModel(), enabled=True),
        base_state(question="what about errors"),
    )

    assert final["intent"] is Intent.CODEBASE_QUESTION
    assert final["search_query"] == "what about errors"


async def test_an_overlong_query_falls_back_to_the_raw_question() -> None:
    """Past this the model has returned a preamble or an explanation, not a query."""
    from app.rag.graph.nodes import MAX_QUERY_CHARS, build_classify
    from app.rag.graph.state import Classification
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(
        structured_results=[
            Classification(intent="codebase_question", search_query="x" * (MAX_QUERY_CHARS + 1))
        ]
    )

    _, final = await run_node(build_classify(model, enabled=True), base_state(question="q"))

    assert final["search_query"] == "q"


async def test_an_empty_query_falls_back_to_the_raw_question() -> None:
    from app.rag.graph.nodes import build_classify
    from app.rag.graph.state import Classification
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(
        structured_results=[Classification(intent="codebase_question", search_query="   ")]
    )

    _, final = await run_node(build_classify(model, enabled=True), base_state(question="q"))

    assert final["search_query"] == "q"


async def test_a_disabled_classifier_makes_no_model_call() -> None:
    """Short-circuits to the same values the failure path produces — one code path,
    not two. This is what makes PRD §6's per-node benchmark measure a real delta."""
    from app.rag.graph.nodes import build_classify
    from tests.fakes import ScriptedChatModel

    model = ScriptedChatModel(structured_results=[])  # would raise if called

    _, final = await run_node(build_classify(model, enabled=False), base_state(question="q"))

    assert final["intent"] is Intent.CODEBASE_QUESTION
    assert final["search_query"] == "q"
