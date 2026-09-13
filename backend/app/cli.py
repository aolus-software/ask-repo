"""Operational commands. Run as `python -m app.cli <command>`.

Kept out of the request-serving app deliberately (D6): boot side effects would run for
every `TestClient(create_app())`, and a failed seed would become a failed boot. The
container entrypoint invokes this after `alembic upgrade head`.
"""

import argparse
import asyncio
import logging
import sys
import uuid

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


async def seed_admins() -> int:
    """Create the bootstrap admin accounts if they are missing. Returns how many.

    Idempotent, because the container entrypoint runs it on every start. Refuses
    outright rather than seeding a weak password: an instance whose admin account has a
    guessable password is worse than one that failed to start and said why.

    An already-seeded instance must boot regardless of `BOOTSTRAP_ADMIN_PASSWORD`'s
    presence *or* quality — the entrypoint chains this command with `&&`, and with
    `restart: unless-stopped` a non-zero exit here crash-loops the container. So the
    "nothing left to create" return happens before either password check, not just
    before the missing-password one.
    """
    settings = get_settings()
    password = settings.bootstrap_admin_password

    async with get_sessionmaker()() as session:
        users = UserRepository(session)
        missing: list[str] = []
        for email in settings.bootstrap_admin_emails:
            normalised = email.strip().lower()
            if await users.email_exists(normalised):
                logger.info("Bootstrap admin %s already exists; skipping", normalised)
            else:
                missing.append(normalised)

        if not missing:
            if password:
                logger.warning(
                    "BOOTSTRAP_ADMIN_PASSWORD is set but unused: every bootstrap admin "
                    "already exists"
                )
            else:
                logger.info("All bootstrap admins already exist; nothing to seed")
            return 0

        if not password:
            raise ValueError(
                "BOOTSTRAP_ADMIN_PASSWORD is not set; refusing to seed administrator accounts"
            )

        try:
            check_password(
                password,
                min_length=settings.password_min_length,
                max_bytes=settings.password_max_bytes,
                common=get_common_passwords(),
            )
        except PasswordPolicyError as error:
            raise ValueError(
                f"BOOTSTRAP_ADMIN_PASSWORD fails password policy: {error.reason}"
            ) from error

        password_hash = hash_password(password, cost=settings.bcrypt_cost)
        created = 0
        for normalised in missing:
            await users.add(
                User(
                    id=uuid.uuid4(),
                    name=normalised.split("@")[0],
                    email=normalised,
                    password_hash=password_hash,
                    is_admin=True,
                    must_change_password=True,
                )
            )
            created += 1
            logger.info("Created bootstrap admin %s", normalised)
        await session.commit()

    return created


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    configure_logging("cli")
    parser = argparse.ArgumentParser(prog="app.cli", description="AskRepo operational commands")
    parser.add_argument("command", choices=["seed-admins"])
    arguments = parser.parse_args(argv)

    if arguments.command == "seed-admins":
        try:
            created = asyncio.run(seed_admins())
        except ValueError as error:
            logger.error("%s", error)
            return 1
        logger.info("Seeding complete; %d account(s) created", created)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
