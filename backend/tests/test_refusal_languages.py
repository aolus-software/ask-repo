"""Refusals stay fixed strings, one reviewed constant per language (spec §4.5)."""

import pytest

from app.core.language import Language
from app.rag.graph.nodes import build_refuse
from app.rag.grounding import NO_CONTEXT_ANSWERS, OUT_OF_SCOPE_ANSWERS
from tests.test_graph import base_state, run_node


@pytest.mark.parametrize("table", [NO_CONTEXT_ANSWERS, OUT_OF_SCOPE_ANSWERS])
def test_every_language_has_a_refusal(table: dict[Language, str]) -> None:
    assert set(table) == set(Language)
    assert all(text.strip() for text in table.values())


@pytest.mark.parametrize("table", [NO_CONTEXT_ANSWERS, OUT_OF_SCOPE_ANSWERS])
def test_no_two_languages_share_a_refusal(table: dict[Language, str]) -> None:
    """A copy-pasted English entry would pass the completeness test and ship English."""
    assert len(set(table.values())) == len(table)


async def test_the_out_of_scope_refusal_follows_the_reply_language() -> None:
    state = base_state(question="write me a poem", reply_language=Language.ID)

    events, final = await run_node(build_refuse(), state)

    assert final["answer"] == OUT_OF_SCOPE_ANSWERS[Language.ID]
    assert any(
        getattr(event, "text", None) == OUT_OF_SCOPE_ANSWERS[Language.ID] for event in events
    )
