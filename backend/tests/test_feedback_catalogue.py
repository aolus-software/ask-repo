"""The feedback catalogue is a wire contract: pin it in both directions."""

import pytest

from app.core.feedback import (
    CHANGE_SET_TARGETS,
    MESSAGE_TARGETS,
    FeedbackFeature,
    FeedbackTarget,
    ReasonCode,
    feature_for,
    reasons_for,
)
from app.models.checklist import ChangeSetOrigin


def test_targets_partition_into_messages_and_change_sets() -> None:
    assert MESSAGE_TARGETS | CHANGE_SET_TARGETS == frozenset(FeedbackTarget)
    assert not MESSAGE_TARGETS & CHANGE_SET_TARGETS


@pytest.mark.parametrize("target", list(FeedbackTarget))
def test_every_target_has_a_reason_and_other(target: FeedbackTarget) -> None:
    reasons = reasons_for(target)
    assert ReasonCode.OTHER in reasons
    assert len(reasons) >= 2


def test_every_reason_applies_somewhere() -> None:
    covered = set().union(*(reasons_for(t) for t in FeedbackTarget))
    assert covered == set(ReasonCode)


def test_citation_codes_are_answer_only() -> None:
    for target in CHANGE_SET_TARGETS:
        assert ReasonCode.WRONG_FILE_CITED not in reasons_for(target)
        assert ReasonCode.WRONG_LANGUAGE_OR_TONE not in reasons_for(target)
    for target in MESSAGE_TARGETS:
        assert ReasonCode.DUPLICATE_OR_REDUNDANT not in reasons_for(target)
        assert ReasonCode.WRONG_SCOPE not in reasons_for(target)


def test_no_code_restates_a_grounding_warning() -> None:
    """spec §2.4: `unknown_paths` / `uncited_answer` are already on the wire."""
    for code in ReasonCode:
        assert "uncited" not in code.value
        assert "unknown_path" not in code.value


@pytest.mark.parametrize(
    ("target", "origin", "expected"),
    [
        (FeedbackTarget.MESSAGE, None, FeedbackFeature.ANSWER),
        (FeedbackTarget.CHECKLIST_MESSAGE, None, FeedbackFeature.REFINE_CHECKLIST),
        (FeedbackTarget.MOCK_DATA_MESSAGE, None, FeedbackFeature.REFINE_MOCK_DATA),
        (FeedbackTarget.CHECKLIST_CHANGE_SET, ChangeSetOrigin.GENERATION, FeedbackFeature.GENERATE_CHECKLIST),
        (FeedbackTarget.CHECKLIST_CHANGE_SET, ChangeSetOrigin.CHAT, FeedbackFeature.PROPOSE_CHECKLIST),
        (FeedbackTarget.MOCK_DATA_CHANGE_SET, ChangeSetOrigin.GENERATION, FeedbackFeature.GENERATE_MOCK_DATA),
        (FeedbackTarget.MOCK_DATA_CHANGE_SET, ChangeSetOrigin.CHAT, FeedbackFeature.PROPOSE_MOCK_DATA),
    ],
)
def test_feature_is_derived_from_the_target(
    target: FeedbackTarget, origin: str | None, expected: FeedbackFeature
) -> None:
    assert feature_for(target, origin=origin) == expected
