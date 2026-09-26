"""A sender that records instead of sending — the test double for `MailSender`.

Lives beside the protocol, as `InMemoryIngestionQueue` does for the queue, so every test
drives the real outbox and the real routes with no relay.
"""

from app.mail.sender import MailSendError, OutboundEmail


class RecordingMailSender:
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []
        self.fail_with: MailSendError | None = None

    async def send(self, email: OutboundEmail) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(email)
