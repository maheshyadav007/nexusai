"""Links between things that own nothing: a matter related to another, merged into another, or
using a document. Ownership isn't here: a task's matter is a column on the task, so it can only
have one.

A link is a decision someone made, with who made it and why. Facts the mail already holds, like
which email a file came with, are read from the mail instead. A wrong link is ended with a
reason, never deleted, so what happened stays true.
"""

from datetime import UTC, datetime
from typing import Any

from nexusai.kernel.database import Database, Migration
from nexusai.modules.agent.kinds import KINDS, parse

MIGRATION = Migration(
    "agent_links_001",
    """
CREATE TABLE links (
  id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT NOT NULL, b TEXT NOT NULL, kind TEXT NOT NULL,
  by TEXT NOT NULL, why TEXT NOT NULL DEFAULT '', confidence TEXT NOT NULL DEFAULT 'high',
  started TEXT NOT NULL, ended TEXT, ended_why TEXT);
CREATE UNIQUE INDEX links_live ON links (a, b, kind) WHERE ended IS NULL;
CREATE INDEX links_a ON links (a, kind);
CREATE INDEX links_b ON links (b, kind);
""",
)
# related: alike, not the same thing. merged: a was folded into b. uses: a matter uses a file.
KINDS_OF_LINK = ("related", "merged", "uses")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def add(
    tx: Any, a: str, b: str, kind: str, by: str, why: str = "", confidence: str = "high"
) -> bool:
    """One live link of a kind between two things; asking again changes nothing."""
    if kind not in KINDS_OF_LINK or not parse(a) or not parse(b) or a == b:
        return False
    return bool(
        tx.execute(
            "INSERT OR IGNORE INTO links (a, b, kind, by, why, confidence, started) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (a, b, kind, by, why[:300], confidence, _now()),
        ).rowcount
    )


def end(tx: Any, a: str, b: str, kind: str, why: str) -> bool:
    return bool(
        tx.execute(
            "UPDATE links SET ended = ?, ended_why = ? WHERE a = ? AND b = ? AND kind = ? AND ended IS NULL",
            (_now(), why[:300], a, b, kind),
        ).rowcount
    )


def live(db: Database, end_at: str, kind: str, *, reverse: bool = False) -> list[Any]:
    """Links of a kind from this thing (or to it, reversed), newest first."""
    side, other = ("b", "a") if reverse else ("a", "b")
    return db.fetch_all(
        f"SELECT id, {other} AS other, by, why, started FROM links"  # noqa: S608
        f" WHERE {side} = ? AND kind = ? AND ended IS NULL ORDER BY id DESC",
        (end_at, kind),
    )


def tidy(db: Database) -> int:
    """Links to something that's gone are ended, so nothing points at nothing."""
    ended = 0
    with db.transaction() as tx:
        for row in tx.execute("SELECT id, a, b FROM links WHERE ended IS NULL").fetchall():
            for end_at in (row["a"], row["b"]):
                found = parse(end_at)
                table = KINDS[found[0]].table if found else None
                if (
                    not found
                    or not table
                    or not tx.execute(
                        f"SELECT 1 FROM {table} WHERE id = ?",  # noqa: S608
                        (found[1],),
                    ).fetchone()
                ):
                    tx.execute(
                        "UPDATE links SET ended = ?, ended_why = 'deleted' WHERE id = ?",
                        (_now(), row["id"]),
                    )
                    ended += 1
                    break
    return ended
