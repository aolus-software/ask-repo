"""Project request and response bodies.

Every model inherits `ApiModel`, so `repo_url` arrives and leaves as `repoUrl`.
`encrypted_pat` appears in no response model at all — not masked, not optional
(`docs/PRD.md` §4.1). The safest way not to leak a field is not to declare it.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.project import ProjectStatus
from app.schemas.base import ApiModel


class ProjectCreateRequest(ApiModel):
    """Create a project from a repository URL."""

    repo_url: str = Field(max_length=2048)
    branch: str = Field(default="main", max_length=255)
    # Write-only: accepted here, encrypted immediately, never echoed back.
    pat: str | None = Field(default=None, max_length=512)


class ProjectResponse(ApiModel):
    """A project as the API presents it."""

    id: uuid.UUID
    created_by: uuid.UUID
    name: str
    repo_url: str
    branch: str
    status: ProjectStatus
    error: str | None
    last_indexed_commit: str | None
    file_count: int | None
    chunk_count: int | None
    embedding_model: str | None
    reindex_in_progress: bool
    created_at: datetime
    updated_at: datetime


class IndexedPathEntry(ApiModel):
    """One row of the repository tree the checklist path picker browses.

    `file_count` is the number of indexed files in a directory's whole subtree, and is
    `null` on a file, where the number would mean nothing.
    """

    name: str
    path: str
    kind: Literal["dir", "file"]
    file_count: int | None


class IndexedPathsResponse(ApiModel):
    """One level of a project's indexed tree, or the matches for a search.

    `path` echoes the directory that was listed, and is empty on a search because the
    results span the tree (phase 1.1 design §2). `generation` names the index generation
    the entries came from, so a client can tell a tree that has been re-indexed under it
    from one that has not.
    """

    path: str
    generation: int
    entries: list[IndexedPathEntry]
    # Whether the search cap cut anything off. Reported rather than hidden: a picker
    # that silently shows the first N of many matches teaches the user that what they
    # are looking for is not indexed.
    truncated: bool


class ReindexResponse(ApiModel):
    """The outcome of a reindex trigger.

    Always returned with `202`. `enqueued` is false when a run was already in
    flight, so a caller can tell "I started one" from "one was already going"
    without an error branch (spec §2.2).
    """

    enqueued: bool
    project: ProjectResponse
