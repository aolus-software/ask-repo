"""Request and response models for `/auth`.

The refresh token is never a field here. It travels only as an httpOnly cookie, so it
is unreadable by any script on the page (D3).
"""

from pydantic import EmailStr, field_validator

from app.schemas.base import ApiModel
from app.schemas.user import MAX_PASSWORD_FIELD_LENGTH, UserResponse


class LoginRequest(ApiModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        # Bounds bcrypt's work before any policy check runs.
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str

    @field_validator("current_password", "new_password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value


class PasswordPolicyResponse(ApiModel):
    """The rules a new password must satisfy, so a client can show them.

    This exists so the frontend never hard-codes the policy. The values come from
    `Settings`, which is the same source `validate_password` enforces against, so an
    operator who raises `PASSWORD_MIN_LENGTH` gets a UI that follows rather than a UI
    that confidently states the old number.

    The common-password blocklist is deliberately **not** exposed: it is a large
    wordlist, and shipping it to the browser would be both wasteful and a hint sheet.
    A client can therefore check length locally but never conclude a password is
    acceptable — only the API decides that.
    """

    min_length: int
    max_bytes: int


class AccessTokenResponse(ApiModel):
    """What login and refresh return. The refresh token is in the cookie, not here."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
