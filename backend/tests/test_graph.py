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
