"""Request and response schemas for the v1 API."""

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal, Self
from zoneinfo import available_timezones

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


@lru_cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def _normalise_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Password
    display_name: DisplayName | None = None

    _email = field_validator("email")(_normalise_email)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # No length rule here: a wrong password must fail as "invalid credentials".
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]

    _email = field_validator("email")(_normalise_email)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (a scheme name, not a secret)
    expires_in: int = Field(description="Seconds until the access token expires")


class AuthConfigResponse(BaseModel):
    allow_registration: bool


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    timezone: str
    role: Literal["user", "admin"]
    is_active: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    timezone: str | None = Field(default=None, description="IANA time zone, e.g. Europe/Rome")
    current_password: Annotated[str, Field(max_length=PASSWORD_MAX_LENGTH)] | None = None
    new_password: Password | None = None

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _timezones():
            raise ValueError("must be a valid IANA time zone, e.g. Europe/Rome")
        return value

    @model_validator(mode="after")
    def _check_password_change(self) -> Self:
        if self.new_password is not None and not self.current_password:
            raise ValueError("current_password is required to set a new password")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    checks: dict[str, str]
