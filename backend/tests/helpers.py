"""Small test helpers shared across suites."""

from app.core.middleware import AuthenticatedUser
from app.models.user import User


def authenticated(user: User) -> AuthenticatedUser:
    """The frozen identity a service receives, built from a row.

    `AuthenticatedUser` is deliberately not the ORM `User`: the middleware resolves
    identity in its own session, which closes before the handler runs.
    """
    return AuthenticatedUser(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
    )
