"""Sync runs and the items they record."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import UserSummary
from app.db.models import ItemAction, RunStatus, RunTrigger


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool | None = Field(
        default=None, description="Defaults to the project's dry_run_default"
    )


class SyncStarted(BaseModel):
    run_id: uuid.UUID


class RunsDeleted(BaseModel):
    deleted: int


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    trigger: RunTrigger
    dry_run: bool
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    commits_scanned: int
    comments_posted: int
    skipped: int
    errors: int
    error_message: str | None
    cancel_requested: bool
    triggered_by: UserSummary | None = Field(
        default=None, description="Who started a manual run; null for scheduled runs"
    )


class RunDetailResponse(RunResponse):
    counts_by_action: dict[ItemAction, int] = Field(
        description="Number of items per action, for the filters on the run page"
    )


class RunItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    commit_sha: str
    commit_subject: str
    branch: str
    work_item_id: int | None
    action: ItemAction
    detail: str | None
