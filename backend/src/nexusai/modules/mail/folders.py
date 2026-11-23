"""Mail folders as one tree, the way a file system holds files.

Two homes sit at the top: the Inbox, holding everything the AI reads, and Kept from the AI,
holding everything it doesn't. They aren't rows; a folder with no parent is at the top of one of
them, and its `ai_reads` says which. A folder inside another takes its side from its home, so
moving a folder is one field, and every folder in it moves with it.

Names are unique across the whole tree, whatever their case, so a rule, an agent or the person
can name a folder and mean exactly one. Opening a folder shows its own mail and everything
under it.
"""

import sqlite3
from typing import Any

from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError

MIGRATION = Migration(
    "mail_folder_tree_001",
    "ALTER TABLE mail_categories ADD COLUMN parent TEXT;",
)
# The catch-all of Kept from the AI. It stays, but is never listed: its mail is simply kept.
AUTOMATED = "Automated"
CALENDAR = "Calendar"
# Kept from the AI whatever happens: tools' mail, and invitations.
KEPT_WHOLE = (AUTOMATED, CALENDAR)
# What the two homes and the Priority view are called, which no folder can take.
RESERVED = ("Inbox", "Kept from the AI", "Read by AI", "Hidden from AI", "Priority")
INBOX, KEPT = "Read by AI", "Hidden from AI"
LONGEST_NAME = 64

# Every folder in the tree under one, itself included. UNION stops at a loop.
SUBTREE = (
    "WITH RECURSIVE tree(n) AS (SELECT ? UNION SELECT c.name FROM mail_categories c"
    " JOIN tree ON c.parent = tree.n) SELECT n FROM tree"
)


def in_tree(table: str = "") -> str:
    """A conversation in this folder or anything under it. Takes the folder's name twice."""
    return (
        f"({table}category IN ({SUBTREE}) OR EXISTS (SELECT 1 FROM"
        f" json_each({table}extra_categories) WHERE value IN ({SUBTREE})))"
    )


Source = Database | sqlite3.Connection


def _rows(source: Source, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    if isinstance(source, Database):
        return source.fetch_all(sql, params)
    return list(source.execute(sql, params).fetchall())


def find(source: Source, name: str) -> sqlite3.Row | None:
    """The folder with this name, whatever its case."""
    rows = _rows(
        source,
        "SELECT * FROM mail_categories WHERE name = ? COLLATE NOCASE AND proposed = 0"
        " ORDER BY name = ? DESC LIMIT 1",
        (name.strip(), name.strip()),
    )
    return rows[0] if rows else None


def place_of(source: Source, row: sqlite3.Row) -> str:
    """Where a folder is, said plainly: under its parent, or in its home."""
    if row["parent"]:
        return f"under {row['parent']}"
    return f"in {INBOX if row['ai_reads'] else KEPT}"


def check_name(source: Source, name: str, keep: str | None = None) -> str:
    """A name a folder can have: not empty, not a home's, and not another folder's. Says where
    the clash is, so the person knows which folder already has it."""
    clean = " ".join(name.split())[:LONGEST_NAME]
    if not clean:
        raise CommandError("category.name", "A folder needs a name.", 422)
    if "/" in clean:
        raise CommandError(
            "category.name", "A folder name can't have a /. Put it inside another instead.", 422
        )
    if clean.casefold() in {reserved.casefold() for reserved in RESERVED}:
        raise CommandError("category.exists", f"{clean} is already a part of your mail.", 409)
    taken = find(source, clean)
    if taken is not None and (keep is None or taken["name"].casefold() != keep.casefold()):
        raise CommandError(
            "category.exists",
            f"There's already a folder called {taken['name']}, {place_of(source, taken)}.",
            409,
        )
    return clean


def free_name(source: Source, base: str, keep: str | None = None) -> str:
    """The name, or the name with the first number that makes it unique."""
    clean = " ".join(base.split())[: LONGEST_NAME - 3] or "Folder"
    taken = {
        row["name"].casefold()
        for row in _rows(source, "SELECT name FROM mail_categories WHERE proposed = 0")
    } | {reserved.casefold() for reserved in RESERVED}
    if keep:
        taken.discard(keep.casefold())
    if clean.casefold() not in taken:
        return clean
    number = 2
    while f"{clean} {number}".casefold() in taken:
        number += 1
    return f"{clean} {number}"


def subtree(source: Source, name: str) -> list[str]:
    """The folder and every folder under it, nearest first."""
    return [row["n"] for row in _rows(source, SUBTREE, (name,))]


def move(tx: sqlite3.Connection, name: str, parent: str | None, reads: bool | None) -> list[str]:
    """Puts a folder inside another, or at the top of a home. Everything under it moves with it
    and takes its new side. Says which folders changed sides."""
    if parent:
        above = find(tx, parent)
        if above is None:
            raise CommandError("category.not_found", f"There's no folder called {parent}.", 404)
        if above["name"] in subtree(tx, name):
            raise CommandError(
                "category.move", "A folder can't go inside itself or a folder in it.", 409
            )
        parent, side = above["name"], bool(above["ai_reads"])
    else:
        parent = None
        row = find(tx, name)
        side = bool(row["ai_reads"]) if reads is None and row else bool(reads)
    tx.execute("UPDATE mail_categories SET parent = ? WHERE name = ?", (parent, name))
    changed = []
    for folder in subtree(tx, name):
        updated = tx.execute(
            "UPDATE mail_categories SET ai_reads = ? WHERE name = ? AND ai_reads != ?",
            (int(side), folder, int(side)),
        ).rowcount
        if updated:
            changed.append(folder)
    return changed


def suggest_kept_name(source: Source, name: str, senders: list[str]) -> str:
    """A name for the half of a folder the AI doesn't read, from what its senders send."""
    words = " ".join(senders).lower()
    if "alert" in words or "job" in words:
        tail = "alerts"
    elif any(word in words for word in ("offer", "deal", "promo", "store", "market", "mailer")):
        tail = "offers"
    elif "news" in words:
        tail = "newsletters"
    else:
        tail = "updates"
    first = name.split()[0] if name.split() else name
    return free_name(source, f"{first} {tail}" if tail not in first.lower() else f"{name} 2")
