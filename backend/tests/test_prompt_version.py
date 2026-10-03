"""`prompt_version` changes when any prompt string does, and only then."""

import types

from app.rag import prompts
from app.rag.prompt_version import PROMPT_VERSION, compute_prompt_version


def _fake(**constants: object) -> types.ModuleType:
    module = types.ModuleType("fake_prompts")
    for name, value in constants.items():
        setattr(module, name, value)
    return module


def test_the_live_version_is_twelve_hex_characters() -> None:
    assert len(PROMPT_VERSION) == 12
    int(PROMPT_VERSION, 16)
    assert compute_prompt_version(prompts) == PROMPT_VERSION


def test_editing_a_prompt_changes_the_version() -> None:
    before = compute_prompt_version(_fake(ANSWER_SYSTEM="Answer.", GRADE_SYSTEM="Grade."))
    after = compute_prompt_version(_fake(ANSWER_SYSTEM="Answer!", GRADE_SYSTEM="Grade."))
    assert before != after


def test_non_prompt_attributes_do_not_count() -> None:
    base = compute_prompt_version(_fake(ANSWER_SYSTEM="Answer."))
    noisy = compute_prompt_version(
        _fake(ANSWER_SYSTEM="Answer.", _private="x", helper="y", MAX_TOKENS=5)
    )
    assert base == noisy
