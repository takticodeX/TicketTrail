"""Projects: one Git connection paired with one Azure board, plus the pattern tester.

A project belongs to a user or to an organization (spec section 4, *Access rules*).
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from app.api.access import insufficient_role, organization_for, project_for
from app.api.deps import CurrentUser, DbSession, PageDep, SettingsDep
from app.api.v1.schemas import (
    OrganizationSummary,
    Page,
    PatternSampleResult,
    PatternTestRequest,
    PatternTestResponse,
    ProjectAzureSummary,
    ProjectCreate,
    ProjectGitSummary,
    ProjectMove,
    ProjectMoved,
    ProjectResponse,
    ProjectUpdate,
    RunResponse,
    UserSummary,
)
from app.config import Settings
from app.core.cron import InvalidCronError, next_slot, validate_cron
from app.core.errors import AppError, field_error
from app.db.models import (
    AzureConnection,
    GitConnection,
    OrganizationRole,
    Project,
    ProjectRole,
    ProjectShare,
    User,
)
from app.db.repositories import (
    AzureConnectionRepository,
    GitConnectionRepository,
    MemberRepository,
    ProjectAccessRepository,
    ProjectRepository,
    ProjectScope,
    ProjectShareRepository,
    SeenProject,
    project_summaries,
)
from app.db.repositories.transfers import Owner, move_project
from app.integrations.git.hosts import commit_url_pattern, detect_host
from app.sync.parser import InvalidPatternError, PatternTimeoutError, compile_ticket_pattern

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def _name_taken(whose: str) -> AppError:
    return AppError(409, "name_taken", f"{whose} a project with this name.")


def _whose(seen: SeenProject) -> str:
    if seen.organization is not None:
        return "The organization already has"
    return "You already have" if seen.role is ProjectRole.OWNER else "The owner already has"


def _check_connections(
    db: DbSession, project: Project, git_connection_id: uuid.UUID, azure_connection_id: uuid.UUID
) -> None:
    """A project uses its own owner's connections only.

    Anyone else's connection gets the same answer as a missing one.
    """
    if GitConnectionRepository.owning(db, project).get(git_connection_id) is None:
        raise field_error("git_connection_id", "Git connection not found")
    if AzureConnectionRepository.owning(db, project).get(azure_connection_id) is None:
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


def _responses(db: DbSession, seen: Sequence[SeenProject]) -> list[ProjectResponse]:
    """Projects with what the dashboard shows: last run, next scheduled run, comments posted."""
    projects = [s.project for s in seen]
    ids = [p.id for p in projects]
    summaries = project_summaries(db, ids)
    shares = _share_counts(db, ids)
    gits, azures = _connections(db, projects)
    now = datetime.now(UTC)
    responses = []
    for item in seen:
        project = item.project
        last_run, posted = summaries.get(project.id, (None, 0))
        next_run_at = None
        if project.schedule_enabled and project.schedule_cron:
            # The scheduler evaluates the schedule in the owner's time zone.
            next_run_at = next_slot(project.schedule_cron, item.timezone, now)
        organization = item.organization
        responses.append(
            ProjectResponse.model_validate(project).model_copy(
                update={
                    "last_run": RunResponse.model_validate(last_run) if last_run else None,
                    "next_run_at": next_run_at,
                    "comments_posted": posted,
                    "role": item.role.value,
                    "owner": UserSummary.model_validate(item.owner) if item.owner else None,
                    "organization": (
                        OrganizationSummary.model_validate(organization) if organization else None
                    ),
                    "schedule_timezone": item.timezone,
                    "shares": shares.get(project.id, 0),
                    "git_connection": gits.get(project.git_connection_id),
                    "azure_connection": azures.get(project.azure_connection_id),
                }
            )
        )
    return responses


def _response(db: DbSession, user: User, project_id: uuid.UUID) -> ProjectResponse:
    seen = ProjectAccessRepository(db, user.id).get(project_id)
    assert seen is not None  # noqa: S101  (the caller just checked or created it)
    return _responses(db, [seen])[0]


@router.get("")
def list_projects(
    user: CurrentUser,
    db: DbSession,
    page: PageDep,
    scope: Annotated[
        ProjectScope,
        Query(description="Your own projects, your organizations', those shared with you, or all"),
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
    """A personal project, or an organization's when organization_id is set.

    Members are viewers of their organization's projects, so a member who is not an
    admin becomes an editor of the project they create.
    """
    org_role = None
    if body.organization_id is None:
        repo = ProjectRepository(db, user.id)
    else:
        _, org_role = organization_for(db, user, body.organization_id)
        repo = ProjectRepository(db, organization_id=body.organization_id)
    if repo.name_taken(body.name):
        raise _name_taken(
            "You already have" if org_role is None else "The organization already has"
        )
    project = Project(
        **body.model_dump(exclude={"organization_id"}),
        owner_id=repo.owner_id,
        organization_id=repo.organization_id,
    )
    _check_connections(db, project, body.git_connection_id, body.azure_connection_id)
    _check_schedule(project, settings)
    _arm_schedule(project)
    repo.add(project)
    if org_role is OrganizationRole.MEMBER:
        ProjectShareRepository(db, project.id).add(user.id, ProjectRole.EDITOR)
    db.commit()
    return _response(db, user, project.id)


@router.post("/test-pattern")
def test_pattern(body: PatternTestRequest, user: CurrentUser) -> PatternTestResponse:
    """Try a pattern on sample commit messages before the project is saved."""
    if not body.pattern:
        raise field_error("pattern", "required")
    return _run_pattern_test(body.pattern, body.samples)


@router.get("/{project_id}")
def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectResponse:
    return _responses(db, [project_for(db, user, project_id)])[0]


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
    project = seen.project
    sent = body.model_fields_set
    nullable = {"start_from", "schedule_cron"}

    changes_connections = body.git_connection_id not in (
        None,
        project.git_connection_id,
    ) or body.azure_connection_id not in (None, project.azure_connection_id)
    if changes_connections and seen.role is not ProjectRole.OWNER:
        raise insufficient_role(ProjectRole.OWNER)
    # Names are unique per owner.
    if body.name is not None and ProjectRepository.owning(db, project).name_taken(
        body.name, exclude_id=project.id
    ):
        raise _name_taken(_whose(seen))
    schedule_before = (project.schedule_cron, project.schedule_enabled)
    for field in sent:
        value = getattr(body, field)
        if value is None and field not in nullable:
            continue  # null for a required field means "leave it"
        setattr(project, field, value)

    if changes_connections:
        _check_connections(db, project, project.git_connection_id, project.azure_connection_id)
    _check_schedule(project, settings)
    if (project.schedule_cron, project.schedule_enabled) != schedule_before:
        _arm_schedule(project)  # the scheduler reads it at the next minute: no restart
    db.commit()
    return _response(db, user, project.id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    project = project_for(db, user, project_id, ProjectRole.OWNER).project
    ProjectRepository.owning(db, project).delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/move")
def move(
    project_id: uuid.UUID, body: ProjectMove, user: CurrentUser, db: DbSession
) -> ProjectMoved:
    """Move a project into an organization, or out of it to one of its members.

    - Into an organization: the project's personal owner, who must be a member.
      If they are not an admin there, they stay an editor of the project.
    - Out of an organization: its admins, to an active member.

    The connections come along; one the previous owner still uses elsewhere is copied.
    """
    seen = project_for(db, user, project_id, ProjectRole.OWNER)
    project = seen.project
    if body.organization_id is not None:
        if seen.owner is None:
            raise AppError(
                409, "not_personal", "Only a personal project can be moved into an organization."
            )
        organization, org_role = organization_for(db, user, body.organization_id)
        previous, target = Owner.of_user(seen.owner), Owner.of_organization(organization)
        tally = move_project(db, project, previous, target)
        if org_role is OrganizationRole.MEMBER:
            ProjectShareRepository(db, project.id).add(user.id, ProjectRole.EDITOR)
    else:
        if seen.organization is None:
            raise AppError(
                409, "not_in_organization", "Only an organization's project can go to a member."
            )
        assert body.to_user_id is not None  # noqa: S101  (validated by ProjectMove)
        member = MemberRepository(db, seen.organization.id).get(body.to_user_id)
        recipient = db.get(User, body.to_user_id)
        if member is None or recipient is None or not recipient.is_active:
            raise field_error("to_user_id", "Not an active member of the organization")
        previous, target = Owner.of_organization(seen.organization), Owner.of_user(recipient)
        tally = move_project(db, project, previous, target)
    db.commit()
    summary = "; ".join(
        [f'Project "{project.name}" from {previous.describe} to {target.describe}', *tally.notes]
    )
    logger.info("User %s moved project %s: %s", user.id, project.id, summary)
    return ProjectMoved(project_id=project.id, summary=summary)


@router.post("/{project_id}/test-pattern")
def test_project_pattern(
    project_id: uuid.UUID, body: PatternTestRequest, user: CurrentUser, db: DbSession
) -> PatternTestResponse:
    """Try a pattern (by default the project's saved one) on sample commit messages."""
    project = project_for(db, user, project_id).project
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
