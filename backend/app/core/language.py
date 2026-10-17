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
