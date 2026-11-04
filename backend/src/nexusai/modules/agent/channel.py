"""How agents talk to the person (user channel), and to each other (agent channel and work board)."""

import json
from datetime import UTC, datetime, time
from typing import Any

from nexusai.contracts.agent import (
    AgentChannelList,
    AgentChannelMessage,
    BoardItem,
    BoardList,
    ChannelList,
    ChannelMessage,
    QuietHours,
)
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context

MIGRATION = Migration(
    "agent_channel_001",
    """
CREATE TABLE channel_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, agent TEXT NOT NULL, session TEXT, thread INTEGER, text TEXT NOT NULL,
  options TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open', answer TEXT, time TEXT NOT NULL, urgent INTEGER NOT NULL DEFAULT 0,
  count INTEGER NOT NULL DEFAULT 1, triage_message INTEGER);
CREATE INDEX channel_status ON channel_messages (status, id);
CREATE TABLE work_board (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL, thread INTEGER, due TEXT, by TEXT NOT NULL,
  updated TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
CREATE INDEX work_board_due ON work_board (done, due);
CREATE TABLE agent_channel (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT, topic TEXT, text TEXT NOT NULL, time TEXT NOT NULL,
  untrusted INTEGER NOT NULL DEFAULT 0, read_by TEXT NOT NULL DEFAULT '[]');
CREATE TABLE agent_channel_muted (topic TEXT PRIMARY KEY);
CREATE TABLE quiet_hours (id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL);
""",
)
QUESTIONS_MIGRATION = Migration(
    "agent_channel_questions_001",
    """
ALTER TABLE channel_messages ADD COLUMN multiple INTEGER NOT NULL DEFAULT 0;
ALTER TABLE channel_messages ADD COLUMN tool_call TEXT;
""",
)


HANDOFF_MIGRATION = Migration(
    "agent_handoffs_001",
    "ALTER TABLE agent_channel ADD COLUMN run INTEGER;"
    "ALTER TABLE agent_channel ADD COLUMN tool_call TEXT;"
    "ALTER TABLE agent_channel ADD COLUMN purpose TEXT;"
    "ALTER TABLE agent_channel ADD COLUMN expected_output TEXT;"
    "ALTER TABLE agent_channel ADD COLUMN evidence TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE agent_channel ADD COLUMN state TEXT NOT NULL DEFAULT 'note';"
    "ALTER TABLE agent_channel ADD COLUMN outcome TEXT;"
    "ALTER TABLE agent_channel ADD COLUMN owner_turn INTEGER;"
    "CREATE UNIQUE INDEX agent_channel_call ON agent_channel(sender,run,tool_call);",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_quiet(db: Database) -> QuietHours:
    rows = db.fetch_all("SELECT value FROM quiet_hours")
    return QuietHours.model_validate_json(rows[0]["value"]) if rows else QuietHours()


def save_quiet(db: Database, value: QuietHours) -> None:
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO quiet_hours (id, value) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET value = excluded.value",
            (value.model_dump_json(),),
        )


def in_quiet_hours(settings: QuietHours, now: datetime) -> bool:
    if not settings.enabled:
        return False
    start, end = time.fromisoformat(settings.start), time.fromisoformat(settings.end)
    current = now.time()
    # A window like 22:00 to 07:00 runs across midnight.
    return start <= current < end if start <= end else current >= start or current < end


def notify(
    ctx: Context, work: Any, title: str, detail: str, link: str | None, kind: str, urgent: bool
) -> None:
    """Quiet hours hold back everything except what's marked urgent."""
    if not urgent and in_quiet_hours(load_quiet(ctx.bus.db), datetime.now().astimezone()):
        return
    work.emit(
        "notification.requested",
        NotificationRequested(
            kind=kind, title=title[:200], detail=detail[:500], link=link
        ).model_dump(),
        source="agent",
        trace_id=ctx.trace_id,
    )


def post(
    ctx: Context,
    kind: str,
    agent: str,
    text: str,
    *,
    session: str | None = None,
    thread: int | None = None,
    options: list[str] | None = None,
    urgent: bool = False,
    triage_message: int | None = None,
    multiple: bool = False,
    tool_call: str | None = None,
) -> int | None:
    """A message to the person. Repeats group together, and a daily limit keeps noise down.

    Asks always get through, because something is waiting on them. Returns None if it was dropped.
    """
    db = ctx.bus.db
    limit = load_quiet(db).channel_daily_limit
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with ctx.bus.unit_of_work() as work:
        # A session's question belongs to its own call, so identical ones don't merge.
        same = (
            None
            if tool_call
            else work.tx.execute(
                "SELECT id FROM channel_messages WHERE status = 'open' AND kind = ? AND agent = ? AND text = ?",
                (kind, agent, text),
            ).fetchone()
        )
        if same:
            work.tx.execute(
                "UPDATE channel_messages SET count = count + 1 WHERE id = ?", (same[0],)
            )
            work.emit("channel.posted", {"id": same[0]}, source="agent", trace_id=ctx.trace_id)
            return int(same[0])
        posted = work.tx.execute(
            "SELECT COUNT(*) FROM channel_messages WHERE time LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        if kind != "ask" and limit and posted >= limit:
            return None
        cursor = work.tx.execute(
            "INSERT INTO channel_messages (kind, agent, session, thread, text, options, time, urgent, triage_message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                agent,
                session,
                thread,
                text,
                json.dumps(options or []),
                _now(),
                int(urgent),
                triage_message,
            ),
        )
        identifier = int(cursor.lastrowid or 0)
        work.tx.execute(
            "UPDATE channel_messages SET multiple = ?, tool_call = ? WHERE id = ?",
            (int(multiple), tool_call, identifier),
        )
        work.emit("channel.posted", {"id": identifier}, source="agent", trace_id=ctx.trace_id)
        if urgent:
            notify(ctx, work, text, "", "/today", "ask", True)
    return identifier


def messages(db: Database) -> ChannelList:
    rows = db.fetch_all(
        "SELECT * FROM channel_messages WHERE status = 'open' ORDER BY urgent DESC, id DESC LIMIT 200"
    )
    return ChannelList(messages=[_message(row) for row in rows])


def _message(row: Any) -> ChannelMessage:
    return ChannelMessage(
        id=row["id"],
        kind=row["kind"],
        agent=row["agent"],
        session=row["session"],
        thread=row["thread"],
        text=row["text"],
        options=json.loads(row["options"]),
        multiple=bool(row["multiple"]),
        status=row["status"],
        answer=row["answer"],
        time=row["time"],
        urgent=bool(row["urgent"]),
        count=row["count"],
    )


def get(db: Database, identifier: int) -> Any:
    rows = db.fetch_all("SELECT * FROM channel_messages WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("channel.not_found", "That message no longer exists.", 404)
    return rows[0]


def close(ctx: Context, identifier: int, status: str, answer: str | None) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE channel_messages SET status = ?, answer = ? WHERE id = ?",
            (status, answer, identifier),
        )
        work.emit("channel.posted", {"id": identifier}, source="agent", trace_id=ctx.trace_id)


def board_add(
    ctx: Context, kind: str, title: str, thread: int | None, due: str | None, by: str
) -> int:
    with ctx.bus.unit_of_work() as work:
        same = work.tx.execute(
            "SELECT id FROM work_board WHERE kind = ? AND title = ? AND COALESCE(thread, 0) = COALESCE(?, 0) AND done = 0",
            (kind, title, thread),
        ).fetchone()
        if same:
            return int(same[0])
        cursor = work.tx.execute(
            "INSERT INTO work_board (kind, title, thread, due, by, updated) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, title, thread, due, by, _now()),
        )
        work.emit("board.changed", {}, source="agent", trace_id=ctx.trace_id)
    return int(cursor.lastrowid or 0)


def board(db: Database, thread: int | None = None) -> BoardList:
    where, params = (
        ("WHERE done = 0 AND thread = ?", (thread,)) if thread else ("WHERE done = 0", ())
    )
    rows = db.fetch_all(
        f"SELECT * FROM work_board {where} ORDER BY due IS NULL, due, id DESC LIMIT 200", params
    )  # noqa: S608
    return BoardList(
        items=[
            BoardItem(
                id=r["id"],
                kind=r["kind"],
                title=r["title"],
                thread=r["thread"],
                due=r["due"],
                by=r["by"],
                updated=r["updated"],
                done=bool(r["done"]),
            )
            for r in rows
        ]
    )


def agent_post(
    ctx: Context, sender: str, recipient: str | None, topic: str | None, text: str, untrusted: bool
) -> None:
    """Between agents. It's data for the receiver, never an instruction."""
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO agent_channel (sender, recipient, topic, text, time, untrusted) VALUES (?, ?, ?, ?, ?, ?)",
            (sender, recipient, topic, text, _now(), int(untrusted)),
        )
        work.emit("agentChannel.posted", {"topic": topic}, source="agent", trace_id=ctx.trace_id)


def agent_inbox(db: Database, session: str) -> list[Any]:
    rows = db.fetch_all(
        "SELECT * FROM agent_channel WHERE sender != ? AND (recipient = ? OR recipient IS NULL) ORDER BY id",
        (session, session),
    )
    unread = [row for row in rows if session not in json.loads(row["read_by"])]
    with db.transaction() as tx:
        for row in unread:
            tx.execute(
                "UPDATE agent_channel SET read_by = ? WHERE id = ?",
                (json.dumps([*json.loads(row["read_by"]), session]), row["id"]),
            )
    return unread


def agent_messages(db: Database) -> AgentChannelList:
    muted = [
        row["topic"] for row in db.fetch_all("SELECT topic FROM agent_channel_muted ORDER BY topic")
    ]
    rows = db.fetch_all("SELECT * FROM agent_channel ORDER BY id DESC LIMIT 200")
    shown = [row for row in rows if row["topic"] not in muted]
    return AgentChannelList(
        messages=[
            AgentChannelMessage(
                id=r["id"],
                sender=r["sender"],
                recipient=r["recipient"],
                topic=r["topic"],
                text=r["text"],
                time=r["time"],
                untrusted=bool(r["untrusted"]),
                purpose=r["purpose"],
                expected_output=r["expected_output"],
                state=r["state"],
                outcome=r["outcome"],
                evidence=json.loads(r["evidence"]),
            )
            for r in shown
        ],
        muted=muted,
    )


def set_muted(db: Database, topic: str, muted: bool) -> None:
    with db.transaction() as tx:
        if muted:
            tx.execute("INSERT OR IGNORE INTO agent_channel_muted (topic) VALUES (?)", (topic,))
        else:
            tx.execute("DELETE FROM agent_channel_muted WHERE topic = ?", (topic,))


def open_ask(db: Database, session: str) -> Any:
    """The question this session is waiting on, if any."""
    rows = db.fetch_all(
        "SELECT * FROM channel_messages WHERE session = ? AND kind = 'ask' AND status = 'open'"
        " ORDER BY id LIMIT 1",
        (session,),
    )
    return rows[0] if rows else None
