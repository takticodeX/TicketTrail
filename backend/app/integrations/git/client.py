"""Plain Git over HTTPS through the git CLI (via GitPython).

Credentials are handed to git as an http.extraHeader through GIT_CONFIG_*
environment variables, so they never appear in the remote URL, in .git/config,
on the command line (visible in the process list) or in logs.
"""

import base64
import re
import sys
from dataclasses import dataclass, field

from git.cmd import Git
from git.exc import GitCommandError

DEFAULT_ALLOWED_PROTOCOLS = "https"


@dataclass(frozen=True)
class GitCredentials:
    username: str
    secret: str

    def header(self) -> str:
        token = base64.b64encode(f"{self.username}:{self.secret}".encode()).decode()
        return f"Authorization: Basic {token}"


@dataclass(frozen=True)
class RemoteInfo:
    branches: list[str] = field(default_factory=list)
    default_branch: str | None = None


class GitError(Exception):
    """A git command failed. The message is safe to show and store."""


class GitAuthError(GitError):
    pass


class GitNotFoundError(GitError):
    pass


class GitTimeoutError(GitError):
    pass


_SECRET_PATTERNS = [
    re.compile(r"(Authorization:\s*\w+\s+)\S+", re.IGNORECASE),
    re.compile(r"(https?://)[^/\s:@]+(?::[^/\s@]*)?@"),  # user[:password]@ in URLs
]


def scrub(text: str, *secrets: str) -> str:
    """Remove credentials from git output before it is shown or stored."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "***" + ("@" if "@" in m.group(0) else ""), text)
    return text


def _classify(stderr: str) -> type[GitError]:
    lowered = stderr.lower()
    if any(
        marker in lowered
        for marker in (
            "authentication failed",
            "could not read username",
            "could not read password",
            "the requested url returned error: 401",
            "the requested url returned error: 403",
            "access denied",
            "invalid username or password",
        )
    ):
        return GitAuthError
    if any(
        marker in lowered
        for marker in ("not found", "error: 404", "does not appear to be a git repository")
    ):
        return GitNotFoundError
    return GitError


class GitClient:
    def __init__(
        self,
        credentials: GitCredentials | None,
        *,
        timeout: float,
        allowed_protocols: str = DEFAULT_ALLOWED_PROTOCOLS,
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._allowed_protocols = allowed_protocols

    def _env(self) -> dict[str, str]:
        config = [
            ("credential.helper", ""),  # never use a stored credential helper
            # Abort transfers that stall below 1 KB/s, on every platform.
            ("http.lowSpeedLimit", "1000"),
            ("http.lowSpeedTime", str(max(int(self._timeout), 1))),
        ]
        if self._credentials is not None:
            config.append(("http.extraHeader", self._credentials.header()))
        env = {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "GIT_ALLOW_PROTOCOL": self._allowed_protocols,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": str(len(config)),
        }
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    def _run(self, *args: str) -> str:
        secret = self._credentials.secret if self._credentials else ""
        # GitPython can't kill on timeout on Windows (dev machines only; the
        # containers run Linux). http.lowSpeedTime still bounds network stalls there.
        kill_after = None if sys.platform == "win32" else self._timeout
        try:
            output: str = Git().execute(
                ["git", *args],
                env=self._env(),
                kill_after_timeout=kill_after,
                stdout_as_string=True,
            )
        except GitCommandError as exc:
            stderr = scrub(str(exc.stderr or ""), secret).strip()
            if "did not complete in" in stderr or "timed out" in stderr.lower():
                raise GitTimeoutError(f"git timed out after {self._timeout:g} s") from None
            message = stderr.removeprefix("stderr:").strip(" '\n") or "git command failed"
            raise _classify(stderr)(message) from None
        return output

    def ls_remote(self, url: str) -> RemoteInfo:
        """List the remote's branches and its default branch (HEAD)."""
        output = self._run("ls-remote", "--symref", url, "HEAD", "refs/heads/*")
        branches: list[str] = []
        default_branch: str | None = None
        for line in output.splitlines():
            if line.startswith("ref: "):
                target, _, name = line[len("ref: ") :].partition("\t")
                if name == "HEAD":
                    default_branch = target.removeprefix("refs/heads/")
                continue
            _, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                branches.append(ref.removeprefix("refs/heads/"))
        return RemoteInfo(branches=sorted(branches), default_branch=default_branch)
