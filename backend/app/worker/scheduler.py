"""Scheduled syncs (spec section 7): a dispatcher that Celery Beat calls every minute.

Schedules live in the database (projects.schedule_cron, evaluated in the owner's
time zone: the user's, or the organization's), so a change in the UI applies at the
next minute without a restart. Each schedule slot fires at most once: it is claimed
with an atomic update of projects.schedule_last_fired_at, which also makes several
schedulers safe.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.cron import latest_slot
from app.db.models import Organization, Project, RunStatus, RunTrigger, SyncRun, User
from app.worker import task_names
from app.worker.context import WorkerContext
from app.worker.runner import TaskRunner, WorkerUnavailableError

logger = logging.getLogger(__name__)


def _claim(db: Session, project: Project, slot: datetime) -> bool:
    """Mark the slot as fired, unless another scheduler already did."""
    last = project.schedule_last_fired_at
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.schedule_last_fired_at.is_(None)
            if last is None
            else Project.schedule_last_fired_at == last,
        )
        .values(schedule_last_fired_at=slot)
        .returning(Project.id)
    )
    return result.first() is not None


def dispatch_due_schedules(
    context: WorkerContext, runner: TaskRunner, *, now: datetime | None = None
) -> list[uuid.UUID]:
    """Start a run for every project whose schedule came due. Returns the new run IDs."""
    now = now or datetime.now(UTC)
    started: list[uuid.UUID] = []
    with context.session_factory() as db:
        rows = db.execute(
            select(Project, func.coalesce(Organization.timezone, User.timezone, "UTC"))
            .outerjoin(User, User.id == Project.owner_id)
            .outerjoin(Organization, Organization.id == Project.organization_id)
            .where(
                Project.schedule_enabled.is_(True),
                Project.schedule_cron.is_not(None),
                # A turned-off account's projects stop; an organization's keep running.
                or_(Project.organization_id.is_not(None), User.is_active.is_(True)),
            )
        ).all()
        for project, timezone in rows:
            cron = project.schedule_cron or ""
            try:
                slot = latest_slot(cron, timezone, now)
            except (ValueError, KeyError):
                logger.warning("Project %s has an unusable schedule %r", project.id, cron)
                continue
            last = project.schedule_last_fired_at
            if last is None:
                # Never armed (should not happen: the API sets it). Start counting from now.
                db.execute(
                    update(Project)
                    .where(Project.id == project.id, Project.schedule_last_fired_at.is_(None))
                    .values(schedule_last_fired_at=now)
                )
                db.commit()
                continue
            if slot <= last or not _claim(db, project, slot):
                continue
            run = SyncRun(
                project_id=project.id,
                trigger=RunTrigger.SCHEDULED,
                dry_run=project.dry_run_default,
            )
            db.add(run)
            db.commit()
            try:
                runner.enqueue(
                    task_names.SYNC_PROJECT,
                    [str(project.id), RunTrigger.SCHEDULED.value, run.dry_run, str(run.id)],
                )
            except WorkerUnavailableError:
                run.status = RunStatus.FAILED
                run.error_message = "The task queue was unavailable; the run never started."
                run.finished_at = datetime.now(UTC)
                db.commit()
                continue
            logger.info(
                "Started scheduled run %s for project %s (slot %s)", run.id, project.id, slot
            )
            started.append(run.id)
    return started
