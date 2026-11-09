"""The owner-change history as the API returns it (Change owner, Transfer all)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import OrganizationSummary, TransferResponse, UserSummary
from app.db.models import Organization, OwnershipTransfer, User


def transfer_responses(
    db: Session, transfers: Sequence[OwnershipTransfer]
) -> list[TransferResponse]:
    user_ids = {u for t in transfers for u in (t.actor_id, t.from_user_id, t.to_user_id) if u}
    org_ids = {o for t in transfers for o in (t.from_organization_id, t.to_organization_id) if o}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}

    def user(user_id: uuid.UUID | None) -> UserSummary | None:
        found = users.get(user_id) if user_id else None
        return UserSummary.model_validate(found) if found else None

    def org(organization_id: uuid.UUID | None) -> OrganizationSummary | None:
        found = orgs.get(organization_id) if organization_id else None
        return OrganizationSummary.model_validate(found) if found else None

    return [
        TransferResponse(
            id=t.id,
            created_at=t.created_at,
            actor=user(t.actor_id),
            from_user=user(t.from_user_id),
            from_organization=org(t.from_organization_id),
            to_user=user(t.to_user_id),
            to_organization=org(t.to_organization_id),
            project_id=t.project_id,
            projects_moved=t.projects_moved,
            connections_moved=t.connections_moved,
            connections_copied=t.connections_copied,
            summary=t.summary,
        )
        for t in transfers
    ]
