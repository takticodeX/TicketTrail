import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Write-only secrets: tokens, passwords and PATs.
Secret = Annotated[str, Field(max_length=4096)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class UserSummary(BaseModel):
    """Another user, as shown next to a project or run they own, share or started."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
