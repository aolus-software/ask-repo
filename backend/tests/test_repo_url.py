"""Clone-URL validation.

The rebinding test is the reason this module exists: validating an address and then
letting git resolve the name again validates one thing and clones another.
"""

import pytest

from app.core.repo_url import RepoUrlRejected, Resolver, validate_repo_url

ALLOWLIST = ["github.com", "gitlab.com"]


def resolver(*addresses: str) -> Resolver:
    """A resolver returning fixed addresses, so no test touches real DNS."""

    async def _resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return _resolve


async def test_accepts_an_allowlisted_public_host() -> None:
    result = await validate_repo_url(
        "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=resolver("140.82.121.4")
    )
    assert result.host == "github.com"
    assert result.pinned_ip == "140.82.121.4"
    assert result.port == 443


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/acme/repo.git",
        "git://github.com/acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "file:///etc/passwd",
    ],
)
async def test_rejects_non_https_schemes(url: str) -> None:
    with pytest.raises(RepoUrlRejected, match="https"):
        await validate_repo_url(url, allowlist=ALLOWLIST, resolve=resolver("140.82.121.4"))


async def test_rejects_a_host_not_on_the_allowlist() -> None:
    with pytest.raises(RepoUrlRejected, match="not allowed"):
        await validate_repo_url(
            "https://evil.example/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("140.82.121.4"),
        )


async def test_userinfo_cannot_smuggle_a_host() -> None:
    """`https://github.com@10.0.0.1/` has hostname 10.0.0.1, not github.com."""
    with pytest.raises(RepoUrlRejected, match="not allowed"):
        await validate_repo_url(
            "https://github.com@10.0.0.1/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("10.0.0.1"),
        )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "172.16.4.2",  # RFC1918
        "192.168.1.10",  # RFC1918
        "169.254.169.254",  # link-local — the cloud metadata endpoint
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
    ],
)
async def test_rejects_private_and_reserved_addresses(address: str) -> None:
    with pytest.raises(RepoUrlRejected, match="private"):
        await validate_repo_url(
            "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=resolver(address)
        )


async def test_rejects_when_any_record_is_private() -> None:
    """A host resolving to one public and one private address is rejected, not raced."""
    with pytest.raises(RepoUrlRejected, match="private"):
        await validate_repo_url(
            "https://github.com/acme/repo.git",
            allowlist=ALLOWLIST,
            resolve=resolver("140.82.121.4", "10.0.0.5"),
        )


async def test_rejects_when_the_host_does_not_resolve() -> None:
    async def _fails(host: str, port: int) -> list[str]:
        raise OSError("Name or service not known")

    with pytest.raises(RepoUrlRejected, match="did not resolve"):
        await validate_repo_url(
            "https://github.com/acme/repo.git", allowlist=ALLOWLIST, resolve=_fails
        )
