"""ORM models. Importing this package registers every table on `Base.metadata`,
which is what makes Alembic autogenerate able to see them."""

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.conversation import Conversation, FinishReason, Message, MessageRole
from app.models.project import Project, ProjectStatus
from app.models.qa_pair import QAPair, QASource, QAStatus
from app.models.refresh_token import RefreshToken, RevokedReason
from app.models.user import User

__all__ = [
    "Base",
    "Conversation",
    "FinishReason",
    "Message",
    "MessageRole",
    "Project",
    "ProjectStatus",
    "QAPair",
    "QASource",
    "QAStatus",
    "RefreshToken",
    "RevokedReason",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
]
