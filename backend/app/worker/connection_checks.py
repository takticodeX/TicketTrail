"""Connection tests run by the worker: `git ls-remote` and the board lookup.

Each loads the connection by ID and owner, decrypts its secret in memory only,
records last_test_at / last_test_ok, and returns a result safe to show the user.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.api.v1.schemas import BoardTestResult, GitTestResult
from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import BoardConnection, GitAuthType, GitConnection
from app.integrations.git.client import (
    GitAuthError,
    GitClient,
    GitCredentials,
    GitError,
    GitNotFoundError,
)
from app.integrations.trackers.base import TrackerError
from app.worker.boards import UNDECRYPTABLE, BoardUnavailableError, open_board
from app.worker.context import WorkerContext

# A test should answer quickly even when TT_GIT_TIMEOUT allows long syncs.
TEST_TIMEOUT_SECONDS = 20.0

GIT_AUTH_FAILED = (
    "Authentication failed. Check the username and token; the token needs read access "
    "to the repository's code (for example Code: Read)."
)
GIT_NOT_FOUND = "Repository not found, or these credentials can't see it."


def _git_test(context: WorkerContext, connection: GitConnection) -> GitTestResult:
    try:
        check_public_host(connection.repo_url, allow_private=context.settings.allow_private_hosts)
    except UnsafeUrlError as exc:
        return GitTestResult(ok=False, error=f"Repository URL refused: {exc}.")

    credentials = None
    if connection.auth_type != GitAuthType.NONE:
        try:
            secret = context.secret_box.decrypt(connection.secret_enc or "")
        except SecretDecryptionError:
            return GitTestResult(ok=False, error=UNDECRYPTABLE)
        credentials = GitCredentials(connection.username or "", secret)

    timeout = min(float(context.settings.git_timeout), TEST_TIMEOUT_SECONDS)
    try:
        info = GitClient(credentials, timeout=timeout).ls_remote(connection.repo_url)
    except GitAuthError:
        return GitTestResult(ok=False, error=GIT_AUTH_FAILED)
    except GitNotFoundError:
        return GitTestResult(ok=False, error=GIT_NOT_FOUND)
    except GitError as exc:
        return GitTestResult(ok=False, error=str(exc))
    return GitTestResult(ok=True, branches=info.branches, default_branch=info.default_branch)


def _board_test(context: WorkerContext, connection: BoardConnection) -> BoardTestResult:
    try:
        with open_board(context, connection, timeout=TEST_TIMEOUT_SECONDS, limited=False) as client:
            name = client.test_connection()
    except BoardUnavailableError as exc:
        return BoardTestResult(ok=False, error=str(exc))
    except TrackerError as exc:
        return BoardTestResult(ok=False, error=str(exc))
    return BoardTestResult(ok=True, scope_name=name)


def run_git_connection_check(context: WorkerContext, connection_id: uuid.UUID) -> dict[str, Any]:
    """The API has already checked that the caller may test this connection."""
    with context.session_factory() as db:
        connection = db.get(GitConnection, connection_id)
        if connection is None:
            return GitTestResult(ok=False, error="Connection not found.").model_dump(mode="json")
        result = _git_test(context, connection)
        connection.last_test_at = datetime.now(UTC)
        connection.last_test_ok = result.ok
        db.commit()
    return result.model_dump(mode="json")


def run_board_connection_check(context: WorkerContext, connection_id: uuid.UUID) -> dict[str, Any]:
    """The API has already checked that the caller may test this connection."""
    with context.session_factory() as db:
        connection = db.get(BoardConnection, connection_id)
        if connection is None:
            return BoardTestResult(ok=False, error="Connection not found.").model_dump(mode="json")
        result = _board_test(context, connection)
        connection.last_test_at = datetime.now(UTC)
        connection.last_test_ok = result.ok
        db.commit()
    return result.model_dump(mode="json")
