"""Mail settings: off by default, and refused when switched on half-configured."""

import pytest
from pydantic import ValidationError

from app.config import Settings

COMPLETE = {
    "mail_enabled": True,
    "smtp_host": "relay.internal",
    "smtp_from": "askrepo@example.com",
    "app_base_url": "https://askrepo.internal",
}


def test_mail_is_off_by_default() -> None:
    assert Settings().mail_enabled is False


def test_a_complete_configuration_is_accepted() -> None:
    settings = Settings(**COMPLETE)
    assert settings.mail_enabled is True
    assert settings.smtp_port == 587
    assert settings.smtp_security == "starttls"
    assert settings.mail_app_name == "AskRepo"


@pytest.mark.parametrize("missing", ["smtp_host", "smtp_from", "app_base_url"])
def test_mail_enabled_without_a_required_field_is_refused(missing: str) -> None:
    with pytest.raises(ValidationError, match=missing.upper()):
        Settings(**{**COMPLETE, missing: ""})


@pytest.mark.parametrize("url", ["askrepo.internal", "ftp://askrepo.internal", "/relative"])
def test_a_non_http_base_url_is_refused(url: str) -> None:
    with pytest.raises(ValidationError, match="APP_BASE_URL"):
        Settings(**{**COMPLETE, "app_base_url": url})


def test_half_configuration_is_fine_while_mail_is_off() -> None:
    assert Settings(mail_enabled=False, smtp_host="").mail_enabled is False


def test_the_smtp_password_never_prints() -> None:
    settings = Settings(**COMPLETE, smtp_password="hunter2-but-longer")
    assert "hunter2" not in repr(settings)
    assert settings.smtp_password.get_secret_value() == "hunter2-but-longer"


def test_password_reset_token_ttl_below_minimum_is_refused() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 5"):
        Settings(password_reset_token_ttl_minutes=4)
