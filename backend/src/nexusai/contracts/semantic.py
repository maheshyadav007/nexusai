from typing import Any, Literal

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


IndexKind = Literal["mail", "document"]
IndexState = Literal["off", "current", "partial", "out_of_date"]


class IndexInfo(BaseModel):
    """One index, and exactly what was used to build it."""

    kind: IndexKind
    state: IndexState
    indexed: int
    total: int
    # Built with different settings than these. They still work until it's rebuilt.
    stale: int = 0
    fingerprint: str
    build_settings: dict[str, Any]
    built: str | None = None


class SemanticStatus(BaseModel):
    """What's true right now. Events carry this whole, so screens update without asking."""

    models: list[LocalModel]
    active: str
    ready: bool
    mirror: str | None = None
    indexed: int = 0
    total: int = 0
    indexing: bool = False
    indexes: list[IndexInfo] = Field(default_factory=list)


class DetectModels(BaseModel):
    pass


class ModelDetection(BaseModel):
    on_this_computer: list[str]
    recommended: str
    reason: Literal["already_here", "small_computer", "best"]
    reachable: bool
    memory_bytes: int
    free_bytes: int
    cores: int


class RebuildIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: IndexKind


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
    # The page, slide or sheet it came from, for files that have them.
    place: str | None = None
