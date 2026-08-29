"""Encryption for stored PATs, and scrubbing for text that may quote one.

`docs/PRD.md` §9 requires PATs encrypted at rest with an env-provided key, never
logged and never returned. §4.0 extends that to logs and tracebacks. Clone stderr
is the most likely place a token surfaces, and it lands in `Project.error`, so
`scrub` runs on the way in rather than being remembered at each call site.
"""

from cryptography.fernet import Fernet, InvalidToken

REDACTION = "***"


class SecretBox:
    """Symmetric encryption for values that must survive a database read.

    Fernet rather than raw AES-GCM: it carries its own IV and authentication tag,
    so there is no nonce-reuse footgun for a caller to step on.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a secret for storage."""
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        """Decrypt a stored secret.

        Raises `ValueError` rather than propagating `InvalidToken`, so a rotated or
        wrong key reads as a configuration problem at the call site instead of a
        cryptography-library detail.
        """
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken as error:
            raise ValueError(
                "stored secret could not be decrypted — the encryption key may have changed"
            ) from error


def scrub(text: str, *secrets: str | None) -> str:
    """Replace every occurrence of each secret with `***`.

    Empty and `None` secrets are skipped: `str.replace` with an empty needle inserts
    the replacement at every character boundary, so a project with no PAT would
    otherwise have its error text destroyed.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTION)
    return text
