"""Nothing feedback-authored ever reaches a model (`.claude/rules/feedback.md`).

Structural, not a promise: the packages that build prompts cannot import feedback.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
MODEL_FACING = ("rag", "checklist", "mockdata")
FORBIDDEN = re.compile(
    r"^\s*(from|import)\s+app\.(models\.feedback|repositories\.feedback|services\.feedback|schemas\.feedback|core\.feedback)\b",
    re.MULTILINE,
)


def test_no_model_facing_module_imports_feedback() -> None:
    offenders = [
        str(path.relative_to(APP))
        for package in MODEL_FACING
        for path in (APP / package).rglob("*.py")
        if FORBIDDEN.search(path.read_text())
    ]
    assert offenders == []
