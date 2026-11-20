"""What a sorting page shows for the grouping engine's report: each group with sample emails and
the folder it starts in, then the biggest senders left in no group.

Only the engine and the parser, so the Sort lab can use it without the database or the keychain.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from nexusai.modules.mail import grouping
from nexusai.modules.mail.parse import parse_message

SAMPLES = 10
MISSED_SENDERS = 40
# Where each section of the engine's report starts out.
FOLDER_OF = {
    "automated": "automated",
    "calendar": "calendar",
    "people": "inbox",
    "too_few": "inbox",
}


def _summary(key: str, raw: bytes, named: set[str]) -> dict[str, Any]:
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
        "names_you": key in named,
    }


def describe(
    report: grouping.Report, read: Callable[[str], bytes]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """What a sorting page shows, and every email behind each entry: the engine's groups with
    sample emails and the folder they start in, then the biggest senders left in no group."""
    # Mentions count only outside groups that name the person in nearly every email.
    ignored = {group.id for group in report.groups if group.mentions_ignored}
    named = {
        key
        for key, decision in report.decisions.items()
        if decision.named and decision.group not in ignored
    }
    members: dict[str, list[str]] = {}
    groups = []
    for group in report.groups:
        data = json.loads(grouping.to_json(grouping.Report("", "", [group], {})))["groups"][0]
        data["folder"] = FOLDER_OF[group.section]
        data["emails"] = [_summary(key, read(key), named) for key in group.members[:SAMPLES]]
        groups.append(data)
        members[group.id] = list(group.members)
    loose = [key for key, decision in report.decisions.items() if decision.group is None]
    by_sender: dict[str, list[dict[str, Any]]] = {}
    for key in loose:
        summary = _summary(key, read(key), named)
        by_sender.setdefault(summary["sender"], []).append(summary)
    # The person's own mail is theirs, never something to sort.
    by_sender.pop(report.owner, None)
    missed = sorted(by_sender.items(), key=lambda item: -len(item[1]))[:MISSED_SENDERS]
    own_domain = report.owner.partition("@")[2]
    endings = grouping._endings(
        {sender.partition("@")[2] for sender in by_sender}
        | {sender.partition("@")[2] for group in report.groups for sender in group.senders}
    )

    def label(sender: str) -> str:
        """Named like the engine names a group: the domain outside the company."""
        local, _, domain = sender.partition("@")
        return local if domain == own_domain else grouping._site(domain, endings)

    shown = []
    for sender, items in missed:
        if len(items) < 2:
            continue
        shown.append(
            {
                "sender": sender,
                "label": label(sender),
                "count": len(items),
                "emails": items[:SAMPLES],
            }
        )
        members[f"miss:{sender}"] = [item["key"] for item in items]
    found = {
        "owner": report.owner,
        "owner_name": report.owner_name,
        "total": len(report.decisions),
        "reach_ai": sum(decision.reaches_ai for decision in report.decisions.values()),
        "ungrouped": len(loose),
        "groups": groups,
        "missed": shown,
    }
    return found, members
