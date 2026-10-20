"""The permission check for projects and their runs (viewer < editor < owner).

No access at all answers 404, as if the project didn't exist; access with too weak
a role answers 403, since the user already knows the project.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.db.models import Project, ProjectRole, SyncRun, User
from app.db.repositories import ProjectAccessRepository, SyncRunRepository

_WHO = {
    ProjectRole.VIEWER: "someone it is shared with",
    ProjectRole.EDITOR: "an editor",
    ProjectRole.OWNER: "the owner",
}


def insufficient_role(need: ProjectRole) -> AppError:
    return AppError(403, "insufficient_role", f"Only {_WHO[need]} of this project can do this.")


def project_for(
    db: Session, user: User, project_id: uuid.UUID, need: ProjectRole = ProjectRole.VIEWER
) -> tuple[Project, ProjectRole, User]:
    """The project, the user's role on it, and its owner."""
    found = ProjectAccessRepository(db, user.id).get(project_id)
    if found is None:
        raise not_found("Project")
    project, role, owner = found
    if not role.at_least(need):
        raise insufficient_role(need)
    return project, role, owner


def run_for(db: Session, user: User, run_id: uuid.UUID) -> tuple[SyncRun, ProjectRole]:
    """The run and the user's role on its project."""
    run = SyncRunRepository(db, user.id).get(run_id)
    if run is None:
        raise not_found("Run")
    _, role, _ = project_for(db, user, run.project_id)
    return run, role


def can_manage_run(user: User, role: ProjectRole, run: SyncRun) -> bool:
    """Editors manage every run; a viewer only the dry runs they started."""
    return role.at_least(ProjectRole.EDITOR) or (run.dry_run and run.triggered_by_id == user.id)


def need_run_manager(user: User, role: ProjectRole, run: SyncRun) -> None:
    if not can_manage_run(user, role, run):
        raise insufficient_role(ProjectRole.EDITOR)
