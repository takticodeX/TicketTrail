"""Git and Azure DevOps connections. Secrets are write-only: responses carry has_secret."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.common import Name, Secret
from app.core.urls import UnsafeUrlError, normalise_https_url
from app.db.models import GitAuthType
from app.integrations.git.hosts import GitHost


def _https_url(value: str) -> str:
    try:
        return normalise_https_url(value)
    except UnsafeUrlError as exc:
        raise ValueError(str(exc)) from exc


def _commit_url_template(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if "{sha}" not in value:
        raise ValueError("must contain the {sha} placeholder")
    _https_url(value.replace("{sha}", "0" * 40))
    if value.replace("{sha}", "").count("{") or value.replace("{sha}", "").count("}"):
        raise ValueError("{sha} is the only placeholder allowed")
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


HttpsUrl = Annotated[str, Field(max_length=2048), AfterValidator(_https_url)]
CommitUrlTemplate = Annotated[
    str | None, Field(max_length=2048), AfterValidator(_commit_url_template)
]
Username = Annotated[str | None, Field(max_length=255), AfterValidator(_optional_text)]
AzureProjectName = Annotated[str, Field(min_length=1, max_length=255)]


# --- Git -------------------------------------------------------------------------------------


class GitConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    repo_url: HttpsUrl
    auth_type: GitAuthType
    username: Username = None
    secret: Secret | None = Field(default=None, description="Token or password (write-only)")
    commit_url_template: CommitUrlTemplate = Field(
        default=None, description="Link to a commit with a {sha} placeholder; inferred if empty"
    )

    @model_validator(mode="after")
    def _check_auth(self) -> Self:
        if self.auth_type == GitAuthType.NONE:
            self.username = None
            self.secret = None
        else:
            if not self.username:
                raise ValueError("username is required for token and basic authentication")
            if not self.secret:
                raise ValueError("secret is required for token and basic authentication")
        return self


class GitConnectionUpdate(BaseModel):
    """Omitted fields stay as they are. An empty secret keeps the saved one."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    repo_url: HttpsUrl | None = None
    auth_type: GitAuthType | None = None
    username: Username = None
    secret: Secret | None = None
    commit_url_template: CommitUrlTemplate = None


class GitConnectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    repo_url: str
    auth_type: GitAuthType
    username: str | None
    has_secret: bool
    commit_url_template: str | None
    commit_url_pattern: str = Field(
        description="The commit link actually used, with {sha}; empty for unknown hosts"
    )
    host: GitHost
    last_test_at: datetime | None
    last_test_ok: bool | None
    created_at: datetime
    updated_at: datetime


class GitTestResult(BaseModel):
    ok: bool
    branches: list[str] = Field(default_factory=list)
    default_branch: str | None = None
    error: str | None = None


# --- Azure DevOps ----------------------------------------------------------------------------


class AzureConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    organization_url: Annotated[HttpsUrl, AfterValidator(lambda url: url.rstrip("/"))] = Field(
        description="For example https://dev.azure.com/acme"
    )
    azure_project: Annotated[AzureProjectName, AfterValidator(str.strip)]
    pat: Annotated[Secret, Field(min_length=1, description="Personal access token (write-only)")]


class AzureConnectionUpdate(BaseModel):
    """Omitted fields stay as they are. An empty PAT keeps the saved one."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    organization_url: Annotated[HttpsUrl, AfterValidator(lambda url: url.rstrip("/"))] | None = None
    azure_project: Annotated[AzureProjectName, AfterValidator(str.strip)] | None = None
    pat: Secret | None = None


class AzureConnectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    organization_url: str
    azure_project: str
    has_secret: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    created_at: datetime
    updated_at: datetime


class AzureTestResult(BaseModel):
    ok: bool
    project_name: str | None = None
    error: str | None = None
