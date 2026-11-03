"""What the agent recommends doing with whole groups of mail. Nothing happens until the person says."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from nexusai.contracts.agent import MailSuggestion
from nexusai.contracts.mail import MailRule, MoveThread, RuleActions, RuleCondition, SaveCategory
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import signals
from nexusai.modules.mail import accounts
from nexusai.modules.mail import module as mail

MIGRATION = Migration(
    "agent_suggestions_001",
    """
CREATE TABLE mail_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, senders TEXT NOT NULL, reason TEXT NOT NULL,
  quiet INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', time TEXT NOT NULL, by TEXT NOT NULL DEFAULT 'agent');
""",
)
# So a run can't bury the page, and what's turned down isn't suggested again.
MOST_OPEN = 8
MOST_SENDERS = 25
# A cleanup only touches mail they've read, once it's old enough not to be in use.
ARCHIVE_AFTER_DAYS = 30
MOST_ARCHIVED = 500


def _counted(ctx: Context, senders: list[str]) -> int:
    account = accounts.current_account(ctx.config)
    marks = ", ".join("?" * len(senders))
    return int(
        ctx.bus.db.fetch_all(
            "SELECT COUNT(*) AS n FROM messages WHERE account = ? AND folder_role = 'inbox'"  # noqa: S608
            f" AND LOWER(from_addr) IN ({marks})",
            (account, *senders),
        )[0]["n"]
    )


def _opened(ctx: Context, senders: list[str]) -> int:
    account = accounts.current_account(ctx.config)
    marks = ", ".join("?" * len(senders))
    return int(
        ctx.bus.db.fetch_all(
            "SELECT COUNT(*) AS n FROM messages WHERE account = ? AND folder_role = 'inbox'"  # noqa: S608
            f" AND read = 1 AND LOWER(from_addr) IN ({marks})",
            (account, *senders),
        )[0]["n"]
    )


def _replied(ctx: Context, senders: list[str]) -> int:
    own = signals.own_addresses(ctx)
    if not own:
        return 0
    marks = ", ".join("?" * len(senders))
    mine = ", ".join("?" * len(own))
    return int(
        ctx.bus.db.fetch_all(
            "SELECT COUNT(DISTINCT m.thread_id) AS n FROM messages m WHERE"  # noqa: S608
            f" LOWER(m.from_addr) IN ({marks}) AND EXISTS (SELECT 1 FROM messages o WHERE"
            f" o.thread_id = m.thread_id AND LOWER(o.from_addr) IN ({mine}))",
            (*senders, *own),
        )[0]["n"]
    )


def _to_archive(ctx: Context, senders: list[str]) -> list[int]:
    account = accounts.current_account(ctx.config)
    marks = ", ".join("?" * len(senders))
    since = (datetime.now(UTC) - timedelta(days=ARCHIVE_AFTER_DAYS)).isoformat()
    rows = ctx.bus.db.fetch_all(
        "SELECT DISTINCT t.id FROM threads t JOIN messages m ON m.thread_id = t.id"  # noqa: S608
        f" WHERE t.account = ? AND t.in_inbox = 1 AND t.unread_count = 0 AND t.flagged = 0 AND t.last_date < ?"
        f" AND t.status IN ('none', 'fyi', 'resolved') AND LOWER(m.from_addr) IN ({marks}) LIMIT ?",
        (account, since, *senders, MOST_ARCHIVED),
    )
    return [row["id"] for row in rows]


def add(
    ctx: Context, category: str, senders: list[str], reason: str, quiet: bool, by: str = "agent"
) -> str:
    """Only for senders really in the mailbox, and the counts shown are always the app's own."""
    db = ctx.bus.db
    name = category.strip()[:64]
    wanted = sorted({sender.strip().lower() for sender in senders if "@" in sender})
    found = [sender for sender in wanted if _counted(ctx, [sender])][:MOST_SENDERS]
    if not name or not found:
        return "None of those senders are in the mailbox, so nothing was suggested."
    earlier = db.fetch_all("SELECT status, category, senders FROM mail_suggestions")
    for row in earlier:
        overlaps = set(json.loads(row["senders"])) & set(found)
        # Whatever it's called, the same mail shouldn't be offered twice or come back once refused.
        if overlaps and (row["category"] == name or row["status"] != "accepted"):
            return "That's been suggested already."
    opened = sum(1 for row in earlier if row["status"] == "open")
    if opened >= MOST_OPEN:
        return "Enough suggestions are waiting on the person already."
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO mail_suggestions (category, senders, reason, quiet, time, by) VALUES (?, ?, ?, ?, ?, ?)",
            (name, json.dumps(found), reason[:500], int(quiet), datetime.now(UTC).isoformat(), by),
        )
        work.emit("suggestions.changed", {}, source="agent", trace_id=ctx.trace_id)
    return f"Suggested. It will show {_counted(ctx, found)} emails from {len(found)} senders."


def _row(ctx: Context, row: Any) -> MailSuggestion:
    senders = json.loads(row["senders"])
    return MailSuggestion(
        id=row["id"],
        category=row["category"],
        senders=senders,
        reason=row["reason"],
        quiet=bool(row["quiet"]),
        emails=_counted(ctx, senders),
        opened=_opened(ctx, senders),
        replied=_replied(ctx, senders),
        to_archive=len(_to_archive(ctx, senders)) if row["quiet"] else 0,
    )


def waiting(ctx: Context) -> list[MailSuggestion]:
    rows = ctx.bus.db.fetch_all("SELECT * FROM mail_suggestions WHERE status = 'open' ORDER BY id")
    return [_row(ctx, row) for row in rows]


def decide(ctx: Context, identifier: int, accept: bool) -> None:
    db = ctx.bus.db
    rows = db.fetch_all(
        "SELECT * FROM mail_suggestions WHERE id = ? AND status = 'open'", (identifier,)
    )
    if not rows:
        raise CommandError("suggestion.gone", "That suggestion has already been handled.", 409)
    row = rows[0]
    if accept:
        _apply(ctx, row["category"], json.loads(row["senders"]), bool(row["quiet"]))
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE mail_suggestions SET status = ? WHERE id = ?",
            ("accepted" if accept else "declined", identifier),
        )
        work.emit("suggestions.changed", {}, source="agent", trace_id=ctx.trace_id)


def _apply(ctx: Context, category: str, senders: list[str], quiet: bool) -> None:
    """Files what's here and what's coming. A quiet group also skips the agent and leaves the inbox."""
    mail.save_category(SaveCategory(name=category, source="agent"), ctx)
    for sender in senders:
        mail.upsert_rule(
            ctx,
            MailRule(
                name=f"{category}: {sender}",
                conditions=[RuleCondition(field="sender", value=sender)],
                actions=RuleActions(category=category, skip_agent=quiet),
            ),
        )
        mail.file_by_sender(ctx, category, sender)
    if quiet:
        for thread in _to_archive(ctx, senders):
            mail.move_thread(MoveThread(id=thread, to="archive"), ctx)
