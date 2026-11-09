"""Reviewing a dry run: picking work items, linking and deselecting commits."""

from pydantic import BaseModel, ConfigDict, Field


class WorkItemOption(BaseModel):
    id: int
    title: str
    type: str = Field(description="Bug, Task, User Story, ...")
    state: str
    closed: bool = Field(description="Closed, done or removed: listed last")


class WorkItemSearchResult(BaseModel):
    ok: bool
    items: list[WorkItemOption] = Field(default_factory=list)
    error: str | None = None


class ItemWorkItem(BaseModel):
    """The work item a dry-run row should post to, chosen in the review."""

    model_config = ConfigDict(extra="forbid")

    work_item_id: int = Field(gt=0)
