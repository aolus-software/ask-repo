"""Prompt versions are per feature: an edit moves the version of the features it
reaches, and only those (audit §9.31)."""

import types

import pytest

from app.core.feedback import FeedbackFeature
from app.observability.features import CallFeature
from app.rag import prompts
from app.rag.prompt_version import (
    ANSWER_GRAPH,
    ANSWER_PROMPT_VERSION,
    CALL_PROMPT_VERSIONS,
    CALL_PROMPTS,
    JUDGE_PROMPT_VERSION,
    compute_prompt_version,
    prompt_constants,
    version_for,
)
from app.services.feedback import FEATURE_CALLS, FEATURE_PROMPT_VERSIONS


def _fake(**constants: object) -> types.ModuleType:
    module = types.ModuleType("fake_prompts")
    for name, value in constants.items():
        setattr(module, name, value)
    return module


def test_every_prompt_constant_belongs_to_a_feature() -> None:
    """A prompt no feature claims changes model output without moving any version."""
    claimed = set().union(*CALL_PROMPTS.values())
    assert set(prompt_constants(prompts)) - claimed == set()


def test_every_claimed_name_is_a_real_prompt() -> None:
    """A renamed constant must fail here, not silently drop out of its feature."""
    claimed = set().union(*CALL_PROMPTS.values())
    assert claimed - set(prompt_constants(prompts)) == set()


def test_every_call_feature_has_a_prompt_set() -> None:
    assert set(CALL_PROMPTS) == set(CallFeature)


def test_every_feedback_feature_maps_to_calls() -> None:
    assert set(FEATURE_CALLS) == set(FeedbackFeature)


def test_live_versions_are_twelve_hex_characters() -> None:
    for version in (*CALL_PROMPT_VERSIONS.values(), ANSWER_PROMPT_VERSION, JUDGE_PROMPT_VERSION):
        assert len(version) == 12
        int(version, 16)


def test_the_judge_prompt_does_not_move_the_answer_version() -> None:
    """The defect §9.31 named: one module-wide hash moved Ask's version on a judge edit."""
    assert "EVAL_JUDGE_SYSTEM" not in set().union(*(CALL_PROMPTS[f] for f in ANSWER_GRAPH))
    assert ANSWER_PROMPT_VERSION != JUDGE_PROMPT_VERSION


def test_an_ask_answer_and_an_eval_run_answer_share_a_version() -> None:
    assert FEATURE_PROMPT_VERSIONS[FeedbackFeature.ANSWER] == ANSWER_PROMPT_VERSION


def test_a_refinement_reply_versions_the_answer_graph_and_its_propose_prompt() -> None:
    expected = version_for((*ANSWER_GRAPH, CallFeature.PROPOSE_CHECKLIST))
    assert FEATURE_PROMPT_VERSIONS[FeedbackFeature.REFINE_CHECKLIST] == expected
    assert FEATURE_PROMPT_VERSIONS[FeedbackFeature.REFINE_CHECKLIST] != ANSWER_PROMPT_VERSION


def test_editing_a_prompt_changes_only_the_versions_that_name_it() -> None:
    before = _fake(ANSWER_SYSTEM="Answer.", GRADE_SYSTEM="Grade.")
    after = _fake(ANSWER_SYSTEM="Answer!", GRADE_SYSTEM="Grade.")
    assert compute_prompt_version(before, ["ANSWER_SYSTEM"]) != compute_prompt_version(
        after, ["ANSWER_SYSTEM"]
    )
    assert compute_prompt_version(before, ["GRADE_SYSTEM"]) == compute_prompt_version(
        after, ["GRADE_SYSTEM"]
    )


def test_an_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        compute_prompt_version(_fake(ANSWER_SYSTEM="Answer."), ["MISSING_SYSTEM"])


def test_non_prompt_attributes_do_not_count() -> None:
    base = compute_prompt_version(_fake(ANSWER_SYSTEM="Answer."))
    noisy = compute_prompt_version(
        _fake(ANSWER_SYSTEM="Answer.", _private="x", helper="y", MAX_TOKENS=5)
    )
    assert base == noisy
