"""`docs/PRD.md` §7: "read scoping happens in exactly one function, confirmed by grep".

A criterion confirmed by a human running grep is a criterion that stops being
confirmed. This is that grep, as a test.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# The only module allowed to interpret membership.
ACCESS = APP / "core" / "access.py"
# Where the snapshot is built, and where the rows are read from.
ALLOWED_MEMBERSHIP_READERS = {
    ACCESS,
    APP / "core" / "middleware.py",
    APP / "core" / "grant_cache.py",
    APP / "repositories" / "membership.py",
    APP / "repositories" / "role.py",
    APP / "services" / "membership.py",
    APP / "services" / "role.py",
    APP / "models" / "membership.py",
    APP / "models" / "__init__.py",
}


def _python_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def test_nothing_else_queries_the_membership_table() -> None:
    """A service that joins `project_memberships` itself is a second enforcement
    point, which is exactly what §2's phase-2 readiness goal exists to prevent."""
    offenders = [
        path.relative_to(APP)
        for path in _python_files()
        if path not in ALLOWED_MEMBERSHIP_READERS
        and "ProjectMembership" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"membership read outside the access core: {offenders}"


def test_no_module_compares_created_by_to_an_actor() -> None:
    """`created_by` is attribution. After Phase 2.1 it gates nothing — the six inline
    gates it used to drive are now `require_permission` calls."""
    pattern = re.compile(r"created_by\s*[!=]=\s*actor\.id|actor\.id\s*[!=]=\s*\w+\.created_by")
    offenders = [
        path.relative_to(APP)
        for path in _python_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"created_by used as an authorization gate: {offenders}"
