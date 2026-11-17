"""What an email thread is called, from the database, for anything that points to one."""

from nexusai.contracts.agent import SourceRef
from nexusai.kernel.database import Database


def thread_source(
    db: Database, thread: int | str | None, message: int | None = None
) -> SourceRef | None:
    """None when there's no thread or it's gone, so nothing points to mail that isn't there."""
    if not thread:
        return None
    rows = db.fetch_all(
        "SELECT t.subject, t.last_date, (SELECT COALESCE(NULLIF(m.from_name, ''), m.from_addr)"
        " FROM messages m WHERE m.thread_id = t.id ORDER BY m.date DESC LIMIT 1) AS sender"
        " FROM threads t WHERE t.id = ?",
        (thread,),
    )
    if not rows:
        return None
    return SourceRef(
        kind="mail",
        ref=str(thread),
        message=message,
        title=rows[0]["subject"] or "No subject",
        detail=rows[0]["sender"] or "",
        date=rows[0]["last_date"],
    )
