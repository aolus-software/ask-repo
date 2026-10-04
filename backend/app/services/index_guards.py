"""The guards every generation takes, in one place.

Checklist generation, mock-data generation and eval runs all read the index the same way
and so refuse the same states. They live here so a fourth caller cannot drift from the
first three.
"""

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.project import Project, ProjectStatus
from app.services import path_tree
from app.services.indexed_path import IndexedPathReader


def require_indexed(project: Project) -> None:
    """There has to be an index to enumerate.

    No embedding-model check, deliberately -- a scroll reads payloads, never vectors.
    """
    if project.status != ProjectStatus.READY.value or not project.embedding_collection:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.PROJECT_NOT_READY,
            "This project is not indexed yet. Wait for indexing to finish.",
        )


def require_stable_index(project: Project) -> None:
    """Refuse to generate while a reindex is in flight.

    A reindex keeps `status` at `ready` and raises `reindex_in_progress` instead
    (`ProjectRepository.claim`), so `require_indexed` passes throughout one. A
    generation started in that window reads the *current* generation, stamps
    `indexed_generation` with it, and then the reindex flips the pointer and deletes
    the points underneath it -- leaving a result that reports `stale` immediately
    after being produced, built from an index that no longer exists. Reporting it
    stale is right; the defect is having let the run start.

    Only the generation paths take this. Asking a question and refining by chat read
    the live generation and stamp nothing, and a reindex can run for twenty minutes --
    silencing Q&A for that long would cost far more than it saves.
    """
    if project.reindex_in_progress:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.PROJECT_NOT_READY,
            "This project is being re-indexed. Wait for that to finish, then try again.",
        )


async def require_path_indexed(
    indexed_paths: IndexedPathReader, project: Project, source_path: str
) -> None:
    """Refuse a `source_path` that matches nothing in the project's index.

    This is the point of phase 1.1 (`docs/PRD.md` §2.1). Without it a typo'd path
    returns `201` and the mistake surfaces later and silently, when the background
    generation cannot match anything under it -- tolerable for someone who already
    knows the tree, a wall for someone whose first contact with the repository is
    AskRepo itself.

    `400`, not `422`: the string is well-formed and passed schema validation, so
    this is "semantically invalid input" as `.claude/rules/response-api.md` defines
    it. `MODULE_PATH_NOT_INDEXED` rather than a new code, because generation
    already reports this exact condition under this exact name and a second code
    would make the frontend branch on two.

    **The generate-time check stays.** A reindex can drop the files a module was
    pointed at, so a path valid at creation can stop being indexed while the module
    lives on; removing the later check would turn that into a run that scrolls
    nothing and proposes an empty result.
    """
    paths = await indexed_paths.paths_for(project)
    if not path_tree.covers(paths, source_path):
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.MODULE_PATH_NOT_INDEXED,
            (
                f"Nothing under {source_path!r} is indexed for this project. "
                "Pick a path from the repository tree."
            ),
        )
