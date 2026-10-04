"""Nothing feedback-authored ever reaches a model (`.claude/rules/feedback.md`).

Structural, not a promise: the packages that build prompts cannot import feedback.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
MODEL_FACING = ("rag", "checklist", "mockdata", "eval")
_FEEDBACK_PACKAGES = "core|models|repositories|services|schemas"
# Catches both `from app.<pkg>.feedback import ...` / `import app.<pkg>.feedback`
# (the feedback module itself) and `from app.<pkg> import feedback` (the package,
# with feedback named as one of the imported members) for every package that
# carries a feedback module.
FORBIDDEN = re.compile(
    rf"^\s*(?:from\s+app\.(?:{_FEEDBACK_PACKAGES})\.feedback\s+import\b"
    rf"|import\s+app\.(?:{_FEEDBACK_PACKAGES})\.feedback\b"
    rf"|from\s+app\.(?:{_FEEDBACK_PACKAGES})\s+import\s+(?:[^\n]*\bfeedback\b))",
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


def test_forbidden_regex_matches_every_import_form() -> None:
    matching = [
        "from app.services.feedback import FeedbackService",
        "import app.services.feedback",
        "from app.core.feedback import FeedbackFeature",
        "from app.core import feedback",
        "from app.services import feedback",
        "from app.models import feedback",
        "from app.repositories import feedback",
        "from app.schemas import feedback",
    ]
    for line in matching:
        assert FORBIDDEN.search(line), line


def test_forbidden_regex_does_not_match_unrelated_imports() -> None:
    non_matching = [
        "from app.rag.prompt_version import PROMPT_VERSION",
        "from app.core import access",
        "import app.rag.prompts",
        "from app.services import project_service",
    ]
    for line in non_matching:
        assert not FORBIDDEN.search(line), line
