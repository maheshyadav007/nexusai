"""What the person changed after the agent judged. It's the plainest evidence of what they want."""

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.agent import CorrectionRow
from nexusai.kernel.database import Database, Migration

MIGRATION = Migration(
    "agent_feedback_001",
    """
CREATE TABLE mail_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, sender TEXT NOT NULL, thread INTEGER NOT NULL,
  field TEXT NOT NULL, value TEXT NOT NULL);
CREATE INDEX mail_feedback_sender ON mail_feedback (sender);
""",
)
FIELDS = {"category", "status", "importance"}
RECENT = 200
MOST_SHOWN = 30
# The same choice this many times is a habit, so it's worth offering to make it automatic.
HABIT = 3
ADDRESS = re.compile(r"[^\s<>\"',;]+@[^\s<>\"',;]+")
WORDING = {
    ("status", "resolved"): "marked as done",
    ("status", "waiting_on_you"): "marked as waiting on them",
    ("status", "waiting_on_others"): "marked as waiting on someone else",
    ("status", "fyi"): "marked as just for information",
    ("importance", "high"): "marked as important",
    ("importance", "low"): "marked as not important",
    ("importance", "normal"): "marked as normal importance",
}


def _say(field: str, value: str) -> str:
    return f"filed under {value}" if field == "category" else WORDING.get((field, value), value)


def note(
    db: Database, thread: int, field: str, value: Any, own: set[str]
) -> tuple[str, str] | None:
    """Saves what the person did. Says who sent it and the choice, when it's a habit by now."""
    if field not in FIELDS or not value:
        return None
    rows = db.fetch_all(
        "SELECT from_addr FROM messages WHERE thread_id = ? ORDER BY date DESC", (thread,)
    )
    sender = next((r["from_addr"].lower() for r in rows if r["from_addr"].lower() not in own), None)
    if sender is None:
        return None
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_feedback (time, sender, thread, field, value) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), sender, thread, field, str(value)),
        )
    if field != "category":
        return None
    same = db.fetch_all(
        "SELECT COUNT(DISTINCT thread) AS n FROM mail_feedback WHERE sender = ? AND field = 'category' AND value = ?",
        (sender, str(value)),
    )[0]["n"]
    return (sender, str(value)) if same >= HABIT else None


def recent(db: Database) -> list[CorrectionRow]:
    rows = db.fetch_all(
        "SELECT sender, field, value, COUNT(DISTINCT thread) AS times, MAX(time) AS latest FROM"
        " (SELECT * FROM mail_feedback ORDER BY id DESC LIMIT ?)"
        " GROUP BY sender, field, value ORDER BY latest DESC LIMIT ?",
        (RECENT, MOST_SHOWN),
    )
    return [
        CorrectionRow(
            sender=row["sender"],
            field=row["field"],
            value=row["value"],
            said=_say(row["field"], row["value"]),
            times=row["times"],
            latest=row["latest"],
        )
        for row in rows
    ]


def layer(db: Database) -> str:
    """Their corrections, for every judgement, so the same mistake isn't made twice."""
    lines = [f"- Mail from {item.sender}: {item.said}, {item.times}x" for item in recent(db)]
    if not lines:
        return ""
    return "What the person changed after you judged. Do the same from now on:\n" + "\n".join(lines)


def for_sender(db: Database, sender: str) -> str:
    rows = db.fetch_all(
        "SELECT field, value FROM mail_feedback WHERE sender = ? ORDER BY id DESC LIMIT 20",
        (sender,),
    )
    counted = Counter((row["field"], row["value"]) for row in rows)
    return "; ".join(f"{_say(*key)} {times}x" for key, times in counted.most_common(3))
