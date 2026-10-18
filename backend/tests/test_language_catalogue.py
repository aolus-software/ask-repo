"""The language catalogue is a wire contract: values are BCP-47 tags and never renamed."""

import re
from pathlib import Path

from app.core.language import Language

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
