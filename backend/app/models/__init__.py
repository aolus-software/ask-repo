"""ORM models. Importing this package registers every table on `Base.metadata`,
which is what makes Alembic autogenerate able to see them."""

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistItem,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistMessage,
    ChecklistModule,
    ChecklistModuleStatus,
)
from app.models.conversation import Conversation, FinishReason, Message, MessageRole
from app.models.mock_data import (
    MockDataChangeSet,
    MockDataDataset,
    MockDataDatasetStatus,
    MockDataMessage,
    MockDataRecord,
)
from app.models.project import Project, ProjectStatus
from app.models.refresh_token import RefreshToken, RevokedReason
from app.models.user import User

__all__ = [
    "Base",
    "ChangeSetOrigin",
    "ChangeSetStatus",
    "ChecklistChangeSet",
    "ChecklistItem",
    "ChecklistItemSource",
    "ChecklistItemStatus",
    "ChecklistMessage",
    "ChecklistModule",
    "ChecklistModuleStatus",
    "Conversation",
    "FinishReason",
    "Message",
    "MessageRole",
    "MockDataChangeSet",
    "MockDataDataset",
    "MockDataDatasetStatus",
    "MockDataMessage",
    "MockDataRecord",
    "Project",
    "ProjectStatus",
    "RefreshToken",
    "RevokedReason",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
]
