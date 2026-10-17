"""Starting syncs and reading their history (spec section 8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, PageDep, TaskRunnerDep
from app.api.v1.git_connections import worker_unavailable
from app.api.v1.schemas import (
    Page,
    RunDetailResponse,
    RunItemResponse,
    RunResponse,
    SyncRequest,
    SyncStarted,
)
from app.core.errors import AppError, not_found
from app.db.models import ItemAction, RunStatus, RunTrigger, SyncRun
from app.db.repositories import ProjectRepository, SyncRunRepository
from app.worker import task_names
from app.worker.runner import WorkerUnavailableError

router = APIRouter(tags=["runs"])


@router.post(
    "/projects/{project_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"description": "Real syncs are not available yet"}},
)
def start_sync(
    project_id: uuid.UUID,
    body: SyncRequest,
    user: CurrentUser,
    db: DbSession,
    runner: TaskRunnerDep,
) -> SyncStarted:
    """Queue a run and return its ID straight away; the worker does the work."""
    project = ProjectRepository(db, user.id).get(project_id)
    if project is None:
        raise not_found("Project")
    dry_run = project.dry_run_default if body.dry_run is None else body.dry_run
    if not dry_run:
        raise AppError(
            400,
            "sync_not_available",
            "Only dry runs are available in this version; posting to Azure DevOps comes next.",
        )

    run = SyncRun(project_id=project.id, trigger=RunTrigger.MANUAL, dry_run=dry_run)
    db.add(run)
    db.commit()
    try:
        runner.enqueue(
            task_names.SYNC_PROJECT,
            [str(project.id), RunTrigger.MANUAL.value, dry_run, str(run.id)],
        )
    except WorkerUnavailableError as exc:
        run.status = RunStatus.FAILED
        run.error_message = "The task queue was unavailable; the run never started."
        db.commit()
        raise worker_unavailable() from exc
    return SyncStarted(run_id=run.id)


@router.get("/projects/{project_id}/runs")
def list_runs(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, page: PageDep
) -> Page[RunResponse]:
    """Newest first."""
    if ProjectRepository(db, user.id).get(project_id) is None:
        raise not_found("Project")
    runs, total = SyncRunRepository(db, user.id).list_for_project(
        project_id, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[RunResponse.model_validate(r) for r in runs],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


def _get_run(db: DbSession, user: CurrentUser, run_id: uuid.UUID) -> SyncRun:
    run = SyncRunRepository(db, user.id).get(run_id)
    if run is None:
        raise not_found("Run")
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunDetailResponse:
    run = _get_run(db, user, run_id)
    counts = SyncRunRepository(db, user.id).counts_by_action(run.id)
    return RunDetailResponse.model_validate(
        {**RunResponse.model_validate(run).model_dump(), "counts_by_action": counts}
    )


@router.get("/runs/{run_id}/items")
def list_run_items(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    page: PageDep,
    action: Annotated[ItemAction | None, Query(description="Only items with this action")] = None,
) -> Page[RunItemResponse]:
    """Oldest commit first."""
    run = _get_run(db, user, run_id)
    items, total = SyncRunRepository(db, user.id).items(
        run.id, action=action, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[RunItemResponse.model_validate(i) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
