"""Password hashing, token minting, and token decoding.

The distinction these tests protect is D13: bcrypt for passwords because they are
low-entropy and guessable, SHA-256 for refresh tokens because they are 256 random
bits and need an indexed lookup. Using either in the other's place is the easiest
way to get M0 wrong, and neither mistake is visible at runtime.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    BCRYPT_MAX_BYTES,
    DUMMY_PASSWORD_HASH,
    PasswordTooLongError,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_password,
    needs_rehash,
    sha256_hex,
    verify_password,
)

SECRET = "test-secret-key-not-used-anywhere-real"
COST = 4  # keep tests fast; the production value is asserted in test_config.py


def test_hash_then_verify_round_trips() -> None:
    hashed = hash_password("correct horse battery", cost=COST)

    assert verify_password("correct horse battery", hashed) is True


def test_verify_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery", cost=COST)

    assert verify_password("incorrect horse battery", hashed) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    """Per-row salt. Identical hashes would mean a missing or reused salt."""
    assert hash_password("same input", cost=COST) != hash_password("same input", cost=COST)


def test_hash_is_a_bcrypt_string_of_the_expected_length() -> None:
    hashed = hash_password("some password", cost=COST)

    assert hashed.startswith("$2b$")
    assert len(hashed) == 60


def test_verify_returns_false_for_a_malformed_hash() -> None:
    """A corrupt column value must not raise out of the auth path."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hashing_rejects_input_over_the_bcrypt_limit() -> None:
    """bcrypt ignores bytes past 72 — silently, if we let it (D24)."""
    with pytest.raises(PasswordTooLongError):
        hash_password("a" * (BCRYPT_MAX_BYTES + 1), cost=COST)


def test_the_limit_is_measured_in_bytes_not_characters() -> None:
    """A CJK passphrase reaches 72 bytes at roughly 24 characters."""
    password = "密" * 25  # 3 bytes each once UTF-8 encoded == 75 bytes

    assert len(password) < BCRYPT_MAX_BYTES
    with pytest.raises(PasswordTooLongError):
        hash_password(password, cost=COST)


def test_a_password_at_exactly_the_limit_is_accepted() -> None:
    hashed = hash_password("a" * BCRYPT_MAX_BYTES, cost=COST)

    assert verify_password("a" * BCRYPT_MAX_BYTES, hashed) is True


def test_needs_rehash_is_true_when_the_stored_cost_is_lower() -> None:
    hashed = hash_password("some password", cost=4)

    assert needs_rehash(hashed, cost=6) is True


def test_needs_rehash_is_false_at_the_configured_cost() -> None:
    hashed = hash_password("some password", cost=COST)

    assert needs_rehash(hashed, cost=COST) is False


def test_needs_rehash_is_false_for_an_unparseable_hash() -> None:
    """Never re-hash on the basis of a value we could not read."""
    assert needs_rehash("garbage", cost=COST) is False


def test_the_dummy_hash_verifies_nothing_but_costs_the_same_work() -> None:
    """Used for unknown emails so login timing does not reveal existence."""
    assert DUMMY_PASSWORD_HASH.startswith("$2b$")
    assert verify_password("any guess at all", DUMMY_PASSWORD_HASH) is False


def test_sha256_hex_is_stable_and_the_right_width() -> None:
    """64 characters is what the token_hash column is sized for."""
    digest = sha256_hex("a-token-value")

    assert digest == sha256_hex("a-token-value")
    assert len(digest) == 64


def test_opaque_tokens_are_unique_and_long() -> None:
    tokens = {generate_opaque_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(len(token) >= 43 for token in tokens)  # 32 bytes base64url


def test_access_token_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, secret=SECRET, ttl_minutes=15)

    assert decode_access_token(token, secret=SECRET) == user_id
    assert expires_in == 15 * 60


def test_access_token_carries_no_authorisation_claims() -> None:
    """is_admin and must_change_password would go stale for up to the token's TTL."""
    token, _ = create_access_token(uuid.uuid4(), secret=SECRET, ttl_minutes=15)
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert set(claims) == {"sub", "iat", "exp", "jti", "typ"}
    assert claims["typ"] == "access"


def test_each_access_token_has_a_distinct_jti() -> None:
    user_id = uuid.uuid4()
    first, _ = create_access_token(user_id, secret=SECRET, ttl_minutes=15)
    second, _ = create_access_token(user_id, secret=SECRET, ttl_minutes=15)

    assert first != second


def test_decoding_rejects_a_token_signed_with_another_key() -> None:
    different_secret = "a-different-secret-key-not-used-anywhere"
    token, _ = create_access_token(uuid.uuid4(), secret=different_secret, ttl_minutes=15)

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_an_expired_token() -> None:
    token, _ = create_access_token(uuid.uuid4(), secret=SECRET, ttl_minutes=-1)

    with pytest.raises(TokenExpiredError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_garbage() -> None:
    with pytest.raises(TokenInvalidError):
        decode_access_token("not.a.jwt", secret=SECRET)


def test_decoding_rejects_a_token_of_the_wrong_type() -> None:
    """`typ` guards against some future non-access token being replayed here."""
    claims = {
        "sub": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "typ": "something-else",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)


def test_decoding_rejects_a_non_uuid_subject() -> None:
    claims = {
        "sub": "not-a-uuid",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret=SECRET)
