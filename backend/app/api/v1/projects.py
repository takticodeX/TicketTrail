"""Projects: one Git connection paired with one Azure board, plus the pattern tester."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, PageDep, SettingsDep
from app.api.v1.schemas import (
    Page,
    PatternSampleResult,
    PatternTestRequest,
    PatternTestResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    RunResponse,
)
from app.config import Settings
from app.core.cron import InvalidCronError, next_slot, validate_cron
from app.core.errors import AppError, field_error, not_found
from app.db.models import Project
from app.db.repositories import (
    AzureConnectionRepository,
    GitConnectionRepository,
    ProjectRepository,
    project_summaries,
)
from app.sync.parser import InvalidPatternError, PatternTimeoutError, compile_ticket_pattern

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_or_404(repo: ProjectRepository, project_id: uuid.UUID) -> Project:
    project = repo.get(project_id)
    if project is None:
        raise not_found("Project")
    return project


def _name_taken() -> AppError:
    return AppError(409, "name_taken", "You already have a project with this name.")


def _check_connections(
    db: DbSession, user: CurrentUser, git_connection_id: uuid.UUID, azure_connection_id: uuid.UUID
) -> None:
    # Another user's connection gets the same answer as a missing one.
    if GitConnectionRepository(db, user.id).get(git_connection_id) is None:
        raise field_error("git_connection_id", "Git connection not found")
    if AzureConnectionRepository(db, user.id).get(azure_connection_id) is None:
        raise field_error("azure_connection_id", "Azure connection not found")


def _check_schedule(project: Project, settings: Settings) -> None:
    if project.schedule_cron:
        try:
            validate_cron(project.schedule_cron, min_interval_minutes=settings.min_schedule_minutes)
        except InvalidCronError as exc:
            raise field_error("schedule_cron", f"schedule {exc}") from exc
    elif project.schedule_enabled:
        raise field_error("schedule_cron", "required when schedule_enabled is true")


def _arm_schedule(project: Project) -> None:
    """A new or changed schedule counts from now: no slot that already passed fires."""
    project.schedule_last_fired_at = datetime.now(UTC)


def _responses(
    db: DbSession, user: CurrentUser, projects: Sequence[Project]
) -> list[ProjectResponse]:
    """Projects with what the dashboard shows: last run, next scheduled run, comments posted."""
    summaries = project_summaries(db, [p.id for p in projects])
    now = datetime.now(UTC)
    responses = []
    for project in projects:
        last_run, posted = summaries.get(project.id, (None, 0))
        next_run_at = None
        if project.schedule_enabled and project.schedule_cron:
            next_run_at = next_slot(project.schedule_cron, user.timezone, now)
        responses.append(
            ProjectResponse.model_validate(project).model_copy(
                update={
                    "last_run": RunResponse.model_validate(last_run) if last_run else None,
                    "next_run_at": next_run_at,
                    "comments_posted": posted,
                }
            )
        )
    return responses


def _response(db: DbSession, user: CurrentUser, project: Project) -> ProjectResponse:
    return _responses(db, user, [project])[0]


@router.get("")
def list_projects(user: CurrentUser, db: DbSession, page: PageDep) -> Page[ProjectResponse]:
    items, total = ProjectRepository(db, user.id).list(offset=page.offset, limit=page.page_size)
    return Page(
        items=_responses(db, user, items),
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ProjectResponse:
    repo = ProjectRepository(db, user.id)
    if repo.name_taken(body.name):
        raise _name_taken()
    _check_connections(db, user, body.git_connection_id, body.azure_connection_id)
    project = Project(**body.model_dump())
    _check_schedule(project, settings)
    _arm_schedule(project)
    repo.add(project)
    db.commit()
    return _response(db, user, project)


@router.post("/test-pattern")
def test_pattern(body: PatternTestRequest, user: CurrentUser) -> PatternTestResponse:
    """Try a pattern on sample commit messages before the project is saved."""
    if not body.pattern:
        raise field_error("pattern", "required")
    return _run_pattern_test(body.pattern, body.samples)


@router.get("/{project_id}")
def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectResponse:
    return _response(db, user, _get_or_404(ProjectRepository(db, user.id), project_id))


@router.patch("/{project_id}")
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> ProjectResponse:
    repo = ProjectRepository(db, user.id)
    project = _get_or_404(repo, project_id)
    sent = body.model_fields_set
    nullable = {"start_from", "schedule_cron"}

    if body.name is not None and repo.name_taken(body.name, exclude_id=project.id):
        raise _name_taken()
    schedule_before = (project.schedule_cron, project.schedule_enabled)
    for field in sent:
        value = getattr(body, field)
        if value is None and field not in nullable:
            continue  # null for a required field means "leave it"
        setattr(project, field, value)

    if sent & {"git_connection_id", "azure_connection_id"}:
        _check_connections(db, user, project.git_connection_id, project.azure_connection_id)
    _check_schedule(project, settings)
    if (project.schedule_cron, project.schedule_enabled) != schedule_before:
        _arm_schedule(project)  # the scheduler reads it at the next minute: no restart
    db.commit()
    db.refresh(project)
    return _response(db, user, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    repo = ProjectRepository(db, user.id)
    repo.delete(_get_or_404(repo, project_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/test-pattern")
def test_project_pattern(
    project_id: uuid.UUID, body: PatternTestRequest, user: CurrentUser, db: DbSession
) -> PatternTestResponse:
    """Try a pattern (by default the project's saved one) on sample commit messages."""
    project = _get_or_404(ProjectRepository(db, user.id), project_id)
    return _run_pattern_test(body.pattern or project.ticket_pattern, body.samples)


def _run_pattern_test(pattern: str, samples: list[str]) -> PatternTestResponse:
    try:
        compiled = compile_ticket_pattern(pattern)
    except InvalidPatternError as exc:
        raise field_error("pattern", f"pattern {exc}") from exc
    results: list[PatternSampleResult] = []
    for sample in samples:
        try:
            results.append(PatternSampleResult(ids=compiled.extract(sample)))
        except PatternTimeoutError:
            results.append(
                PatternSampleResult(
                    ids=[], error="The pattern took too long on this message (over 100 ms)."
                )
            )
    return PatternTestResponse(pattern=pattern, results=results)
