"""`CLAUDE.md`: one error shape, and the declared carve-outs from it.

`AppError`'s `extra` widens `detail` past `code` and `message`. That is allowed where
the extra field is what makes the error actionable, but it is invisible on the wire
contract unless the route declares a model for that status -- `/docs` and every
generated client would otherwise describe a body the route does not return.

Nothing about that fails loudly. A route that widens its body and leaves the generic
`ERROR_RESPONSES[...]` entry in place still returns 200s and 409s exactly as before,
and the only symptom is a client written against the documented shape that cannot see
the field it needs. So the obligation is a test rather than a sentence in a docstring.
"""

import ast
from pathlib import Path

from app.main import create_app

APP = Path(__file__).resolve().parent.parent / "app"

# Every module that raises a widened error body. Each entry owes a declared response
# model on the route that surfaces it -- see the OpenAPI test below.
ALLOWED_WIDENED_ERRORS = {
    APP / "services" / "user.py",  # 409 LAST_OWNER -> LastOwnerErrorResponse
}


def _python_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def _widens_an_error(source: str) -> bool:
    """True if this module constructs an `AppError` with `extra=`.

    Parsed rather than grepped: `extra=` is also `logging`'s own keyword, and it is
    used all over the codebase for structured log fields. A text search would report
    every one of them.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name == "AppError" and any(word.arg == "extra" for word in node.keywords):
            return True
    return False


def test_only_declared_modules_widen_an_error_body() -> None:
    """A new `extra=` call site is a deliberate change to the wire contract."""
    offenders = [
        path.relative_to(APP)
        for path in _python_files()
        if path not in ALLOWED_WIDENED_ERRORS and _widens_an_error(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"error body widened without declaring a response model: {offenders}. "
        "Declare a model for that status and add the module above."
    )


def test_the_last_owner_refusal_documents_the_projects_it_names() -> None:
    """The generic 409 body would document `{code, message}` and omit `projects`,
    which is the field that tells an admin which projects to hand over first."""
    responses = create_app().openapi()["paths"]["/users/{user_id}"]["delete"]["responses"]

    reference = responses["409"]["content"]["application/json"]["schema"]["$ref"]

    assert reference.endswith("/LastOwnerErrorResponse")


def test_the_widened_body_still_carries_the_common_two_fields() -> None:
    """A carve-out extends the shape; it never replaces it. A client that only knows
    `code` and `message` must still parse this error."""
    schemas = create_app().openapi()["components"]["schemas"]

    assert set(schemas["LastOwnerErrorBody"]["properties"]) == {
        "code",
        "message",
        "projects",
    }
