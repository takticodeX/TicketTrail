"""Projects (one repo paired with one board) and the ticket-pattern tester."""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.common import Name, OrganizationSummary, UserSummary
from app.api.v1.schemas.runs import RunResponse
from app.core.cron import InvalidCronError, validate_cron
from app.integrations.git.hosts import GitHost
from app.sync.parser import (
    DEFAULT_TICKET_PATTERN,
    InvalidPatternError,
    compile_ticket_pattern,
)
from app.sync.template import (
    DEFAULT_COMMENT_TEMPLATE,
    InvalidTemplateError,
    validate_comment_template,
)

MAX_BRANCHES = 50

# Enough of git's ref-name rules (git check-ref-format) to catch typos.
_BRANCH = re.compile(
    r"(?!-)(?!.*\.\.)(?!.*//)(?!.*@\{)[^\s~^:?*\[\\\x00-\x1f\x7f]+(?<![./])(?<!\.lock)"
)
_SHA = re.compile(r"[0-9a-f]{7,40}")


def _branch(value: str) -> str:
    value = value.strip()
    if not _BRANCH.fullmatch(value):
        raise ValueError(f"{value!r} is not a valid branch name")
    return value


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ticket_pattern(value: str) -> str:
    try:
        compile_ticket_pattern(value)
    except InvalidPatternError as exc:
        raise ValueError(f"pattern {exc}") from exc
    return value


def _comment_template(value: str) -> str:
    try:
        return validate_comment_template(value)
    except InvalidTemplateError as exc:
        raise ValueError(f"template {exc}") from exc


def _start_from(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().lower()
    if _SHA.fullmatch(value):
        return value
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(
            "must be a date (YYYY-MM-DD) or a commit SHA (7-40 hex characters)"
        ) from None


def _cron_syntax(value: str | None) -> str | None:
    """Syntax only; the minimum interval depends on settings and is checked in the router."""
    if value is None or not value.strip():
        return None
    try:
        return validate_cron(value, min_interval_minutes=1)
    except InvalidCronError as exc:
        raise ValueError(f"schedule {exc}") from exc


BranchName = Annotated[str, Field(max_length=255), AfterValidator(_branch)]
Branches = Annotated[list[BranchName], Field(max_length=MAX_BRANCHES), AfterValidator(_unique)]
TicketPatternField = Annotated[str, Field(max_length=500), AfterValidator(_ticket_pattern)]
CommentTemplateField = Annotated[str, Field(max_length=10_000), AfterValidator(_comment_template)]
StartFrom = Annotated[str | None, Field(max_length=64), AfterValidator(_start_from)]
ScheduleCron = Annotated[str | None, Field(max_length=100), AfterValidator(_cron_syntax)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Create it in this organization (any member), with its connections",
    )
    git_connection_id: uuid.UUID
    azure_connection_id: uuid.UUID
    branches: Branches = Field(
        default_factory=list, description="Empty means the remote's default branch only"
    )
    ticket_pattern: TicketPatternField = DEFAULT_TICKET_PATTERN
    comment_template: CommentTemplateField = DEFAULT_COMMENT_TEMPLATE
    start_from: StartFrom = None
    include_merge_commits: bool = False
    schedule_cron: ScheduleCron = None
    schedule_enabled: bool = False
    dry_run_default: bool = False

    @model_validator(mode="after")
    def _check_schedule(self) -> Self:
        if self.schedule_enabled and not self.schedule_cron:
            raise ValueError("schedule_cron is required when schedule_enabled is true")
        return self


class ProjectUpdate(BaseModel):
    """Omitted fields stay as they are. Send start_from or schedule_cron as null to clear them."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    git_connection_id: uuid.UUID | None = None
    azure_connection_id: uuid.UUID | None = None
    branches: Branches | None = None
    ticket_pattern: TicketPatternField | None = None
    comment_template: CommentTemplateField | None = None
    start_from: StartFrom = None
    include_merge_commits: bool | None = None
    schedule_cron: ScheduleCron = None
    schedule_enabled: bool | None = None
    dry_run_default: bool | None = None


class ProjectGitSummary(BaseModel):
    """What everyone with access sees of the project's Git connection: never its secret."""

    id: uuid.UUID
    name: str
    repo_url: str
    host: GitHost
    commit_url_pattern: str


class ProjectAzureSummary(BaseModel):
    """What everyone with access sees of the project's Azure connection: never its PAT."""

    id: uuid.UUID
    name: str
    organization_url: str
    azure_project: str


ProjectRoleName = Literal["owner", "editor", "viewer"]


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_connection_id: uuid.UUID
    azure_connection_id: uuid.UUID
    branches: list[str]
    ticket_pattern: str
    comment_template: str
    start_from: str | None
    include_merge_commits: bool
    schedule_cron: str | None
    schedule_enabled: bool
    dry_run_default: bool
    created_at: datetime
    updated_at: datetime
    # For the dashboard cards.
    last_run: RunResponse | None = None
    next_run_at: datetime | None = Field(
        default=None, description="Next scheduled run (UTC), if the schedule is on"
    )
    comments_posted: int = Field(default=0, description="Comments posted for this project so far")
    # Sharing.
    role: ProjectRoleName = Field(default="owner", description="Your role on this project")
    owner: UserSummary | None = Field(default=None, description="Null for an organization's")
    organization: OrganizationSummary | None = None
    schedule_timezone: str = Field(
        default="UTC", description="The owner's time zone, which the schedule runs in"
    )
    shares: int = Field(default=0, description="Number of users the project is shared with")
    git_connection: ProjectGitSummary | None = None
    azure_connection: ProjectAzureSummary | None = None


class ProjectMove(BaseModel):
    """Exactly one: into an organization (the personal owner), or to a member (its admins)."""

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID | None = None
    to_user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.organization_id is None) == (self.to_user_id is None):
            raise ValueError("send exactly one of organization_id and to_user_id")
        return self


class ProjectMoved(BaseModel):
    project_id: uuid.UUID
    summary: str = Field(description="What moved, what was copied and what was renamed")


class PatternTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str | None = Field(
        default=None,
        max_length=500,
        description="Required on /projects/test-pattern; defaults to the saved pattern on "
        "/projects/{id}/test-pattern",
    )
    samples: list[Annotated[str, Field(max_length=20_000)]] = Field(max_length=50)


class PatternSampleResult(BaseModel):
    ids: list[int]
    error: str | None = None


class PatternTestResponse(BaseModel):
    pattern: str
    results: list[PatternSampleResult]
