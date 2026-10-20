"""The permission checks for projects, runs, organizations and connections.

No access at all answers 404, as if the resource didn't exist; access with too weak
a role answers 403, since the user already knows the resource.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.db.base import OwnedModel
from app.db.models import Organization, OrganizationRole, ProjectRole, SyncRun, User
from app.db.repositories import (
    OrganizationRepository,
    ProjectAccessRepository,
    SeenProject,
    SyncRunRepository,
)

_WHO = {
    ProjectRole.VIEWER: "someone it is shared with",
    ProjectRole.EDITOR: "an editor",
    ProjectRole.OWNER: "the owner",
}


def insufficient_role(need: ProjectRole) -> AppError:
    return AppError(403, "insufficient_role", f"Only {_WHO[need]} of this project can do this.")


def not_organization_admin() -> AppError:
    return AppError(403, "insufficient_role", "Only an admin of the organization can do this.")


def project_for(
    db: Session, user: User, project_id: uuid.UUID, need: ProjectRole = ProjectRole.VIEWER
) -> SeenProject:
    """The project, the user's role on it, and its owner."""
    seen = ProjectAccessRepository(db, user.id).get(project_id)
    if seen is None:
        raise not_found("Project")
    if not seen.role.at_least(need):
        raise insufficient_role(need)
    return seen


def run_for(db: Session, user: User, run_id: uuid.UUID) -> tuple[SyncRun, ProjectRole]:
    """The run and the user's role on its project."""
    run = SyncRunRepository(db, user.id).get(run_id)
    if run is None:
        raise not_found("Run")
    return run, project_for(db, user, run.project_id).role


def can_manage_run(user: User, role: ProjectRole, run: SyncRun) -> bool:
    """Editors manage every run; a viewer only the dry runs they started."""
    return role.at_least(ProjectRole.EDITOR) or (run.dry_run and run.triggered_by_id == user.id)


def need_run_manager(user: User, role: ProjectRole, run: SyncRun) -> None:
    if not can_manage_run(user, role, run):
        raise insufficient_role(ProjectRole.EDITOR)


def organization_for(
    db: Session, user: User, organization_id: uuid.UUID, *, admin: bool = False
) -> tuple[Organization, OrganizationRole]:
    """The organization and the user's role in it. Non-members get 404."""
    found = OrganizationRepository(db, user.id).get(organization_id)
    if found is None:
        raise not_found("Organization")
    if admin and found[1] is not OrganizationRole.ADMIN:
        raise not_organization_admin()
    return found


def connection_for[C: OwnedModel](
    db: Session, user: User, model: type[C], connection_id: uuid.UUID, what: str, *, write: bool
) -> C:
    """A connection the user owns, or one of their organization's.

    Members of the organization see, use and test its connections; only its admins
    change or delete them. Anyone else gets 404.
    """
    connection = db.get(model, connection_id)
    if connection is None:
        raise not_found(what)
    if connection.owner_id == user.id:
        return connection
    if connection.organization_id is not None:
        found = OrganizationRepository(db, user.id).get(connection.organization_id)
        if found is not None:
            if write and found[1] is not OrganizationRole.ADMIN:
                raise not_organization_admin()
            return connection
    raise not_found(what)
