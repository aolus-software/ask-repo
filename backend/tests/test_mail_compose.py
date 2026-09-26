"""What leaves the network: a fixed message, a link, and nothing from a repository."""

import inspect
import re
import uuid
from typing import Any

import pytest

from app.config import Settings
from app.core.notifications import NotificationType
from app.mail.compose import (
    _ENVIRONMENT,
    MESSAGES,
    compose_notification,
    compose_password_reset,
    compose_subject,
)

# Every href in a rendered template must start with this, since a rendered email links
# only the app itself.
BASE_URL = "https://askrepo.internal"

FORBIDDEN_HTML_SNIPPETS = ("<img", "<script", "<link", "url(", "src=")

BASE: dict[str, Any] = {
    "mail_enabled": True,
    "smtp_host": "relay.internal",
    "smtp_from": "askrepo@example.com",
    "app_base_url": "https://askrepo.internal/",
    # Satisfy the production-only validators regardless of which `app_env` a given
    # test passes — irrelevant to composing an email, but required for Settings to
    # construct at all once `app_env="production"` is under test.
    "secret_key": "a-real-secret-value-for-testing-only",
    "trusted_proxy_hops": 1,
    "pat_encryption_key": "Hu25IBLmyXgJmARywo5aj5DQrr3yGs3RPgqyC7_kVDo=",
}
PROJECT = uuid.UUID("7f3c0000-0000-0000-0000-000000000001")
MODULE = uuid.UUID("9a1b0000-0000-0000-0000-000000000002")


def _settings(app_env: str) -> Settings:
    return Settings(**BASE, app_env=app_env)


def test_production_subjects_carry_no_environment_tag() -> None:
    subject = compose_subject("Index finished", settings=_settings("production"))
    assert subject == "Index finished | AskRepo"


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_other_environments_are_tagged(env: str) -> None:
    subject = compose_subject("Index finished", settings=_settings(env))
    assert subject == f"[{env}] Index finished | AskRepo"


def test_the_app_name_is_configurable() -> None:
    settings = _settings("production").model_copy(update={"mail_app_name": "Acme Code"})
    assert compose_subject("Index finished", settings=settings) == "Index finished | Acme Code"


def test_every_event_type_has_a_message() -> None:
    assert set(MESSAGES) == set(NotificationType)
    for subject_message, body_sentence in MESSAGES.values():
        assert subject_message and body_sentence


@pytest.mark.parametrize("event_type", list(NotificationType))
def test_every_event_type_composes_with_a_link(event_type: NotificationType) -> None:
    target_type = (
        "project" if event_type.value.startswith(("project", "membership")) else "checklist_module"
    )
    email = compose_notification(
        event_type=event_type,
        target_type=target_type,
        target_id=PROJECT if target_type == "project" else MODULE,
        project_id=PROJECT,
        to="dev@example.com",
        settings=_settings("production"),
    )
    assert email.to == "dev@example.com"
    assert email.subject == f"{MESSAGES[event_type][0]} | AskRepo"
    assert "https://askrepo.internal/settings/notifications" in email.body
    expected = (
        f"https://askrepo.internal/projects/{PROJECT}"
        if target_type == "project"
        else f"https://askrepo.internal/checklist/{MODULE}"
    )
    assert f"Open: {expected}" in email.body

    assert email.html is not None
    assert expected in email.html
    assert f"{BASE_URL}/settings/notifications" in email.html
    for snippet in FORBIDDEN_HTML_SNIPPETS:
        assert snippet not in email.html
    for href in _hrefs(email.html):
        assert href.startswith(BASE_URL)


def test_the_composer_cannot_receive_content() -> None:
    """A "helpful preview" must be a signature change, not a quiet extra field."""
    assert set(inspect.signature(compose_notification).parameters) == {
        "event_type",
        "target_type",
        "target_id",
        "project_id",
        "to",
        "settings",
    }
    assert set(inspect.signature(compose_password_reset).parameters) == {
        "raw_token",
        "to",
        "settings",
    }


def test_the_reset_link_carries_the_token_in_the_fragment() -> None:
    email = compose_password_reset(
        raw_token="abc-123_XYZ", to="dev@example.com", settings=_settings("production")
    )
    assert email.subject == "Reset your password | AskRepo"
    assert "https://askrepo.internal/reset-password#token=abc-123_XYZ" in email.body
    assert "?token=" not in email.body
    assert "30 minutes" in email.body

    assert email.html is not None
    assert "https://askrepo.internal/reset-password#token=abc-123_XYZ" in email.html
    assert "30 minutes" in email.html
    for snippet in FORBIDDEN_HTML_SNIPPETS:
        assert snippet not in email.html
    for href in _hrefs(email.html):
        assert href.startswith(BASE_URL)


def _hrefs(html: str) -> list[str]:
    """Every `href="..."` value in a rendered template, in document order."""
    return re.findall(r'href="([^"]*)"', html)


def test_the_environment_autoescapes() -> None:
    assert _ENVIRONMENT.autoescape
    template = _ENVIRONMENT.from_string("{{ value }}")
    assert template.render(value="<b>hi</b>") == "&lt;b&gt;hi&lt;/b&gt;"
