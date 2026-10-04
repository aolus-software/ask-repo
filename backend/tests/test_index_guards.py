"""The guards every generation takes, in one place."""

from typing import cast

import pytest

from app.core.errors import AppError, ErrorCode
from app.models.project import Project
from app.services.index_guards import require_indexed, require_path_indexed, require_stable_index
from app.services.indexed_path import IndexedPathReader


def _project(**fields: object) -> Project:
    project = Project()
    project.status = "ready"
    project.embedding_collection = "c"
    project.reindex_in_progress = False
    for name, value in fields.items():
        setattr(project, name, value)
    return project


class _Reader:
    async def paths_for(self, project: Project) -> tuple[str, ...]:
        return ("src/app.py",)


def test_an_unindexed_project_is_not_ready() -> None:
    for project in (_project(status="pending"), _project(embedding_collection=None)):
        with pytest.raises(AppError) as raised:
            require_indexed(project)
        assert raised.value.status_code == 409
        assert raised.value.code == ErrorCode.PROJECT_NOT_READY


def test_a_ready_project_passes() -> None:
    require_indexed(_project())
    require_stable_index(_project())


def test_a_reindex_in_flight_is_refused() -> None:
    with pytest.raises(AppError) as raised:
        require_stable_index(_project(reindex_in_progress=True))
    assert raised.value.status_code == 409
    assert raised.value.code == ErrorCode.PROJECT_NOT_READY
    assert raised.value.message.endswith("then try again.")


async def test_a_path_nothing_indexed_covers_is_refused() -> None:
    reader = cast(IndexedPathReader, _Reader())
    await require_path_indexed(reader, _project(), "src")
    with pytest.raises(AppError) as raised:
        await require_path_indexed(reader, _project(), "docs")
    assert raised.value.status_code == 400
    assert raised.value.code == ErrorCode.MODULE_PATH_NOT_INDEXED
