"""Draining notification email: claim, send, mark (spec §4).

Runs in the worker as `mail_loop`, a sibling of `reconcile_loop` and never a step
inside it: a slow relay — a 10-second timeout across 50 rows — must not delay the
recovery of stranded indexes and generations.

Delivery is at least once. A drain that dies after the relay accepts a message and
before the row is marked sends it again when the lease expires; for a nudge that is
the correct side of the trade.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.notifications import NotificationType
from app.db.session import get_sessionmaker
from app.mail.compose import compose_notification
from app.mail.sender import MailSender, MailSendError
from app.models.notification import EmailState
from app.repositories.notification import NotificationRepository, PendingEmail

logger = logging.getLogger(__name__)

MAIL_INTERVAL_SECONDS = 60
CLAIM_BATCH = 50
# A batch of 50 rows against a 10-second SMTP timeout (`SEND_TIMEOUT_SECONDS`) can run
# for over eight minutes in the worst case. Two worker replicas both drain on the same
# 60-second tick, so a lease shorter than one batch's worst case lets a second replica
# reclaim rows the first is still sending, and send them twice. 15 minutes covers that
# batch with headroom without leaving a crashed worker's rows stranded for long.
CLAIM_LEASE = timedelta(minutes=15)
# No setting: no operator decision turns on it (spec §4.3).
MAX_EMAIL_ATTEMPTS = 5
# Turning mail off for a week and back on must not deliver a week of "Index finished".
STALE_AFTER = timedelta(hours=24)


async def send_pending_once(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    sender: MailSender,
    settings: Settings,
) -> int:
    """One drain pass. Returns how many emails were handed to the relay."""
    async with sessionmaker() as session:
        claimed = await NotificationRepository(session).claim_pending_email(
            limit=CLAIM_BATCH, lease=CLAIM_LEASE
        )
        await session.commit()

    sent = 0
    for pending in claimed:
        try:
            outcome = await _deliver(pending, sender=sender, settings=settings)
        except Exception:
            # Anything that is not a MailSendError -- an unrecognised event_type, a
            # bug inside compose_notification -- is deterministic, not a relay hiccup:
            # retrying it reproduces the same crash on every future drain. Failing the
            # row outright is what stops it climbing past MAX_EMAIL_ATTEMPTS while
            # never reaching mark_email, and lets the rest of the batch proceed
            # instead of sitting leased for CLAIM_LEASE (15 minutes) behind it.
            logger.exception(
                "notification email %s (%s) raised outside MailSendError",
                pending.notification_id,
                pending.event_type,
            )
            outcome = "failed"
        if outcome is None:
            continue  # retryable: stays pending; the lease spaces the next attempt
        async with sessionmaker() as session:
            await NotificationRepository(session).mark_email(pending.notification_id, outcome)
            await session.commit()
        if outcome == "sent":
            sent += 1
    return sent


async def _deliver(
    pending: PendingEmail, *, sender: MailSender, settings: Settings
) -> EmailState | None:
    """`sent`, `failed` or `skipped` — or `None` to leave the row pending."""
    if pending.recipient_deactivated:
        return "skipped"
    if datetime.now(UTC) - pending.event_created_at > STALE_AFTER:
        return "skipped"
    email = compose_notification(
        event_type=NotificationType(pending.event_type),
        target_type=pending.target_type,
        target_id=pending.target_id,
        project_id=pending.project_id,
        to=pending.to,
        settings=settings,
    )
    try:
        await sender.send(email)
    except MailSendError as error:
        logger.warning(
            "notification email %s (%s) not sent, attempt %d, retryable=%s: %s",
            pending.notification_id,
            pending.event_type,
            pending.attempts,
            error.retryable,
            error,
        )
        if error.retryable and pending.attempts < MAX_EMAIL_ATTEMPTS:
            return None
        return "failed"
    return "sent"


async def mail_loop(*, sender: MailSender, settings: Settings) -> None:
    """The worker's mail task. Started only when `MAIL_ENABLED`."""
    sessionmaker = get_sessionmaker()
    while True:
        await asyncio.sleep(MAIL_INTERVAL_SECONDS)
        try:
            sent = await send_pending_once(
                sessionmaker=sessionmaker, sender=sender, settings=settings
            )
            if sent:
                logger.info("sent %d notification emails", sent)
        except Exception:
            logger.exception("mail tick failed")
