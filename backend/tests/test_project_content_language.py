"""A project's content language: set at creation, changed by `PATCH`, gated and audited."""

import uuid
from typing import Any, cast

import httpx

from tests.conftest import AuditRows


async def _create(client: httpx.AsyncClient, **extra: str) -> str:
    response = await client.post(
        "/projects",
        json={"repoUrl": "https://github.com/o/r.git", "branch": "main", **extra},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_a_new_project_defaults_to_english(client_for_user_a: Any) -> None:
    project_id = await _create(client_for_user_a)

    response = await client_for_user_a.get(f"/projects/{project_id}")

    assert response.json()["contentLanguage"] == "en"


async def test_creation_accepts_a_content_language(client_for_user_a: Any) -> None:
    project_id = await _create(client_for_user_a, contentLanguage="id")

    response = await client_for_user_a.get(f"/projects/{project_id}")

    assert response.json()["contentLanguage"] == "id"


async def test_creation_refuses_an_unshipped_language(client_for_user_a: Any) -> None:
    response = await client_for_user_a.post(
        "/projects",
        json={"repoUrl": "https://github.com/o/r.git", "contentLanguage": "fr"},
    )

    assert response.status_code == 422


async def test_an_owner_changes_the_content_language(client_for_user_a: Any) -> None:
    project_id = await _create(client_for_user_a)

    response = await client_for_user_a.patch(
        f"/projects/{project_id}", json={"contentLanguage": "ja"}
    )

    assert response.status_code == 200
    assert response.json()["contentLanguage"] == "ja"
    assert response.json()["role"] == "owner"


async def test_a_viewer_is_refused_with_403(
    client_for_user_a: Any, client_for_user_b: Any, grant_membership: Any
) -> None:
    project_id = await _create(client_for_user_a)
    viewer_id = (await client_for_user_b.get("/auth/me")).json()["id"]
    await grant_membership(uuid.UUID(viewer_id), uuid.UUID(project_id), role="viewer")

    response = await client_for_user_b.patch(
        f"/projects/{project_id}", json={"contentLanguage": "ja"}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


async def test_a_non_member_is_told_it_does_not_exist(
    client_for_user_a: Any, client_for_user_b: Any
) -> None:
    project_id = await _create(client_for_user_a)

    response = await client_for_user_b.patch(
        f"/projects/{project_id}", json={"contentLanguage": "ja"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


async def test_an_unshipped_language_is_422(client_for_user_a: Any) -> None:
    project_id = await _create(client_for_user_a)

    response = await client_for_user_a.patch(
        f"/projects/{project_id}", json={"contentLanguage": "fr"}
    )

    assert response.status_code == 422


async def test_the_body_carries_nothing_but_the_language(client_for_user_a: Any) -> None:
    """Widening the body is a separate change (spec §1.3); `name` must not be writable here."""
    project_id = await _create(client_for_user_a)

    response = await client_for_user_a.patch(
        f"/projects/{project_id}", json={"contentLanguage": "ko", "name": "renamed"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "r"


async def test_the_change_is_audited_after_the_commit(
    client_for_user_a: Any, audit_rows: AuditRows
) -> None:
    project_id = await _create(client_for_user_a)

    await client_for_user_a.patch(f"/projects/{project_id}", json={"contentLanguage": "ms"})

    [event] = await audit_rows("project.updated")
    assert event.target_id == uuid.UUID(project_id)
    assert event.details["changed"] == {"contentLanguage": {"before": "en", "after": "ms"}}


async def test_an_unchanged_language_records_nothing(
    client_for_user_a: Any, audit_rows: AuditRows
) -> None:
    project_id = await _create(client_for_user_a)

    await client_for_user_a.patch(f"/projects/{project_id}", json={"contentLanguage": "en"})

    assert await audit_rows("project.updated") == []


async def test_creation_records_the_language(client_for_user_a: Any, audit_rows: AuditRows) -> None:
    await _create(client_for_user_a, contentLanguage="zh-TW")

    [event] = await audit_rows("project.created")
    changed = cast("dict[str, Any]", event.details["changed"])
    assert changed["contentLanguage"] == {"before": None, "after": "zh-TW"}


def test_an_unshipped_stored_language_reads_as_english() -> None:
    """`projects.content_language` is a plain string; a tag a later release drops must
    not 500 every read of the project."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.models.project import ProjectStatus
    from app.schemas.project import ProjectResponse

    row = SimpleNamespace(
        id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="r",
        repo_url="https://github.com/o/r.git",
        branch="main",
        status=ProjectStatus.READY,
        error=None,
        last_indexed_commit=None,
        file_count=None,
        chunk_count=None,
        embedding_model=None,
        reindex_in_progress=False,
        content_language="xx",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert ProjectResponse.model_validate(row, from_attributes=True).content_language == "en"
