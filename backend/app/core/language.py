"""The languages AskRepo ships, as BCP-47 tags.

A wire contract like `ErrorCode`: add members, never rename them. Stored as plain
strings (`users.language`), not a Postgres ENUM, so a new member needs no migration.
`frontend/lib/i18n/languages.ts` holds the same list, and
`tests/test_language_catalogue.py` fails when the two differ.
"""

from enum import StrEnum


class Language(StrEnum):
    """One interface and answer language."""

    EN = "en"
    ID = "id"
    JA = "ja"
    MS = "ms"
    ZH_HK = "zh-HK"
    ZH_TW = "zh-TW"
    KO = "ko"


def parse_language(value: str | None) -> Language | None:
    """A stored language tag as a `Language`, or `None` when unset or not shipped.

    `users.language` is a plain string, so a row can hold a tag a later release no
    longer ships; that must read as "no preference" rather than fail the request.
    """
    try:
        return Language(value) if value else None
    except ValueError:
        return None
