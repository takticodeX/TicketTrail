"""The sync engine: one run of one project (spec section 7).

A run is safe to repeat at any point: running it twice, or after a crash,
never posts a comment twice, because every comment is guarded by a
`posted_comments` row (unique per project, commit and work item) that is
committed as `pending` before the comment is sent.

Steps:
 1. (Milestone 6: per-project lock.) Close this project's runs whose heartbeat stopped.
 2. Mark the run running; secrets are decrypted in memory only.
 3. Fetch the repository and list the new commits per branch.
 4. Extract work-item IDs; commits without one are `no_reference`.
 5. Resolve `pending` rows left by a crash (look for the tt:{sha} marker), then
    skip pairs already `posted` (`skipped_duplicate`).
 6. Check in batches that the work items exist (`skipped_not_found`).
 7. Post each pair, oldest commit first: insert `pending`, post, mark `posted`.
    A dry run stops here and records `would_post` instead.
 8. Move each branch cursor past the commits that are done for good.
 9. Finish as success, partial (some errors) or failed.
"""

import logging
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import (
    AzureConnection,
    CommentStatus,
    GitAuthType,
    GitConnection,
    ItemAction,
    PostedComment,
    Project,
    RunStatus,
    SyncRun,
    SyncRunItem,
)
from app.db.repositories import (
    CursorRepository,
    PostedCommentRepository,
    close_stale_runs,
    other_run_active,
)
from app.integrations.git.client import (
    Commit,
    GitAuthError,
    GitClient,
    GitCredentials,
    GitError,
    GitNotFoundError,
)
from app.integrations.git.hosts import commit_url, repo_name
from app.integrations.trackers.azure import AzureBoardsClient
from app.integrations.trackers.base import (
    TrackerAuthError,
    TrackerError,
    TrackerNotFoundError,
    TrackerTransientError,
)
from app.sync.parser import (
    InvalidPatternError,
    PatternTimeoutError,
    TicketPattern,
    compile_ticket_pattern,
)
from app.sync.template import CommentContext, render_comment
from app.worker.context import WorkerContext

logger = logging.getLogger(__name__)

MAX_SUBJECT_LENGTH = 500
HEARTBEAT_SECONDS = 5.0
AZURE_TIMEOUT_SECONDS = 30.0


def stale_after(context: WorkerContext) -> timedelta:
    """How long a run may go without a heartbeat. Longer than any single git command."""
    return max(timedelta(minutes=10), timedelta(seconds=2 * context.settings.git_timeout))


class RunFailedError(Exception):
    """Stops the run; the message is shown to the user."""


@dataclass(frozen=True)
class _Pair:
    commit: Commit
    branch: str
    work_item_id: int


@dataclass
class _Run:
    """Everything one run accumulates. Items are written as they are produced."""

    db: Session
    run: SyncRun
    project: Project
    context: WorkerContext
    warnings: list[str] = field(default_factory=list)
    # Commits with an error that may go away: cursors must not move past them.
    blocked: set[str] = field(default_factory=set)
    _position: int = 0
    _last_beat: float = field(default_factory=time.monotonic)

    def item(
        self,
        commit: Commit,
        branch: str,
        action: ItemAction,
        work_item_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.db.add(
            SyncRunItem(
                sync_run_id=self.run.id,
                position=self._position,
                commit_sha=commit.sha,
                work_item_id=work_item_id,
                action=action,
                detail=detail,
                commit_subject=commit.subject[:MAX_SUBJECT_LENGTH],
                branch=branch,
            )
        )
        self._position += 1
        if action == ItemAction.POSTED:
            self.run.comments_posted += 1
        elif action in (ItemAction.SKIPPED_DUPLICATE, ItemAction.SKIPPED_NOT_FOUND):
            self.run.skipped += 1
        elif action == ItemAction.ERROR:
            self.run.errors += 1

    def heartbeat(self, *, force: bool = False) -> None:
        """Commit progress and show the run is alive, at most every few seconds."""
        if force or time.monotonic() - self._last_beat >= HEARTBEAT_SECONDS:
            self.run.updated_at = datetime.now(UTC)
            self.db.commit()
            self._last_beat = time.monotonic()


# --- Git -----------------------------------------------------------------------------------


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


@dataclass
class _Scan:
    # Unique commits to process, oldest first, with the branch they were found on.
    commits: list[tuple[Commit, str]] = field(default_factory=list)
    # Every commit each branch listed, in order: what its cursor may move past.
    branch_shas: dict[str, list[str]] = field(default_factory=dict)


def _scan_git(state: _Run, connection: GitConnection) -> _Scan:
    context, project = state.context, state.project
    try:
        check_public_host(connection.repo_url, allow_private=context.settings.allow_private_hosts)
    except UnsafeUrlError as exc:
        raise RunFailedError(f"Repository URL refused: {exc}.") from exc

    client = _git_client(context, connection)
    path = context.repos_dir / str(project.id)
    client.mirror(connection.repo_url, path)
    cursors = CursorRepository(state.db).for_project(project.id)

    if project.branches:
        branches = list(project.branches)
    else:
        default = client.ls_remote(connection.repo_url).default_branch
        if default is None:
            raise RunFailedError(
                "The repository has no default branch. Choose branches in Settings."
            )
        branches = [default]

    scan = _Scan()
    seen: set[str] = set()
    start_sha, start_date = _start_from(project)
    for branch in branches:
        if not client.has_branch(path, branch):
            state.warnings.append(f"Branch {branch!r} does not exist in the repository.")
            state.run.errors += 1
            continue
        cursor = cursors.get(branch)
        if cursor is not None and not client.is_ancestor(path, cursor, branch):
            # History was rewritten (force-push): rescan; posted_comments prevents repeats.
            logger.warning("Cursor %s is not on %s any more; rescanning", cursor, branch)
            state.warnings.append(
                f"The history of {branch!r} was rewritten; "
                "it was scanned again from the start point."
            )
            cursor = None
        if cursor is None and start_sha is not None:
            if not client.has_commit(path, start_sha):
                raise RunFailedError(f"The start commit {start_sha} is not in the repository.")
            commits = client.list_commits(path, branch, after_sha=start_sha)
        else:
            commits = client.list_commits(path, branch, after_sha=cursor, since=start_date)

        scan.branch_shas[branch] = [commit.sha for commit in commits]
        for commit in commits:
            if commit.sha in seen:  # reachable from several branches: once per run
                continue
            seen.add(commit.sha)
            state.run.commits_scanned += 1
            if commit.is_merge and not project.include_merge_commits:
                continue
            scan.commits.append((commit, branch))
    return scan


@dataclass(frozen=True)
class _Entry:
    """One commit to process, with the IDs it references (or why they couldn't be read)."""

    commit: Commit
    branch: str
    ids: list[int]
    error: str | None = None


def _extract(scan: _Scan, pattern: TicketPattern) -> list[_Entry]:
    entries: list[_Entry] = []
    for commit, branch in scan.commits:
        try:
            entries.append(_Entry(commit, branch, pattern.extract(commit.message)))
        except PatternTimeoutError:
            entries.append(
                _Entry(commit, branch, [], "The ticket pattern took too long on this message.")
            )
    return entries


# --- Azure ---------------------------------------------------------------------------------


def _tracker(state: _Run, connection: AzureConnection) -> AzureBoardsClient:
    context = state.context
    try:
        check_public_host(
            connection.organization_url, allow_private=context.settings.allow_private_hosts
        )
    except UnsafeUrlError as exc:
        raise RunFailedError(f"Organization URL refused: {exc}.") from exc
    try:
        pat = context.secret_box.decrypt(connection.pat_enc)
    except SecretDecryptionError as exc:
        raise RunFailedError(
            "The Azure connection's PAT can't be decrypted. Enter it again in Settings."
        ) from exc
    return AzureBoardsClient(
        connection.organization_url,
        connection.azure_project,
        pat,
        timeout=AZURE_TIMEOUT_SECONDS,
        limiter=context.azure_limiter(connection.organization_url),
        sleep=context.sleep,
    )


def _recover_pending(state: _Run, tracker: AzureBoardsClient) -> None:
    """Resolve `pending` rows a crashed run left behind (spec section 7, crash recovery).

    Skipped while another run of the project is active: its pending rows may be
    comments being posted right now.
    """
    if other_run_active(state.db, state.project.id, state.run.id):
        return
    for row in PostedCommentRepository(state.db, state.project.id).pending():
        marker = f"tt:{row.commit_sha}"
        try:
            comments = tracker.list_comments(row.work_item_id)
        except TrackerNotFoundError:
            comments = []  # the work item is gone; the pair will be skipped as not found
        match = next((c for c in comments if marker in c.text), None)
        if match is not None:  # it was posted before the crash: don't post again
            row.status = CommentStatus.POSTED
            row.azure_comment_id = match.id
            row.posted_at = datetime.now(UTC)
        else:  # never reached Azure: drop the guard so the pair is posted below
            state.db.delete(row)
        state.heartbeat()
    state.db.commit()


def _comment_text(state: _Run, pair: _Pair, connection: GitConnection) -> str:
    commit = pair.commit
    return render_comment(
        state.project.comment_template,
        CommentContext(
            sha=commit.sha,
            message=commit.message,
            subject=commit.subject,
            body=commit.body,
            author_name=commit.author_name,
            author_email=commit.author_email,
            author_date=commit.author_date,
            branch=pair.branch,
            repo_name=repo_name(connection.repo_url),
            commit_url=commit_url(connection.repo_url, connection.commit_url_template, commit.sha),
        ),
    )


def _post(state: _Run, tracker: AzureBoardsClient, pair: _Pair, git: GitConnection) -> None:
    commit, branch, work_item_id = pair.commit, pair.branch, pair.work_item_id
    db = state.db
    guard = PostedComment(
        project_id=state.project.id, commit_sha=commit.sha, work_item_id=work_item_id
    )
    try:
        with db.begin_nested():  # a savepoint: a conflict mustn't discard other progress
            db.add(guard)
    except IntegrityError as exc:
        if "uq_posted_comments_pair" not in str(exc.orig):
            raise
        state.item(
            commit,
            branch,
            ItemAction.SKIPPED_DUPLICATE,
            work_item_id,
            "Being posted by another run.",
        )
        return
    db.commit()  # the guard must be durable before the comment is sent

    try:
        comment_id = tracker.add_comment(work_item_id, _comment_text(state, pair, git))
    except TrackerTransientError as exc:
        # The comment may have reached Azure (for example a timeout after sending):
        # keep the guard pending; the next run checks for the marker.
        state.blocked.add(commit.sha)
        state.item(commit, branch, ItemAction.ERROR, work_item_id, f"{exc} Will retry.")
        db.commit()
        return
    except TrackerNotFoundError:
        db.delete(guard)
        state.item(
            commit,
            branch,
            ItemAction.SKIPPED_NOT_FOUND,
            work_item_id,
            "The work item was deleted during the run.",
        )
        db.commit()
        return
    except TrackerAuthError:
        db.delete(guard)  # nothing was posted
        db.commit()
        raise
    except TrackerError as exc:  # refused for good (for example a 400)
        db.delete(guard)
        state.item(commit, branch, ItemAction.ERROR, work_item_id, str(exc))
        db.commit()
        return

    guard.status = CommentStatus.POSTED
    guard.azure_comment_id = comment_id
    guard.posted_at = datetime.now(UTC)
    state.item(commit, branch, ItemAction.POSTED, work_item_id, f"Comment {comment_id}")
    db.commit()


def _process(
    state: _Run, entries: list[_Entry], azure: AzureConnection, git: GitConnection
) -> None:
    """Steps 5-7, recording one item per commit or pair, oldest commit first."""
    pairs = [_Pair(e.commit, e.branch, work_item_id) for e in entries for work_item_id in e.ids]
    with ExitStack() as stack:
        tracker = stack.enter_context(_tracker(state, azure)) if pairs else None
        posted: set[tuple[str, int]] = set()
        found: set[int] = set()
        if tracker is not None:  # no references at all: Azure isn't needed
            if not state.run.dry_run:
                _recover_pending(state, tracker)
            existing = PostedCommentRepository(state.db, state.project.id).for_commits(
                pair.commit.sha for pair in pairs
            )
            posted = {key for key, row in existing.items() if row.status == CommentStatus.POSTED}
            found = tracker.existing_work_items(
                p.work_item_id for p in pairs if (p.commit.sha, p.work_item_id) not in posted
            )

        for entry in entries:
            commit, branch = entry.commit, entry.branch
            if entry.error is not None:
                state.item(commit, branch, ItemAction.ERROR, detail=entry.error)
            elif not entry.ids:
                state.item(commit, branch, ItemAction.NO_REFERENCE)
            for work_item_id in entry.ids:
                if (commit.sha, work_item_id) in posted:
                    state.item(
                        commit,
                        branch,
                        ItemAction.SKIPPED_DUPLICATE,
                        work_item_id,
                        "Already posted.",
                    )
                elif work_item_id not in found:
                    state.item(
                        commit,
                        branch,
                        ItemAction.SKIPPED_NOT_FOUND,
                        work_item_id,
                        "No such work item in this project.",
                    )
                elif state.run.dry_run:
                    state.item(commit, branch, ItemAction.WOULD_POST, work_item_id)
                elif tracker is not None:
                    _post(state, tracker, _Pair(commit, branch, work_item_id), git)
            state.heartbeat()


def _move_cursors(state: _Run, scan: _Scan) -> None:
    cursors = CursorRepository(state.db)
    for branch, shas in scan.branch_shas.items():
        last_done = None
        for sha in shas:
            if sha in state.blocked:
                break
            last_done = sha
        if last_done is not None:
            cursors.move(state.project.id, branch, last_done)


# --- The run -------------------------------------------------------------------------------


def _execute(state: _Run) -> None:
    db, project = state.db, state.project
    git = db.get(GitConnection, project.git_connection_id)
    azure = db.get(AzureConnection, project.azure_connection_id)
    if git is None or azure is None:  # protected by foreign keys; defensive
        raise RunFailedError("The project's connections no longer exist.")
    try:
        pattern = compile_ticket_pattern(project.ticket_pattern)
    except InvalidPatternError as exc:
        raise RunFailedError(f"The ticket pattern {exc}.") from exc

    scan = _scan_git(state, git)
    state.heartbeat(force=True)
    entries = _extract(scan, pattern)
    try:
        _process(state, entries, azure, git)
    except TrackerAuthError as exc:
        azure.last_test_ok = False  # show the connection as failing in Settings
        azure.last_test_at = datetime.now(UTC)
        raise RunFailedError(f"Azure DevOps: {exc}") from exc
    except TrackerError as exc:  # the existence check or recovery could not complete
        raise RunFailedError(f"Azure DevOps: {exc}") from exc
    if not state.run.dry_run:  # dry runs never move cursors
        _move_cursors(state, scan)


def _git_failure(exc: GitError) -> str:
    if isinstance(exc, GitAuthError):
        return "Git authentication failed. Check the connection's username and token in Settings."
    if isinstance(exc, GitNotFoundError):
        return "The repository was not found, or the connection's credentials can't see it."
    return f"Git failed: {exc}"


@dataclass(frozen=True)
class _Outcome:
    status: RunStatus
    message: str | None


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
        close_stale_runs(db, older_than=stale_after(context), project_id=project.id, exclude=run.id)
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        db.commit()

        state = _Run(db=db, run=run, project=project, context=context)
        outcome = _run_safely(state)
        run.status = outcome.status
        run.error_message = outcome.message
        run.finished_at = datetime.now(UTC)
        db.commit()


def _run_safely(state: _Run) -> _Outcome:
    try:
        _execute(state)
    except RunFailedError as exc:
        return _failed(state, str(exc))
    except GitError as exc:
        return _failed(state, _git_failure(exc))
    except Exception:
        logger.exception("Run %s crashed", state.run.id)
        state.db.rollback()
        return _Outcome(RunStatus.FAILED, "The run failed unexpectedly. See the worker log.")
    status = RunStatus.PARTIAL if state.run.errors else RunStatus.SUCCESS
    return _Outcome(status, "\n".join(state.warnings) or None)


def _failed(state: _Run, message: str) -> _Outcome:
    return _Outcome(RunStatus.FAILED, "\n".join([message, *state.warnings]))
