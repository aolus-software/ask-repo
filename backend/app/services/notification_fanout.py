"""The notification write path.

**It flushes; it never commits.** The event row, the recipient rows and the state
change that caused them are one transaction, owned by the caller. That is approach A
in `docs/superpowers/specs/2026-09-20-phase-2.3-notifications-design.md` §5.1, and it
is why *"the generation finished and nobody was told"* is unrepresentable.

**It is called before the commit; `AuditRecorder.record` is called after it.** The two
orderings look inconsistent at the same call site and both are correct: an audit
failure must not fail a user's action, and a lost notification is the feature not
working. The requirements point in opposite directions. See
`.claude/rules/notifications.md`.

Unlike `AuditRecorder`, this **raises**. A `ValueError` from `build_details` is a
programming error — a key nobody named — and swallowing it would ship a silently
empty notification. A database error propagates and takes the caller's transaction
with it, which is the point.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import resolve_notification_recipients
from app.core.notifications import (
    ACTOR_EXCLUDED,
    DIRECT_EVENTS,
    RECIPIENT_PERMISSIONS,
    TARGET_TYPES,
    NotificationType,
    build_details,
)
from app.models.notification import Notification, NotificationEvent
from app.repositories.membership import MembershipRepository
from app.repositories.notification import NotificationRepository
from app.repositories.notification_event import NotificationEventRepository
from app.repositories.notification_preference import NotificationPreferenceRepository


class NotificationFanout:
    """Raise one event and write a row for each of its recipients."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._memberships = MembershipRepository(session)
        self._events = NotificationEventRepository(session)
        self._notifications = NotificationRepository(session)
        self._preferences = NotificationPreferenceRepository(session)

    async def raise_event(
        self,
        *,
        event_type: NotificationType,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        target_id: uuid.UUID | None,
        details: dict[str, object],
    ) -> None:
        """Raise an event whose recipients come from membership."""
        if event_type in DIRECT_EVENTS:
            raise ValueError(f"{event_type} names its recipient; use raise_direct")

        excluding = actor_user_id if event_type in ACTOR_EXCLUDED else None
        recipients = await resolve_notification_recipients(
            self._memberships,
            project_id,
            RECIPIENT_PERMISSIONS[event_type],
            excluding=excluding,
        )
        await self._write(
            event_type=event_type,
            project_id=project_id,
            actor_user_id=actor_user_id,
            target_id=target_id,
            details=details,
            recipients=recipients,
        )

    async def raise_direct(
        self,
        *,
        event_type: NotificationType,
        recipient: uuid.UUID,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        target_id: uuid.UUID | None,
        details: dict[str, object],
    ) -> None:
        """Raise an event whose single recipient the caller names.

        A separate method rather than a branch inside `raise_event`, because a branch
        is how "we already have one recipient resolver" quietly becomes two.
        """
        if event_type not in DIRECT_EVENTS:
            raise ValueError(f"{event_type} resolves its recipients from membership")
        await self._write(
            event_type=event_type,
            project_id=project_id,
            actor_user_id=actor_user_id,
            target_id=target_id,
            details=details,
            recipients=frozenset({recipient}),
        )

    async def _write(
        self,
        *,
        event_type: NotificationType,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        target_id: uuid.UUID | None,
        details: dict[str, object],
        recipients: frozenset[uuid.UUID],
    ) -> None:
        """Stage the event and its deliveries, and flush.

        The event row is written **even when `recipients` is empty** — everyone
        eligible may have muted it, or the only eligible member may be the excluded
        actor. The record is the record; a transport having no audience for one
        occurrence is not a reason to lose it, and Phase 2.4 reads this table.
        """
        event = NotificationEvent(
            id=uuid.uuid4(),
            event_type=event_type.value,
            actor_user_id=actor_user_id,
            project_id=project_id,
            target_type=TARGET_TYPES[event_type],
            target_id=target_id,
            details=build_details(event_type, details),
        )
        await self._events.add(event)

        if recipients:
            muted = await self._muted_for(event_type, recipients)
            await self._notifications.add_all(
                [
                    Notification(
                        id=uuid.uuid4(),
                        event_id=event.id,
                        user_id=user_id,
                        in_app_visible=user_id not in muted,
                    )
                    for user_id in sorted(recipients)
                ]
            )
        await self.session.flush()

    async def _muted_for(
        self, event_type: NotificationType, recipients: frozenset[uuid.UUID]
    ) -> frozenset[uuid.UUID]:
        """Which recipients have turned this event's in-app delivery off.

        Preferences are **sparse and absence means on**, so this asks which rows say
        `false` rather than which rows say `true`. It snapshots onto the delivery row
        rather than gating it — see the module docstring and §2.4 of the spec.
        """
        return await self._preferences.muted_in_app(event_type.value, recipients)
