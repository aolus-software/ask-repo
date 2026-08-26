"""Cloning a repository, safely.

Every flag below closes a specific hole from `docs/PRD.md` §9. Read the comments
before changing any of them — none is stylistic.
"""

import asyncio
import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.crypto import scrub
from app.core.repo_url import ValidatedRepoUrl
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

# Fragments git prints for failures no amount of retrying will fix.
TERMINAL_MARKERS = (
    "Remote branch",
    "not found in upstream",
    "Authentication failed",
    "could not read Username",
    "Repository not found",
    "access denied",
)

SIZE_POLL_SECONDS = 1.0


def build_git_command(validated: ValidatedRepoUrl, *, branch: str, destination: Path) -> list[str]:
    """The clone command, with the safety configuration baked in.

    Separated from `clone` so the flags can be asserted without running git.
    """
    return [
        "git",
        # Pin git to the address Task 3 validated. Without this git resolves the
        # host itself, and an attacker controlling DNS returns a public address
        # for the check and a private one here.
        "-c",
        f"http.curloptResolve={validated.host}:{validated.port}:{validated.pinned_ip}",
        # curl follows redirects, and a redirect to another host resolves unpinned.
        # The cost is that renamed repositories need their canonical URL.
        "-c",
        "http.followRedirects=false",
        # Never consult the host's credential store or prompt for one.
        "-c",
        "credential.helper=",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        branch,
        validated.url,
        str(destination),
    ]


@dataclass(frozen=True, slots=True)
class CloneResult:
    """Where the working copy landed, and what commit it is at."""

    path: Path
    commit_sha: str


@dataclass(slots=True)
class _SizeCapState:
    """A flag the watcher and `clone` both close over.

    `_enforce_size_cap` runs as a background task that `clone` cancels once the
    git process exits. A return value cannot survive that cancellation, so the two
    coroutines share this instead of `clone` trying to inspect the cancelled
    task's result.
    """

    killed_for_size: bool = False


async def _directory_size(path: Path) -> int:
    """Bytes on disk under `path`, following no symlinks."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


async def _enforce_size_cap(
    destination: Path,
    process: asyncio.subprocess.Process,
    max_bytes: int,
    state: _SizeCapState,
) -> None:
    """Kill the clone if it outgrows the cap while it is still running.

    `--depth 1` bounds history but not the working tree, so a repository that is
    simply enormous at HEAD needs watching rather than trusting. A clone that
    finishes before this ever wakes up is caught separately, by `clone` checking
    the final size on the success path.
    """
    while process.returncode is None:
        await asyncio.sleep(SIZE_POLL_SECONDS)
        if destination.exists() and await _directory_size(destination) > max_bytes:
            state.killed_for_size = True
            process.kill()
            return


async def clone(
    validated: ValidatedRepoUrl,
    *,
    branch: str,
    destination: Path,
    pat: str | None,
    timeout_seconds: int,
    max_bytes: int,
) -> CloneResult:
    """Clone a validated repository into `destination`.

    Raises `TerminalIngestionError` for anything a retry cannot fix, and
    `RetryableIngestionError` for transient trouble.
    """
    if destination.exists():
        # Re-running a job must start clean: a half-written tree from a killed
        # attempt would otherwise be indexed as if it were complete.
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    environment = {
        # Never block on a credential prompt — a hung clone holds its partition
        # and its lease until both expire.
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    command = build_git_command(validated, branch=branch, destination=destination)
    if pat:
        # The PAT goes in the environment, never on the command line: `ps` output
        # is readable by other processes and git echoes its argv in some errors.
        environment["ASKREPO_PAT"] = pat
        command[1:1] = [
            "-c",
            'credential.helper=!f() { echo "username=x-access-token"; '
            'echo "password=$ASKREPO_PAT"; }; f',
        ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    state = _SizeCapState()
    watcher = asyncio.create_task(_enforce_size_cap(destination, process, max_bytes, state))

    try:
        _, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as error:
        process.kill()
        raise TerminalIngestionError(f"Cloning timed out after {timeout_seconds}s.") from error
    finally:
        watcher.cancel()
        # Wait for the watcher to actually stop before touching `state`. Without
        # this, a slow watcher iteration could still be mid-check — reading disk,
        # about to set the flag — when we read it a line below.
        with contextlib.suppress(asyncio.CancelledError):
            await watcher

    if state.killed_for_size:
        raise TerminalIngestionError("Repository is too large to index.")

    # Scrubbed before it goes anywhere: clone stderr is the likeliest place a
    # token surfaces, and this text lands in Project.error.
    stderr = scrub(stderr_bytes.decode(errors="replace"), pat)

    if process.returncode != 0:
        if any(marker in stderr for marker in TERMINAL_MARKERS):
            raise TerminalIngestionError(f"Clone failed: {stderr.strip()[:500]}")
        raise RetryableIngestionError(f"Clone failed: {stderr.strip()[:500]}")

    # The watcher only catches a clone that is still running when it wakes up
    # every SIZE_POLL_SECONDS. A clone against a small, fast source can finish
    # before the watcher's first sleep returns, so a repository that ends up over
    # the cap needs checking again here — on the success path, not only when git
    # itself reported failure.
    if await _directory_size(destination) > max_bytes:
        raise TerminalIngestionError("Repository is too large to index.")

    head = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        cwd=destination,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    sha_bytes, _ = await head.communicate()
    return CloneResult(path=destination, commit_sha=sha_bytes.decode().strip())
