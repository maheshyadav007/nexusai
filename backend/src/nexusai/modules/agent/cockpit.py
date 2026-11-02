"""Turns the event log into what a person wants to read about what's going on in the app."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nexusai.contracts.agent import CockpitEvent, CockpitEvents, GetCockpitEvents
from nexusai.contracts.events import AppEvent
from nexusai.kernel.module import Context

BATCH = 200
MOST_BATCHES = 10


@dataclass(frozen=True)
class Line:
    title: str
    detail: str | None = None
    link: str | None = None
    problem: bool = False


def _session(ctx: Context, identifier: Any) -> tuple[str, str | None]:
    rows = ctx.bus.db.fetch_all(
        "SELECT title, error FROM agent_sessions WHERE id = ?", (identifier,)
    )
    return (rows[0]["title"], rows[0]["error"]) if rows else ("A chat", None)


def _subject(ctx: Context, thread: Any) -> str:
    rows = ctx.bus.db.fetch_all("SELECT subject FROM threads WHERE id = ?", (thread,))
    return (rows[0]["subject"] or "no subject") if rows else "a conversation"


def _triggered(ctx: Context, event: AppEvent) -> Line:
    session = event.payload["session"]
    title, _ = _session(ctx, session)
    words = {
        "mail": "Mail agent started on new mail",
        "mail-hourly": "Mail agent started on the hourly check",
        "schedule": f"Schedule started: {title}",
        "event": f"Trigger started: {title}",
    }
    return Line(
        words.get(event.payload["origin"], f"Message sent in {title}"),
        link=f"/agent/sessions/{session}",
    )


def _session_changed(ctx: Context, event: AppEvent) -> Line | None:
    session = event.payload["id"]
    if event.payload.get("status") != "failed":
        return None
    title, error = _session(ctx, session)
    return Line(f"Failed: {title}", error, f"/agent/sessions/{session}", True)


def _triaged(ctx: Context, event: AppEvent) -> Line:
    thread = event.payload["thread_id"]
    failed = event.payload.get("status") == "failed"
    words = "Couldn't judge" if failed else "Judged"
    return Line(f"{words}: {_subject(ctx, thread)}", link=f"/mail/thread/{thread}", problem=failed)


def _sync(ctx: Context, event: AppEvent) -> Line | None:
    state = event.payload.get("state")
    words = {
        "live": ("Mail is up to date", False),
        "failed": ("Mail couldn't sign in", True),
        "offline": ("Mail can't reach its server", True),
        "syncing": ("Mail is downloading", False),
        "paused": ("Mail sync paused", False),
    }.get(state or "")
    return Line(words[0], link="/connectors", problem=words[1]) if words else None


def _history(ctx: Context, event: AppEvent) -> Line:
    pulled, total = event.payload["pulled"], event.payload["total"]
    return Line(f"Older mail finished: {pulled:,} of {total:,} here", link="/connectors")


def _pst(ctx: Context, event: AppEvent) -> Line | None:
    words = {
        "queued": ("Archive import added", False),
        "done": ("Archive import finished", False),
        "failed": ("Archive import failed", True),
        "paused": ("Archive import paused", False),
    }.get(event.payload.get("status") or "")
    return Line(words[0], link="/connectors", problem=words[1]) if words else None


def _approval(ctx: Context, event: AppEvent) -> Line | None:
    if event.payload.get("status") != "pending":
        return None
    return Line("An agent is waiting for your approval", link="/today")


def _due(ctx: Context, event: AppEvent) -> Line:
    rows = ctx.bus.db.fetch_all(
        "SELECT title FROM schedules WHERE id = ?", (event.payload.get("id"),)
    )
    return Line(f"Came due: {rows[0]['title'] if rows else 'a schedule'}", link="/agent/schedules")


def _notice(ctx: Context, event: AppEvent) -> Line:
    return Line(
        event.payload.get("title", ""), event.payload.get("detail"), event.payload.get("link")
    )


def _connector(ctx: Context, event: AppEvent) -> Line | None:
    identifier = event.payload.get("id")
    words = {
        "failed": f"Can't reach the connector {identifier}",
        "changed": f"The connector {identifier} changed its tools, so they're stopped",
    }.get(event.payload.get("state") or "")
    return Line(words, link="/connectors", problem=True) if words else None


Describe = Callable[[Context, AppEvent], Line | None]
# Only what's worth a person's attention. Everything is still in the event inspector, under Logs.
FEED: dict[str, tuple[str, Describe]] = {
    "agent.triggered": ("agents", _triggered),
    "agent.held": (
        "agents",
        lambda ctx, e: Line("An agent is waiting for the model", problem=True),
    ),
    "session.changed": ("agents", _session_changed),
    "session.compacted": ("agents", lambda ctx, e: Line("A chat was compacted")),
    "approval.changed": ("agents", _approval),
    "schedule.due": ("agents", _due),
    "mail.received": (
        "mail",
        lambda ctx, e: Line(
            f"New mail: {_subject(ctx, e.payload['thread_id'])}",
            link=f"/mail/thread/{e.payload['thread_id']}",
        ),
    ),
    "mail.triaged": ("mail", _triaged),
    "mail.urgent": (
        "mail",
        lambda ctx, e: Line(
            f"Important: {_subject(ctx, e.payload['thread_id'])}",
            link=f"/mail/thread/{e.payload['thread_id']}",
        ),
    ),
    "mail.sent": ("mail", lambda ctx, e: Line("Mail sent")),
    "mail.historyFinished": ("mail", _history),
    "mail.pulled": (
        "mail",
        lambda ctx, e: Line(f"Found {e.payload['found']:,} new, pulled {e.payload['pulled']:,}"),
    ),
    "mail.syncChanged": ("mail", _sync),
    "pst.progress": ("mail", _pst),
    "document.indexed": ("indexing", lambda ctx, e: Line("A document was read")),
    "index.finished": (
        "indexing",
        lambda ctx, e: Line(e.payload.get("title", "Index is up to date")),
    ),
    "notification.requested": ("system", _notice),
    "connectors.changed": ("system", _connector),
}


def events(query: GetCockpitEvents, ctx: Context) -> CockpitEvents:
    """The newest first. Some events say nothing worth showing, so this reads on until it has enough."""
    found: list[CockpitEvent] = []
    before = query.before
    for _ in range(MOST_BATCHES):
        batch = ctx.bus.recent_events(list(FEED), before, BATCH)
        for event in batch:
            group, describe = FEED[event.type]
            line = describe(ctx, event)
            if line is None:
                continue
            wanted = (
                query.filter == "all"
                or (query.filter == "problems" and line.problem)
                or query.filter == group
            )
            if wanted:
                found.append(
                    CockpitEvent(
                        seq=event.seq, time=event.time, type=event.type, group=group,
                        title=line.title, detail=line.detail, link=line.link, problem=line.problem,
                    )
                )  # fmt: skip
            if len(found) >= query.limit:
                return CockpitEvents(events=found)
        if len(batch) < BATCH:
            break
        before = batch[-1].seq
    return CockpitEvents(events=found)
