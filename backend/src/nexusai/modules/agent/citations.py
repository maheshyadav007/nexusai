"""What a turn actually read, so an answer can only cite that, and titles never come from a model."""

import re
from typing import Any

from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import sources as source_names
from nexusai.modules.agent.sources import DOCUMENT, MAIL

MIGRATION = Migration(
    "agent_citations_001",
    """
CREATE TABLE agent_turn_sources (
  turn INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, opened INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (turn, kind, ref));
""",
)
# A message in a thread is cited as a page of the thread: [mail:123#m456].
MESSAGE = re.compile(r"^m(\d+)$")
MARKER = re.compile(r"\[(mail|doc):([^\]\s#]{1,200})(?:#([^\]\s]{1,40}))?\]")
# The start of a marker that may finish in the next chunk of a stream.
PARTIAL = re.compile(r"\[(?:m|ma|mai|mail|d|do|doc|(?:mail|doc):[^\]\s]{0,240})?$")
REPEATED = re.compile(r"(\[(\d+)\]\(#cite-\2\))(?:\s*\[\2\]\(#cite-\2\))+")
__all__ = ["DOCUMENT", "MAIL", "Citations", "note"]


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


def mark(kind: str, ref: object) -> str:
    """How a tool shows an email or a document, so the model cites it by copying it as written."""
    return f"[{kind}:{ref}]"


def shown(tx: Any, turn: int, text: str | None) -> None:
    """Every marker the model was shown in a turn, in its task or a tool's result, can be cited."""
    found = {(m.group(1), m.group(2)) for m in MARKER.finditer(text or "")}
    for kind, ref in found:
        tx.execute(
            "INSERT INTO agent_turn_sources (turn, kind, ref) VALUES (?, ?, ?)"
            " ON CONFLICT (turn, kind, ref) DO NOTHING",
            (turn, kind, ref),
        )


def shown_in_session(db: Database, session: str, text: str | None) -> None:
    """The same for the session's open turn, for a tool's result."""
    if not text or not MARKER.search(text):
        return
    rows = db.fetch_all(
        "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if rows:
        with db.transaction() as tx:
            shown(tx, rows[0]["id"], text)


def used_in_session(db: Database, session: str) -> bool:
    """Whether the session's open turn was shown any email or document."""
    return bool(
        db.fetch_all(
            "SELECT 1 FROM agent_turn_sources s JOIN agent_turns t ON t.id = s.turn"
            " WHERE t.session = ? AND t.closed = 0 LIMIT 1",
            (session,),
        )
    )


class Citations:
    """Numbers markers in the order they appear. One for something unread just disappears."""

    def __init__(self, ctx: Context, turn: int) -> None:
        self.ctx = ctx
        self.turn = turn
        self.numbers: dict[tuple[str, str], int] = {}
        self.pages: dict[tuple[str, str], str] = {}
        self.messages: dict[tuple[str, str], int] = {}

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
        message = MESSAGE.match(page or "") if kind == MAIL else None
        if message:
            self.messages.setdefault((kind, ref), int(message.group(1)))
        elif page:
            self.pages.setdefault((kind, ref), page)
        return f"[{number}](#cite-{number})"

    def rewrite(self, text: str) -> str:
        # Two messages of one thread cited side by side are one source, so one number.
        return REPEATED.sub(r"\1", MARKER.sub(self._replace, text))

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
            found = source_names.describe(
                self.ctx,
                row["kind"],
                row["ref"],
                message=self.messages.get(key),
                page=self.pages.get(key),
            )
            if found is not None:
                sources.append({**found.model_dump(), "n": number})
        if not sources:
            return []
        sources.sort(key=lambda source: (source["n"] is None, source["n"] or 0))
        return [{"type": "data-sources", "data": {"sources": sources}}]
