"""Data access. Repositories for user-owned tables filter every query on owner_id."""

from app.db.repositories.access import (
    ProjectAccessRepository,
    ProjectScope,
    ProjectShareRepository,
    SeenProject,
    accessible_project_ids,
    member_organization_ids,
)
from app.db.repositories.organizations import (
    MemberRepository,
    OrganizationRepository,
    organization_name_taken,
    owned_counts,
)
from app.db.repositories.owned import (
    AzureConnectionRepository,
    GitConnectionRepository,
    OwnedRepository,
    ProjectRepository,
)
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.repositories.sync import (
    CursorRepository,
    PostedCommentRepository,
    SyncRunRepository,
    close_stale_runs,
    other_run_active,
    project_summaries,
)
from app.db.repositories.users import UserRepository

__all__ = [
    "AzureConnectionRepository",
    "CursorRepository",
    "GitConnectionRepository",
    "MemberRepository",
    "OrganizationRepository",
    "OwnedRepository",
    "PostedCommentRepository",
    "ProjectAccessRepository",
    "ProjectRepository",
    "ProjectScope",
    "ProjectShareRepository",
    "RefreshTokenRepository",
    "SeenProject",
    "SyncRunRepository",
    "UserRepository",
    "accessible_project_ids",
    "close_stale_runs",
    "member_organization_ids",
    "organization_name_taken",
    "other_run_active",
    "owned_counts",
    "project_summaries",
]
