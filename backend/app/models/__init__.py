"""ORM models. Importing this package registers every table on `Base.metadata`,
which is what makes Alembic autogenerate able to see them."""

from app.models.audit import AuditEvent
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
from app.models.membership import ProjectMembership, Role, RolePermission
from app.models.mock_data import (
    MockDataChangeSet,
    MockDataDataset,
    MockDataDatasetStatus,
    MockDataMessage,
    MockDataRecord,
)
from app.models.notification import Notification, NotificationEvent, NotificationPreference
from app.models.password_reset_token import PasswordResetToken
from app.models.project import Project, ProjectStatus
from app.models.refresh_token import RefreshToken, RevokedReason
from app.models.user import User

__all__ = [
    "AuditEvent",
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
    "Notification",
    "NotificationEvent",
    "NotificationPreference",
    "PasswordResetToken",
    "Project",
    "ProjectMembership",
    "ProjectStatus",
    "RefreshToken",
    "RevokedReason",
    "Role",
    "RolePermission",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
]
