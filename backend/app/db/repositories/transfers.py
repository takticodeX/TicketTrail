"""Moving projects and connections from one user to another (an administrator's tool).

Secrets move as they are, still encrypted: nobody sees them on the way. A connection
the previous owner still uses in another project is copied instead of moved, so
their remaining projects keep working.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.base import OwnedModel
from app.db.models import (
    AzureConnection,
    GitConnection,
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


@dataclass
class _Tally:
    projects: int = 0
    moved: int = 0
    copied: int = 0
    notes: list[str] = field(default_factory=list)


def _name_taken(session: Session, model: type[OwnedModel], owner_id: uuid.UUID, name: str) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.owner_id == owner_id, model.name == name)
        )
    )


def _free_name(
    session: Session, model: type[OwnedModel], owner_id: uuid.UUID, name: str, previous: User
) -> str:
    """The name itself, or "name (from Previous)" when the new owner already uses it."""
    if not _name_taken(session, model, owner_id, name):
        return name
    for attempt in range(1, 1000):
        suffix = f" (from {previous.display_name})" + (f" {attempt}" if attempt > 1 else "")
        candidate = name[: NAME_MAX - len(suffix)] + suffix
        if not _name_taken(session, model, owner_id, candidate):
            return candidate
    return f"{name[: NAME_MAX - 37]} {uuid.uuid4()}"  # pragma: no cover


def _hand_over(
    session: Session, item: OwnedModel, previous: User, to: User, tally: _Tally, kind: str
) -> None:
    name = _free_name(session, type(item), to.id, item.name, previous)
    if name != item.name:
        tally.notes.append(f'{kind} "{item.name}" renamed to "{name}"')
    item.owner_id = to.id
    item.name = name
    session.flush()


def _copy[C: (GitConnection, AzureConnection)](
    session: Session, original: C, copied: tuple[str, ...], previous: User, to: User
) -> C:
    copy = type(original)(
        owner_id=to.id,
        name=_free_name(session, type(original), to.id, original.name, previous),
        **{column: getattr(original, column) for column in copied},
    )
    session.add(copy)
    session.flush()
    return copy


def _still_used(
    session: Session, column: object, connection_id: uuid.UUID, owner_id: uuid.UUID
) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Project)
            .where(column == connection_id, Project.owner_id == owner_id)  # type: ignore[arg-type]
        )
    )


def _drop_own_shares(session: Session, project_ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
    """A user doesn't need a share on a project they now own."""
    session.execute(
        delete(ProjectShare).where(
            ProjectShare.project_id.in_(project_ids), ProjectShare.user_id == user_id
        )
    )


def _record(
    session: Session,
    *,
    admin: User,
    previous: User,
    to: User,
    project: Project | None,
    tally: _Tally,
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
    """Give one project, and the connections it uses, to another user."""
    tally = _Tally(projects=1)
    headline = f'Project "{project.name}" from {previous.email} to {to.email}'
    _hand_over(session, project, previous, to, tally, "Project")
    _drop_own_shares(session, [project.id], to.id)

    git = session.get(GitConnection, project.git_connection_id)
    azure = session.get(AzureConnection, project.azure_connection_id)
    assert git is not None and azure is not None  # noqa: S101  (RESTRICT foreign keys)
    if _still_used(session, Project.git_connection_id, git.id, previous.id):
        project.git_connection_id = _copy(session, git, _GIT_COPIED, previous, to).id
        tally.copied += 1
        tally.notes.append(f'Git connection "{git.name}" copied (still used by {previous.email})')
    else:
        _hand_over(session, git, previous, to, tally, "Git connection")
        tally.moved += 1
    if _still_used(session, Project.azure_connection_id, azure.id, previous.id):
        project.azure_connection_id = _copy(session, azure, _AZURE_COPIED, previous, to).id
        tally.copied += 1
        tally.notes.append(
            f'Azure connection "{azure.name}" copied (still used by {previous.email})'
        )
    else:
        _hand_over(session, azure, previous, to, tally, "Azure connection")
        tally.moved += 1
    session.flush()
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
    """Give every project and connection a user owns to another user."""
    tally = _Tally()
    headline = f"Everything owned by {previous.email} to {to.email}"
    projects = session.scalars(select(Project).where(Project.owner_id == previous.id)).all()
    for project in projects:
        _hand_over(session, project, previous, to, tally, "Project")
        tally.projects += 1
    for model in (GitConnection, AzureConnection):
        kind = "Git connection" if model is GitConnection else "Azure connection"
        for connection in session.scalars(select(model).where(model.owner_id == previous.id)).all():
            _hand_over(session, connection, previous, to, tally, kind)
            tally.moved += 1
    _drop_own_shares(session, [p.id for p in projects], to.id)
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
