from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

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
