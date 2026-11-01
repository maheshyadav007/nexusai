from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelState = Literal["missing", "downloading", "ready", "failed"]


class LocalModel(BaseModel):
    id: str
    label: str
    description: str
    size_bytes: int
    state: ModelState
    downloaded_bytes: int = 0
    error: str | None = None
    active: bool = False


class SemanticStatus(BaseModel):
    """What's true right now. Events carry this whole, so screens update without asking."""

    models: list[LocalModel]
    active: str
    ready: bool
    auto_download: bool
    mirror: str | None = None
    indexed: int = 0
    total: int = 0
    indexing: bool = False


class GetSemanticStatus(BaseModel):
    pass


class DownloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=64)


class ModelName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class SaveSemanticSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_download: bool | None = None
    mirror: str | None = Field(default=None, max_length=500)


class ImportModel(BaseModel):
    """For networks that block downloads: files already copied to this computer."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    folder: str = Field(min_length=1, max_length=4096)


class SemanticHit(BaseModel):
    kind: Literal["mail", "document"]
    ref: str
    score: float
    excerpt: str
