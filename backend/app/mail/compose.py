"""The only code that turns a delivery into an email — and what it cannot see.

`docs/PRD.md` §9: an outbound message carries an event type and a link, never content
derived from an indexed repository. Repository names, module names and paths are
inventory of the organization's private codebases. The signatures below are the
enforcement: there is no parameter through which `details`, a name or a path could
arrive, and `tests/test_mail_compose.py` pins the parameter sets. See
`.claude/rules/mail.md`.

Each function renders an HTML alternative from `app/mail/templates/` alongside the
plain-text body, from the same fixed sentence and the same link — no template is handed
anything the text body does not already carry. The templates load no remote or embedded
asset (no image, no external stylesheet, no script), so the HTML part cannot itself
become a second egress path.
"""

import uuid

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from app.config import Settings
from app.core.notifications import NotificationType
from app.mail.sender import OutboundEmail

# Autoescaping is what keeps a value nobody has vetted from becoming markup: every value
# handed to a template here is already a fixed sentence or a link built from ids (see the
# module docstring), but the escaping is a property of the environment, not of
# remembering to call `|e` at every call site. `StrictUndefined` turns a template typo —
# a variable a `.html` file references that the composer never passed — into a render
# failure instead of a silently blank line. `tests/test_mail_compose.py` asserts both.
_ENVIRONMENT = Environment(
    loader=PackageLoader("app.mail", "templates"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# (the subject's {message}, the body's one sentence). Fixed strings: the subject is the
# most visible part of an email and carries the same ban as the body.
MESSAGES: dict[NotificationType, tuple[str, str]] = {
    NotificationType.PROJECT_READY: (
        "Index finished",
        "A project you are a member of finished indexing.",
    ),
    NotificationType.PROJECT_FAILED: (
        "Index failed",
        "A project you are a member of failed to index.",
    ),
    NotificationType.PROJECT_REINDEX_FINISHED: (
        "Reindex finished",
        "A project you are a member of finished reindexing.",
    ),
    NotificationType.PROJECT_REINDEX_FAILED: (
        "Reindex failed",
        "A project you are a member of failed to reindex. The previous index is still serving.",
    ),
    NotificationType.CHECKLIST_CHANGE_SET_PENDING: (
        "Checklist change set awaiting review",
        "A checklist change set is waiting for someone to review it.",
    ),
    NotificationType.CHECKLIST_CHANGE_SET_APPLIED: (
        "Checklist change set applied",
        "A checklist change set was applied.",
    ),
    NotificationType.CHECKLIST_CHANGE_SET_DISCARDED: (
        "Checklist change set discarded",
        "A checklist change set was discarded.",
    ),
    NotificationType.MOCK_DATA_CHANGE_SET_PENDING: (
        "Mock data change set awaiting review",
        "A mock data change set is waiting for someone to review it.",
    ),
    NotificationType.MOCK_DATA_CHANGE_SET_APPLIED: (
        "Mock data change set applied",
        "A mock data change set was applied.",
    ),
    NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED: (
        "Mock data change set discarded",
        "A mock data change set was discarded.",
    ),
    NotificationType.MEMBERSHIP_GRANTED: (
        "You were added to a project",
        "You were added to a project.",
    ),
}

RESET_MESSAGE = "Reset your password"


def _base(settings: Settings) -> str:
    return settings.app_base_url.rstrip("/")


def compose_subject(message: str, *, settings: Settings) -> str:
    """`[{env}] {message} | {app name}`, with the tag omitted in production."""
    title = f"{message} | {settings.mail_app_name}"
    if settings.app_env == "production":
        return title
    return f"[{settings.app_env}] {title}"


def _link(target_type: str | None, target_id: uuid.UUID | None, project_id: uuid.UUID) -> str:
    # The Mock Data tab lives on the module page, so both change-set kinds link there.
    if target_type == "checklist_module" and target_id is not None:
        return f"/checklist/{target_id}"
    return f"/projects/{project_id}"


def compose_notification(
    *,
    event_type: NotificationType,
    target_type: str | None,
    target_id: uuid.UUID | None,
    project_id: uuid.UUID,
    to: str,
    settings: Settings,
) -> OutboundEmail:
    """One notification email: a fixed sentence and a link that reveals only an id."""
    subject_message, sentence = MESSAGES[event_type]
    base = _base(settings)
    link_url = f"{base}{_link(target_type, target_id, project_id)}"
    settings_url = f"{base}/settings/notifications"
    body = (
        f"{sentence}\n\n"
        f"Open: {link_url}\n\n"
        "—\n"
        "You are receiving this because email notifications are on for this event.\n"
        f"Manage them: {settings_url}\n"
    )
    template = _ENVIRONMENT.get_template("notification.html")
    html = template.render(
        subject=compose_subject(subject_message, settings=settings),
        app_name=settings.mail_app_name,
        sentence=sentence,
        link_url=link_url,
        settings_url=settings_url,
    )
    return OutboundEmail(
        to=to,
        subject=compose_subject(subject_message, settings=settings),
        body=body,
        html=html,
    )


def compose_password_reset(*, raw_token: str, to: str, settings: Settings) -> OutboundEmail:
    """The reset link, with the token in the fragment so no server ever logs it."""
    minutes = settings.password_reset_token_ttl_minutes
    link_url = f"{_base(settings)}/reset-password#token={raw_token}"
    body = (
        "Someone asked to reset the password for this account.\n\n"
        f"Choose a new password: {link_url}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not ask for "
        "this, ignore this email — your password has not changed.\n"
    )
    template = _ENVIRONMENT.get_template("password_reset.html")
    html = template.render(
        subject=compose_subject(RESET_MESSAGE, settings=settings),
        app_name=settings.mail_app_name,
        link_url=link_url,
        minutes=minutes,
    )
    return OutboundEmail(
        to=to,
        subject=compose_subject(RESET_MESSAGE, settings=settings),
        body=body,
        html=html,
    )
