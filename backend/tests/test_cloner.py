"""Clone mechanics. The command-shape tests are security tests: each flag closes a
specific hole named in docs/PRD.md §9."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.core.repo_url import ValidatedRepoUrl
from app.ingestion import cloner
from app.ingestion.cloner import _SizeCapState, build_git_command, clone
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

VALIDATED = ValidatedRepoUrl(
    url="https://github.com/acme/repo.git",
    host="github.com",
    port=443,
    pinned_ip="140.82.121.4",
)


def test_git_is_pinned_to_the_validated_address() -> None:
    """Without this, git resolves the host again and DNS rebinding defeats Task 3."""
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert "http.curloptResolve=github.com:443:140.82.121.4" in command


def test_redirects_are_disabled() -> None:
    """A redirect to an internal host would resolve unpinned."""
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert "http.followRedirects=false" in command


def test_the_clone_is_shallow_and_single_branch() -> None:
    command = build_git_command(VALIDATED, branch="develop", destination=Path("/tmp/x"))
    assert "--depth" in command and "1" in command
    assert "--single-branch" in command
    assert "--branch" in command
    assert "develop" in command


def test_the_pat_is_never_in_the_command_line() -> None:
    """`ps` output is world-readable; the PAT goes in the environment instead.

    `build_git_command` takes no `pat` parameter, so this cannot fail — it
    documents intent only. `test_the_pat_helper_is_installed_after_the_reset`
    below is the real regression gate: it inspects the argv `clone` actually
    builds, which is the one that reaches `ps`.
    """
    command = build_git_command(VALIDATED, branch="main", destination=Path("/tmp/x"))
    assert not any("ghp_" in part for part in command)


async def test_clone_copies_a_real_repository(tmp_path: Path) -> None:
    """Against a local fixture repo, bypassing validation — that is tested separately."""
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "hello.py").write_text("def hello() -> str:\n    return 'hi'\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")
    destination = tmp_path / "clone"

    result = await clone(
        local,
        branch="main",
        destination=destination,
        pat=None,
        timeout_seconds=60,
        max_bytes=100_000_000,
    )

    assert (result.path / "hello.py").exists()
    assert len(result.commit_sha) == 40


async def test_a_missing_branch_is_terminal(tmp_path: Path) -> None:
    """Retrying will not conjure the branch, so it must not enter the retry chain."""
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    with pytest.raises(TerminalIngestionError):
        await clone(
            local,
            branch="nonexistent",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=100_000_000,
        )


async def test_a_repository_over_the_cap_is_terminal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "big.bin").write_bytes(b"0" * 2_000_000)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )

    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    with pytest.raises(TerminalIngestionError, match="too large"):
        await clone(
            local,
            branch="main",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=1_000,
        )


async def test_the_pat_helper_is_installed_after_the_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression gate for the credential-helper ordering bug.

    `credential.helper` is git's one multi-valued config key where an empty
    value resets the accumulated list rather than appending, and git applies
    `-c` options in argv order. If the PAT helper ever lands before
    `build_git_command`'s `-c credential.helper=` reset again, that reset would
    silently clear it and every private-repo clone would fail closed with a
    misleading "could not read Username" error. This inspects the real argv
    `clone` builds — the one that reaches `ps` — not `build_git_command` alone.
    """
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )
    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    captured: list[str] = []
    real_exec = asyncio.create_subprocess_exec

    async def spy(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        if args and args[0] == "git" and "clone" in args:
            captured.extend(args)
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    await clone(
        local,
        branch="main",
        destination=tmp_path / "clone",
        pat="ghp_SECRET123",
        timeout_seconds=60,
        max_bytes=100_000_000,
    )

    assert not any("ghp_SECRET123" in part for part in captured)
    reset_index = captured.index("credential.helper=")
    helper_index = next(
        index for index, part in enumerate(captured) if part.startswith("credential.helper=!")
    )
    assert helper_index > reset_index


async def test_scrub_removes_the_pat_from_a_failing_clones_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The most important secret-containment behaviour in this module: a PAT that
    leaks into git's stderr must never reach the raised error message.
    """

    class _FakeProcess:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"fatal: Authentication failed for token ghp_SECRET123\n"

        def kill(self) -> None:
            pass

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    remote = ValidatedRepoUrl(
        url="https://example.com/r.git", host="example.com", port=443, pinned_ip="1.2.3.4"
    )

    with pytest.raises(TerminalIngestionError) as exc_info:
        await clone(
            remote,
            branch="main",
            destination=tmp_path / "clone",
            pat="ghp_SECRET123",
            timeout_seconds=60,
            max_bytes=100_000_000,
        )

    assert "ghp_SECRET123" not in str(exc_info.value)


async def test_a_non_terminal_clone_failure_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transient trouble — a network blip, a provider 5xx — must not be treated the
    same as a bad URL or a missing branch: it has to re-enter the retry chain.
    """

    class _FakeProcess:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"fatal: unable to access remote: Could not resolve host\n"

        def kill(self) -> None:
            pass

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    remote = ValidatedRepoUrl(
        url="https://example.com/r.git", host="example.com", port=443, pinned_ip="1.2.3.4"
    )

    with pytest.raises(RetryableIngestionError):
        await clone(
            remote,
            branch="main",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=100_000_000,
        )


async def test_rev_parse_failure_after_a_successful_clone_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clone that finishes but whose HEAD cannot be resolved (a corrupt tree, git
    missing from PATH) must not be reported as success with an empty commit sha.
    """
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    (source / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=source,
        check=True,
    )
    local = ValidatedRepoUrl(url=str(source), host="localhost", port=443, pinned_ip="127.0.0.1")

    real_exec = asyncio.create_subprocess_exec

    async def fail_rev_parse(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        if args[:2] == ("git", "rev-parse"):
            args = ("git", "rev-parse", "--verify", "does-not-exist-xyz")
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_rev_parse)

    with pytest.raises(RetryableIngestionError):
        await clone(
            local,
            branch="main",
            destination=tmp_path / "clone",
            pat=None,
            timeout_seconds=60,
            max_bytes=100_000_000,
        )


async def test_the_watchdog_kills_a_clone_that_outgrows_the_cap_mid_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises `_enforce_size_cap` directly: a process that has not exited on its
    own keeps the watcher's loop running until it notices the working tree is
    over the cap and kills it. This is the mid-flight half of the size cap; the
    other half — a clone that finishes fast and over-sized — is covered by
    `test_a_repository_over_the_cap_is_terminal`.
    """
    monkeypatch.setattr(cloner, "SIZE_POLL_SECONDS", 0.01)

    destination = tmp_path / "clone"
    destination.mkdir()
    (destination / "big.bin").write_bytes(b"0" * 2_000)

    class _NeverExitsProcess:
        returncode: int | None = None
        killed = False

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

    process = _NeverExitsProcess()
    state = _SizeCapState()

    await cloner._enforce_size_cap(destination, process, max_bytes=1_000, state=state)  # type: ignore[arg-type]  # test double stands in for asyncio.subprocess.Process

    assert state.killed_for_size is True
    assert process.killed is True
