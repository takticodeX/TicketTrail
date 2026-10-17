"""Git repositories built inside the tests, to sync from over file://."""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path


class FixtureRepo:
    """A working repository on `main`. Each commit is one day after the previous one."""

    def __init__(self, path: Path, *, start: datetime | None = None) -> None:
        self.path = path
        self._clock = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    @property
    def url(self) -> str:
        return self.path.as_uri()

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", "-c", "user.name=Ada Lovelace", "-c", "user.email=ada@example.com", *args],
            cwd=self.path,
            check=True,
            capture_output=True,
            env={**os.environ, **(env or {})},
        )
        return result.stdout.decode(errors="replace").strip()

    def _dated(self) -> dict[str, str]:
        stamp = self._clock.isoformat()
        self._clock += timedelta(days=1)
        return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

    def commit(self, message: str | bytes) -> str:
        """An empty commit with this message; returns its SHA."""
        message_file = self.path.parent / f"{self.path.name}.msg"
        message_file.write_bytes(message if isinstance(message, bytes) else message.encode())
        self.git("commit", "-q", "--allow-empty", "-F", str(message_file), env=self._dated())
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def checkout(self, branch: str, *, create: bool = False) -> None:
        self.git("checkout", "-q", *(["-b"] if create else []), branch)

    def merge(self, branch: str, message: str) -> str:
        self.git("merge", "-q", "--no-ff", "-m", message, branch, env=self._dated())
        return self.head()

    def rewrite_last(self, message: str) -> str:
        """Replace the tip commit, as a force-push would."""
        self.git("reset", "-q", "--hard", "HEAD~1")
        return self.commit(message)
