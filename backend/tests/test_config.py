"""Settings defaults and the production guards.

`Settings` is the only place that reads the environment (`CLAUDE.md`), so a wrong
default here is invisible until deployment. The production validators exist because
`SECURITY.md:54` promises operators that a real `SECRET_KEY` is required.
"""

import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_SECRET_KEY, Settings


def test_database_url_default_uses_the_async_driver() -> None:
    """A sync driver silently breaks the async engine at first connect."""
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_password_max_bytes_is_bcryptsafe() -> None:
    """bcrypt ignores input past 72 bytes; a larger cap would allow silent truncation."""
    assert Settings().password_max_bytes == 72


def test_development_tolerates_the_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing set, the default resolves to the placeholder and dev accepts it."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(app_env="development")

    assert settings.secret_key == PLACEHOLDER_SECRET_KEY


def test_production_rejects_the_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production must refuse to boot on the default signing key."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production")


def test_production_rejects_an_insecure_refresh_cookie() -> None:
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            app_env="production",
            secret_key="a-real-secret-value-for-testing-only",
            refresh_cookie_secure=False,
        )


def test_production_accepts_a_complete_configuration() -> None:
    settings = Settings(
        app_env="production",
        secret_key="a-real-secret-value-for-testing-only",
        trusted_proxy_hops=1,
    )

    assert settings.app_env == "production"


def test_production_rejects_zero_trusted_proxy_hops() -> None:
    """Left at 0 behind Caddy, the per-IP limit silently becomes instance-wide."""
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_HOPS"):
        Settings(
            app_env="production",
            secret_key="a-real-secret-value-for-testing-only",
            trusted_proxy_hops=0,
        )
