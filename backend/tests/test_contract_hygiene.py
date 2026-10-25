"""Small contract fixes from the 2026-10 audit: declared responses, page-only lists,
stripped names, one source-path normaliser and one language fallback."""

import datetime
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.errors import AppError
from app.core.language import Language, language_or_default, shared_language
from app.models.eval import EvalMix
from app.schemas.checklist import ChecklistModuleCreateRequest, ChecklistModuleUpdateRequest
from app.schemas.eval import EvalSetCreate, EvalSetSummary
from app.schemas.feedback import FeedbackListQuery
from app.schemas.pagination import ListQuery, PageQuery
from app.services.checklist_export import filter_audit_details, require_within_cap
from app.services.path_tree import normalise_source_path

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _operation(app: FastAPI, method: str, path: str) -> dict[str, Any]:
    operation: dict[str, Any] = app.openapi()["paths"][path][method]
    return operation


def _query_names(operation: dict[str, Any]) -> set[str]:
    return {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}


def test_page_query_has_no_sort_or_search() -> None:
    assert set(PageQuery.model_fields) == {"page", "limit"}
    assert issubclass(ListQuery, PageQuery)
    assert issubclass(FeedbackListQuery, PageQuery)
    assert not issubclass(FeedbackListQuery, ListQuery)


@pytest.mark.parametrize(
    "path",
    [
        "/projects/{project_id}/eval-sets",
        "/eval-sets/{set_id}/runs",
        "/feedback",
        "/me/activity",
    ],
)
def test_fixed_order_lists_do_not_advertise_sort_or_search(app: FastAPI, path: str) -> None:
    names = _query_names(_operation(app, "get", path))
    assert {"page", "limit"} <= names
    assert not names & {"sort", "search", "sortDirection"}


def test_feedback_list_keeps_its_filters(app: FastAPI) -> None:
    names = _query_names(_operation(app, "get", "/feedback"))
    assert {"projectId", "feature", "rating", "reasonCode", "createdFrom", "createdTo"} <= names


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/eval-sets/{set_id}"),
        ("delete", "/eval-sets/{set_id}"),
        ("post", "/eval-sets/{set_id}/runs"),
        ("get", "/eval-runs/{run_id}"),
    ],
)
def test_eval_routes_declare_422(app: FastAPI, method: str, path: str) -> None:
    assert "422" in _operation(app, method, path)["responses"]


def test_membership_routes_declare_their_contract(app: FastAPI) -> None:
    base = "/projects/{project_id}/members"
    for method, path, with_conflict in (
        ("get", base, False),
        ("post", base, True),
        ("patch", base + "/{user_id}", True),
        ("delete", base + "/{user_id}", True),
    ):
        operation = _operation(app, method, path)
        assert operation.get("summary")
        declared = set(operation["responses"])
        assert {"401", "403", "404", "422"} <= declared
        assert ("409" in declared) is with_conflict


def test_source_path_routes_declare_400_and_503(app: FastAPI) -> None:
    for method, path in (
        ("post", "/checklist-modules"),
        ("patch", "/checklist-modules/{module_id}"),
        ("post", "/projects/{project_id}/eval-sets"),
    ):
        assert {"400", "503"} <= set(_operation(app, method, path)["responses"])
    assert "409" in _operation(app, "patch", "/checklist-modules/{module_id}")["responses"]


def test_delete_user_409_is_declared_as_either_shape(app: FastAPI) -> None:
    schema = _operation(app, "delete", "/users/{user_id}")["responses"]["409"]
    assert "anyOf" in schema["content"]["application/json"]["schema"]


def test_download_routes_declare_a_file_body(app: FastAPI) -> None:
    for method, path, media_types in (
        ("get", "/checklist-items/export", {XLSX}),
        ("get", "/projects/{project_id}/export", {XLSX, "application/zip"}),
        ("get", "/checklist-modules/{module_id}/mock-data/export.json", {"application/json"}),
        ("get", "/checklist-modules/{module_id}/mock-data/export.xlsx", {XLSX}),
    ):
        ok = _operation(app, method, path)["responses"]["200"]
        assert set(ok["content"]) == media_types
        assert "Content-Disposition" in ok["headers"]


def test_eval_set_create_describes_both_shapes(app: FastAPI) -> None:
    description = _operation(app, "post", "/projects/{project_id}/eval-sets")["description"]
    assert "sourceSetId" in description
    assert 'fields["request"]' in description


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_whitespace_only_names_are_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        EvalSetCreate(name=name, count=10, mix=EvalMix.BALANCED)
    with pytest.raises(ValidationError):
        ChecklistModuleCreateRequest(project_id=uuid.uuid4(), name=name, source_path="src")
    with pytest.raises(ValidationError):
        ChecklistModuleUpdateRequest(name=name)


def test_names_are_stored_stripped() -> None:
    assert EvalSetCreate(name="  Auth  ", count=10, mix=EvalMix.BALANCED).name == "Auth"
    update = ChecklistModuleUpdateRequest(name="  Billing ")
    assert update.name == "Billing"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("src", "src"), ("src/", "src"), ("/src", "src"), ("  /src/app/ ", "src/app"), ("/", "")],
)
def test_source_path_is_normalised_in_one_place(typed: str, expected: str) -> None:
    assert normalise_source_path(typed) == expected


def test_source_path_length_matches_the_checklist_column() -> None:
    EvalSetCreate(name="n", count=10, mix=EvalMix.BALANCED, source_path="a" * 512)
    with pytest.raises(ValidationError):
        EvalSetCreate(name="n", count=10, mix=EvalMix.BALANCED, source_path="a" * 513)


def test_an_eval_set_with_a_retired_language_reads_as_english() -> None:
    summary = EvalSetSummary.model_validate(
        {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "name": "n",
            "source_path": None,
            "requested_count": 10,
            "mix": "balanced",
            "language": "xx",
            "source_set_id": None,
            "status": "ready",
            "error": None,
            "pair_count": 0,
            "indexed_generation": None,
            "created_at": datetime.datetime.now(datetime.UTC),
        }
    )
    assert summary.language is Language.EN


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(None, Language.EN), ("", Language.EN), ("xx", Language.EN), ("ko", Language.KO)],
)
def test_language_or_default(stored: str | None, expected: Language) -> None:
    assert language_or_default(stored) is expected


def test_shared_language_still_falls_back_to_english() -> None:
    assert shared_language(["ko", "ko"]) is Language.KO
    assert shared_language(["ko", None]) is Language.EN
    assert shared_language([None]) is Language.EN
    assert shared_language(["ko", "ja"]) is Language.EN


def test_export_filter_details_name_only_what_the_query_set() -> None:
    project_id = uuid.uuid4()
    assert filter_audit_details(project_id=project_id, feature="Login", search="x") == {
        "projectId": str(project_id),
        "featureFilterApplied": "true",
        "search": "x",
    }
    assert filter_audit_details() == {}


def test_export_cap_refuses_only_past_the_cap() -> None:
    require_within_cap(5, 5, "never raised")
    with pytest.raises(AppError) as refused:
        require_within_cap(6, 5, "too many")
    assert refused.value.status_code == 409
    assert refused.value.detail["code"]  # type: ignore[index]  # AppError detail is a dict == ErrorCode.EXPORT_TOO_LARGE
