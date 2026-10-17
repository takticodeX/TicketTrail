"""The sync engine: one run of one project (spec section 7).

Milestone 4 covers steps 2-4 for dry runs: fetch the repository, list the new
commits and extract the work-item IDs. Each commit/work item pair is recorded
as `would_post`, and commits without a reference as `no_reference`. Nothing is
sent to Azure and no cursors move. Posting, de-duplication and cursor updates
come in Milestone 5; the per-project lock in Milestone 6.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import (
    GitAuthType,
    GitConnection,
    ItemAction,
    Project,
    RunStatus,
    SyncRun,
    SyncRunItem,
)
from app.db.repositories import CursorRepository
from app.integrations.git.client import (
    Commit,
    GitAuthError,
    GitClient,
    GitCredentials,
    GitError,
    GitNotFoundError,
)
from app.sync.parser import (
    InvalidPatternError,
    PatternTimeoutError,
    TicketPattern,
    compile_ticket_pattern,
)
from app.worker.context import WorkerContext

logger = logging.getLogger(__name__)

MAX_SUBJECT_LENGTH = 500


class RunFailedError(Exception):
    """Stops the run; the message is shown to the user."""


@dataclass
class _Progress:
    items: list[SyncRunItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    commits_scanned: int = 0
    errors: int = 0


def _start_from(project: Project) -> tuple[str | None, date | None]:
    """The project's start point as (sha, date); at most one is set."""
    if project.start_from is None:
        return None, None
    try:
        return None, date.fromisoformat(project.start_from)
    except ValueError:
        return project.start_from, None


def _git_client(context: WorkerContext, connection: GitConnection) -> GitClient:
    credentials = None
    if connection.auth_type != GitAuthType.NONE:
        try:
            secret = context.secret_box.decrypt(connection.secret_enc or "")
        except SecretDecryptionError as exc:
            raise RunFailedError(
                "The Git connection's secret can't be decrypted. Enter it again in Settings."
            ) from exc
        credentials = GitCredentials(connection.username or "", secret)
    return GitClient(
        credentials,
        timeout=float(context.settings.git_timeout),
        allowed_protocols=context.git_protocols,
    )


def _branches(client: GitClient, project: Project, connection: GitConnection) -> list[str]:
    if project.branches:
        return list(project.branches)
    default = client.ls_remote(connection.repo_url).default_branch
    if default is None:
        raise RunFailedError("The repository has no default branch. Choose branches in Settings.")
    return [default]


def _commits_for_branch(
    client: GitClient,
    context: WorkerContext,
    project: Project,
    branch: str,
    cursor: str | None,
    progress: _Progress,
) -> list[Commit]:
    path = context.repos_dir / str(project.id)
    if cursor is not None and not client.is_ancestor(path, cursor, branch):
        # History was rewritten (force-push): rescan; de-duplication prevents repeats.
        logger.warning("Cursor %s is not on %s any more; rescanning", cursor, branch)
        progress.warnings.append(
            f"The history of {branch!r} was rewritten; it was scanned again from the start point."
        )
        cursor = None
    start_sha, start_date = _start_from(project)
    if cursor is None and start_sha is not None:
        if not client.has_commit(path, start_sha):
            raise RunFailedError(f"The start commit {start_sha} is not in the repository.")
        return client.list_commits(path, branch, after_sha=start_sha)
    return client.list_commits(path, branch, after_sha=cursor, since=start_date)


def _scan(context: WorkerContext, db: Session, run: SyncRun, project: Project) -> _Progress:
    connection = db.get(GitConnection, project.git_connection_id)
    if connection is None:  # protected by the foreign key; defensive
        raise RunFailedError("The project's Git connection no longer exists.")
    try:
        pattern = compile_ticket_pattern(project.ticket_pattern)
    except InvalidPatternError as exc:
        raise RunFailedError(f"The ticket pattern {exc}.") from exc
    try:
        check_public_host(connection.repo_url, allow_private=context.settings.allow_private_hosts)
    except UnsafeUrlError as exc:
        raise RunFailedError(f"Repository URL refused: {exc}.") from exc

    client = _git_client(context, connection)
    path = context.repos_dir / str(project.id)
    client.mirror(connection.repo_url, path)
    cursors = CursorRepository(db).for_project(project.id)

    progress = _Progress()
    seen: set[str] = set()
    for branch in _branches(client, project, connection):
        if not client.has_branch(path, branch):
            progress.warnings.append(f"Branch {branch!r} does not exist in the repository.")
            progress.errors += 1
            continue
        for commit in _commits_for_branch(
            client, context, project, branch, cursors.get(branch), progress
        ):
            if commit.sha in seen:  # reachable from several branches: once per run
                continue
            seen.add(commit.sha)
            progress.commits_scanned += 1
            if commit.is_merge and not project.include_merge_commits:
                continue
            _record_commit(run, commit, branch, pattern, progress)
    return progress


def _record_commit(
    run: SyncRun, commit: Commit, branch: str, pattern: TicketPattern, progress: _Progress
) -> None:
    def item(
        action: ItemAction, work_item_id: int | None = None, detail: str | None = None
    ) -> None:
        progress.items.append(
            SyncRunItem(
                sync_run_id=run.id,
                position=len(progress.items),
                commit_sha=commit.sha,
                work_item_id=work_item_id,
                action=action,
                detail=detail,
                commit_subject=commit.subject[:MAX_SUBJECT_LENGTH],
                branch=branch,
            )
        )

    try:
        ids = pattern.extract(commit.message)
    except PatternTimeoutError:
        progress.errors += 1
        item(ItemAction.ERROR, detail="The ticket pattern took too long on this message.")
        return
    if not ids:
        item(ItemAction.NO_REFERENCE)
        return
    for work_item_id in ids:
        item(ItemAction.WOULD_POST, work_item_id)


def _git_failure(exc: GitError) -> str:
    if isinstance(exc, GitAuthError):
        return "Git authentication failed. Check the connection's username and token in Settings."
    if isinstance(exc, GitNotFoundError):
        return "The repository was not found, or the connection's credentials can't see it."
    return f"Git failed: {exc}"


def run_sync(context: WorkerContext, run_id: uuid.UUID) -> None:
    """Execute a queued run. Never raises: the outcome is stored on the run."""
    with context.session_factory() as db:
        run = db.get(SyncRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            logger.warning("Run %s is not queued; ignoring", run_id)
            return
        project = db.get(Project, run.project_id)
        if project is None:
            return
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        db.commit()

        if not run.dry_run:  # posting arrives in Milestone 5
            _finish(db, run, RunStatus.FAILED, "Only dry runs are available in this version.")
            return
        try:
            progress = _scan(context, db, run, project)
        except RunFailedError as exc:
            _finish(db, run, RunStatus.FAILED, str(exc))
            return
        except GitError as exc:
            _finish(db, run, RunStatus.FAILED, _git_failure(exc))
            return
        except Exception:
            logger.exception("Run %s crashed", run_id)
            db.rollback()
            _finish(db, run, RunStatus.FAILED, "The run failed unexpectedly. See the worker log.")
            return

        db.add_all(progress.items)
        run.commits_scanned = progress.commits_scanned
        run.errors = progress.errors
        status = RunStatus.PARTIAL if progress.errors else RunStatus.SUCCESS
        _finish(db, run, status, "\n".join(progress.warnings) or None)


def _finish(db: Session, run: SyncRun, status: RunStatus, message: str | None) -> None:
    run.status = status
    run.error_message = message
    run.finished_at = datetime.now(UTC)
    db.commit()
