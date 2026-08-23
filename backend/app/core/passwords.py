"""Password policy: length bounds and a common-password blocklist.

Policy lives here, in a service-layer helper, rather than in Pydantic field
constraints, so every rejection carries the same error code (`WEAK_PASSWORD`) instead
of being split between 422 for length and 400 for the wordlist.

The list is checked in-process against a vendored file. No network call: `SECURITY.md`
requires the instance to stay off the public internet, which rules out an online
breach-corpus API.
"""

import logging
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


class PasswordPolicyError(ValueError):
    """A password failed policy. `reason` is safe to show a user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_common_passwords(path: Path) -> frozenset[str]:
    """Read a wordlist into a set, lowercased and stripped.

    A missing file degrades the check to a no-op rather than preventing boot: the
    length minimum is doing most of the work, and an unbootable API is worse than a
    weaker blocklist.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Common-password list not found at %s; the check is disabled", path)
        return frozenset()

    return frozenset(
        stripped.lower()
        for line in raw.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


@lru_cache
def get_common_passwords() -> frozenset[str]:
    """The vendored list, read once per process."""
    return load_common_passwords(get_settings().common_password_list_path)


def check_password(
    password: str, *, min_length: int, max_bytes: int, common: frozenset[str]
) -> None:
    """Raise `PasswordPolicyError` if the password fails policy, else return."""
    if len(password) < min_length:
        raise PasswordPolicyError(f"Password must be at least {min_length} characters.")

    encoded_length = len(password.encode("utf-8"))
    if encoded_length > max_bytes:
        raise PasswordPolicyError(
            f"Password must be at most {max_bytes} bytes; this one is {encoded_length}. "
            "Non-ASCII characters use more than one byte each."
        )

    if password.strip().lower() in common:
        raise PasswordPolicyError("Password is too common. Choose something less predictable.")
