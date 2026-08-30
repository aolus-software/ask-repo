"""The graph: routing, the corrective retrieval loop, and the streaming contract."""

from app.rag.graph.state import Classification, EvidenceVerdict, Intent


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
