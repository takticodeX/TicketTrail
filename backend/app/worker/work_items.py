"""The work item search behind the review's picker, run by the worker.

The API never talks to Azure DevOps itself; it asks the worker and waits, as for the
connection tests.
"""

import uuid
from typing import Any

from app.api.v1.schemas.review import WorkItemOption, WorkItemSearchResult
from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import AzureConnection, Project
from app.integrations.trackers.azure import AzureBoardsClient
from app.integrations.trackers.base import TrackerError
from app.worker.connection_checks import TEST_TIMEOUT_SECONDS, UNDECRYPTABLE
from app.worker.context import WorkerContext

SEARCH_LIMIT = 50


def _search(context: WorkerContext, connection: AzureConnection, text: str) -> WorkItemSearchResult:
    try:
        check_public_host(
            connection.organization_url, allow_private=context.settings.allow_private_hosts
        )
    except UnsafeUrlError as exc:
        return WorkItemSearchResult(ok=False, error=f"Organization URL refused: {exc}.")
    try:
        pat = context.secret_box.decrypt(connection.pat_enc)
    except SecretDecryptionError:
        return WorkItemSearchResult(ok=False, error=UNDECRYPTABLE)
    try:
        with AzureBoardsClient(
            connection.organization_url,
            connection.azure_project,
            pat,
            timeout=TEST_TIMEOUT_SECONDS,
            limiter=context.azure_limiter(connection.organization_url),
            sleep=context.sleep,
        ) as client:
            found = client.search_work_items(text, limit=SEARCH_LIMIT)
    except TrackerError as exc:
        return WorkItemSearchResult(ok=False, error=str(exc))
    return WorkItemSearchResult(
        ok=True,
        items=[
            WorkItemOption(id=w.id, title=w.title, type=w.type, state=w.state, closed=w.closed)
            for w in found
        ],
    )


def run_work_item_search(
    context: WorkerContext, project_id: uuid.UUID, text: str
) -> dict[str, Any]:
    """The API has already checked that the caller may review this project."""
    with context.session_factory() as db:
        project = db.get(Project, project_id)
        connection = db.get(AzureConnection, project.azure_connection_id) if project else None
        if connection is None:
            return WorkItemSearchResult(ok=False, error="Project not found.").model_dump(
                mode="json"
            )
        return _search(context, connection, text).model_dump(mode="json")
