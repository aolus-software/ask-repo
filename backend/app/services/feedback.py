"""Record, revise and withdraw a vote on model output; read the aggregate.

**No audit event, and that is a decision:** the audit trail's seventh exemption
(`.claude/rules/audit-trail.md`). A vote describes no change to a shared resource,
this table is its own record, and its write rate tracks attention.

**Every write-side miss is one answer.** A nonexistent id, a user-role message,
someone else's conversation and a module outside scope all raise the same
`404 FEEDBACK_TARGET_NOT_FOUND`, so this route cannot tell a caller that an id exists.
Visibility re-uses exactly the checks that already gate reading each subject.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.feedback import FeedbackFeature, FeedbackTarget, feature_for, reasons_for
from app.core.middleware import AuthenticatedUser
from app.models.conversation import MessageRole
from app.rag.prompt_version import PROMPT_VERSION
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_message import ChecklistMessageRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.conversation import ConversationRepository, MessageRepository
from app.repositories.feedback import FeedbackFilters, FeedbackRepository
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_message import MockDataMessageRepository
from app.schemas.feedback import (
    FeatureVotes,
    FeedbackAdminRead,
    FeedbackFilterFields,
    FeedbackListQuery,
    FeedbackRead,
    FeedbackSummary,
    FeedbackSummaryQuery,
    FeedbackWrite,
    MyFeedback,
    PromptVersionVotes,
    ReasonCount,
)
from app.schemas.pagination import PaginatedResponse


@dataclass(frozen=True, slots=True)
class _Subject:
    project_id: uuid.UUID
    feature: FeedbackFeature


def _not_found() -> AppError:
    return AppError(
        status.HTTP_404_NOT_FOUND, ErrorCode.FEEDBACK_TARGET_NOT_FOUND, "Nothing to rate here."
    )


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._feedback = FeedbackRepository(session)

    async def put(
        self,
        target_type: FeedbackTarget,
        target_id: uuid.UUID,
        payload: FeedbackWrite,
        *,
        actor: AuthenticatedUser,
    ) -> FeedbackRead:
        """Record or revise the caller's vote."""
        subject = await self._resolve(target_type, target_id, actor)
        allowed = reasons_for(target_type)
        if not_allowed := [code for code in payload.reason_codes if code not in allowed]:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.FEEDBACK_REASON_NOT_APPLICABLE,
                f"Not a reason for this kind of output: {', '.join(not_allowed)}.",
            )
        row = await self._feedback.upsert(
            user_id=actor.id,
            project_id=subject.project_id,
            target_type=target_type.value,
            target_id=target_id,
            feature=subject.feature.value,
            rating=payload.rating.value,
            reason_codes=[code.value for code in dict.fromkeys(payload.reason_codes)],
            note=(payload.note or "").strip() or None,
            prompt_version=PROMPT_VERSION,
        )
        response = FeedbackRead(
            target_type=target_type,
            target_id=target_id,
            rating=row.rating,
            reason_codes=row.reason_codes,
            note=row.note,
            updated_at=row.updated_at,
        )
        await self.session.commit()
        return response

    async def withdraw(
        self, target_type: FeedbackTarget, target_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> None:
        """Remove the caller's vote. Idempotent: there being none is not an error.

        Only ever deletes the caller's own row, so there is nothing to check first —
        and checking would re-open the existence oracle `put` closes.
        """
        await self._feedback.delete_mine(
            user_id=actor.id, target_type=target_type.value, target_id=target_id
        )
        await self.session.commit()

    async def list_for_admin(
        self, query: FeedbackListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[FeedbackAdminRead]:
        """One page of votes with their notes, newest first."""
        rows, total = await self._feedback.page(
            limit=query.limit,
            offset=(query.page - 1) * query.limit,
            filters=self._filters(query, actor),
        )
        items = [
            FeedbackAdminRead(
                id=row.id,
                project_id=row.project_id,
                project_name=project_name,
                target_type=row.target_type,
                feature=row.feature,
                rating=row.rating,
                reason_codes=row.reason_codes,
                note=row.note,
                prompt_version=row.prompt_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row, project_name in rows
        ]
        return PaginatedResponse[FeedbackAdminRead].build(
            items, page=query.page, limit=query.limit, total_count=total
        )

    async def summary(
        self, query: FeedbackSummaryQuery, *, actor: AuthenticatedUser
    ) -> FeedbackSummary:
        """Counts per feature, per reason, and per prompt version."""
        filters = self._filters(query, actor)
        by_feature: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
        for feature, rating, count in await self._feedback.counts_by_feature(filters):
            by_feature[feature][rating] = count
        by_version: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
        for version, rating, count in await self._feedback.counts_by_prompt_version(filters):
            by_version[version][rating] = count
        reasons = await self._feedback.counts_by_reason(filters)
        return FeedbackSummary(
            by_feature=[
                FeatureVotes(feature=feature, **votes)
                for feature, votes in sorted(by_feature.items())
            ],
            by_reason=[
                ReasonCount(feature=feature, reason_code=reason, count=count)
                for feature, reason, count in sorted(reasons, key=lambda r: (r[0], -r[2], r[1]))
            ],
            by_prompt_version=[
                PromptVersionVotes(prompt_version=version, **votes)
                for version, votes in sorted(by_version.items())
            ],
        )

    @staticmethod
    def _filters(query: FeedbackFilterFields, actor: AuthenticatedUser) -> FeedbackFilters:
        """The query's filters, with the project filter narrowing the caller's scope —
        never replacing it (`ProjectScope.narrowed_to`, `docs/PRD.md` §7)."""
        scope = access.resolve_project_scope(actor)
        if query.project_id is not None:
            scope = scope.narrowed_to({query.project_id})
        return {
            "project_ids": None if scope.unrestricted else scope.ids,
            "feature": query.feature.value if query.feature else None,
            "rating": query.rating.value if query.rating else None,
            "reason_code": query.reason_code.value if query.reason_code else None,
            "prompt_version": query.prompt_version,
            "created_from": query.created_from,
            "created_to": query.created_to,
        }

    async def _resolve(
        self, target_type: FeedbackTarget, target_id: uuid.UUID, actor: AuthenticatedUser
    ) -> _Subject:
        """Prove the target exists and the caller may read it, or raise the one 404."""
        if target_type is FeedbackTarget.MESSAGE:
            message = await MessageRepository(self.session).get(target_id)
            if message is None or message.role != MessageRole.ASSISTANT.value:
                raise _not_found()
            conversation = await ConversationRepository(self.session).get_for_owner(
                message.conversation_id, access.resolve_conversation_owner(actor)
            )
            if conversation is None:
                raise _not_found()
            return _Subject(conversation.project_id, feature_for(target_type, origin=None))

        module_id, origin = await self._module_scoped(target_type, target_id)
        module = await ChecklistModuleRepository(self.session).get_in_scope(
            module_id, scope=access.resolve_project_scope(actor)
        )
        if module is None:
            raise _not_found()
        return _Subject(module.project_id, feature_for(target_type, origin=origin))

    async def _module_scoped(
        self, target_type: FeedbackTarget, target_id: uuid.UUID
    ) -> tuple[uuid.UUID, str | None]:
        """(owning checklist module id, change-set origin or None) for the four module targets."""
        match target_type:
            case FeedbackTarget.CHECKLIST_MESSAGE:
                row = await ChecklistMessageRepository(self.session).get(target_id)
                if row is None or row.role != MessageRole.ASSISTANT.value:
                    raise _not_found()
                return row.module_id, None
            case FeedbackTarget.MOCK_DATA_MESSAGE:
                row = await MockDataMessageRepository(self.session).get(target_id)
                if row is None or row.role != MessageRole.ASSISTANT.value:
                    raise _not_found()
                return row.checklist_module_id, None
            case FeedbackTarget.CHECKLIST_CHANGE_SET:
                change_set = await ChecklistChangeSetRepository(self.session).get(target_id)
                if change_set is None:
                    raise _not_found()
                return change_set.module_id, change_set.origin
            case FeedbackTarget.MOCK_DATA_CHANGE_SET:
                mock_change_set = await MockDataChangeSetRepository(self.session).get(target_id)
                if mock_change_set is None:
                    raise _not_found()
                return mock_change_set.checklist_module_id, mock_change_set.origin
            case _:
                raise _not_found()


async def my_feedback_map(
    session: AsyncSession,
    *,
    actor: AuthenticatedUser,
    target_type: FeedbackTarget,
    target_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, MyFeedback]:
    """The caller's own votes on a list the caller has already been allowed to read."""
    rows = await FeedbackRepository(session).mine_for_targets(
        user_id=actor.id, target_type=target_type.value, target_ids=target_ids
    )
    return {
        target_id: MyFeedback(rating=row.rating, reason_codes=row.reason_codes, note=row.note)
        for target_id, row in rows.items()
    }
