"""The query behind `GET /projects/{id}/export`.

One model rather than sibling `Query(...)` parameters, for the reason
`ConversationListQuery` gives: FastAPI flattens a query model only while it is the
route's sole query parameter.
"""

import uuid
from enum import StrEnum

from pydantic import Field

from app.models.checklist import ChecklistItemKind, ChecklistItemSource, ChecklistItemStatus
from app.schemas.base import ApiModel


class ProjectExportPart(StrEnum):
    """What one export may carry. Values are a wire contract."""

    CHECKLIST = "checklist"
    MOCK_DATA = "mockData"


class ProjectExportQuery(ApiModel):
    """Which parts, which modules, and the checklist grid's filters.

    `module_ids` empty means every live module of the project. The four filters narrow
    the checklist part only: a mock data record has no status, source, kind or feature.
    """

    include: list[ProjectExportPart] = Field(min_length=1, max_length=2)
    module_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    feature: str | None = None
    status: ChecklistItemStatus | None = None
    source: ChecklistItemSource | None = None
    kind: ChecklistItemKind | None = None
