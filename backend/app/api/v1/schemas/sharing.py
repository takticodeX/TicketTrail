"""Sharing projects with other users, and the administrator's ownership transfers."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.api.v1.schemas.common import UserSummary
from app.api.v1.schemas.runs import RunResponse

ShareRoleName = Literal["viewer", "editor"]


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(description="The exact email of a registered user")
    role: ShareRoleName = "viewer"

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class ShareUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ShareRoleName


class ShareResponse(BaseModel):
    user: UserSummary
    role: ShareRoleName
    created_at: datetime


class AdminUserSummary(UserSummary):
    is_active: bool


class AdminProjectResponse(BaseModel):
    """A project as the administrator sees it: who owns it, never its settings or secrets."""

    id: uuid.UUID
    name: str
    owner: AdminUserSummary
    shares: int
    created_at: datetime
    last_run: RunResponse | None


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_user_id: uuid.UUID


class TransferResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    admin: UserSummary | None
    from_user: UserSummary | None
    to_user: UserSummary | None
    project_id: uuid.UUID | None = Field(description="Null when everything was moved")
    projects_moved: int
    connections_moved: int
    connections_copied: int = Field(
        description="Connections still used by the previous owner's other projects are copied"
    )
    summary: str
