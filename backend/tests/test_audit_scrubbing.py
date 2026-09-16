"""The two content bans, as tests.

An audit trail is by definition something an operator reads, so it is a destination
on the scrub path rather than an exception to it (`docs/PRD.md` §9).
"""

from httpx import AsyncClient

from app.core.audit import AuditEventType, repo_url_host
from tests.conftest import AuditRows

PAT = "ghp_exampletokenvalue0123456789"


def test_repo_url_host_drops_userinfo() -> None:
    """A PAT is embedded in the clone URL, so the host is derived, never trimmed.

    String-trimming is what goes wrong under a URL shape nobody anticipated; parsing
    and keeping only the hostname cannot carry credentials through by construction.
    """
    assert repo_url_host(f"https://{PAT}@github.com/acme/private.git") == "github.com"
    assert repo_url_host("https://github.com/acme/private.git") == "github.com"
    assert repo_url_host("not-a-url") is None


async def test_project_create_stores_the_host_not_the_credentialed_url(
    authed_client: AsyncClient, audit_rows: AuditRows
) -> None:
    response = await authed_client.post(
        "/projects",
        json={"repoUrl": "https://github.com/acme/private.git", "pat": PAT},
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.PROJECT_CREATED)
    assert len(rows) == 1
    serialised = str(rows[0].details)
    assert PAT not in serialised
    assert "github.com/acme/private" not in serialised
    assert rows[0].details["changed"]["repoUrlHost"]["after"] == "github.com"
    assert rows[0].details["patSupplied"] is True
