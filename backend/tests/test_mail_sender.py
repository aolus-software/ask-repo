"""The sender's contract: plain text, and a retryable/terminal split the outbox trusts."""

import aiosmtplib
import pytest

from app.config import Settings
from app.mail.recording import RecordingMailSender
from app.mail.sender import MailSendError, OutboundEmail, SmtpMailSender, build_message, classify

SETTINGS = Settings(
    mail_enabled=True,
    smtp_host="relay.internal",
    smtp_from="askrepo@example.com",
    app_base_url="https://askrepo.internal",
)
EMAIL = OutboundEmail(to="dev@example.com", subject="Index finished | AskRepo", body="Hi.\n")


def test_the_message_is_plain_text_only() -> None:
    message = build_message(EMAIL, sender="askrepo@example.com")
    assert message.get_content_type() == "text/plain"
    assert not message.is_multipart()
    assert message["From"] == "askrepo@example.com"
    assert message["To"] == "dev@example.com"
    assert message["Subject"] == "Index finished | AskRepo"


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (aiosmtplib.SMTPConnectError("refused"), True),
        (aiosmtplib.SMTPServerDisconnected("gone"), True),
        (aiosmtplib.SMTPConnectTimeoutError("slow"), True),
        (aiosmtplib.SMTPTimeoutError("slow"), True),
        (aiosmtplib.SMTPResponseException(421, "try later"), True),
        (aiosmtplib.SMTPResponseException(451, "greylisted"), True),
        (aiosmtplib.SMTPRecipientsRefused([]), False),
        (aiosmtplib.SMTPSenderRefused(550, "no", "askrepo@example.com"), False),
        (aiosmtplib.SMTPAuthenticationError(535, "bad credentials"), False),
        (aiosmtplib.SMTPResponseException(554, "rejected"), False),
    ],
)
def test_failures_are_classified(error: Exception, retryable: bool) -> None:
    assert classify(error).retryable is retryable


def test_an_unknown_os_level_failure_is_retryable() -> None:
    assert classify(OSError("network unreachable")).retryable is True


async def test_smtp_sender_wraps_library_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(*_args: object, **_kwargs: object) -> None:
        raise aiosmtplib.SMTPConnectError("refused")

    monkeypatch.setattr(aiosmtplib, "send", refuse)
    with pytest.raises(MailSendError) as raised:
        await SmtpMailSender(SETTINGS).send(EMAIL)
    assert raised.value.retryable is True


async def test_smtp_sender_passes_the_security_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def capture(_message: object, **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(aiosmtplib, "send", capture)
    await SmtpMailSender(SETTINGS.model_copy(update={"smtp_security": "tls"})).send(EMAIL)
    assert seen["use_tls"] is True
    assert seen["start_tls"] is False
    assert seen["hostname"] == "relay.internal"


async def test_the_recording_sender_records_and_can_fail() -> None:
    sender = RecordingMailSender()
    await sender.send(EMAIL)
    assert sender.sent == [EMAIL]

    sender.fail_with = MailSendError("down", retryable=True)
    with pytest.raises(MailSendError):
        await sender.send(EMAIL)
    assert sender.sent == [EMAIL]
