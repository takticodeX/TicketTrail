"""GitClient against a real bare repository built in a temp directory."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git.cmd import Git

from app.integrations.git.client import (
    GitClient,
    GitCredentials,
    GitError,
    GitNotFoundError,
    scrub,
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def remote(tmp_path: Path) -> str:
    """A bare repo with branches main (HEAD) and feature/x."""
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git(
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "first AB#1",
        cwd=work,
    )
    _git("branch", "feature/x", cwd=work)
    bare = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
    return bare.as_uri()


def test_ls_remote_lists_branches_and_default(remote: str) -> None:
    info = GitClient(None, timeout=30, allowed_protocols="file").ls_remote(remote)
    assert info.branches == ["feature/x", "main"]
    assert info.default_branch == "main"


def test_missing_repository_is_not_found(tmp_path: Path) -> None:
    client = GitClient(None, timeout=30, allowed_protocols="file")
    with pytest.raises(GitNotFoundError):
        client.ls_remote((tmp_path / "missing.git").as_uri())


def test_only_https_is_allowed_by_default(remote: str) -> None:
    with pytest.raises(GitError):
        GitClient(None, timeout=30).ls_remote(remote)


def test_credentials_go_through_the_environment_not_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute(self: Git, command: list[str], **kwargs: Any) -> str:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return ""

    monkeypatch.setattr(Git, "execute", fake_execute)
    client = GitClient(GitCredentials("pat", "s3cr3t-token"), timeout=30)
    client.ls_remote("https://dev.azure.com/acme/proj/_git/repo")

    assert not any("s3cr3t" in part for part in captured["command"])
    assert not any("Authorization" in part for part in captured["command"])
    env = captured["env"]
    headers = [v for k, v in env.items() if k.startswith("GIT_CONFIG_VALUE_")]
    # base64("pat:s3cr3t-token")
    assert "Authorization: Basic cGF0OnMzY3IzdC10b2tlbg==" in headers
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ALLOW_PROTOCOL"] == "https"


def test_scrub_removes_secrets_and_url_credentials() -> None:
    text = (
        "fatal: unable to access 'https://user:hunter2@example.com/r.git/': "
        "Authorization: Basic abc123== s3cr3t"
    )
    cleaned = scrub(text, "s3cr3t")
    assert "hunter2" not in cleaned
    assert "abc123" not in cleaned
    assert "s3cr3t" not in cleaned
    assert "https://***@example.com" in cleaned
