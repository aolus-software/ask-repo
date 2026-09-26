"""Self-service password reset. The wire never carries a token back out."""

from pydantic import EmailStr, field_validator

from app.schemas.base import ApiModel
from app.schemas.user import MAX_PASSWORD_FIELD_LENGTH

# A `token_urlsafe(32)` is 43 characters. Anything far longer is not one of ours, and
# bounding it keeps a pathological body from reaching the hash.
MAX_TOKEN_LENGTH = 128


class PasswordResetAvailability(ApiModel):
    enabled: bool


class PasswordResetRequest(ApiModel):
    email: EmailStr


class PasswordResetConfirm(ApiModel):
    token: str
    new_password: str

    @field_validator("token")
    @classmethod
    def _bound_token_length(cls, value: str) -> str:
        if not value or len(value) > MAX_TOKEN_LENGTH:
            raise ValueError(f"must be between 1 and {MAX_TOKEN_LENGTH} characters")
        return value

    @field_validator("new_password")
    @classmethod
    def _bound_password_length(cls, value: str) -> str:
        if len(value) > MAX_PASSWORD_FIELD_LENGTH:
            raise ValueError(f"must be at most {MAX_PASSWORD_FIELD_LENGTH} characters")
        return value
