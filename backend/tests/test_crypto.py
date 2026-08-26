"""PAT encryption at rest, and keeping secrets out of stored error text."""

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import SecretBox, scrub


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(Fernet.generate_key().decode())


def test_round_trip(box: SecretBox) -> None:
    token = box.encrypt("ghp_realtokenvalue")
    assert box.decrypt(token) == "ghp_realtokenvalue"


def test_ciphertext_does_not_contain_the_plaintext(box: SecretBox) -> None:
    """Guards against a 'null' implementation that stores the value verbatim."""
    assert b"ghp_realtokenvalue" not in box.encrypt("ghp_realtokenvalue")


def test_a_different_key_cannot_decrypt(box: SecretBox) -> None:
    other = SecretBox(Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="could not be decrypted"):
        other.decrypt(box.encrypt("ghp_realtokenvalue"))


def test_scrub_replaces_every_occurrence() -> None:
    message = "fatal: auth failed for https://x:ghp_secret@github.com (ghp_secret)"
    assert scrub(message, "ghp_secret") == "fatal: auth failed for https://x:***@github.com (***)"


def test_scrub_ignores_empty_secrets() -> None:
    """A None PAT must not turn every character boundary into ***."""
    assert scrub("plain message", "", None) == "plain message"
