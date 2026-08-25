"""Password policy.

The wordlist is injected rather than read from its real location, so these tests do
not depend on which list happens to be vendored. `docs/PRD.md:110` is the policy of
record.
"""

from pathlib import Path

import pytest

from app.config import get_settings
from app.core.passwords import (
    PasswordPolicyError,
    check_password,
    load_common_passwords,
)

COMMON = frozenset({"password123456", "letmeinplease"})


def test_a_good_password_passes() -> None:
    check_password("a-perfectly-fine-passphrase", min_length=12, max_bytes=72, common=COMMON)


def test_too_short_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="12 characters"):
        check_password("short", min_length=12, max_bytes=72, common=COMMON)


def test_a_password_at_the_minimum_is_accepted() -> None:
    check_password("a" * 12, min_length=12, max_bytes=72, common=COMMON)


def test_a_common_password_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="too common"):
        check_password("password123456", min_length=12, max_bytes=72, common=COMMON)


def test_the_common_check_ignores_case_and_surrounding_space() -> None:
    with pytest.raises(PasswordPolicyError, match="too common"):
        check_password("  PassWord123456 ", min_length=12, max_bytes=72, common=COMMON)


def test_over_the_byte_limit_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="72 bytes"):
        check_password("a" * 73, min_length=12, max_bytes=72, common=COMMON)


def test_the_byte_limit_counts_bytes_not_characters() -> None:
    """25 CJK characters are 75 UTF-8 bytes but only 25 characters."""
    with pytest.raises(PasswordPolicyError, match="72 bytes"):
        check_password("密" * 25, min_length=12, max_bytes=72, common=COMMON)


def test_the_error_message_names_bytes_so_a_user_is_not_counting_letters() -> None:
    with pytest.raises(PasswordPolicyError) as caught:
        check_password("密" * 25, min_length=12, max_bytes=72, common=COMMON)

    assert "bytes" in caught.value.reason


def test_loading_a_wordlist_normalises_and_skips_blanks(tmp_path: Path) -> None:
    listing = tmp_path / "words.txt"
    listing.write_text("Password1\n\n  hunter2  \n# a comment\n", encoding="utf-8")

    loaded = load_common_passwords(listing)

    assert loaded == frozenset({"password1", "hunter2"})


def test_loading_a_missing_wordlist_returns_empty_rather_than_raising(tmp_path: Path) -> None:
    """A missing data file must not stop the app booting; it degrades the check."""
    assert load_common_passwords(tmp_path / "absent.txt") == frozenset()


def test_every_vendored_entry_is_long_enough_to_ever_fire() -> None:
    """Entries below the minimum length are unreachable: check_password rejects on
    length first, so a short entry in the blocklist is dead weight that reads as
    protection without being any."""
    settings = get_settings()
    vendored = load_common_passwords(settings.common_password_list_path)

    assert vendored, "the vendored blocklist is empty"
    too_short = sorted(entry for entry in vendored if len(entry) < settings.password_min_length)
    assert not too_short, f"unreachable entries: {too_short}"
