"""Every ErrorCode the API can send has a translation key in the frontend catalogue.

The frontend translates by `detail.code` (spec §2.4). A code with no entry falls back
to the backend's English message, which works and is half-translated -- exactly the
silent gap this test exists to make loud.
"""

import json
from pathlib import Path

from app.core.errors import ErrorCode

EN_ERRORS = Path(__file__).resolve().parents[2] / "frontend" / "messages" / "en" / "errors.json"


def test_every_error_code_has_an_english_entry() -> None:
    errors = json.loads(EN_ERRORS.read_text())
    missing = sorted(code.value for code in ErrorCode if code.value not in errors)
    assert missing == []
