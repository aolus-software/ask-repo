"""The feedback catalogue: what can be judged, why, and which feature produced it.

A wire contract, like `ErrorCode`: add members, never rename them. Reason codes map
onto parts of the system an administrator can change — retrieval, the relevance
floor, the prompt, the grader — which is what makes a thumbs-down actionable.

There is deliberately no code restating `app/rag/grounding.py`'s warnings: those are
already computed and on the wire, and feedback exists for what they cannot see.
"""

from enum import StrEnum

from app.models.checklist import ChangeSetOrigin

NOTE_MAX_LENGTH = 500


class FeedbackTarget(StrEnum):
    """What a vote points at. One value per table that holds model output."""

    MESSAGE = "message"
    CHECKLIST_MESSAGE = "checklist_message"
    MOCK_DATA_MESSAGE = "mock_data_message"
    CHECKLIST_CHANGE_SET = "checklist_change_set"
    MOCK_DATA_CHANGE_SET = "mock_data_change_set"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


class FeedbackFeature(StrEnum):
    """Which feature produced the judged output — the dimension feedback aggregates on."""

    ANSWER = "answer"
    REFINE_CHECKLIST = "refine_checklist"
    REFINE_MOCK_DATA = "refine_mock_data"
    GENERATE_CHECKLIST = "generate_checklist"
    PROPOSE_CHECKLIST = "propose_checklist"
    GENERATE_MOCK_DATA = "generate_mock_data"
    PROPOSE_MOCK_DATA = "propose_mock_data"


class ReasonCode(StrEnum):
    WRONG_FILE_CITED = "wrong_file_cited"
    MISSED_SOMETHING = "missed_something"
    INVENTED_SOMETHING = "invented_something"
    RIGHT_BUT_UNUSABLE = "right_but_unusable"
    WRONG_LANGUAGE_OR_TONE = "wrong_language_or_tone"
    DUPLICATE_OR_REDUNDANT = "duplicate_or_redundant"
    WRONG_SCOPE = "wrong_scope"
    OTHER = "other"


MESSAGE_TARGETS = frozenset(
    {FeedbackTarget.MESSAGE, FeedbackTarget.CHECKLIST_MESSAGE, FeedbackTarget.MOCK_DATA_MESSAGE}
)
CHANGE_SET_TARGETS = frozenset(
    {FeedbackTarget.CHECKLIST_CHANGE_SET, FeedbackTarget.MOCK_DATA_CHANGE_SET}
)

_MESSAGE_REASONS = frozenset(
    {
        ReasonCode.WRONG_FILE_CITED,
        ReasonCode.MISSED_SOMETHING,
        ReasonCode.INVENTED_SOMETHING,
        ReasonCode.RIGHT_BUT_UNUSABLE,
        ReasonCode.WRONG_LANGUAGE_OR_TONE,
        ReasonCode.OTHER,
    }
)
_CHANGE_SET_REASONS = frozenset(
    {
        ReasonCode.MISSED_SOMETHING,
        ReasonCode.INVENTED_SOMETHING,
        ReasonCode.DUPLICATE_OR_REDUNDANT,
        ReasonCode.WRONG_SCOPE,
        ReasonCode.RIGHT_BUT_UNUSABLE,
        ReasonCode.OTHER,
    }
)


def reasons_for(target: FeedbackTarget) -> frozenset[ReasonCode]:
    """The reason codes a vote on this kind of target may carry."""
    return _MESSAGE_REASONS if target in MESSAGE_TARGETS else _CHANGE_SET_REASONS


_MESSAGE_FEATURES = {
    FeedbackTarget.MESSAGE: FeedbackFeature.ANSWER,
    FeedbackTarget.CHECKLIST_MESSAGE: FeedbackFeature.REFINE_CHECKLIST,
    FeedbackTarget.MOCK_DATA_MESSAGE: FeedbackFeature.REFINE_MOCK_DATA,
}
_CHANGE_SET_FEATURES = {
    (
        FeedbackTarget.CHECKLIST_CHANGE_SET,
        ChangeSetOrigin.GENERATION,
    ): FeedbackFeature.GENERATE_CHECKLIST,
    (FeedbackTarget.CHECKLIST_CHANGE_SET, ChangeSetOrigin.CHAT): FeedbackFeature.PROPOSE_CHECKLIST,
    (
        FeedbackTarget.MOCK_DATA_CHANGE_SET,
        ChangeSetOrigin.GENERATION,
    ): FeedbackFeature.GENERATE_MOCK_DATA,
    (FeedbackTarget.MOCK_DATA_CHANGE_SET, ChangeSetOrigin.CHAT): FeedbackFeature.PROPOSE_MOCK_DATA,
}


def feature_for(target: FeedbackTarget, *, origin: str | None) -> FeedbackFeature:
    """The feature that produced a target. A change set needs its `origin`."""
    if target in MESSAGE_TARGETS:
        return _MESSAGE_FEATURES[target]
    if origin is None:
        raise ValueError(f"change-set feedback target {target} requires an origin")
    return _CHANGE_SET_FEATURES[(target, ChangeSetOrigin(origin))]
