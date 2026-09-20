"""The forgetting guard, in both directions.

Mirrors `tests/test_audit_coverage.py`. A catalogue member with no write site is a
notification nobody can receive; a write site naming something outside the catalogue
is a row the frontend cannot render. Both fail silently in production and loudly here.
"""

import re
from pathlib import Path

from app.core.notifications import NotificationType

APP = Path(__file__).resolve().parent.parent / "app"


def _raised_members() -> set[str]:
    """Every `NotificationType.X` named anywhere under `app/`, minus the catalogue."""
    pattern = re.compile(r"NotificationType\.([A-Z_]+)")
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        if path.name == "notifications.py" and path.parent.name == "core":
            continue
        found.update(pattern.findall(path.read_text()))
    return found


def test_every_catalogue_member_has_a_write_site() -> None:
    missing = {event.name for event in NotificationType} - _raised_members()
    assert not missing, f"declared but never raised: {sorted(missing)}"


def test_every_write_site_names_a_catalogue_member() -> None:
    known = {event.name for event in NotificationType}
    unknown = _raised_members() - known
    assert not unknown, f"raised but not in the catalogue: {sorted(unknown)}"
