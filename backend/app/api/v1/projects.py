"""Projects: one Git connection paired with one Azure board, plus the pattern tester."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from app.api.access import insufficient_role, project_for
from app.api.deps import CurrentUser, DbSession, PageDep, SettingsDep
from app.api.v1.schemas import (
    Page,
    PatternSampleResult,
    PatternTestRequest,
    PatternTestResponse,
    ProjectAzureSummary,
    ProjectCreate,
    ProjectGitSummary,
    ProjectResponse,
    ProjectUpdate,
    RunResponse,
    UserSummary,
)
from app.config import Settings
from app.core.cron import InvalidCronError, next_slot, validate_cron
from app.core.errors import AppError, field_error
from app.db.models import AzureConnection, GitConnection, Project, ProjectRole, ProjectShare, User
from app.db.repositories import (
    AzureConnectionRepository,
    GitConnectionRepository,
    ProjectAccessRepository,
    ProjectRepository,
    ProjectScope,
    project_summaries,
)
from app.integrations.git.hosts import commit_url_pattern, detect_host
from app.sync.parser import InvalidPatternError, PatternTimeoutError, compile_ticket_pattern

router = APIRouter(prefix="/projects", tags=["projects"])

# A project as one user sees it: the project, their role on it, and its owner.
type Seen = tuple[Project, ProjectRole, User]


def _name_taken(*, mine: bool = True) -> AppError:
    whose = "You already have" if mine else "The owner already has"
    return AppError(409, "name_taken", f"{whose} a project with this name.")


def _check_connections(
    db: DbSession, owner_id: uuid.UUID, git_connection_id: uuid.UUID, azure_connection_id: uuid.UUID
) -> None:
    # Another user's connection gets the same answer as a missing one.
    if GitConnectionRepository(db, owner_id).get(git_connection_id) is None:
        raise field_error("git_connection_id", "Git connection not found")
    if AzureConnectionRepository(db, owner_id).get(azure_connection_id) is None:
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


def _share_counts(db: DbSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(ProjectShare.project_id, func.count())
        .where(ProjectShare.project_id.in_(project_ids))
        .group_by(ProjectShare.project_id)
    ).all()
    return {project_id: count for project_id, count in rows}


def _connections(
    db: DbSession, projects: Sequence[Project]
) -> tuple[dict[uuid.UUID, ProjectGitSummary], dict[uuid.UUID, ProjectAzureSummary]]:
    """The projects' connections, without secrets: shared users can't list the owner's."""
    gits = db.scalars(
        select(GitConnection).where(GitConnection.id.in_({p.git_connection_id for p in projects}))
    ).all()
    azures = db.scalars(
        select(AzureConnection).where(
            AzureConnection.id.in_({p.azure_connection_id for p in projects})
        )
    ).all()
    return (
        {
            c.id: ProjectGitSummary(
                id=c.id,
                name=c.name,
                repo_url=c.repo_url,
                host=detect_host(c.repo_url),
                commit_url_pattern=commit_url_pattern(c.repo_url, c.commit_url_template),
            )
            for c in gits
        },
        {
            c.id: ProjectAzureSummary(
                id=c.id,
                name=c.name,
                organization_url=c.organization_url,
                azure_project=c.azure_project,
            )
            for c in azures
        },
    )


def _responses(db: DbSession, seen: Sequence[Seen]) -> list[ProjectResponse]:
    """Projects with what the dashboard shows: last run, next scheduled run, comments posted."""
    projects = [project for project, _, _ in seen]
    ids = [p.id for p in projects]
    summaries = project_summaries(db, ids)
    shares = _share_counts(db, ids)
    gits, azures = _connections(db, projects)
    now = datetime.now(UTC)
    responses = []
    for project, role, owner in seen:
        last_run, posted = summaries.get(project.id, (None, 0))
        next_run_at = None
        if project.schedule_enabled and project.schedule_cron:
            # The scheduler evaluates the schedule in the owner's time zone.
            next_run_at = next_slot(project.schedule_cron, owner.timezone, now)
        responses.append(
            ProjectResponse.model_validate(project).model_copy(
                update={
                    "last_run": RunResponse.model_validate(last_run) if last_run else None,
                    "next_run_at": next_run_at,
                    "comments_posted": posted,
                    "role": role.value,
                    "owner": UserSummary.model_validate(owner),
                    "schedule_timezone": owner.timezone,
                    "shares": shares.get(project.id, 0),
                    "git_connection": gits.get(project.git_connection_id),
                    "azure_connection": azures.get(project.azure_connection_id),
                }
            )
        )
    return responses


def _response(db: DbSession, seen: Seen) -> ProjectResponse:
    return _responses(db, [seen])[0]


@router.get("")
def list_projects(
    user: CurrentUser,
    db: DbSession,
    page: PageDep,
    scope: Annotated[
        ProjectScope, Query(description="Your own projects, those shared with you, or both")
    ] = ProjectScope.ALL,
) -> Page[ProjectResponse]:
    items, total = ProjectAccessRepository(db, user.id).list(
        scope=scope, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=_responses(db, items),
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
    _check_connections(db, user.id, body.git_connection_id, body.azure_connection_id)
    project = Project(**body.model_dump())
    _check_schedule(project, settings)
    _arm_schedule(project)
    repo.add(project)
    db.commit()
    return _response(db, (project, ProjectRole.OWNER, user))


@router.post("/test-pattern")
def test_pattern(body: PatternTestRequest, user: CurrentUser) -> PatternTestResponse:
    """Try a pattern on sample commit messages before the project is saved."""
    if not body.pattern:
        raise field_error("pattern", "required")
    return _run_pattern_test(body.pattern, body.samples)


@router.get("/{project_id}")
def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectResponse:
    return _response(db, project_for(db, user, project_id))


@router.patch("/{project_id}")
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> ProjectResponse:
    """Editors change everything but the connections, which belong to the owner."""
    seen = project_for(db, user, project_id, ProjectRole.EDITOR)
    project, role, owner = seen
    sent = body.model_fields_set
    nullable = {"start_from", "schedule_cron"}

    changes_connections = body.git_connection_id not in (
        None,
        project.git_connection_id,
    ) or body.azure_connection_id not in (None, project.azure_connection_id)
    if changes_connections and role is not ProjectRole.OWNER:
        raise insufficient_role(ProjectRole.OWNER)
    repo = ProjectRepository(db, owner.id)  # names are unique per owner
    if body.name is not None and repo.name_taken(body.name, exclude_id=project.id):
        raise _name_taken(mine=role is ProjectRole.OWNER)
    schedule_before = (project.schedule_cron, project.schedule_enabled)
    for field in sent:
        value = getattr(body, field)
        if value is None and field not in nullable:
            continue  # null for a required field means "leave it"
        setattr(project, field, value)

    if changes_connections:
        _check_connections(db, owner.id, project.git_connection_id, project.azure_connection_id)
    _check_schedule(project, settings)
    if (project.schedule_cron, project.schedule_enabled) != schedule_before:
        _arm_schedule(project)  # the scheduler reads it at the next minute: no restart
    db.commit()
    db.refresh(project)
    return _response(db, seen)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    project, _, _ = project_for(db, user, project_id, ProjectRole.OWNER)
    ProjectRepository(db, user.id).delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/test-pattern")
def test_project_pattern(
    project_id: uuid.UUID, body: PatternTestRequest, user: CurrentUser, db: DbSession
) -> PatternTestResponse:
    """Try a pattern (by default the project's saved one) on sample commit messages."""
    project, _, _ = project_for(db, user, project_id)
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
