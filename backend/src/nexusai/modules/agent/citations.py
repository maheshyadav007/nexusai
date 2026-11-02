"""What a turn actually read, so an answer can only cite that, and titles never come from a model."""

import re
from typing import Any

from nexusai.contracts.documents import GetDocument
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.documents import module as documents

MIGRATION = Migration(
    "agent_citations_001",
    """
CREATE TABLE agent_turn_sources (
  turn INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, opened INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (turn, kind, ref));
""",
)
MARKER = re.compile(r"\[(mail|doc):([^\]\s#]{1,200})(?:#([^\]\s]{1,40}))?\]")
# The start of a marker that may finish in the next chunk of a stream.
PARTIAL = re.compile(r"\[(?:m|ma|mai|mail|d|do|doc|(?:mail|doc):[^\]\s]{0,240})?$")
MAIL, DOCUMENT = "mail", "doc"


def note(db: Database, session: str, kind: str, ref: str, *, opened: bool = False) -> None:
    """A tool handed this to the model during the session's open turn."""
    rows = db.fetch_all(
        "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if not rows:
        return
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_turn_sources (turn, kind, ref, opened) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (turn, kind, ref) DO UPDATE SET opened = MAX(opened, excluded.opened)",
            (rows[0]["id"], kind, ref, int(opened)),
        )


class Citations:
    """Numbers markers in the order they appear. One for something unread just disappears."""

    def __init__(self, ctx: Context, turn: int) -> None:
        self.ctx = ctx
        self.turn = turn
        self.numbers: dict[tuple[str, str], int] = {}
        self.pages: dict[tuple[str, str], str] = {}

    def _was_read(self, kind: str, ref: str) -> bool:
        return bool(
            self.ctx.bus.db.fetch_all(
                "SELECT 1 FROM agent_turn_sources WHERE turn = ? AND kind = ? AND ref = ?",
                (self.turn, kind, ref),
            )
        )

    def _replace(self, match: re.Match[str]) -> str:
        kind, ref, page = match.group(1), match.group(2), match.group(3)
        if not self._was_read(kind, ref):
            return ""
        number = self.numbers.setdefault((kind, ref), len(self.numbers) + 1)
        if page:
            self.pages.setdefault((kind, ref), page)
        return f"[{number}](#cite-{number})"

    def rewrite(self, text: str) -> str:
        return MARKER.sub(self._replace, text)

    def part(self) -> list[dict[str, Any]]:
        """Everything this turn drew on, cited first, as one part for the message."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT kind, ref, opened FROM agent_turn_sources WHERE turn = ?", (self.turn,)
        )
        sources: list[dict[str, Any]] = []
        for row in rows:
            key = (row["kind"], row["ref"])
            number = self.numbers.get(key)
            # Search results only count once they were opened or cited.
            if number is None and not row["opened"]:
                continue
            found = describe(self.ctx, row["kind"], row["ref"])
            if found is not None:
                sources.append({**found, "n": number, "page": self.pages.get(key)})
        if not sources:
            return []
        sources.sort(key=lambda source: (source["n"] is None, source["n"] or 0))
        return [{"type": "data-sources", "data": {"sources": sources}}]


def describe(ctx: Context, kind: str, ref: str) -> dict[str, Any] | None:
    """Title and detail from the database, so nothing a model wrote is shown as a source's name."""
    if kind == MAIL:
        rows = ctx.bus.db.fetch_all(
            "SELECT t.subject, t.last_date, (SELECT COALESCE(NULLIF(m.from_name, ''), m.from_addr)"
            " FROM messages m WHERE m.thread_id = t.id ORDER BY m.date DESC LIMIT 1) AS sender"
            " FROM threads t WHERE t.id = ?",
            (ref,),
        )
        if not rows:
            return None
        return {
            "kind": MAIL,
            "ref": ref,
            "title": rows[0]["subject"] or "No subject",
            "detail": rows[0]["sender"] or "",
            "date": rows[0]["last_date"],
        }
    try:
        found = documents.get_document(GetDocument(key=ref), ctx)
    except CommandError:
        return None
    row = found.document  # type: ignore[attr-defined]
    return {"kind": DOCUMENT, "ref": ref, "title": row.name, "detail": row.source, "date": row.date}
