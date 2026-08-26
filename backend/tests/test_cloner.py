"""Clone mechanics. The command-shape tests are security tests: each flag closes a
specific hole named in docs/PRD.md §9."""

import subprocess
from pathlib import Path

import pytest

from app.core.repo_url import ValidatedRepoUrl
from app.ingestion.cloner import build_git_command, clone
from app.ingestion.errors import TerminalIngestionError

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
    """`ps` output is world-readable; the PAT goes in the environment instead."""
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
