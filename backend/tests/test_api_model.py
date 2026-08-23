"""The wire contract: internal `snake_case`, external `camelCase`.

`.claude/rules/response-api.md` makes `ApiModel` mandatory for anything crossing the
HTTP boundary. These tests are what makes that rule enforceable rather than aspirational
— none of the routes shipped so far has a multi-word field, so without them a regression
in `ApiModel` would go unnoticed until the first `lastIndexedCommit` lands.
"""

from app.schemas.base import ApiModel


class _Sample(ApiModel):
    last_indexed_commit: str
    file_count: int
    status: str


def test_serializes_multi_word_fields_as_camel_case() -> None:
    dumped = _Sample(last_indexed_commit="abc123", file_count=7, status="ready").model_dump(
        by_alias=True
    )

    assert dumped == {"lastIndexedCommit": "abc123", "fileCount": 7, "status": "ready"}


def test_accepts_snake_case_when_constructed_internally() -> None:
    """Services build models with Python names; `populate_by_name` must allow it."""
    model = _Sample(last_indexed_commit="abc123", file_count=7, status="ready")

    assert model.last_indexed_commit == "abc123"


def test_accepts_camel_case_from_a_request_body() -> None:
    model = _Sample.model_validate(
        {"lastIndexedCommit": "abc123", "fileCount": 7, "status": "ready"}
    )

    assert model.last_indexed_commit == "abc123"
    assert model.file_count == 7


def test_single_word_fields_are_unchanged() -> None:
    """Guards against an alias generator that mangles already-correct names."""
    dumped = _Sample(last_indexed_commit="x", file_count=0, status="ready").model_dump(
        by_alias=True
    )

    assert "status" in dumped
