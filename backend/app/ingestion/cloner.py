"""Cloning a repository, safely.

Every flag below closes a specific hole from `docs/PRD.md` §9. Read the comments
before changing any of them — none is stylistic.
"""

import asyncio
import contextlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.crypto import scrub
from app.core.repo_url import ValidatedRepoUrl
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

logger = logging.getLogger(__name__)

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
        # Never consult the host's credential store or prompt for one. `clone`
        # inserts the PAT helper (when there is a PAT) immediately before
        # "clone" below — after this reset, never before it. `credential.helper`
        # is git's one multi-valued config key where an empty value resets the
        # accumulated list rather than appending, and git applies `-c` options in
        # argv order, so a helper added before this reset would be cleared right
        # back out.
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


def _directory_size(path: Path) -> int:
    """Bytes on disk under `path`, following no symlinks.

    Plain and synchronous — the walk is blocking I/O, so callers run it via
    `asyncio.to_thread` rather than awaiting it directly. A large repository's
    directory tree can take real time to walk, and stalling the event loop for
    that long would delay lease heartbeats for other jobs the same worker is
    servicing.

    Entries that vanish between being listed and being stat'd are skipped rather
    than raising: git churns temporary pack and lock files throughout a clone,
    and multiple polls only happen for large repositories — exactly the ones
    this function is watching.
    """
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


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

    Any unexpected error here disables cap enforcement for the rest of this
    clone rather than propagating: a watchdog hiccup should not turn into an
    unclassified exception that the consumer cannot branch on, and the
    post-communicate size check on the success path is the backstop for a clone
    that finishes normally anyway.
    """
    try:
        while process.returncode is None:
            await asyncio.sleep(SIZE_POLL_SECONDS)
            if not destination.exists():
                continue
            size = await asyncio.to_thread(_directory_size, destination)
            if size > max_bytes:
                state.killed_for_size = True
                process.kill()
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Size-cap watchdog failed; cap enforcement disabled for this clone.",
            exc_info=True,
        )


def _is_valid_commit_sha(value: str) -> bool:
    """Whether `value` looks like a real, fully-resolved git commit hash."""
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


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
        # HOME is deliberately absent, which is what keeps git from consulting
        # ~/.gitconfig. But /etc/gitconfig is read regardless of HOME, and a
        # system-level `url.<base>.insteadOf` there could rewrite the clone URL
        # after Task 3 already validated it — this is the other half of that
        # same control.
        "GIT_CONFIG_NOSYSTEM": "1",
        # TERMINAL_MARKERS matches the English strings git prints, which this
        # minimal environment produces only because LANG/LC_ALL happen to be
        # unset. Pinning the locale explicitly makes that a decision rather than
        # an accident some later change could break silently.
        "LC_ALL": "C",
    }
    command = build_git_command(validated, branch=branch, destination=destination)
    if pat:
        # The PAT goes in the environment, never on the command line: `ps` output
        # is readable by other processes and git echoes its argv in some errors.
        environment["ASKREPO_PAT"] = pat
        # Must land after `build_git_command`'s `-c credential.helper=` reset —
        # see the comment on that line. Computing the index from "clone" rather
        # than hard-coding a position keeps `build_git_command` free to change
        # shape without this silently breaking.
        clone_index = command.index("clone")
        command[clone_index:clone_index] = [
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
    if await asyncio.to_thread(_directory_size, destination) > max_bytes:
        raise TerminalIngestionError("Repository is too large to index.")

    head = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        cwd=destination,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    sha_bytes, head_stderr_bytes = await head.communicate()
    commit_sha = sha_bytes.decode().strip()

    if head.returncode != 0 or not _is_valid_commit_sha(commit_sha):
        # The working tree is on disk and nothing about this says the URL, the
        # branch, or the PAT was wrong — a re-clone may well succeed.
        head_stderr = scrub(head_stderr_bytes.decode(errors="replace"), pat)
        raise RetryableIngestionError(
            f"Could not resolve the cloned commit: {head_stderr.strip()[:500]}"
        )

    return CloneResult(path=destination, commit_sha=commit_sha)
