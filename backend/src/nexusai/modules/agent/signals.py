"""What the mailbox itself shows, counted by the app. No model and no one's say-so goes into it."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from nexusai.contracts.agent import ContactRow
from nexusai.kernel.module import Context
from nexusai.modules.agent import feedback
from nexusai.modules.mail import accounts

CONTACT_WINDOW_DAYS = 180
MOST_SENT_READ = 2000
MOST_CONTACTS = 15
# Past this a message is a broadcast. Its list says nothing and can be thousands of addresses long,
# so the model is told the count, and looks through the list only if it needs to.
MOST_NAMED_RECIPIENTS = 10
MOST_DOMAINS_LISTED = 8
MOST_RECIPIENTS_READ = 50
REVIEW_SENDERS = 40
REVIEW_MIN_EMAILS = 5
STYLE_SAMPLES = 2
STYLE_SAMPLE_CHARS = 400
BROAD_CATEGORIES = ("Promotions", "Updates", "Social", "Forums")


def own_addresses(ctx: Context) -> set[str]:
    _, profiles = accounts.read_accounts(ctx.config)
    found: set[str] = set()
    for profile in profiles.values():
        found |= {(profile.address or "").lower(), profile.auth.user.lower()}
    return {address for address in found if "@" in address}


def addresses(column: str) -> list[str]:
    parsed = json.loads(column or "[]")
    found = (item.get("address", "") if isinstance(item, dict) else str(item) for item in parsed)
    return [address.lower() for address in found if address]


def recipient_lines(to_column: str, cc_column: str, own: set[str]) -> list[str]:
    """Everyone by name when it's a few. When it's a broadcast, how many and where the person is."""
    to, cc = addresses(to_column), addresses(cc_column)
    total = len({*to, *cc})
    if total > MOST_NAMED_RECIPIENTS:
        where = "in To" if own & set(to) else "only in Cc" if own & set(cc) else "not named"
        return [
            f"To: broadcast to {total:,} people ({len(to):,} in To, {len(cc):,} in Cc)."
            f" The person is {where}."
        ]

    def named(people: list[str]) -> str:
        return ", ".join(f"{p} (the person)" if p in own else p for p in people)

    return [
        *([f"To: {named(to)}"] if to else []),
        *([f"Cc: {named(cc)}"] if cc else []),
    ]


def read_recipients(ctx: Context, thread: int, contains: str | None = None, offset: int = 0) -> str:
    """Who a message went to, for when that matters. A long list is summarized, then searched."""
    rows = ctx.bus.db.fetch_all(
        "SELECT to_json, cc_json FROM messages WHERE thread_id = ?"
        " ORDER BY json_array_length(to_json) + json_array_length(cc_json) DESC LIMIT 1",
        (thread,),
    )
    if not rows:
        return "That conversation no longer exists."
    to, cc = addresses(rows[0]["to_json"]), addresses(rows[0]["cc_json"])
    everyone = [(person, "To") for person in to] + [(person, "Cc") for person in cc]
    needle = (contains or "").strip().lower()
    found = [item for item in everyone if needle in item[0]]
    shown = found[offset : offset + MOST_RECIPIENTS_READ]
    lines = [
        f"{len(everyone):,} recipients."
        + (f" {len(found):,} match “{contains}”." if needle else "")
    ]
    if not needle:
        domains = Counter(person.rpartition("@")[2] for person, _ in everyone)
        lines.append(
            "Largest domains: "
            + ", ".join(f"{name} {n:,}" for name, n in domains.most_common(MOST_DOMAINS_LISTED))
        )
    lines += [f"- {person} ({field})" for person, field in shown]
    left = len(found) - offset - len(shown)
    if left > 0:
        lines.append(
            f"{left:,} more. Search with contains, or read on from offset {offset + len(shown)}."
        )
    return "\n".join(lines)


def _placeholders(items: set[str]) -> str:
    return ", ".join("?" * len(items)) or "''"


def _days_ago(moment: str) -> int:
    try:
        parsed = datetime.fromisoformat(moment)
    except ValueError:
        return 0
    return max((datetime.now(UTC) - parsed.astimezone(UTC)).days, 0)


def _when(moment: str) -> str:
    days = _days_ago(moment)
    return "today" if days == 0 else "1 day ago" if days == 1 else f"{days} days ago"


def _written_in(ctx: Context, own: set[str]) -> set[int]:
    if not own:
        return set()
    rows = ctx.bus.db.fetch_all(
        "SELECT DISTINCT thread_id FROM messages WHERE LOWER(from_addr) IN"  # noqa: S608
        f" ({_placeholders(own)})",
        tuple(own),
    )
    return {row["thread_id"] for row in rows}


def contacts(ctx: Context, limit: int = MOST_CONTACTS) -> list[ContactRow]:
    """Who they actually write to. Anyone can email someone, so being written to says more."""
    own = own_addresses(ctx)
    if not own:
        return []
    since = (datetime.now(UTC) - timedelta(days=CONTACT_WINDOW_DAYS)).isoformat()
    rows = ctx.bus.db.fetch_all(
        "SELECT to_json, cc_json, date FROM messages WHERE LOWER(from_addr) IN"  # noqa: S608
        f" ({_placeholders(own)}) AND date > ? GROUP BY message_id ORDER BY date DESC LIMIT ?",
        (*own, since, MOST_SENT_READ),
    )
    counted: dict[str, ContactRow] = {}
    for row in rows:
        people = [*addresses(row["to_json"]), *addresses(row["cc_json"])]
        # Writing to everyone doesn't say anyone in particular matters to them.
        if len(people) > MOST_NAMED_RECIPIENTS:
            continue
        for address in people:
            if address in own:
                continue
            found = counted.setdefault(
                address, ContactRow(address=address, written=0, last=row["date"])
            )
            found.written += 1
    return sorted(counted.values(), key=lambda item: (-item.written, item.address))[:limit]


def mailbox_layer(ctx: Context) -> str:
    people = contacts(ctx)
    if not people:
        return ""
    lines = "\n".join(
        f"- {item.address}: wrote to them {item.written} times, last {_when(item.last)}"
        for item in people
    )
    return (
        f"Who they write to most, counted from their sent mail over the past six months:\n{lines}"
    )


def _position(row: Any, own: set[str]) -> str:
    if own & set(addresses(row["to_json"])):
        return "in To"
    if own & set(addresses(row["cc_json"])):
        return "only in Cc"
    return "not named, so it reached them through a list or Bcc"


def about_thread(ctx: Context, thread: int) -> str:
    """The facts the model can't see in the text: who it's addressed to, and how they've behaved."""
    db = ctx.bus.db
    own = own_addresses(ctx)
    rows = db.fetch_all(
        "SELECT from_addr, to_json, cc_json, date FROM messages WHERE thread_id = ?"
        " GROUP BY message_id ORDER BY date",
        (thread,),
    )
    if not rows:
        return ""
    latest = rows[-1]
    theirs = [row for row in rows if row["from_addr"].lower() not in own]
    wrote_last = latest["from_addr"].lower() in own
    lines = [
        f"- Last to write: {'the person' if wrote_last else 'someone else'}, {_when(latest['date'])}",
        f"- This conversation has {len(rows)} messages, and the person wrote {len(rows) - len(theirs)}.",
    ]
    if theirs:
        last_in = theirs[-1]
        lines.insert(0, f"- The person is {_position(last_in, own)} on the latest incoming message")
        lines.append(_sender_line(ctx, last_in["from_addr"].lower(), own))
        corrected = feedback.for_sender(db, last_in["from_addr"].lower())
        if corrected:
            lines.append(f"- The person's corrections for this sender: {corrected}")
    flagged = db.fetch_all("SELECT flagged FROM threads WHERE id = ?", (thread,))
    if flagged and flagged[0]["flagged"]:
        lines.append("- The person starred this conversation")
    folders = db.fetch_all(
        "SELECT DISTINCT l.folder FROM message_locations l JOIN messages m ON m.id = l.message"
        " WHERE m.thread_id = ?",
        (thread,),
    )
    if any("important" in str(row["folder"]).lower() for row in folders):
        lines.append("- Their mail service marks this as important")
    return "Counted by the app from their mailbox, so this is reliable:\n" + "\n".join(lines)


def _sender_line(ctx: Context, sender: str, own: set[str]) -> str:
    db = ctx.bus.db
    seen = db.fetch_all(
        "SELECT COUNT(*) AS n, COALESCE(SUM(read), 0) AS opened FROM messages WHERE LOWER(from_addr) = ?",
        (sender,),
    )[0]
    replied = db.fetch_all(
        "SELECT COUNT(DISTINCT m.thread_id) AS n FROM messages m WHERE LOWER(m.from_addr) = ?"  # noqa: S608
        " AND EXISTS (SELECT 1 FROM messages o WHERE o.thread_id = m.thread_id"
        f" AND LOWER(o.from_addr) IN ({_placeholders(own)}))",
        (sender, *own),
    )[0]["n"]
    conversations = db.fetch_all(
        "SELECT COUNT(DISTINCT thread_id) AS n FROM messages WHERE LOWER(from_addr) = ?", (sender,)
    )[0]["n"]
    if seen["n"] <= 1:
        return f"- {sender} is new: this is the first email from them"
    return (
        f"- {sender}: {seen['n']} emails over time, the person opened {seen['opened']},"
        f" and replied in {replied} of {conversations} conversations"
    )


def writing_samples(ctx: Context, sender: str) -> list[str]:
    """How they write, to this person if they ever have, so a draft sounds like them."""
    own = own_addresses(ctx)
    if not own:
        return []
    db = ctx.bus.db
    mine = (
        "SELECT own_text, to_json FROM messages WHERE encrypted = 0 AND LOWER(from_addr) IN"  # noqa: S608
        f" ({_placeholders(own)}) AND LENGTH(own_text) > 20 GROUP BY message_id ORDER BY date DESC LIMIT 200"
    )
    rows = db.fetch_all(mine, tuple(own))
    to_them = [row for row in rows if sender.lower() in addresses(row["to_json"])]
    chosen = (to_them or rows)[:STYLE_SAMPLES]
    return [row["own_text"].strip()[:STYLE_SAMPLE_CHARS] for row in chosen]


# Too few to say anything about a whole category.
MOST_FEW_THREADS = 3


def sender_table(ctx: Context) -> str:
    """The inbox by sender, for recommending where whole groups of mail should go."""
    db = ctx.bus.db
    account = accounts.current_account(ctx.config)
    own = own_addresses(ctx)
    engaged = _written_in(ctx, own)
    broad = ", ".join(f"'{name}'" for name in BROAD_CATEGORIES)
    rows = db.fetch_all(
        "SELECT LOWER(m.from_addr) AS sender, MAX(m.from_name) AS name, COUNT(*) AS n, COALESCE(SUM(m.read), 0) AS opened,"  # noqa: S608
        " MAX(m.date) AS latest, GROUP_CONCAT(DISTINCT m.thread_id) AS threads"
        " FROM messages m JOIN threads t ON t.id = m.thread_id"
        " WHERE m.account = ? AND m.folder_role = 'inbox' AND COALESCE(t.category_source, '') != 'user'"
        f" AND (t.category IS NULL OR t.category IN ({broad}))"
        " GROUP BY sender HAVING n >= ? ORDER BY n DESC LIMIT ?",
        (account, REVIEW_MIN_EMAILS, REVIEW_SENDERS),
    )
    lines = []
    for row in rows:
        if row["sender"] in own:
            continue
        threads = {int(item) for item in str(row["threads"]).split(",")}
        subjects = db.fetch_all(
            "SELECT DISTINCT subject FROM messages WHERE LOWER(from_addr) = ? ORDER BY date DESC LIMIT 2",
            (row["sender"],),
        )
        shown = " | ".join(str(item["subject"])[:60] for item in subjects)
        lines.append(
            f"- {row['name'] or 'Unnamed'} <{row['sender']}>: {row['n']} emails, opened {row['opened']},"
            f" replied in {len(threads & engaged)}, latest {_when(row['latest'])}. Subjects: {shown}"
        )
    return "\n".join(lines)


def category_table(ctx: Context) -> str:
    """Each category by how much of its mail needed the person, for what's worth putting first."""
    broad = ", ".join(f"'{name}'" for name in BROAD_CATEGORIES)
    rows = ctx.bus.db.fetch_all(
        "SELECT t.category AS name, COUNT(*) AS n,"  # noqa: S608
        " SUM(t.importance = 'high' OR t.status = 'waiting_on_you') AS needed,"
        " SUM(t.unread_count = 0) AS opened"
        " FROM threads t JOIN mail_categories c ON c.name = t.category"
        f" WHERE t.account = ? AND c.in_priority = 0 AND c.proposed = 0 AND c.priority_suggested = 0"
        f" AND t.category NOT IN ({broad}) GROUP BY t.category HAVING n >= ? ORDER BY needed DESC",
        (accounts.current_account(ctx.config), MOST_FEW_THREADS),
    )
    return "\n".join(
        f"- {row['name']}: {row['n']} conversations, {row['needed']} needed them,"
        f" {row['opened']} opened"
        for row in rows
    )
