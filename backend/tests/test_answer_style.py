"""The answer-style value type: three optional dials, nothing else."""

import pytest

from app.rag.answer_style import AnswerDetail, AnswerFamiliarity, AnswerFormat, AnswerStyle


def test_a_default_style_is_empty() -> None:
    assert AnswerStyle().is_empty


def test_any_dial_makes_it_non_empty() -> None:
    assert not AnswerStyle(format=AnswerFormat.BULLETS).is_empty


def test_from_columns_parses_stored_strings() -> None:
    style = AnswerStyle.from_columns("brief", "expert", None)

    assert style == AnswerStyle(
        detail=AnswerDetail.BRIEF, familiarity=AnswerFamiliarity.EXPERT, format=None
    )


def test_from_columns_with_all_null_is_empty() -> None:
    assert AnswerStyle.from_columns(None, None, None).is_empty


def test_from_columns_rejects_an_unknown_value() -> None:
    with pytest.raises(ValueError):
        AnswerStyle.from_columns("verbose", None, None)


def test_only_non_default_values_exist() -> None:
    """The middle position of each dial is `NULL`, never a stored value."""
    assert {v.value for v in AnswerDetail} == {"brief", "thorough"}
    assert {v.value for v in AnswerFamiliarity} == {"new", "expert"}
    assert {v.value for v in AnswerFormat} == {"prose", "bullets"}
