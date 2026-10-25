"""The "project is indexed" guard, in a leaf module.

It lives apart from `app/services/index_guards.py` because that module imports
`IndexedPathReader`, which needs this guard: importing it from there would cycle.
`app/core/access.py`, `IndexedPathReader` and the generation guards all call it, so
the condition and its message have one body.
"""

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.project import Project, ProjectStatus


def require_indexed(project: Project) -> None:
    """There has to be an index to enumerate.

    No embedding-model check, deliberately -- a scroll reads payloads, never vectors.
    `409` rather than an empty answer: a picker showing no files is indistinguishable
    from a repository that has none.
    """
    if project.status != ProjectStatus.READY.value or not project.embedding_collection:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.PROJECT_NOT_READY,
            "This project is not indexed yet. Wait for indexing to finish.",
        )
