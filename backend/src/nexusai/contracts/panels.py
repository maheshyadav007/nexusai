from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexusai.contracts.documents import DocumentRow
from nexusai.contracts.mail import ThreadRow

PanelSource = Literal["threads", "documents", "tasks", "reminders"]
PanelSize = Literal["small", "medium", "large"]


class PanelFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    unread_only: bool = False
    flagged_only: bool = False
    query: str | None = Field(default=None, max_length=200)
    folder: str | None = Field(default=None, max_length=200)


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    title: str = Field(min_length=1, max_length=120)
    source: PanelSource
    filters: PanelFilters = Field(default_factory=PanelFilters)
    size: PanelSize = "medium"


class PanelBoard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panels: list[Panel] = Field(max_length=64)


class GetPanelBoard(BaseModel):
    pass


class ResetPanelBoard(BaseModel):
    pass


class GetPanelResults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel: Panel
    limit: int = Field(default=30, ge=1, le=200)


class PanelResults(BaseModel):
    threads: list[ThreadRow] = Field(default_factory=list)
    documents: list[DocumentRow] = Field(default_factory=list)
