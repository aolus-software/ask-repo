"""The language sentences: fixed constants, filled from `LANGUAGE_NAMES` (spec §4.1-§4.4)."""

import pytest

from app.core.language import LANGUAGE_NAMES, Language
from app.rag.prompts import (
    ANSWER_PROMPT,
    CLASSIFY_SYSTEM,
    CONTENT_LANGUAGE,
    GRADE_SYSTEM,
    HISTORY_ANSWER_PROMPT,
    REPLY_LANGUAGE,
    build_mock_data_generate_prompt,
    build_mock_data_propose_prompt,
    build_propose_prompt,
    build_reduce_prompt,
    render_content_language,
    render_reply_language,
)

# The grounding rules own these; a language sentence that touched them would argue with
# a guardrail. `[n]` itself is allowed: the slot tells the model to keep labels verbatim,
# which is what keeps `uncited_answer` working in every language (spec §4.6).
BANNED = ("cite", "citation", "evidence", "guess", "confiden")


def test_classify_asks_for_an_english_query_that_keeps_identifiers() -> None:
    assert "in English" in CLASSIFY_SYSTEM
    assert "exactly as typed" in CLASSIFY_SYSTEM


def test_grade_asks_for_an_english_better_query() -> None:
    assert "in English" in GRADE_SYSTEM


@pytest.mark.parametrize("language", list(Language))
def test_the_reply_slot_names_the_language_and_ends_a_paragraph(language: Language) -> None:
    rendered = render_reply_language(language)

    assert LANGUAGE_NAMES[language] in rendered
    assert rendered.endswith("\n\n")


def test_the_reply_slot_never_mentions_grounding() -> None:
    lowered = REPLY_LANGUAGE.lower()
    assert not [word for word in BANNED if word in lowered]


def test_the_reply_slot_precedes_the_grounding_rules() -> None:
    system = ANSWER_PROMPT.format_messages(
        context="",
        history=[],
        question="q",
        evidence_note="",
        reader_preferences="",
        reply_language=render_reply_language(Language.KO),
    )[0].content
    assert isinstance(system, str)

    assert system.index("Korean") < system.index("Grounding rules.")


def test_the_history_prompt_carries_the_slot() -> None:
    system = HISTORY_ANSWER_PROMPT.format_messages(
        history=[],
        question="q",
        reader_preferences="",
        reply_language=render_reply_language(Language.JA),
    )[0].content
    assert isinstance(system, str)

    assert "Japanese" in system


def test_the_content_sentence_forbids_translation_only_updates() -> None:
    assert "only to translate" in CONTENT_LANGUAGE
    assert LANGUAGE_NAMES[Language.ID] in render_content_language(Language.ID)


@pytest.mark.parametrize(
    "messages",
    [
        build_reduce_prompt(module_name="m", observations=[], existing=[], language=Language.MS),
        build_propose_prompt(module_name="m", answer="a", existing=[], language=Language.MS),
        build_mock_data_generate_prompt(
            module_name="m", source_text="", count=1, existing=[], language=Language.MS
        ),
        build_mock_data_propose_prompt(
            module_name="m", answer="a", existing=[], language=Language.MS
        ),
    ],
)
def test_every_shared_content_prompt_carries_the_language(messages: list) -> None:  # type: ignore[type-arg]  # BaseMessage list
    system = messages[0].content
    assert isinstance(system, str)
    assert "Malay" in system
