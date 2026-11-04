"""What the person changed after the agent judged. It's the plainest evidence of what they want."""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.agent import BriefReaction, CorrectionRow
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
    db: Database,
    thread: int,
    field: str,
    value: Any,
    own: set[str],
    *,
    event_id: str | None = None,
    old_value: Any = None,
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
        inserted = tx.execute(
            "INSERT OR IGNORE INTO mail_feedback(time,sender,thread,field,value,event_id,old_value) VALUES(?,?,?,?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                sender,
                thread,
                field,
                str(value),
                event_id,
                json.dumps(old_value),
            ),
        )
        if not inserted.rowcount:
            return None
    if field != "category":
        return None
    same = db.fetch_all(
        "SELECT COUNT(DISTINCT thread) AS n FROM mail_feedback WHERE sender = ? AND field = 'category' AND value = ?",
        (sender, str(value)),
    )[0]["n"]
    return (sender, str(value)) if same >= HABIT else None


def recent(db: Database, account: str | None = None) -> list[CorrectionRow]:
    rows = db.fetch_all(
        "SELECT sender, field, value, COUNT(DISTINCT thread) AS times, MAX(time) AS latest FROM"
        " (SELECT f.* FROM mail_feedback f JOIN threads t ON t.id=f.thread WHERE (? IS NULL OR t.account=?) ORDER BY f.id DESC LIMIT ?)"
        " GROUP BY sender, field, value ORDER BY latest DESC LIMIT ?",
        (account, account, RECENT, MOST_SHOWN),
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


def layer(db: Database, account: str | None = None) -> str:
    """Their corrections, for every judgement, so the same mistake isn't made twice."""
    lines = [
        f"- Mail from {item.sender}: {item.said}, {item.times}x" for item in recent(db, account)
    ]
    if not lines:
        return ""
    return (
        "Observed corrections to specific decisions, not permanent sender rules. Use similar context, resolve conflicts by recency, and prefer approved instructions:\n"
        + "\n".join(lines)
    )


def for_sender(db: Database, sender: str, account: str | None = None) -> str:
    rows = db.fetch_all(
        "SELECT f.field,f.value FROM mail_feedback f JOIN threads t ON t.id=f.thread WHERE f.sender=? AND (? IS NULL OR t.account=?) ORDER BY f.id DESC LIMIT 20",
        (sender, account, account),
    )
    counted = Counter((row["field"], row["value"]) for row in rows)
    return "; ".join(f"{_say(*key)} {times}x" for key, times in counted.most_common(3))


BRIEF_MIGRATION = Migration(
    "agent_brief_feedback_001",
    """
CREATE TABLE brief_feedback (
  session TEXT NOT NULL, day TEXT NOT NULL, rating TEXT, comment TEXT NOT NULL DEFAULT '', brief TEXT NOT NULL DEFAULT '',
  time TEXT NOT NULL, PRIMARY KEY (session, day));
""",
)
BRIEFS_REMEMBERED = 10
BRIEF_SHOWN_CHARS = 300


def save_brief_reaction(
    db: Database, session: str, day: str, rating: str | None, comment: str, brief: str
) -> None:
    now = datetime.now(UTC).isoformat()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO brief_feedback (session, day, rating, comment, brief, time)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (session, day) DO UPDATE SET"
            " rating = excluded.rating, comment = excluded.comment, brief = excluded.brief, time = excluded.time",
            (session, day, rating, comment.strip(), brief[:BRIEF_SHOWN_CHARS], now),
        )


def brief_reaction(db: Database, session: str, day: str) -> tuple[str | None, str]:
    rows = db.fetch_all(
        "SELECT rating, comment FROM brief_feedback WHERE session = ? AND day = ?", (session, day)
    )
    return (rows[0]["rating"], rows[0]["comment"]) if rows else (None, "")


def brief_reactions(db: Database) -> list[BriefReaction]:
    rows = db.fetch_all(
        "SELECT day,rating,comment FROM (SELECT day,rating,comment,time FROM brief_feedback UNION ALL SELECT substr(a.created,1,10),f.rating,f.comment,f.updated FROM brief_artifact_feedback f JOIN brief_artifacts a ON a.id=f.artifact) ORDER BY time DESC LIMIT ?",
        (BRIEFS_REMEMBERED,),
    )
    return [BriefReaction(day=r["day"], rating=r["rating"], comment=r["comment"]) for r in rows]


def brief_layer(db: Database) -> str:
    """Only the person's own words and marks, so it can sit with what they've told the agent."""
    rows = brief_reactions(db)
    if not rows:
        return ""
    liked = sum(row.rating == "up" for row in rows)
    disliked = sum(row.rating == "down" for row in rows)
    lines = [
        f"Of the last {len(rows)} briefs they reacted to, they liked {liked} and disliked {disliked}."
    ]
    said = [f"- {row.day}: {row.comment}" for row in rows if row.comment]
    if said:
        lines += ["What they asked for, newest first. Newer wins where these differ:", *said]
    return "\n".join(lines)


def briefs_with_reactions(db: Database) -> str:
    """What each rated brief said, for the task, since those words came from reading mail."""
    rows = db.fetch_all(
        "SELECT day,rating,brief FROM (SELECT day,rating,brief,time FROM brief_feedback UNION ALL SELECT substr(a.created,1,10),f.rating,substr(a.text,1,300),f.updated FROM brief_artifact_feedback f JOIN brief_artifacts a ON a.id=f.artifact) WHERE rating IS NOT NULL AND brief != '' ORDER BY time DESC LIMIT ?",
        (BRIEFS_REMEMBERED,),
    )
    return "\n".join(
        f"{row['day']}, {'liked' if row['rating'] == 'up' else 'disliked'}: {row['brief']}"
        for row in rows
    )
