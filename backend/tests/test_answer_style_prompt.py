"""The reader-preference slot: project-authored, before the rules, invisible when unset."""

from pathlib import Path

import pytest

from app.rag import prompts
from app.rag.answer_style import AnswerDetail, AnswerFamiliarity, AnswerFormat, AnswerStyle
from app.rag.prompts import (
    ANSWER_DETAIL_BRIEF,
    ANSWER_FAMILIARITY_EXPERT,
    ANSWER_FORMAT_BULLETS,
    ANSWER_PROMPT,
    ANSWER_SYSTEM,
    HISTORY_ANSWER_PROMPT,
    HISTORY_ANSWER_SYSTEM,
    READER_PREFERENCES_PREAMBLE,
    render_reader_preferences,
)

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"
FULL = AnswerStyle(
    detail=AnswerDetail.BRIEF,
    familiarity=AnswerFamiliarity.EXPERT,
    format=AnswerFormat.BULLETS,
)
FRAGMENT_PREFIXES = (
    "READER_PREFERENCES_",
    "ANSWER_DETAIL_",
    "ANSWER_FAMILIARITY_",
    "ANSWER_FORMAT_",
)
BANNED = ("cite", "citation", "evidence", "guess", "confiden", "[")


def test_no_style_renders_nothing() -> None:
    assert render_reader_preferences(None) == ""
    assert render_reader_preferences(AnswerStyle()) == ""


def test_an_unset_style_leaves_the_answer_prompt_byte_identical() -> None:
    before = (FIXTURES / "answer_system.txt").read_text()
    assert ANSWER_SYSTEM.replace("{reader_preferences}", "") == before


def test_an_unset_style_leaves_the_history_prompt_byte_identical() -> None:
    before = (FIXTURES / "history_answer_system.txt").read_text()
    assert HISTORY_ANSWER_SYSTEM.replace("{reader_preferences}", "") == before


def test_fragments_render_in_fixed_order_after_the_preamble() -> None:
    block = render_reader_preferences(FULL)

    assert block == (
        f"{READER_PREFERENCES_PREAMBLE}\n"
        f"- {ANSWER_DETAIL_BRIEF}\n"
        f"- {ANSWER_FAMILIARITY_EXPERT}\n"
        f"- {ANSWER_FORMAT_BULLETS}\n\n"
    )


def test_one_dial_renders_one_line() -> None:
    block = render_reader_preferences(AnswerStyle(format=AnswerFormat.BULLETS))

    assert block == f"{READER_PREFERENCES_PREAMBLE}\n- {ANSWER_FORMAT_BULLETS}\n\n"


def test_the_block_precedes_the_grounding_rules() -> None:
    system = ANSWER_PROMPT.format_messages(
        context="",
        history=[],
        question="q",
        evidence_note="",
        reader_preferences=render_reader_preferences(FULL),
    )[0].content
    assert isinstance(system, str)

    assert system.index(READER_PREFERENCES_PREAMBLE) < system.index("Grounding rules.")


def test_the_history_prompt_takes_the_block_before_its_routing_cases() -> None:
    system = HISTORY_ANSWER_PROMPT.format_messages(
        history=[], question="q", reader_preferences=render_reader_preferences(FULL)
    )[0].content
    assert isinstance(system, str)

    assert system.index(READER_PREFERENCES_PREAMBLE) < system.index(
        "The message is about this conversation"
    )


@pytest.mark.parametrize(
    "name",
    [n for n in vars(prompts) if n.isupper() and n.startswith(FRAGMENT_PREFIXES)],
)
def test_no_fragment_touches_a_grounding_rule(name: str) -> None:
    """A preference that mentions citing or evidence is arguing with a guardrail."""
    value = getattr(prompts, name).lower()
    assert not [word for word in BANNED if word in value], name


def test_every_dial_value_has_a_fragment() -> None:
    for style in (
        *(AnswerStyle(detail=v) for v in AnswerDetail),
        *(AnswerStyle(familiarity=v) for v in AnswerFamiliarity),
        *(AnswerStyle(format=v) for v in AnswerFormat),
    ):
        assert render_reader_preferences(style).count("\n- ") == 1
