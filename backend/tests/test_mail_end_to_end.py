"""One example, wired end to end: a membership grant, drained through the outbox.

Every other mail test exercises one layer at a time — the fan-out write
(`test_notification_email_fanout.py`), the outbox drain (`test_mail_outbox.py`), the
composer (`test_mail_compose.py`). This one proves the seam between them: a real route
call writes a `pending` row through `NotificationFanout`, and a real outbox drain reads
it back out as an email, with nothing faked in between but the SMTP relay itself.
"""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.mail.outbox import send_pending_once
from app.mail.recording import RecordingMailSender
from app.models import User


async def test_a_membership_grant_is_delivered_by_email(
    app_with_queue: FastAPI,
    client_for_user_a: AsyncClient,
    authed_user: User,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings().model_copy(
        update={
            "mail_enabled": True,
            "smtp_host": "relay.internal",
            "smtp_from": "askrepo@example.com",
            "app_base_url": "https://askrepo.internal",
        }
    )
    # Overriding after the fixtures have built the app and the client still works:
    # FastAPI reads `dependency_overrides` per request, not at app-build time.
    app_with_queue.dependency_overrides[get_settings] = lambda: settings

    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    granted = await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(authed_user.id), "role": "viewer"},
    )
    assert granted.status_code == 201

    sender = RecordingMailSender()
    sent = await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=settings)

    assert sent == 1
    [email] = sender.sent
    assert email.to == authed_user.email
    assert "You were added to a project" in email.subject
    assert f"/projects/{project_id}" in email.body
    assert email.html is not None
    assert f"/projects/{project_id}" in email.html
