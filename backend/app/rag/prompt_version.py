"""Version stamps for the prompts, one per feature, derived rather than maintained.

Every prompt in the application lives in `app/rag/prompts.py`. A version is a hash of
the upper-case string constants a feature's calls actually send, so an edit moves the
version of exactly the features that prompt reaches, and nobody has to remember to
bump anything. That is what lets feedback, the call log and the eval harness compare
"before this prompt change" against "after" for the feature that changed — and only
that one. A single hash over the whole module, as this was until 2026-10-17, moved the
version on Ask answers when only the eval judge's prompt changed.

`CALL_PROMPTS` is the one table. A new prompt constant must join a feature's set:
`tests/test_prompt_version.py` fails on a constant no feature claims, because a prompt
outside every set would change model output without moving any version.

This module imports nothing from feedback, and must not: nothing feedback-authored
reaches a model (`.claude/rules/feedback.md`).
"""

import hashlib
from collections.abc import Iterable
from types import ModuleType

from app.observability.features import CallFeature
from app.rag import prompts

# The reader-preference sentences render into both answer prompts' `{reader_preferences}`.
_READER_PREFERENCES = frozenset(
    {
        "READER_PREFERENCES_PREAMBLE",
        "ANSWER_DETAIL_BRIEF",
        "ANSWER_DETAIL_THOROUGH",
        "ANSWER_FAMILIARITY_NEW",
        "ANSWER_FAMILIARITY_EXPERT",
        "ANSWER_FORMAT_PROSE",
        "ANSWER_FORMAT_BULLETS",
    }
)

CALL_PROMPTS: dict[CallFeature, frozenset[str]] = {
    CallFeature.CLASSIFY: frozenset({"CLASSIFY_SYSTEM"}),
    CallFeature.GRADE: frozenset({"GRADE_SYSTEM"}),
    CallFeature.ANSWER: frozenset({"ANSWER_SYSTEM", "REPLY_LANGUAGE"}) | _READER_PREFERENCES,
    CallFeature.HISTORY_ANSWER: frozenset({"HISTORY_ANSWER_SYSTEM", "REPLY_LANGUAGE"})
    | _READER_PREFERENCES,
    CallFeature.PROPOSE_CHECKLIST: frozenset(
        {"PROPOSE_SYSTEM", "TESTER_LANGUAGE", "CONTENT_LANGUAGE"}
    ),
    CallFeature.PROPOSE_MOCK_DATA: frozenset({"MOCK_DATA_PROPOSE_SYSTEM", "CONTENT_LANGUAGE"}),
    CallFeature.MAP: frozenset({"MAP_FILE_SYSTEM"}),
    CallFeature.REDUCE: frozenset({"REDUCE_SYSTEM", "TESTER_LANGUAGE", "CONTENT_LANGUAGE"}),
    CallFeature.GENERATE_MOCK_DATA: frozenset({"MOCK_DATA_GENERATE_SYSTEM", "CONTENT_LANGUAGE"}),
    CallFeature.EVAL_GENERATE: frozenset({"EVAL_PAIR_SYSTEM"}),
    CallFeature.EVAL_JUDGE: frozenset({"EVAL_JUDGE_SYSTEM"}),
    CallFeature.EVAL_TRANSLATE: frozenset({"EVAL_TRANSLATE_SYSTEM"}),
    # Neither sends a prompt from `prompts.py`: the probe's fixed message lives in
    # `app/rag/capability.py`, and an untagged call is by definition unattributed.
    CallFeature.CAPABILITY_PROBE: frozenset(),
    CallFeature.UNTAGGED: frozenset(),
}

# Every call a question can make: what an Ask answer, and an eval run's answers, depend on.
ANSWER_GRAPH: tuple[CallFeature, ...] = (
    CallFeature.CLASSIFY,
    CallFeature.GRADE,
    CallFeature.ANSWER,
    CallFeature.HISTORY_ANSWER,
)


def prompt_constants(module: ModuleType) -> dict[str, str]:
    """`module`'s prompt constants: public, upper-case, string-valued."""
    return {
        name: value
        for name, value in vars(module).items()
        if name.isupper() and not name.startswith("_") and isinstance(value, str)
    }


def compute_prompt_version(module: ModuleType, names: Iterable[str] | None = None) -> str:
    """The first 12 hex characters of a SHA-256 over `names` in `module`, or over every
    prompt constant when `names` is omitted. A name `module` lacks raises `KeyError`, so
    a renamed prompt cannot silently fall out of its feature's version."""
    constants = prompt_constants(module)
    selected = sorted(constants) if names is None else sorted(set(names))
    parts = [f"{name}={constants[name]}" for name in selected]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


def version_for(features: Iterable[CallFeature]) -> str:
    """The version of everything the given call features send, as one hash."""
    names: set[str] = set()
    for feature in features:
        names |= CALL_PROMPTS[feature]
    return compute_prompt_version(prompts, names)


CALL_PROMPT_VERSIONS: dict[CallFeature, str] = {
    feature: version_for((feature,)) for feature in CallFeature
}

# An Ask answer's version, and an eval run's answer version.
ANSWER_PROMPT_VERSION = version_for(ANSWER_GRAPH)

# What an eval run's verdicts depend on, recorded beside the answer version.
JUDGE_PROMPT_VERSION = CALL_PROMPT_VERSIONS[CallFeature.EVAL_JUDGE]
