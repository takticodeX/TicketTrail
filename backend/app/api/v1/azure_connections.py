"""Azure DevOps connections: CRUD and the project-lookup test (run by the worker)."""

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, PageDep, SecretBoxDep, TaskRunnerDep
from app.api.v1.git_connections import TEST_WAIT_SECONDS, connection_in_use, worker_unavailable
from app.api.v1.schemas import (
    AzureConnectionCreate,
    AzureConnectionResponse,
    AzureConnectionUpdate,
    AzureTestResult,
    Page,
)
from app.core.errors import AppError, not_found
from app.db.models import AzureConnection
from app.db.repositories import AzureConnectionRepository, ProjectRepository
from app.worker import task_names
from app.worker.runner import WorkerUnavailableError

router = APIRouter(prefix="/azure-connections", tags=["azure-connections"])


def to_response(connection: AzureConnection) -> AzureConnectionResponse:
    return AzureConnectionResponse(
        id=connection.id,
        name=connection.name,
        organization_url=connection.organization_url,
        azure_project=connection.azure_project,
        has_secret=bool(connection.pat_enc),
        last_test_at=connection.last_test_at,
        last_test_ok=connection.last_test_ok,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _get_or_404(repo: AzureConnectionRepository, connection_id: uuid.UUID) -> AzureConnection:
    connection = repo.get(connection_id)
    if connection is None:
        raise not_found("Azure connection")
    return connection


def _name_taken() -> AppError:
    return AppError(409, "name_taken", "You already have an Azure connection with this name.")


@router.get("")
def list_azure_connections(
    user: CurrentUser, db: DbSession, page: PageDep
) -> Page[AzureConnectionResponse]:
    items, total = AzureConnectionRepository(db, user.id).list(
        offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[to_response(c) for c in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_azure_connection(
    body: AzureConnectionCreate, user: CurrentUser, db: DbSession, box: SecretBoxDep
) -> AzureConnectionResponse:
    repo = AzureConnectionRepository(db, user.id)
    if repo.name_taken(body.name):
        raise _name_taken()
    connection = repo.add(
        AzureConnection(
            name=body.name,
            organization_url=body.organization_url,
            azure_project=body.azure_project,
            pat_enc=box.encrypt(body.pat),
        )
    )
    db.commit()
    return to_response(connection)


@router.get("/{connection_id}")
def get_azure_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> AzureConnectionResponse:
    return to_response(_get_or_404(AzureConnectionRepository(db, user.id), connection_id))


@router.patch("/{connection_id}")
def update_azure_connection(
    connection_id: uuid.UUID,
    body: AzureConnectionUpdate,
    user: CurrentUser,
    db: DbSession,
    box: SecretBoxDep,
) -> AzureConnectionResponse:
    repo = AzureConnectionRepository(db, user.id)
    connection = _get_or_404(repo, connection_id)
    before = (connection.organization_url, connection.azure_project, connection.pat_enc)

    if body.name is not None:
        if repo.name_taken(body.name, exclude_id=connection.id):
            raise _name_taken()
        connection.name = body.name
    if body.organization_url is not None:
        connection.organization_url = body.organization_url
    if body.azure_project is not None:
        connection.azure_project = body.azure_project
    if body.pat:  # empty or omitted keeps the saved PAT
        connection.pat_enc = box.encrypt(body.pat)

    if (connection.organization_url, connection.azure_project, connection.pat_enc) != before:
        connection.last_test_at = None
        connection.last_test_ok = None
    db.commit()
    db.refresh(connection)
    return to_response(connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_azure_connection(connection_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Refused (409) while a project uses the connection."""
    connection = _get_or_404(AzureConnectionRepository(db, user.id), connection_id)
    in_use = ProjectRepository(db, user.id).names_using(azure_connection_id=connection.id)
    if in_use:
        raise connection_in_use(in_use)
    try:
        db.delete(connection)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise connection_in_use([]) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connection_id}/test")
def test_azure_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession, runner: TaskRunnerDep
) -> AzureTestResult:
    """Looks the project up in Azure DevOps (on the worker) with the saved PAT."""
    connection = _get_or_404(AzureConnectionRepository(db, user.id), connection_id)
    db.close()
    try:
        result = runner.run(
            task_names.TEST_AZURE_CONNECTION,
            [str(connection.id), str(user.id)],
            timeout=TEST_WAIT_SECONDS,
        )
    except WorkerUnavailableError as exc:
        raise worker_unavailable() from exc
    return AzureTestResult.model_validate(result)
