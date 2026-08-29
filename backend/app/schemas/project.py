"""Project request and response bodies.

Every model inherits `ApiModel`, so `repo_url` arrives and leaves as `repoUrl`.
`encrypted_pat` appears in no response model at all — not masked, not optional
(`docs/PRD.md` §4.1). The safest way not to leak a field is not to declare it.
"""

import uuid
from datetime import datetime

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


class ReindexResponse(ApiModel):
    """The outcome of a reindex trigger.

    Always returned with `202`. `enqueued` is false when a run was already in
    flight, so a caller can tell "I started one" from "one was already going"
    without an error branch (spec §2.2).
    """

    enqueued: bool
    project: ProjectResponse
