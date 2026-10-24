"""The languages AskRepo ships, as BCP-47 tags.

A wire contract like `ErrorCode`: add members, never rename them. Stored as plain
strings (`users.language`), not a Postgres ENUM, so a new member needs no migration.
`frontend/lib/i18n/languages.ts` holds the same list, and
`tests/test_language_catalogue.py` fails when the two differ.
"""

from collections.abc import Iterable
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


# Each language's English name. Used only to fill fixed prompt text, so a prompt never
# carries a user-supplied language string (spec §1.1).
LANGUAGE_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.ID: "Indonesian",
    Language.JA: "Japanese",
    Language.MS: "Malay",
    Language.ZH_HK: "Traditional Chinese (Hong Kong)",
    Language.ZH_TW: "Traditional Chinese (Taiwan)",
    Language.KO: "Korean",
}


# Tags that are not an exact match. Simplified Chinese (`zh`, `zh-CN`, `zh-Hans`,
# `zh-SG`) is deliberately absent, matching `frontend/lib/i18n/languages.ts`:
# answering a Simplified reader in Traditional is worse than answering in English.
_CHINESE_ALIASES: dict[str, Language] = {
    "zh-mo": Language.ZH_HK,
    "zh-hant": Language.ZH_TW,
    "zh-hant-hk": Language.ZH_HK,
    "zh-hant-mo": Language.ZH_HK,
    "zh-hant-tw": Language.ZH_TW,
}


def _match_tag(tag: str) -> Language | None:
    """One `Accept-Language` tag as a shipped language: exact, alias, then base."""
    lower = tag.lower()
    for language in Language:
        if language.value.lower() == lower:
            return language
    if lower in _CHINESE_ALIASES:
        return _CHINESE_ALIASES[lower]
    base = lower.split("-")[0]
    if base == "zh":
        return None
    return next((language for language in Language if language.value == base), None)


def _ranked_tags(header: str) -> list[str]:
    """`Accept-Language` tags, highest `q` first; ties keep header order."""
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        tag, *params = part.strip().split(";")
        tag = tag.strip()
        weight = 1.0
        for param in params:
            name, _, value = param.strip().partition("=")
            if name == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        if tag and tag != "*" and weight > 0:
            ranked.append((-weight, index, tag))
    return [tag for _, _, tag in sorted(ranked)]


def resolve_language(stored: str | None, accept_language: str | None) -> Language:
    """The one concrete language for a reader: their stored choice, then the request's
    `Accept-Language`, then English (spec §1.2).

    `NULL` means "never chose", so the header decides; a stored tag a later release no
    longer ships reads the same way. Mirrors `resolveLocale` in
    `frontend/lib/i18n/languages.ts`, so the interface and the answers agree.
    """
    chosen = parse_language(stored)
    if chosen is not None:
        return chosen
    for tag in _ranked_tags(accept_language or ""):
        match = _match_tag(tag)
        if match is not None:
            return match
    return Language.EN


def shared_language(values: Iterable[str | None]) -> Language:
    """The one language several projects share, or English when they do not.

    A document spanning projects -- a checklist export with no project filter -- has no
    single owner whose `content_language` could decide it.
    """
    distinct = {parse_language(value) for value in values}
    if len(distinct) == 1:
        (only,) = distinct
        return only or Language.EN
    return Language.EN
