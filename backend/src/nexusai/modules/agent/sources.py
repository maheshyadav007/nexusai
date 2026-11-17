"""What an email thread or a document is called, from the database, for anything that points to one."""

from nexusai.contracts.agent import SourceRef
from nexusai.contracts.documents import GetDocument
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.documents import module as documents
from nexusai.modules.mail.source import thread_source

MAIL, DOCUMENT = "mail", "doc"


def describe(
    ctx: Context, kind: str, ref: str, *, message: int | None = None, page: str | None = None
) -> SourceRef | None:
    """None when it no longer exists, so nothing points to a thread or document that's gone."""
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
