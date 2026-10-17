"""Plain Git over HTTPS through the git CLI (via GitPython).

Credentials are handed to git as an http.extraHeader through GIT_CONFIG_*
environment variables, so they never appear in the remote URL, in .git/config,
on the command line (visible in the process list) or in logs.
"""

import base64
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

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


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    author_date: datetime
    committer_date: datetime
    subject: str
    message: str  # subject and body
    parent_count: int

    @property
    def is_merge(self) -> bool:
        return self.parent_count > 1

    @property
    def body(self) -> str:
        return self.message.partition("\n")[2].strip()


# NUL between fields and \x1e after each commit: neither appears in commit metadata.
_FIELD = "\x00"
_RECORD_END = "\x1e"
_LOG_FORMAT = "%H%x00%an%x00%ae%x00%aI%x00%cI%x00%P%x00%B%x1e"


def _parse_commit(record: str) -> Commit:
    sha, author_name, author_email, author_date, committer_date, parents, message = record.lstrip(
        "\n"
    ).split(_FIELD, 6)
    message = message.strip()
    return Commit(
        sha=sha,
        author_name=author_name,
        author_email=author_email,
        author_date=datetime.fromisoformat(author_date),
        committer_date=datetime.fromisoformat(committer_date),
        subject=message.partition("\n")[0].strip(),
        message=message,
        parent_count=len(parents.split()),
    )


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


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

    def _execute(self, args: tuple[str, ...], cwd: Path | None) -> str:
        # GitPython can't kill on timeout on Windows (dev machines only; the
        # containers run Linux). http.lowSpeedTime still bounds network stalls there.
        kill_after = None if sys.platform == "win32" else self._timeout
        output = Git(cwd).execute(
            ["git", *args],
            env=self._env(),
            kill_after_timeout=kill_after,
            stdout_as_string=False,
        )
        # Commit messages aren't always valid UTF-8; never let one break a run.
        return (
            output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        )

    def _run(self, *args: str, cwd: Path | None = None) -> str:
        secret = self._credentials.secret if self._credentials else ""
        try:
            return self._execute(args, cwd)
        except GitCommandError as exc:
            stderr = scrub(_text(exc.stderr), secret).strip()
            if "did not complete in" in stderr or "timed out" in stderr.lower():
                raise GitTimeoutError(f"git timed out after {self._timeout:g} s") from None
            message = stderr.removeprefix("stderr:").strip(" '\n") or "git command failed"
            raise _classify(stderr)(message) from None

    def _succeeds(self, *args: str, cwd: Path) -> bool:
        """For commands that answer yes/no through their exit status."""
        try:
            self._execute(args, cwd)
        except GitCommandError:
            return False
        return True

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

    # --- Local mirror ----------------------------------------------------------------------

    def mirror(self, url: str, path: Path) -> None:
        """Mirror-clone the remote into `path` the first time, then only fetch."""
        if (path / "HEAD").is_file():
            self._run("remote", "set-url", "origin", url, cwd=path)  # the URL may have changed
            self._run("fetch", "--prune", "--quiet", "origin", cwd=path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        if partial.exists():
            shutil.rmtree(partial)
        self._run("clone", "--mirror", "--quiet", url, str(partial))
        partial.rename(path)  # never leave a half-cloned mirror at the real path

    def has_branch(self, path: Path, branch: str) -> bool:
        return self._succeeds(
            "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}", cwd=path
        )

    def is_ancestor(self, path: Path, sha: str, branch: str) -> bool:
        """False also when `sha` doesn't exist (for example after a force-push)."""
        return self._succeeds("merge-base", "--is-ancestor", sha, f"refs/heads/{branch}", cwd=path)

    def has_commit(self, path: Path, sha: str) -> bool:
        return self._succeeds("cat-file", "-e", f"{sha}^{{commit}}", cwd=path)

    def list_commits(
        self,
        path: Path,
        branch: str,
        *,
        after_sha: str | None = None,
        since: date | None = None,
    ) -> list[Commit]:
        """Commits on `branch`, oldest first: after `after_sha`, or from `since` on."""
        revision = f"{after_sha}..refs/heads/{branch}" if after_sha else f"refs/heads/{branch}"
        args = ["log", "--reverse", "--no-color", f"--format={_LOG_FORMAT}"]
        if since is not None:
            args.append(f"--since={since.isoformat()} 00:00:00 +0000")
        output = self._run(*args, revision, "--", cwd=path)
        return [_parse_commit(record) for record in output.split(_RECORD_END) if record.strip()]
