"""Clone-URL validation — the control `docs/PRD.md` §9 calls the sharpest risk.

`repo_url` is user-supplied and handed to a network client running *inside* the
corporate network, where `10.0.x.x`, `169.254.169.254`, and internal service names
resolve. This is a security control, not input hygiene.

The subtle part is DNS rebinding. Validating an address and then invoking
`git clone` lets git perform its own lookup, so an attacker controlling DNS can
return a public address for the check and a private one a moment later. This module
therefore returns the address it validated, and the cloner pins git to it via
`http.curloptResolve` — see `app/ingestion/cloner.py`.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str, int], Awaitable[list[str]]]

HTTPS_PORT = 443


class RepoUrlRejected(Exception):
    """A repository URL failed validation. The reason is safe to show a caller."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedRepoUrl:
    """A URL cleared for cloning, plus the address it was cleared against.

    `pinned_ip` is the whole point: the cloner must use this address rather than
    resolving the host again, or the validation above it means nothing.
    """

    url: str
    host: str
    port: int
    pinned_ip: str


def _is_public(address: str) -> bool:
    """Whether an address is globally routable.

    `is_global` covers loopback, private, link-local, unspecified, reserved, and
    multicast in one check for both address families — enumerating ranges by hand
    is how `100.64.0.0/10` gets forgotten.
    """
    return ipaddress.ip_address(address).is_global


async def _system_resolver(host: str, port: int) -> list[str]:
    """Resolve a host to every A/AAAA address the system returns."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    # `str()`: typeshed's sockaddr union includes the AF_NETLINK/AF_UNIX shape
    # (int, bytes), so mypy sees `str | int` here even though TCP lookups never
    # take that branch.
    return [str(info[4][0]) for info in infos]


async def validate_repo_url(
    url: str, *, allowlist: Iterable[str], resolve: Resolver | None = None
) -> ValidatedRepoUrl:
    """Clear a repository URL for cloning, or raise `RepoUrlRejected`.

    `resolve` is injected so tests never touch real DNS and can simulate a host
    that returns mixed public and private records.
    """
    resolve = resolve or _system_resolver
    parts = urlsplit(url)

    if parts.scheme != "https":
        raise RepoUrlRejected("Only https:// repository URLs are accepted.")

    # `.hostname` rather than `.netloc`: it strips userinfo, so
    # `https://github.com@10.0.0.1/` reads as 10.0.0.1 and not as github.com.
    host = parts.hostname
    if not host:
        raise RepoUrlRejected("The repository URL has no host.")

    allowed = {entry.strip().lower() for entry in allowlist}
    if host.lower() not in allowed:
        raise RepoUrlRejected(
            f"Host {host!r} is not allowed. Allowed hosts: {', '.join(sorted(allowed))}."
        )

    port = parts.port or HTTPS_PORT

    try:
        addresses = await resolve(host, port)
    except OSError as error:
        raise RepoUrlRejected(f"Host {host!r} did not resolve.") from error

    if not addresses:
        raise RepoUrlRejected(f"Host {host!r} did not resolve.")

    # Every record, not just the one that will be used: a host answering with one
    # public and one private address must be rejected rather than raced.
    for address in addresses:
        if not _is_public(address):
            raise RepoUrlRejected(
                f"Host {host!r} resolves to a private or reserved address and cannot be cloned."
            )

    return ValidatedRepoUrl(url=url, host=host, port=port, pinned_ip=addresses[0])
