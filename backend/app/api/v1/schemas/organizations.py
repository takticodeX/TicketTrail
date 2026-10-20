"""Organizations: teams that own projects and connections."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.api.v1.schemas.auth import _timezones
from app.api.v1.schemas.common import Name, UserSummary

OrganizationRoleName = Literal["admin", "member"]


def _check_timezone(value: str | None) -> str | None:
    if value is not None and value not in _timezones():
        raise ValueError("must be a valid IANA time zone, e.g. Europe/Rome")
    return value


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    timezone: str | None = Field(
        default=None, description="For scheduled syncs; defaults to your own time zone"
    )

    _timezone = field_validator("timezone")(_check_timezone)


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    timezone: str | None = None

    _timezone = field_validator("timezone")(_check_timezone)


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    role: OrganizationRoleName = Field(description="Your role in the organization")
    members: int
    projects: int
    created_at: datetime


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(description="The exact email of a registered user")
    role: OrganizationRoleName = "member"

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: OrganizationRoleName


class MemberResponse(BaseModel):
    user: UserSummary
    role: OrganizationRoleName
    created_at: datetime


class AdminOrganizationResponse(BaseModel):
    """An organization as the instance administrator sees it."""

    id: uuid.UUID
    name: str
    timezone: str
    members: int
    admins: list[UserSummary]
    people: list[MemberResponse] = Field(description="Every member, with their role")
    projects: int
    connections: int
    created_at: datetime


class PromoteAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID = Field(description="A member who becomes an admin of the organization")
