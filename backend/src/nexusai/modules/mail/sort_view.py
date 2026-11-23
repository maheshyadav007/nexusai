"""What a sorting page shows: every sender with its score, its side and sample emails, the same
for the app's sorting page and the Sort lab.

Only the engine and the parser, so the Sort lab can use it without the database or the keychain.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from nexusai.modules.mail import grouping
from nexusai.modules.mail.parse import parse_message

SAMPLES = 10


def _summary(key: str, raw: bytes) -> dict[str, Any]:
    parsed = parse_message(raw)
    try:
        when = datetime.fromisoformat(parsed.date).strftime("%d %b").lstrip("0")
    except ValueError:
        when = ""
    return {
        "key": key,
        "subject": parsed.subject,
        "sender": parsed.from_addr,
        "from": parsed.from_name or parsed.from_addr,
        "when": when,
        "snippet": parsed.snippet[:140],
    }


# The sender list: one row per sender, on the side the AI reads or the side it ignores.

# The biggest senders the AI ignores start out as their own categories.
TOP_CATEGORIES = 3


def describe_senders(report: grouping.SenderReport, read: Callable[[str], bytes]) -> dict[str, Any]:
    """Every sender biggest first, with its score, its side, whether it starts as its own
    category, and sample emails."""
    ignored = [row.sender for row in report.senders if row.side == "ignores"]
    own = set(ignored[:TOP_CATEGORIES])
    senders = []
    for row in report.senders:
        senders.append(
            {
                "sender": row.sender,
                "label": row.label,
                "count": row.count,
                "score": row.score,
                "repeats": row.repeats,
                "bulk": row.bulk,
                "one_way": row.one_way,
                "side": row.side,
                "kept": row.kept,
                "own": row.sender in own,
                "examples": [pattern for pattern, _ in row.examples],
                "emails": [_summary(key, read(key)) for key in row.members[:SAMPLES]],
                "folder": "",
                "starts": row.starts,
            }
        )
    return {
        "owner": report.owner,
        "owner_name": report.owner_name,
        "total": report.total,
        "reach_ai": report.reach_ai,
        "calendar": len(report.calendar),
        "senders": senders,
    }
