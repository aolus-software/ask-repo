"""Request and response models for accounts.

`password_hash` is not a field on any response model here. Not excluded, not masked —
absent, so it cannot be serialised by accident (`.claude/rules/response-api.md`).
"""

import uuid
from datetime import datetime

from pydantic import EmailStr, field_validator

from app.schemas.base import ApiModel

# Bounds the work bcrypt is asked to do before policy runs. The real policy — minimum
# length and the wordlist — lives in the service so every rejection shares one code.
MAX_PASSWORD_FIELD_LENGTH = 256


class UserResponse(ApiModel):
    """An account as returned by the API."""

    id: uuid.UUID
    name: str
    email: EmailStr
    is_admin: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(ApiModel):
    """Admin-provisioned account. The password is communicated out of band."""

    name: str
    email: EmailStr
    password: str
    is_admin: bool = False

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """Lowercase at the boundary, so storage and lookup agree without citext."""
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value

    @field_validator("name")
    @classmethod
    def _require_a_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class UserUpdateRequest(ApiModel):
    """Partial update. Deliberately cannot change email or password.

    `docs/PRD.md:105` scopes this to name and the admin flag; password changes have
    their own two routes with their own revocation semantics.
    """

    name: str | None = None
    is_admin: bool | None = None

    @field_validator("name")
    @classmethod
    def _require_a_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value else value


class ResetPasswordRequest(ApiModel):
    """The admin supplies the new temporary password.

    Server-generating it would mean returning a secret in a response body, which
    `.claude/rules/response-api.md` forbids outright.
    """

    new_password: str

    @field_validator("new_password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value
