"""What an email thread, a document, a matter or its work is called, from the database, for
anything that points to one."""

from nexusai.contracts.agent import SourceRef
from nexusai.contracts.documents import GetDocument
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.documents import module as documents
from nexusai.modules.mail.source import thread_source

MAIL, DOCUMENT = "mail", "doc"
MATTER, TASK, REMINDER = "matter", "task", "reminder"


def describe(
    ctx: Context, kind: str, ref: str, *, message: int | None = None, page: str | None = None
) -> SourceRef | None:
    """None when it no longer exists, so nothing points to a thread or document that's gone."""
    if kind in (MATTER, TASK, REMINDER):
        return _work_source(ctx, kind, ref)
    if kind == MAIL:
        found = thread_source(ctx.bus.db, ref, message)
        return found.model_copy(update={"page": page}) if found and page else found
    if kind != DOCUMENT:
        return None
    try:
        result = documents.get_document(GetDocument(key=ref), ctx)
    except CommandError:
        return None
    row = result.document  # type: ignore[attr-defined]
    return SourceRef(
        kind=DOCUMENT, ref=ref, page=page, title=row.name, detail=row.source, date=row.date
    )


def thread(ctx: Context, thread_id: int | None) -> SourceRef | None:
    return thread_source(ctx.bus.db, thread_id)


def _work_source(ctx: Context, kind: str, ref: str) -> SourceRef | None:
    """A matter, or a task or reminder with the matter it belongs to, so it can open there."""
    from nexusai.modules.agent import matters

    if not ref.isdigit():
        return None
    db = ctx.bus.db
    if kind == MATTER:
        rows = db.fetch_all("SELECT title, updated FROM matters WHERE id = ?", (int(ref),))
        if not rows:
            return None
        return SourceRef(
            kind=MATTER, ref=ref, title=rows[0]["title"], date=rows[0]["updated"], matter=int(ref)
        )
    table, when = ("tasks", "due") if kind == TASK else ("reminders", "due_at")
    rows = db.fetch_all(f"SELECT title, {when} AS at FROM {table} WHERE id = ?", (int(ref),))  # noqa: S608
    if not rows:
        return None
    owner = matters.home(db, kind, int(ref))[0]
    return SourceRef(kind=kind, ref=ref, title=rows[0]["title"], date=rows[0]["at"], matter=owner)
