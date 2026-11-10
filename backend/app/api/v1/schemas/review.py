"""Reviewing a dry run: picking work items, linking and deselecting commits."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class WorkItemOption(BaseModel):
    id: str
    title: str
    type: str = Field(description="Bug, Task, User Story, ...")
    state: str
    closed: bool = Field(description="Closed, done or removed: listed last")


class WorkItemSearchResult(BaseModel):
    ok: bool
    items: list[WorkItemOption] = Field(default_factory=list)
    error: str | None = None


def _no_leading_zeros(value: str) -> str:
    value = value.lstrip("0")
    if not value:
        raise ValueError("must be a work item ID above 0")
    return value


class ItemWorkItem(BaseModel):
    """The work item a dry-run row should post to, chosen in the review."""

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    work_item_id: Annotated[
        str,
        Field(pattern=r"^[0-9]{1,20}$", description="The work item's ID (a number, as a string)"),
        AfterValidator(_no_leading_zeros),
    ]
