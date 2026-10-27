"""The permission checks for projects, runs, organizations and connections.

No access at all answers 404, as if the resource didn't exist; access with too weak
a role answers 403, since the user already knows the resource.

Administrators of the instance may do everything. What they do to other users'
resources (anything but reading) is recorded: an audit_events row, written in the
same transaction as the action, and a line from the app.audit logger. Callers name
the action (`action="update"`); without one, nothing is recorded.
"""

import logging
import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.db.base import OwnedModel
from app.db.models import (
    AuditEvent,
    Organization,
    OrganizationRole,
    ProjectRole,
    SyncRun,
    User,
)
from app.db.repositories import (
    OrganizationRepository,
    ProjectAccessRepository,
    SeenProject,
    SyncRunRepository,
)

logger = logging.getLogger("app.audit")

_WHO = {
    ProjectRole.VIEWER: "someone it is shared with",
    ProjectRole.EDITOR: "an editor",
    ProjectRole.OWNER: "the owner",
}


def insufficient_role(need: ProjectRole) -> AppError:
    return AppError(403, "insufficient_role", f"Only {_WHO[need]} of this project can do this.")


def not_organization_admin() -> AppError:
    return AppError(403, "insufficient_role", "Only an admin of the organization can do this.")


def audit(
    db: Session,
    user: User,
    action: str,
    *,
    resource_type: str,
    resource_id: uuid.UUID | None,
    resource_name: str,
    owner_label: str,
) -> None:
    """Record what an administrator did to someone else's resource.

    The row is committed with the action itself, and logged once committed: an action
    that fails leaves neither.
    """
    entry = AuditEvent(
        actor_id=user.id,
        actor_email=user.email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name[:200],
        owner_label=owner_label[:320],
    )
    db.add(entry)
    # The values, not the row: after the commit its attributes are expired.
    db.info.setdefault(_PENDING, []).append(
        (user.id, user.email, action, resource_type, resource_id, resource_name, owner_label)
    )


_PENDING = "audit_pending"


@event.listens_for(Session, "after_commit")
def _log_committed(session: Session) -> None:
    for values in session.info.pop(_PENDING, []):
        logger.info("Admin %s (%s): %s %s %s (%r, owned by %s)", *values)


@event.listens_for(Session, "after_rollback")
def _forget_rolled_back(session: Session) -> None:
    session.info.pop(_PENDING, None)


def seen_owner_label(seen: SeenProject) -> str:
    if seen.organization is not None:
        return f"organization {seen.organization.name}"
    return seen.owner.email if seen.owner is not None else "unknown"


def owner_label(db: Session, item: OwnedModel) -> str:
    if item.organization_id is not None:
        org = db.get(Organization, item.organization_id)
        return f"organization {org.name}" if org else "unknown"
    owner = db.get(User, item.owner_id) if item.owner_id else None
    return owner.email if owner else "unknown"


def audit_project(db: Session, user: User, seen: SeenProject, action: str) -> None:
    audit(
        db,
        user,
        action,
        resource_type="project",
        resource_id=seen.project.id,
        resource_name=seen.project.name,
        owner_label=seen_owner_label(seen),
    )


def project_for(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    need: ProjectRole = ProjectRole.VIEWER,
    *,
    action: str | None = None,
) -> SeenProject:
    """The project, the user's role on it, and its owner."""
    seen = ProjectAccessRepository(db, user.id, is_admin=user.is_admin).get(project_id)
    if seen is None:
        raise not_found("Project")
    if not seen.role.at_least(need):
        raise insufficient_role(need)
    if seen.via_admin and action is not None:
        audit_project(db, user, seen, action)
    return seen


def run_for(
    db: Session, user: User, run_id: uuid.UUID, *, action: str | None = None
) -> tuple[SyncRun, ProjectRole]:
    """The run and the user's role on its project. `action` is recorded for administrators."""
    run = SyncRunRepository(db, user.id, is_admin=user.is_admin).get(run_id)
    if run is None:
        raise not_found("Run")
    seen = project_for(db, user, run.project_id)
    if action is not None and seen.via_admin:
        kind = "dry run" if run.dry_run else "run"
        audit(
            db,
            user,
            action,
            resource_type="run",
            resource_id=run.id,
            resource_name=f"{kind} of {seen.project.name}",
            owner_label=seen_owner_label(seen),
        )
    return run, seen.role


def can_manage_run(user: User, role: ProjectRole, run: SyncRun) -> bool:
    """Editors manage every run; a viewer only the dry runs they started."""
    return role.at_least(ProjectRole.EDITOR) or (run.dry_run and run.triggered_by_id == user.id)


def need_run_manager(user: User, role: ProjectRole, run: SyncRun) -> None:
    if not can_manage_run(user, role, run):
        raise insufficient_role(ProjectRole.EDITOR)


def organization_for(
    db: Session,
    user: User,
    organization_id: uuid.UUID,
    *,
    admin: bool = False,
    action: str | None = None,
) -> tuple[Organization, OrganizationRole]:
    """The organization and the user's role in it. Non-members get 404."""
    membership = OrganizationRepository(db, user.id).get(organization_id)
    found = membership
    if found is None and user.is_admin:  # administrators act as an admin of every organization
        found = OrganizationRepository(db, user.id, is_admin=True).get(organization_id)
    if found is None:
        raise not_found("Organization")
    if admin and found[1] is not OrganizationRole.ADMIN:
        raise not_organization_admin()
    if membership is None and action is not None:
        audit(
            db,
            user,
            action,
            resource_type="organization",
            resource_id=found[0].id,
            resource_name=found[0].name,
            owner_label=f"organization {found[0].name}",
        )
    return found


_RESOURCE_TYPES = {"Git connection": "git_connection", "Azure connection": "azure_connection"}


def connection_for[C: OwnedModel](
    db: Session,
    user: User,
    model: type[C],
    connection_id: uuid.UUID,
    what: str,
    *,
    action: str | None = None,
) -> C:
    """A connection the user owns, or one of their organization's.

    Members of the organization see, use and test its connections; only its admins
    change or delete them (an `action`). Anyone else gets 404, administrators aside.
    """
    connection = db.get(model, connection_id)
    if connection is None:
        raise not_found(what)
    if connection.owner_id == user.id:
        return connection
    if connection.organization_id is not None:
        found = OrganizationRepository(db, user.id).get(connection.organization_id)
        if found is not None and (action is None or found[1] is OrganizationRole.ADMIN):
            return connection
        if found is not None and not user.is_admin:
            raise not_organization_admin()
    if user.is_admin:
        if action is not None:
            audit(
                db,
                user,
                action,
                resource_type=_RESOURCE_TYPES[what],
                resource_id=connection.id,
                resource_name=connection.name,
                owner_label=owner_label(db, connection),
            )
        return connection
    raise not_found(what)
