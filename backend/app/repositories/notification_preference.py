"""Reads and writes for `notification_preferences`.

**Rows are sparse: absence means on.** `map_for` returns only what the user has an
opinion about, and every caller fills the gaps with `(True, True)`. That is what makes
a new event type on-by-default for everybody with no data migration.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.notification import NotificationPreference
from app.repositories.base import BaseRepository


class NotificationPreferenceRepository(BaseRepository[NotificationPreference]):
    """One user's opinions, read as a map and written as a set."""

    model = NotificationPreference

    async def map_for(self, user_id: uuid.UUID) -> dict[str, tuple[bool, bool]]:
        """`{event_type: (in_app, email)}` for the rows that exist. Sparse."""
        result = await self.session.execute(
            select(
                NotificationPreference.event_type,
                NotificationPreference.in_app,
                NotificationPreference.email,
            ).where(NotificationPreference.user_id == user_id)
        )
        return {row.event_type: (row.in_app, row.email) for row in result.all()}

    async def upsert_many(self, user_id: uuid.UUID, prefs: dict[str, tuple[bool, bool]]) -> None:
        """Write the whole set in one statement.

        `ON CONFLICT` against `uq_notification_preferences_user_id_event_type`, so the
        settings form saving twice is one row per event type rather than a duplicate
        key error.
        """
        if not prefs:
            return
        rows = [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "event_type": event_type,
                "in_app": in_app,
                "email": email,
            }
            for event_type, (in_app, email) in prefs.items()
        ]
        statement = insert(NotificationPreference).values(rows)
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_notification_preferences_user_id_event_type",
                set_={
                    "in_app": statement.excluded.in_app,
                    "email": statement.excluded.email,
                },
            )
        )

    async def muted_in_app(
        self, event_type: str, user_ids: frozenset[uuid.UUID]
    ) -> frozenset[uuid.UUID]:
        """Which of these users have turned this event's in-app delivery off.

        Asks which rows say `false`, not which say `true`, because preferences are
        sparse and absence means on.
        """
        if not user_ids:
            return frozenset()
        result = await self.session.execute(
            select(NotificationPreference.user_id).where(
                NotificationPreference.user_id.in_(user_ids),
                NotificationPreference.event_type == event_type,
                NotificationPreference.in_app.is_(False),
            )
        )
        return frozenset(result.scalars().all())
