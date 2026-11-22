"""A conversation is the thing going on, and its tasks, reminders and deadlines go with it.

Closing it closes them, opening it again brings back what that closed, and finishing its last
task finishes it. Before this, marking mail done left its task, reminder and deadline open.
"""

from datetime import UTC, datetime

from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent.kinds import KINDS, WORK

MIGRATION = Migration(
    "agent_conversation_closed_001",
    """
CREATE TABLE conversation_closed (
  thread INTEGER NOT NULL, kind TEXT NOT NULL, item INTEGER NOT NULL, PRIMARY KEY (kind, item));
CREATE INDEX conversation_closed_thread ON conversation_closed (thread);
""",
)
# What each kind of work is, and how it's closed and opened again, as kinds.py declares it.
_WORK = {
    name: (
        KINDS[name].table,
        KINDS[name].still_open or "",
        KINDS[name].close or "",
        KINDS[name].reopen or "",
    )
    for name in WORK
}
_EVENTS = {name: KINDS[name].event for name in WORK}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def close_work(ctx: Context, thread: int) -> int:
    """Everything still open about the conversation, closed and remembered. Returns how many."""
    now = _now()
    closed = 0
    with ctx.bus.unit_of_work() as work:
        for kind, (table, still_open, close, _) in _WORK.items():
            ids = [
                row[0]
                for row in work.tx.execute(
                    f"SELECT id FROM {table} WHERE thread = ? AND {still_open}",  # noqa: S608
                    (thread,),
                )
            ]
            for item in ids:
                work.tx.execute(
                    f"UPDATE {table} SET {close}, updated = ?2 WHERE id = ?1",  # noqa: S608
                    (item, now),
                )
                work.tx.execute(
                    "INSERT OR REPLACE INTO conversation_closed (thread, kind, item) VALUES (?, ?, ?)",
                    (thread, kind, item),
                )
            if ids:
                work.emit(_EVENTS[kind], {}, source="agent", trace_id=ctx.trace_id)
            closed += len(ids)
    return closed


def reopen_work(ctx: Context, thread: int) -> int:
    """What closing the conversation closed, open again: undo, or the person changing their mind."""
    now = _now()
    with ctx.bus.unit_of_work() as work:
        rows = work.tx.execute(
            "SELECT kind, item FROM conversation_closed WHERE thread = ?", (thread,)
        ).fetchall()
        kinds = set()
        for kind, item in rows:
            table, _, _, reopen = _WORK[kind]
            work.tx.execute(
                f"UPDATE {table} SET {reopen}, updated = ? WHERE id = ?",  # noqa: S608
                (now, item),
            )
            kinds.add(kind)
        work.tx.execute("DELETE FROM conversation_closed WHERE thread = ?", (thread,))
        for kind in kinds:
            work.emit(_EVENTS[kind], {}, source="agent", trace_id=ctx.trace_id)
    return len(rows)


def _set_status(ctx: Context, thread: int, status: str, was: str) -> bool:
    """As the person's choice, so the agent doesn't set it back on the next look."""
    with ctx.bus.unit_of_work() as work:
        changed = work.tx.execute(
            "UPDATE threads SET status = ?, next_action = CASE WHEN ? = 'resolved' THEN NULL ELSE next_action END,"
            " follow_up_on = NULL, status_user_message = (SELECT MAX(id) FROM messages WHERE thread_id = ?)"
            " WHERE id = ? AND status = ?",
            (status, status, thread, thread, was),
        ).rowcount
        if changed:
            work.emit(
                "mail.changed",
                {"threads": 1, "reason": "status"},
                source="agent",
                trace_id=ctx.trace_id,
            )
    return bool(changed)


def task_finished(ctx: Context, task: int) -> None:
    """The last open task of a conversation waiting on the person was what it was waiting for."""
    rows = ctx.bus.db.fetch_all("SELECT thread FROM tasks WHERE id = ?", (task,))
    thread = rows[0]["thread"] if rows else None
    if not thread or ctx.bus.db.fetch_all(
        "SELECT 1 FROM tasks WHERE thread = ? AND status != 'done' LIMIT 1", (thread,)
    ):
        return
    if _set_status(ctx, thread, "resolved", "waiting_on_you"):
        close_work(ctx, thread)
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT OR REPLACE INTO conversation_closed (thread, kind, item) VALUES (?, 'task', ?)",
                (thread, task),
            )


def task_reopened(ctx: Context, task: int) -> None:
    """Unticking the task that finished a conversation opens the conversation again."""
    rows = ctx.bus.db.fetch_all(
        "SELECT thread FROM conversation_closed WHERE kind = 'task' AND item = ?", (task,)
    )
    if rows and _set_status(ctx, rows[0]["thread"], "waiting_on_you", "resolved"):
        reopen_work(ctx, rows[0]["thread"])
