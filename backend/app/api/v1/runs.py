"""Starting syncs and reading their history (spec section 8).

Everyone a project is shared with sees its runs and may start dry runs; real syncs
and managing the history take an editor. A viewer may cancel or delete the dry
runs they started themselves.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, func, update

from app.api.access import audit, insufficient_role, need_run_manager, project_for, run_for
from app.api.deps import CurrentUser, DbSession, PageDep, TaskRunnerDep
from app.api.v1.git_connections import worker_unavailable
from app.api.v1.schemas import (
    Page,
    RunDetailResponse,
    RunItemResponse,
    RunResponse,
    RunsDeleted,
    SyncRequest,
    SyncStarted,
)
from app.core.errors import AppError
from app.db.models import (
    ACTIVE_STATUSES,
    ItemAction,
    ProjectRole,
    RunStatus,
    RunTrigger,
    SyncRun,
)
from app.db.repositories import SyncRunRepository
from app.worker import task_names
from app.worker.runner import WorkerUnavailableError

router = APIRouter(tags=["runs"])


@router.post("/projects/{project_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def start_sync(
    project_id: uuid.UUID,
    body: SyncRequest,
    user: CurrentUser,
    db: DbSession,
    runner: TaskRunnerDep,
) -> SyncStarted:
    """Queue a run and return its ID straight away; the worker does the work."""
    seen = project_for(db, user, project_id)
    project, role = seen.project, seen.role
    dry_run = project.dry_run_default if body.dry_run is None else body.dry_run
    if not dry_run and not role.at_least(ProjectRole.EDITOR):
        raise insufficient_role(ProjectRole.EDITOR)
    if seen.via_admin:
        kind = "dry run" if dry_run else "sync"
        audit(user, f"{kind} of project {project.id} ({project.name!r})")
    run = SyncRun(
        project_id=project.id, trigger=RunTrigger.MANUAL, dry_run=dry_run, triggered_by_id=user.id
    )
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
    project_for(db, user, project_id)
    runs, total = SyncRunRepository(db, user.id).list_for_project(
        project_id, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[RunResponse.model_validate(r) for r in runs],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunDetailResponse:
    run, _ = run_for(db, user, run_id)
    counts = SyncRunRepository(db, user.id).counts_by_action(run.id)
    return RunDetailResponse.model_validate(
        {**RunResponse.model_validate(run).model_dump(), "counts_by_action": counts}
    )


@router.post(
    "/runs/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"description": "The run has already finished"}},
)
def cancel_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunResponse:
    """Cooperative cancel: a queued run never starts; a running one stops between commits."""
    run, role = run_for(db, user, run_id, action="cancel")
    need_run_manager(user, role, run)
    # Conditional updates: the worker may be starting the run at this very moment.
    never_started = db.execute(
        update(SyncRun)
        .where(SyncRun.id == run.id, SyncRun.status == RunStatus.QUEUED)
        .values(
            status=RunStatus.CANCELLED,
            cancel_requested=True,
            finished_at=func.now(),
            error_message="Cancelled before it started.",
        )
        .returning(SyncRun.id)
    ).first()
    if never_started is None:
        flagged = db.execute(
            update(SyncRun)
            .where(SyncRun.id == run.id, SyncRun.status.in_(ACTIVE_STATUSES))
            .values(cancel_requested=True)
            .returning(SyncRun.id)
        ).first()
        if flagged is None:
            raise AppError(409, "run_finished", "This run has already finished.")
    db.commit()
    db.refresh(run)
    return RunResponse.model_validate(run)


def _run_active() -> AppError:
    return AppError(409, "run_active", "This run is still in progress. Cancel it first.")


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Delete a finished run and its items from the history.

    Safe: whether a comment was posted is recorded in posted_comments, not in the
    run history, so deleting a run can never cause a comment to be posted again.
    """
    run, role = run_for(db, user, run_id, action="delete")
    need_run_manager(user, role, run)
    if run.status in ACTIVE_STATUSES:
        raise _run_active()
    db.delete(run)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/projects/{project_id}/runs")
def delete_runs(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    dry_run: Annotated[
        bool | None, Query(description="Only dry runs (true) or only real syncs (false)")
    ] = None,
) -> RunsDeleted:
    """Delete a project's finished runs, for example every dry run. Active runs stay."""
    project_for(db, user, project_id, ProjectRole.EDITOR)
    statement = delete(SyncRun).where(
        SyncRun.project_id == project_id, SyncRun.status.not_in(ACTIVE_STATUSES)
    )
    if dry_run is not None:
        statement = statement.where(SyncRun.dry_run.is_(dry_run))
    deleted = len(db.execute(statement.returning(SyncRun.id)).all())
    db.commit()
    return RunsDeleted(deleted=deleted)


@router.get("/runs/{run_id}/items")
def list_run_items(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    page: PageDep,
    action: Annotated[ItemAction | None, Query(description="Only items with this action")] = None,
) -> Page[RunItemResponse]:
    """Oldest commit first."""
    run, _ = run_for(db, user, run_id)
    items, total = SyncRunRepository(db, user.id).items(
        run.id, action=action, offset=page.offset, limit=page.page_size
    )
    return Page(
        items=[RunItemResponse.model_validate(i) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
