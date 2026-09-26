"""The SMTP sender, and the retryable/terminal split the outbox relies on.

Classification follows the queue's existing rule: a failure that might succeed on a
later attempt (connection, timeout, a `4xx` reply) is retryable; one that will fail the
same way every time (a `5xx` reply, bad credentials, a refused recipient) is terminal.
"""

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Annotated, Protocol

import aiosmtplib
from fastapi import Depends

from app.config import Settings, get_settings

SEND_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    body: str
    html: str | None = None


class MailSendError(Exception):
    """A send that did not reach the relay. `retryable` decides the outbox's next move."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class MailSender(Protocol):
    async def send(self, email: OutboundEmail) -> None:
        """Hand one message to the relay, or raise `MailSendError`."""
        ...


def build_message(email: OutboundEmail, *, sender: str) -> EmailMessage:
    """Plain text first, always; an HTML alternative is added only when `email.html` is set.

    `set_content` puts the plain text part first, which is what a client without HTML
    rendering (or one honouring the sender's stated preference) falls back to. With no
    `html`, the message stays exactly what it always was: a single `text/plain` part.
    """
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email.to
    message["Subject"] = email.subject
    message.set_content(email.body)
    if email.html is not None:
        message.add_alternative(email.html, subtype="html")
    return message


def classify(error: Exception) -> MailSendError:
    """Map a library or network failure onto the retryable/terminal split."""
    if isinstance(
        error,
        aiosmtplib.SMTPRecipientsRefused
        | aiosmtplib.SMTPSenderRefused
        | aiosmtplib.SMTPAuthenticationError,
    ):
        return MailSendError(str(error), retryable=False)
    if isinstance(error, aiosmtplib.SMTPResponseException):
        return MailSendError(str(error), retryable=400 <= error.code < 500)
    # Connection, disconnect, timeout, and anything raised below SMTP (OSError).
    return MailSendError(str(error), retryable=True)


class SmtpMailSender:
    """Sends through the operator's relay, one connection per message.

    One connection per message is deliberate at this volume: the outbox drains at most
    50 rows a minute, and a pooled connection would be one more thing to recover when
    the relay drops it.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, email: OutboundEmail) -> None:
        settings = self._settings
        message = build_message(email, sender=settings.smtp_from)
        try:
            await aiosmtplib.send(
                message,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password.get_secret_value() or None,
                use_tls=settings.smtp_security == "tls",
                start_tls=settings.smtp_security == "starttls",
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except (aiosmtplib.SMTPException, OSError) as error:
            raise classify(error) from error


def get_mail_sender(settings: Annotated[Settings, Depends(get_settings)]) -> MailSender:
    """The request-scoped sender. Tests override this with `RecordingMailSender`."""
    return SmtpMailSender(settings)


MailSenderDep = Annotated[MailSender, Depends(get_mail_sender)]
