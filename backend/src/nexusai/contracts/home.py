from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HomeState = Literal["ready", "unset", "missing", "locked", "damaged"]


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
    extension: str | None = Field(default=None, pattern=r"^[a-z0-9]+$", max_length=16)


class FolderListing(BaseModel):
    path: str
    parent: str | None
    folders: list[str]
    files: list[str] = Field(default_factory=list)


class UnlockHome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_key: str = Field(min_length=1, max_length=200)


class RecoveryKeyView(BaseModel):
    """Only a key the person hasn't confirmed saving. Afterwards it can't be shown again."""

    pending: str | None = None


class BackupRow(BaseModel):
    name: str
    reason: str
    time: str
    size: int


class BackupList(BaseModel):
    backups: list[BackupRow]


class RestoreBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
