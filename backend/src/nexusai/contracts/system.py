from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SearchLogs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str | None = Field(default=None, pattern=r"^[a-z]+$", max_length=16)
    text: str | None = Field(default=None, max_length=200)


class LogLines(BaseModel):
    lines: list[dict[str, Any]]


class GetTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=64)


class TraceView(BaseModel):
    """Everything that happened under one trace ID, oldest first."""

    events: list[dict[str, Any]]
    lines: list[dict[str, Any]]


class GetDiagnostics(BaseModel):
    pass


class Diagnostics(BaseModel):
    version: str
    platform: str
    python: str
    home: str
    free_bytes: int
    database_bytes: int
    proxy: str | None
    event_count: int
    failed_events: int
    report: str


class CheckNetwork(BaseModel):
    pass


class NetworkCheck(BaseModel):
    name: str
    host: str
    ok: bool
    detail: str


class NetworkChecks(BaseModel):
    checks: list[NetworkCheck]
