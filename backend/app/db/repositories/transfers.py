"""Moving projects and connections to another owner: a user or an organization.

Used by the administrator's transfers and by moving a project into or out of an
organization. Secrets move as they are, still encrypted: nobody sees them on the way.
A connection the previous owner still uses in another project is copied instead of
moved, so their remaining projects keep working.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.base import OwnedModel
from app.db.models import (
    AzureConnection,
    GitConnection,
    Organization,
    OwnershipTransfer,
    Project,
    ProjectShare,
    User,
)

NAME_MAX = 100

_GIT_COPIED = (
    "repo_url",
    "auth_type",
    "username",
    "secret_enc",
    "commit_url_template",
)
_AZURE_COPIED = ("organization_url", "azure_project", "pat_enc")


@dataclass(frozen=True)
class Owner:
    """Who owns a row: exactly one of a user and an organization."""

    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    # Used in "Billing (from Marco)" when the new owner already has that name.
    label: str
    # Used in the summary of a move.
    describe: str

    @classmethod
    def of_user(cls, user: User) -> "Owner":
        return cls(user.id, None, user.display_name, user.email)

    @classmethod
    def of_organization(cls, organization: Organization) -> "Owner":
        return cls(None, organization.id, organization.name, f'organization "{organization.name}"')

    def owns(self, model: type[OwnedModel]) -> Any:
        if self.organization_id is not None:
            return model.organization_id == self.organization_id
        return model.owner_id == self.user_id

    def assign(self, item: OwnedModel) -> None:
        item.owner_id = self.user_id
        item.organization_id = self.organization_id


@dataclass
class Tally:
    projects: int = 0
    moved: int = 0
    copied: int = 0
    notes: list[str] = field(default_factory=list)


def _name_taken(session: Session, model: type[OwnedModel], owner: Owner, name: str) -> bool:
    return bool(
        session.scalar(
            select(func.count()).select_from(model).where(owner.owns(model), model.name == name)
        )
    )


def _free_name(
    session: Session, model: type[OwnedModel], owner: Owner, name: str, previous: Owner
) -> str:
    """The name itself, or "name (from Previous)" when the new owner already uses it."""
    if not _name_taken(session, model, owner, name):
        return name
    for attempt in range(1, 1000):
        suffix = f" (from {previous.label})" + (f" {attempt}" if attempt > 1 else "")
        candidate = name[: NAME_MAX - len(suffix)] + suffix
        if not _name_taken(session, model, owner, candidate):
            return candidate
    return f"{name[: NAME_MAX - 37]} {uuid.uuid4()}"  # pragma: no cover


def _hand_over(
    session: Session, item: OwnedModel, previous: Owner, to: Owner, tally: Tally, kind: str
) -> None:
    name = _free_name(session, type(item), to, item.name, previous)
    if name != item.name:
        tally.notes.append(f'{kind} "{item.name}" renamed to "{name}"')
    to.assign(item)
    item.name = name
    session.flush()


def _copy[C: (GitConnection, AzureConnection)](
    session: Session, original: C, copied: tuple[str, ...], previous: Owner, to: Owner
) -> C:
    copy = type(original)(
        owner_id=to.user_id,
        organization_id=to.organization_id,
        name=_free_name(session, type(original), to, original.name, previous),
        **{column: getattr(original, column) for column in copied},
    )
    session.add(copy)
    session.flush()
    return copy


def _still_used(session: Session, column: Any, connection_id: uuid.UUID, owner: Owner) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Project)
            .where(column == connection_id, owner.owns(Project))
        )
    )


def drop_shares(session: Session, project_ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
    """A user doesn't need a share on a project they now own."""
    session.execute(
        delete(ProjectShare).where(
            ProjectShare.project_id.in_(project_ids), ProjectShare.user_id == user_id
        )
    )


def move_project(session: Session, project: Project, previous: Owner, to: Owner) -> Tally:
    """Give one project, and the connections it uses, to another owner."""
    tally = Tally(projects=1)
    _hand_over(session, project, previous, to, tally, "Project")
    if to.user_id is not None:
        drop_shares(session, [project.id], to.user_id)

    git = session.get(GitConnection, project.git_connection_id)
    azure = session.get(AzureConnection, project.azure_connection_id)
    assert git is not None and azure is not None  # noqa: S101  (RESTRICT foreign keys)
    if _still_used(session, Project.git_connection_id, git.id, previous):
        project.git_connection_id = _copy(session, git, _GIT_COPIED, previous, to).id
        tally.copied += 1
        tally.notes.append(
            f'Git connection "{git.name}" copied (still used by {previous.describe})'
        )
    else:
        _hand_over(session, git, previous, to, tally, "Git connection")
        tally.moved += 1
    if _still_used(session, Project.azure_connection_id, azure.id, previous):
        project.azure_connection_id = _copy(session, azure, _AZURE_COPIED, previous, to).id
        tally.copied += 1
        tally.notes.append(
            f'Azure connection "{azure.name}" copied (still used by {previous.describe})'
        )
    else:
        _hand_over(session, azure, previous, to, tally, "Azure connection")
        tally.moved += 1
    session.flush()
    return tally


def _record(
    session: Session,
    *,
    admin: User,
    previous: User,
    to: User,
    project: Project | None,
    tally: Tally,
    headline: str,
) -> OwnershipTransfer:
    transfer = OwnershipTransfer(
        admin_id=admin.id,
        from_user_id=previous.id,
        to_user_id=to.id,
        project_id=project.id if project else None,
        projects_moved=tally.projects,
        connections_moved=tally.moved,
        connections_copied=tally.copied,
        summary="; ".join([headline, *tally.notes]),
    )
    session.add(transfer)
    session.flush()
    return transfer


def transfer_project(
    session: Session, *, admin: User, project: Project, previous: User, to: User
) -> OwnershipTransfer:
    """The administrator gives one personal project, with its connections, to another user."""
    headline = f'Project "{project.name}" from {previous.email} to {to.email}'
    tally = move_project(session, project, Owner.of_user(previous), Owner.of_user(to))
    return _record(
        session,
        admin=admin,
        previous=previous,
        to=to,
        project=project,
        tally=tally,
        headline=headline,
    )


def transfer_everything(
    session: Session, *, admin: User, previous: User, to: User
) -> OwnershipTransfer:
    """Give every project and connection a user owns personally to another user.

    What belongs to the user's organizations stays there.
    """
    tally = Tally()
    headline = f"Everything owned by {previous.email} to {to.email}"
    source, target = Owner.of_user(previous), Owner.of_user(to)
    projects = session.scalars(select(Project).where(Project.owner_id == previous.id)).all()
    for project in projects:
        _hand_over(session, project, source, target, tally, "Project")
        tally.projects += 1
    for model in (GitConnection, AzureConnection):
        kind = "Git connection" if model is GitConnection else "Azure connection"
        for connection in session.scalars(select(model).where(model.owner_id == previous.id)).all():
            _hand_over(session, connection, source, target, tally, kind)
            tally.moved += 1
    drop_shares(session, [p.id for p in projects], to.id)
    return _record(
        session,
        admin=admin,
        previous=previous,
        to=to,
        project=None,
        tally=tally,
        headline=headline,
    )


def owns_anything(session: Session, user_id: uuid.UUID) -> bool:
    return any(
        session.scalar(select(func.count()).select_from(model).where(model.owner_id == user_id))
        for model in (Project, GitConnection, AzureConnection)
    )
