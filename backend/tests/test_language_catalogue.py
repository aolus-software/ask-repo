"""The language catalogue is a wire contract: values are BCP-47 tags and never renamed."""

import re
from pathlib import Path

import pytest

from app.core.language import LANGUAGE_NAMES, Language, parse_language

FRONTEND_LANGUAGES = (
    Path(__file__).resolve().parents[2] / "frontend" / "lib" / "i18n" / "languages.ts"
)


def test_the_catalogue_is_exactly_the_seven_shipped_languages() -> None:
    assert [member.value for member in Language] == [
        "en",
        "id",
        "ja",
        "ms",
        "zh-HK",
        "zh-TW",
        "ko",
    ]


def test_every_value_fits_the_column() -> None:
    assert max(len(member.value) for member in Language) <= 8


def test_the_frontend_ships_the_same_languages() -> None:
    """A one-sided addition ships a language the other half refuses."""
    source = FRONTEND_LANGUAGES.read_text()
    declaration = re.search(r"LANGUAGES = \[(.*?)\] as const", source, re.DOTALL)
    assert declaration is not None, "LANGUAGES declaration not found in languages.ts"
    frontend = re.findall(r'"([^"]+)"', declaration.group(1))
    assert frontend == [member.value for member in Language]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(None, None), ("", None), ("ja", Language.JA), ("fr", None), ("zh-hk", None)],
)
def test_parse_language_treats_unset_and_unshipped_as_no_preference(
    stored: str | None, expected: Language | None
) -> None:
    assert parse_language(stored) is expected


def test_every_language_has_an_english_name() -> None:
    """Prompt constants name a language through this table, never through user input."""
    assert set(LANGUAGE_NAMES) == set(Language)
    assert all(name.isascii() and name.strip() for name in LANGUAGE_NAMES.values())
