"""Git connections: CRUD and the `git ls-remote` test (run by the worker)."""

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, PageDep, SecretBoxDep, TaskRunnerDep
from app.api.v1.schemas import (
    GitConnectionCreate,
    GitConnectionResponse,
    GitConnectionUpdate,
    GitTestResult,
    Page,
)
from app.core.errors import AppError, field_error, not_found
from app.db.models import GitAuthType, GitConnection
from app.db.repositories import GitConnectionRepository, ProjectRepository
from app.integrations.git.hosts import commit_url_pattern, detect_host
from app.worker import task_names
from app.worker.connection_checks import TEST_TIMEOUT_SECONDS
from app.worker.runner import WorkerUnavailableError

router = APIRouter(prefix="/git-connections", tags=["git-connections"])

# How long the API waits for the worker: the git timeout plus queueing slack.
TEST_WAIT_SECONDS = TEST_TIMEOUT_SECONDS + 10


def to_response(connection: GitConnection) -> GitConnectionResponse:
    return GitConnectionResponse(
        id=connection.id,
        name=connection.name,
        repo_url=connection.repo_url,
        auth_type=GitAuthType(connection.auth_type),
        username=connection.username,
        has_secret=connection.secret_enc is not None,
        commit_url_template=connection.commit_url_template,
        commit_url_pattern=commit_url_pattern(connection.repo_url, connection.commit_url_template),
        host=detect_host(connection.repo_url),
        last_test_at=connection.last_test_at,
        last_test_ok=connection.last_test_ok,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _get_or_404(repo: GitConnectionRepository, connection_id: uuid.UUID) -> GitConnection:
    connection = repo.get(connection_id)
    if connection is None:
        raise not_found("Git connection")
    return connection


def _name_taken() -> AppError:
    return AppError(409, "name_taken", "You already have a Git connection with this name.")


@router.get("")
def list_git_connections(
    user: CurrentUser, db: DbSession, page: PageDep
) -> Page[GitConnectionResponse]:
    items, total = GitConnectionRepository(db, user.id).list(
        offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[to_response(c) for c in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_git_connection(
    body: GitConnectionCreate, user: CurrentUser, db: DbSession, box: SecretBoxDep
) -> GitConnectionResponse:
    repo = GitConnectionRepository(db, user.id)
    if repo.name_taken(body.name):
        raise _name_taken()
    connection = repo.add(
        GitConnection(
            name=body.name,
            repo_url=body.repo_url,
            auth_type=body.auth_type,
            username=body.username,
            secret_enc=box.encrypt(body.secret) if body.secret else None,
            commit_url_template=body.commit_url_template,
        )
    )
    db.commit()
    return to_response(connection)


@router.get("/{connection_id}")
def get_git_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> GitConnectionResponse:
    return to_response(_get_or_404(GitConnectionRepository(db, user.id), connection_id))


@router.patch("/{connection_id}")
def update_git_connection(
    connection_id: uuid.UUID,
    body: GitConnectionUpdate,
    user: CurrentUser,
    db: DbSession,
    box: SecretBoxDep,
) -> GitConnectionResponse:
    repo = GitConnectionRepository(db, user.id)
    connection = _get_or_404(repo, connection_id)
    sent = body.model_fields_set
    before = (connection.repo_url, connection.auth_type, connection.username, connection.secret_enc)

    if body.name is not None:
        if repo.name_taken(body.name, exclude_id=connection.id):
            raise _name_taken()
        connection.name = body.name
    if body.repo_url is not None:
        connection.repo_url = body.repo_url
    if body.auth_type is not None:
        connection.auth_type = body.auth_type
    if "username" in sent:
        connection.username = body.username
    if body.secret:  # empty or omitted keeps the saved secret
        connection.secret_enc = box.encrypt(body.secret)
    if "commit_url_template" in sent:
        connection.commit_url_template = body.commit_url_template

    if connection.auth_type == GitAuthType.NONE:
        connection.username = None
        connection.secret_enc = None
    else:
        if not connection.username:
            raise field_error("username", "required for token and basic authentication")
        if connection.secret_enc is None:
            raise field_error("secret", "required for token and basic authentication")

    after = (connection.repo_url, connection.auth_type, connection.username, connection.secret_enc)
    if after != before:  # an earlier test result no longer says anything
        connection.last_test_at = None
        connection.last_test_ok = None
    db.commit()
    db.refresh(connection)
    return to_response(connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_git_connection(connection_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Refused (409) while a project uses the connection."""
    connection = _get_or_404(GitConnectionRepository(db, user.id), connection_id)
    in_use = ProjectRepository(db, user.id).names_using(git_connection_id=connection.id)
    if in_use:
        raise connection_in_use(in_use)
    try:
        db.delete(connection)
        db.commit()
    except IntegrityError as exc:  # a project was created meanwhile
        db.rollback()
        raise connection_in_use([]) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def connection_in_use(projects: list[str]) -> AppError:
    return AppError(
        409,
        "connection_in_use",
        "This connection is used by a project. Change or delete the project first.",
        {"projects": projects},
    )


@router.post("/{connection_id}/test")
def test_git_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession, runner: TaskRunnerDep
) -> GitTestResult:
    """Runs `git ls-remote` on the worker and lists the branches it finds."""
    connection = _get_or_404(GitConnectionRepository(db, user.id), connection_id)
    db.close()  # don't hold a database connection while the worker runs
    try:
        result = runner.run(
            task_names.TEST_GIT_CONNECTION,
            [str(connection.id), str(user.id)],
            timeout=TEST_WAIT_SECONDS,
        )
    except WorkerUnavailableError as exc:
        raise worker_unavailable() from exc
    return GitTestResult.model_validate(result)


def worker_unavailable() -> AppError:
    return AppError(
        503,
        "worker_unavailable",
        "The background worker did not answer. Check that the worker service is running.",
    )
