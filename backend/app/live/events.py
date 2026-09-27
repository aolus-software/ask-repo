"""The live-update event: what changed, never what it changed to.

A browser receives `kind`, `id` and `projectId` and refetches through REST, whose
`404`/`403` rules still decide what it sees. `recipients` exists only so the API can route a
notification to the people it was for; it never leaves the server.
"""

import uuid
from collections.abc import Iterable

from app.live.kinds import LiveKind
from app.schemas.base import ApiModel


class LiveEvent(ApiModel):
    """One change, as it travels between processes."""

    kind: LiveKind
    id: uuid.UUID
    project_id: uuid.UUID | None
    recipients: tuple[uuid.UUID, ...] = ()

    def to_bytes(self) -> bytes:
        """Serialize for Kafka."""
        return self.model_dump_json(by_alias=True).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "LiveEvent":
        """Parse what `to_bytes` wrote."""
        return cls.model_validate_json(raw)


def project_event(project_id: uuid.UUID) -> LiveEvent:
    """A project's status, lease, reindex flag or existence changed."""
    return LiveEvent(kind="project", id=project_id, project_id=project_id)


def checklist_module_event(module_id: uuid.UUID, project_id: uuid.UUID) -> LiveEvent:
    """A checklist module's generation status changed."""
    return LiveEvent(kind="checklist_module", id=module_id, project_id=project_id)


def mock_data_event(module_id: uuid.UUID, project_id: uuid.UUID) -> LiveEvent:
    """A mock dataset's status changed.

    `id` is the **checklist module** id: the frontend keys mock data by module
    (`keys.mockData.detail(moduleId)`), so that is the id it can invalidate.
    """
    return LiveEvent(kind="mock_data", id=module_id, project_id=project_id)


def notification_event(
    event_id: uuid.UUID, project_id: uuid.UUID, recipients: Iterable[uuid.UUID]
) -> LiveEvent:
    """A notification was written for these users."""
    return LiveEvent(
        kind="notification",
        id=event_id,
        project_id=project_id,
        recipients=tuple(sorted(recipients)),
    )
