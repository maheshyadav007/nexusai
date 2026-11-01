from typing import Any

from pydantic import BaseModel


class AppEvent(BaseModel):
    """One fact that happened. Payloads hold IDs and short facts, never mail content."""

    id: str
    seq: int
    type: str
    version: int
    time: str
    source: str
    trace_id: str
    cause_id: str | None = None
    depth: int = 0
    payload: dict[str, Any]


class FailedEvent(BaseModel):
    listener: str
    event_seq: int
    event_type: str
    error: str
    time: str


class EventLogQuery(BaseModel):
    since: int = 0


class EventLog(BaseModel):
    events: list[AppEvent]
    failed: list[FailedEvent]
