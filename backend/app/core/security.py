"""Password hashing, opaque token minting, and access-token encode/decode.

Two different hashes live here and they are not interchangeable (D13):

- **bcrypt** for passwords. Deliberately slow and salted, because a password is
  low-entropy and an attacker with the database will guess at it offline.
- **SHA-256** for refresh tokens. They are 256 random bits, so there is nothing to
  guess, and a fast digest is what makes an indexed lookup by token possible — a
  salted password hash would force a scan of every row.

Nothing here raises `HTTPException`. Mapping these exceptions to status codes is the
caller's job, which keeps this module usable from the CLI as well as from routes.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import bcrypt
import jwt

# bcrypt ignores input past this many bytes. Enforced rather than tolerated: left
# alone, two different long passwords sharing a 72-byte prefix would both
# authenticate, with no error and no log line (D24).
BCRYPT_MAX_BYTES: Final[int] = 72

_ACCESS_TOKEN_ALGORITHM: Final[str] = "HS256"
_ACCESS_TOKEN_TYPE: Final[str] = "access"
_OPAQUE_TOKEN_BYTES: Final[int] = 32


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte input limit."""


class TokenError(Exception):
    """Base class for access-token failures."""


class TokenExpiredError(TokenError):
    """The token was well-formed and correctly signed, but past its expiry."""


class TokenInvalidError(TokenError):
    """The token was malformed, wrongly signed, or of the wrong type."""


def hash_password(password: str, *, cost: int) -> str:
    """Hash a password with bcrypt at the given cost factor.

    Raises `PasswordTooLongError` above 72 UTF-8 bytes rather than letting bcrypt
    truncate silently.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise PasswordTooLongError(
            f"password is {len(encoded)} bytes; the maximum is {BCRYPT_MAX_BYTES}"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=cost)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored bcrypt hash.

    Returns `False` rather than raising for a malformed stored value: a corrupt row
    must not turn a failed login into a 500.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def needs_rehash(password_hash: str, *, cost: int) -> bool:
    """Whether a stored hash was written at a lower cost than currently configured.

    bcrypt embeds the cost in its prefix (`$2b$12$...`), so raising the configured
    cost can be applied to existing accounts on their next successful login (D22).
    """
    parts = password_hash.split("$")
    if len(parts) < 4 or not parts[2].isdigit():
        return False
    return int(parts[2]) < cost


def sha256_hex(value: str) -> str:
    """Hex SHA-256 digest — always 64 characters, matching `refresh_tokens.token_hash`."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_opaque_token() -> str:
    """A refresh token: 32 random bytes, URL-safe base64."""
    return secrets.token_urlsafe(_OPAQUE_TOKEN_BYTES)


def create_access_token(user_id: uuid.UUID, *, secret: str, ttl_minutes: int) -> tuple[str, int]:
    """Mint a signed access token. Returns the token and its lifetime in seconds.

    Deliberately carries no `is_admin` or `must_change_password` claim: both would go
    stale for up to `ttl_minutes`, and `docs/PRD.md:101` requires deactivation to end
    a session immediately.
    """
    issued_at = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl_minutes),
        "jti": str(uuid.uuid4()),
        "typ": _ACCESS_TOKEN_TYPE,
    }
    token = jwt.encode(claims, secret, algorithm=_ACCESS_TOKEN_ALGORITHM)
    return token, ttl_minutes * 60


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    """Verify an access token and return the user id it identifies."""
    try:
        claims = jwt.decode(token, secret, algorithms=[_ACCESS_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenExpiredError(str(error)) from error
    except jwt.PyJWTError as error:
        raise TokenInvalidError(str(error)) from error

    if claims.get("typ") != _ACCESS_TOKEN_TYPE:
        raise TokenInvalidError("token is not an access token")
    try:
        return uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as error:
        raise TokenInvalidError("token subject is not a UUID") from error


# Verified against when the email is unknown, so a login attempt costs the same work
# whether or not the account exists (`docs/PRD.md:114`).
DUMMY_PASSWORD_HASH: Final[str] = hash_password(secrets.token_urlsafe(32), cost=4)
