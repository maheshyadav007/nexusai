from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HomeState = Literal["ready", "unset", "missing"]


class HomeStatus(BaseModel):
    state: HomeState
    path: str | None = None
    default_path: str
    message: str | None = None


class CheckHome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


class HomeCheck(BaseModel):
    """Problems block the choice. Warnings only inform it."""

    path: str
    ok: bool
    problems: list[str]
    warnings: list[str]
    free_bytes: int | None = None
    is_existing_home: bool = False


class ChooseHome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    must_exist: bool = False


class BrowseFolders(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, max_length=4096)


class FolderListing(BaseModel):
    path: str
    parent: str | None
    folders: list[str]
