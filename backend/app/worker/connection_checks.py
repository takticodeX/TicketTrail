"""Connection tests run by the worker: `git ls-remote` and the Azure project lookup.

Each loads the connection by ID and owner, decrypts its secret in memory only,
records last_test_at / last_test_ok, and returns a result safe to show the user.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.api.v1.schemas import AzureTestResult, GitTestResult
from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import AzureConnection, GitAuthType, GitConnection
from app.db.repositories import AzureConnectionRepository, GitConnectionRepository
from app.integrations.git.client import (
    GitAuthError,
    GitClient,
    GitCredentials,
    GitError,
    GitNotFoundError,
)
from app.integrations.trackers.azure import AzureBoardsClient
from app.integrations.trackers.base import TrackerError
from app.worker.context import WorkerContext

# A test should answer quickly even when TT_GIT_TIMEOUT allows long syncs.
TEST_TIMEOUT_SECONDS = 20.0

UNDECRYPTABLE = (
    "The saved secret can't be decrypted (was TT_ENCRYPTION_KEY changed?). Enter it again."
)
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


def _azure_test(context: WorkerContext, connection: AzureConnection) -> AzureTestResult:
    try:
        check_public_host(
            connection.organization_url, allow_private=context.settings.allow_private_hosts
        )
    except UnsafeUrlError as exc:
        return AzureTestResult(ok=False, error=f"Organization URL refused: {exc}.")
    try:
        pat = context.secret_box.decrypt(connection.pat_enc)
    except SecretDecryptionError:
        return AzureTestResult(ok=False, error=UNDECRYPTABLE)
    try:
        with AzureBoardsClient(
            connection.organization_url, connection.azure_project, pat, timeout=TEST_TIMEOUT_SECONDS
        ) as client:
            project_name = client.test_connection()
    except TrackerError as exc:
        return AzureTestResult(ok=False, error=str(exc))
    return AzureTestResult(ok=True, project_name=project_name)


def run_git_connection_check(
    context: WorkerContext, connection_id: uuid.UUID, owner_id: uuid.UUID
) -> dict[str, Any]:
    with context.session_factory() as db:
        connection = GitConnectionRepository(db, owner_id).get(connection_id)
        if connection is None:
            return GitTestResult(ok=False, error="Connection not found.").model_dump(mode="json")
        result = _git_test(context, connection)
        connection.last_test_at = datetime.now(UTC)
        connection.last_test_ok = result.ok
        db.commit()
    return result.model_dump(mode="json")


def run_azure_connection_check(
    context: WorkerContext, connection_id: uuid.UUID, owner_id: uuid.UUID
) -> dict[str, Any]:
    with context.session_factory() as db:
        connection = AzureConnectionRepository(db, owner_id).get(connection_id)
        if connection is None:
            return AzureTestResult(ok=False, error="Connection not found.").model_dump(mode="json")
        result = _azure_test(context, connection)
        connection.last_test_at = datetime.now(UTC)
        connection.last_test_ok = result.ok
        db.commit()
    return result.model_dump(mode="json")
