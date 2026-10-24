"""`resolve_language`: stored beats the header, the header beats English (spec §1.2)."""

import pytest

from app.core.language import Language, resolve_language, shared_language


def test_a_stored_language_wins_over_the_header() -> None:
    assert resolve_language("ko", "id-ID,id;q=0.9") is Language.KO


def test_no_stored_language_falls_to_the_header() -> None:
    assert resolve_language(None, "id-ID,id;q=0.9,en;q=0.8") is Language.ID


def test_an_unshipped_stored_tag_reads_as_no_preference() -> None:
    assert resolve_language("fr", "ja") is Language.JA


def test_nothing_usable_is_english() -> None:
    assert resolve_language(None, None) is Language.EN
    assert resolve_language(None, "fr-FR,de;q=0.5") is Language.EN
    assert resolve_language(None, "") is Language.EN


def test_quality_values_order_the_header() -> None:
    assert resolve_language(None, "en;q=0.2,ms;q=0.9") is Language.MS


def test_ties_keep_header_order() -> None:
    assert resolve_language(None, "ko,ja") is Language.KO


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("zh-TW", Language.ZH_TW),
        ("zh-hk", Language.ZH_HK),
        ("zh-MO", Language.ZH_HK),
        ("zh-Hant", Language.ZH_TW),
        ("zh-Hant-HK", Language.ZH_HK),
    ],
)
def test_traditional_chinese_aliases(header: str, expected: Language) -> None:
    assert resolve_language(None, header) is expected


@pytest.mark.parametrize("header", ["zh", "zh-CN", "zh-Hans", "zh-SG"])
def test_simplified_chinese_never_matches_traditional(header: str) -> None:
    """Mirrors `frontend/lib/i18n/languages.ts`: Traditional for a Simplified reader is worse."""
    assert resolve_language(None, header) is Language.EN


def test_wildcards_zero_weights_and_garbage_are_ignored() -> None:
    assert resolve_language(None, "*, id;q=0, ja;q=abc, ko;q=0.1") is Language.KO


def test_one_shared_language_is_used() -> None:
    assert shared_language(["id", "id"]) is Language.ID


def test_mixed_or_empty_languages_fall_back_to_english() -> None:
    assert shared_language(["id", "ja"]) is Language.EN
    assert shared_language([]) is Language.EN
    assert shared_language([None]) is Language.EN
