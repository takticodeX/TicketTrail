"""Reviewing a dry run before posting (editors and owners).

- Pick the work item of a commit that had no reference, or a wrong one: the link is
  saved and every later run uses it, as if the message referenced it.
- Deselect a row: the pair is excluded for good; no run will ever post it.
- Post selected: a real run that posts exactly the dry run's remaining rows, without
  scanning the repository again.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.access import insufficient_role, project_for, run_for
from app.api.deps import CurrentUser, DbSession, TaskRunnerDep
from app.api.v1.git_connections import TEST_WAIT_SECONDS, worker_unavailable
from app.api.v1.schemas import (
    ItemWorkItem,
    RunItemResponse,
    SyncStarted,
    WorkItemSearchResult,
)
from app.core.errors import AppError, not_found
from app.db.models import (
    ItemAction,
    ProjectRole,
    RunStatus,
    RunTrigger,
    SyncRun,
    SyncRunItem,
    User,
)
from app.db.repositories import ReviewRepository
from app.worker import task_names
from app.worker.runner import WorkerUnavailableError

router = APIRouter(tags=["review"])

# Rows a review may change: not yet posted, not an error.
_LINKABLE = {
    ItemAction.NO_REFERENCE,
    ItemAction.SKIPPED_NOT_FOUND,
    ItemAction.WOULD_POST,
    ItemAction.EXCLUDED,
}
_REVIEWABLE_STATUSES = {RunStatus.SUCCESS, RunStatus.PARTIAL}


def _reviewable_run(db: DbSession, user: User, run_id: uuid.UUID, action: str) -> SyncRun:
    """A finished dry run that the user may review (an editor of its project)."""
    run, role = run_for(db, user, run_id, action=action)
    if not role.at_least(ProjectRole.EDITOR):
        raise insufficient_role(ProjectRole.EDITOR)
    if not run.dry_run or run.status not in _REVIEWABLE_STATUSES:
        raise AppError(409, "not_reviewable", "Only a finished dry run can be reviewed.")
    return run


def _item(db: DbSession, run: SyncRun, item_id: uuid.UUID) -> SyncRunItem:
    item = db.get(SyncRunItem, item_id)
    if item is None or item.sync_run_id != run.id:
        raise not_found("Item")
    return item


def _done(db: DbSession, item: SyncRunItem) -> RunItemResponse:
    db.commit()
    db.refresh(item)
    return RunItemResponse.model_validate(item)


@router.get("/projects/{project_id}/work-items")
def search_work_items(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    runner: TaskRunnerDep,
    q: Annotated[str, Query(max_length=100, description="Words of the title, or an ID")] = "",
) -> WorkItemSearchResult:
    """Work items of the project's board for the picker: open first, closed last."""
    project_for(db, user, project_id, ProjectRole.EDITOR)
    db.close()  # don't hold a database connection while the worker asks Azure
    try:
        result = runner.run(
            task_names.SEARCH_WORK_ITEMS, [str(project_id), q], timeout=TEST_WAIT_SECONDS
        )
    except WorkerUnavailableError as exc:
        raise worker_unavailable() from exc
    return WorkItemSearchResult.model_validate(result)


@router.put("/runs/{run_id}/items/{item_id}/work-item")
def set_item_work_item(
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemWorkItem,
    user: CurrentUser,
    db: DbSession,
) -> RunItemResponse:
    """Post this row to another work item: links the commit to it from now on.

    The work item the row had before is excluded for this commit (or, if it was
    itself linked by hand, the link is removed).
    """
    run = _reviewable_run(db, user, run_id, "link a commit in")
    item = _item(db, run, item_id)
    if item.action not in _LINKABLE:
        raise AppError(409, "not_linkable", "This row can't be linked to a work item.")
    new = body.work_item_id
    if new == item.work_item_id:
        return RunItemResponse.model_validate(item)
    taken = db.scalar(
        select(func.count())
        .select_from(SyncRunItem)
        .where(
            SyncRunItem.sync_run_id == run.id,
            SyncRunItem.commit_sha == item.commit_sha,
            SyncRunItem.work_item_id == new,
        )
    )
    if taken:
        raise AppError(409, "already_linked", "This commit already has a row for that work item.")
    review = ReviewRepository(db, run.project_id)
    old = item.work_item_id
    if old is not None:
        if item.manual:
            review.unlink(item.commit_sha, old)
        else:
            review.exclude(item.commit_sha, old, user.id)
    review.include(item.commit_sha, new)
    review.link(item.commit_sha, new, user.id)
    item.work_item_id = new
    item.action = ItemAction.WOULD_POST
    item.manual = True
    item.detail = "Linked by hand in a review."
    return _done(db, item)


@router.post("/runs/{run_id}/items/{item_id}/exclude")
def exclude_item(
    run_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> RunItemResponse:
    """Deselect a row: its commit is never posted to that work item, by any run."""
    run = _reviewable_run(db, user, run_id, "deselect a commit in")
    item = _item(db, run, item_id)
    if item.action != ItemAction.WOULD_POST or item.work_item_id is None:
        raise AppError(409, "not_selectable", "Only a row that would be posted can be deselected.")
    ReviewRepository(db, run.project_id).exclude(item.commit_sha, item.work_item_id, user.id)
    item.action = ItemAction.EXCLUDED
    item.detail = "Deselected in a review: never posted."
    return _done(db, item)


@router.delete("/runs/{run_id}/items/{item_id}/exclude")
def include_item(
    run_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> RunItemResponse:
    """Select a deselected row again."""
    run = _reviewable_run(db, user, run_id, "select a commit in")
    item = _item(db, run, item_id)
    if item.action != ItemAction.EXCLUDED or item.work_item_id is None:
        raise AppError(409, "not_selectable", "This row isn't deselected.")
    ReviewRepository(db, run.project_id).include(item.commit_sha, item.work_item_id)
    item.action = ItemAction.WOULD_POST
    item.detail = "Linked by hand in a review." if item.manual else None
    return _done(db, item)


@router.post("/runs/{run_id}/post", status_code=status.HTTP_202_ACCEPTED)
def post_selected(
    run_id: uuid.UUID, user: CurrentUser, db: DbSession, runner: TaskRunnerDep
) -> SyncStarted:
    """Post the reviewed dry run's selected rows: a new real run, without a rescan."""
    source = _reviewable_run(db, user, run_id, "post the selection of")
    selected = db.scalar(
        select(func.count())
        .select_from(SyncRunItem)
        .where(SyncRunItem.sync_run_id == source.id, SyncRunItem.action == ItemAction.WOULD_POST)
    )
    if not selected:
        raise AppError(409, "nothing_selected", "No row of this dry run is selected.")
    run = SyncRun(
        project_id=source.project_id,
        trigger=RunTrigger.MANUAL,
        dry_run=False,
        triggered_by_id=user.id,
        source_run_id=source.id,
    )
    db.add(run)
    db.commit()
    try:
        runner.enqueue(
            task_names.SYNC_PROJECT,
            [str(run.project_id), RunTrigger.MANUAL.value, False, str(run.id)],
        )
    except WorkerUnavailableError as exc:
        run.status = RunStatus.FAILED
        run.error_message = "The task queue was unavailable; the run never started."
        db.commit()
        raise worker_unavailable() from exc
    return SyncStarted(run_id=run.id)
