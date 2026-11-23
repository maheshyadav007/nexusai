"""Hide from AI, from wherever the person sees mail: everything from a sender, or one
conversation, goes to Kept from the AI, its rule follows, and one Undo puts it all back.

What the AI did with that mail (its tasks, its matters) leaves with it, by the agent's own
follow-folders step, and comes back with Undo. Nothing changes on the mail server.
"""

import json
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.mail import HiddenFromAi, HideFromAi, HideFromAiPreview, MailRule, RuleSet
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import accounts, rules, sorting
from nexusai.modules.mail import folders as folder_tree

MIGRATION = Migration(
    "mail_hidden_undo_001",
    "CREATE TABLE mail_hidden_undo (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL,"
    " state TEXT NOT NULL);",
)
FROM_SENDER = "FROM messages WHERE account = ? AND LOWER(from_addr) = ?"
# Where one conversation goes when only it is hidden: Kept from the AI's catch-all.
ALONE = sorting.AUTOMATED
WHY = "You hid it from the AI"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sender(ctx: Context, thread: int) -> tuple[str, str]:
    """Who the conversation is from: the newest email someone else wrote, as address and name."""
    _, profiles = accounts.read_accounts(ctx.config)
    own = {
        address.casefold()
        for profile in profiles.values()
        for address in (profile.address or "", profile.auth.user)
        if "@" in address
    }
    rows = ctx.bus.db.fetch_all(
        "SELECT from_addr, from_name FROM messages WHERE thread_id = ? ORDER BY date DESC, id DESC",
        (thread,),
    )
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    theirs = next((row for row in rows if row["from_addr"].casefold() not in own), None)
    if theirs is None:
        return "", ""
    return theirs["from_addr"].strip().lower(), (theirs["from_name"] or "").strip()


def _kept_folder_of(ctx: Context, sender: str) -> str | None:
    """The folder kept from the AI that the sender's rule already files into, if one does."""
    for rule in rules.load_rules(ctx.config.home):
        if sorting._about(rule, {sender}) and rule.actions.category:
            found = folder_tree.find(ctx.bus.db, rule.actions.category)
            if found is not None and not found["ai_reads"]:
                return str(found["name"])
    return None


def _folder_for(ctx: Context, sender: str, name: str) -> str:
    """The sender's own kept folder, or a new one named after it, unique in the tree."""
    kept = _kept_folder_of(ctx, sender)
    if kept:
        return kept
    base = name or sender.partition("@")[2].split(".")[0].capitalize() or sender
    return folder_tree.free_name(ctx.bus.db, base)


def preview(ctx: Context, thread: int) -> HideFromAiPreview:
    sender, name = _sender(ctx, thread)
    account = accounts.current_account(ctx.config)
    db = ctx.bus.db
    conversation = db.fetch_all(
        "SELECT COUNT(DISTINCT message_id) AS n FROM messages WHERE thread_id = ?", (thread,)
    )[0]["n"]
    if not sender:
        return HideFromAiPreview(conversation_emails=conversation, folder=ALONE)
    emails = db.fetch_all(
        f"SELECT COUNT(DISTINCT message_id) AS n {FROM_SENDER}",  # noqa: S608
        (account, sender),
    )[0]["n"]
    return HideFromAiPreview(
        sender=sender,
        sender_name=name or sender,
        sender_emails=emails,
        conversation_emails=conversation,
        folder=_folder_for(ctx, sender, name),
    )


def hide(ctx: Context, command: HideFromAi) -> HiddenFromAi:
    sender, name = _sender(ctx, command.thread)
    scope = command.scope if sender else "conversation"
    account = accounts.current_account(ctx.config)
    db = ctx.bus.db
    if scope == "sender":
        threads = [
            int(row["thread_id"])
            for row in db.fetch_all(
                f"SELECT DISTINCT thread_id {FROM_SENDER}",  # noqa: S608
                (account, sender),
            )
        ]
        messages = db.fetch_all(
            f"SELECT id, rule, why {FROM_SENDER}",  # noqa: S608
            (account, sender),
        )
    else:
        threads = [command.thread]
        messages = db.fetch_all(
            "SELECT id, rule, why FROM messages WHERE thread_id = ?", (command.thread,)
        )
    threads = sorted({*threads, command.thread})
    marks = ",".join("?" * len(threads))
    before = db.fetch_all(
        "SELECT id, category, category_source, why, latest_rule FROM threads"  # noqa: S608
        f" WHERE id IN ({marks})",
        threads,
    )
    folder = _folder_for(ctx, sender, name) if scope == "sender" else ALONE
    made = folder_tree.find(db, folder) is None
    state: dict[str, Any] = {
        "scope": scope,
        "sender": sender,
        "folder": folder,
        "made": made,
        "rules": [
            rule.model_dump(mode="json")
            for rule in rules.load_rules(ctx.config.home)
            if sender and sorting._about(rule, {sender})
        ]
        if scope == "sender"
        else [],
        "threads": [dict(row) for row in before],
        "messages": [dict(row) for row in messages],
    }
    if scope == "sender":
        sorting.move_sender(ctx, sender, reads=False, folder=folder, refile=True)
    with ctx.bus.unit_of_work() as work:
        # What the person filed by hand stays put elsewhere, but the one they hid goes too.
        work.tx.execute(
            "UPDATE threads SET category = ?, category_source = ?, why = ? WHERE id = ?",
            (folder, "rule" if scope == "sender" else "user", WHY, command.thread),
        )
        undo = int(
            work.tx.execute(
                "INSERT INTO mail_hidden_undo (created, state) VALUES (?, ?)",
                (_now(), json.dumps(state)),
            ).lastrowid
            or 0
        )
        work.emit("mail.changed", {"reason": "categories"}, source="mail", trace_id=ctx.trace_id)
        work.emit("categories.changed", {}, source="mail", trace_id=ctx.trace_id)
    return HiddenFromAi(undo=undo, folder=folder, emails=len({m["id"] for m in messages}))


def undo(ctx: Context, identifier: int) -> None:
    """Everything as it was: the sender's rules, each email's rule, each conversation's folder,
    and the folder hiding made, if nothing else is in it now."""
    db = ctx.bus.db
    rows = db.fetch_all("SELECT state FROM mail_hidden_undo WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("hide.undo_gone", "That can't be undone any more.", 404)
    state = json.loads(rows[0]["state"])
    sender = state["sender"]
    if state["scope"] == "sender":
        restored = RuleSet.model_validate({"rules": state["rules"]}).rules

        def put_back(current: list[MailRule]) -> list[MailRule]:
            return [*(r for r in current if not sorting._about(r, {sender})), *restored]

        rules.change_rules(ctx.config.home, put_back)
    account = accounts.current_account(ctx.config)
    with ctx.bus.unit_of_work() as work:
        if state["scope"] == "sender":
            # Mail that came from the sender while it was hidden goes back with the rest.
            known = [message["id"] for message in state["messages"]]
            marks = ",".join("?" * len(known)) or "NULL"
            work.tx.execute(
                "UPDATE messages SET rule = NULL, why = NULL"  # noqa: S608
                " WHERE account = ? AND LOWER(from_addr) = ?"
                f" AND id NOT IN ({marks})",
                (account, sender, *known),
            )
            work.tx.execute(
                "UPDATE threads SET category = NULL, category_source = NULL, why = NULL,"  # noqa: S608
                " latest_rule = NULL WHERE category = ? AND id IN (SELECT m.thread_id"
                " FROM messages m WHERE m.account = ? AND LOWER(m.from_addr) = ?)",
                (state["folder"], account, sender),
            )
        for message in state["messages"]:
            work.tx.execute(
                "UPDATE messages SET rule = ?, why = ? WHERE id = ?",
                (message["rule"], message["why"], message["id"]),
            )
        for thread in state["threads"]:
            work.tx.execute(
                "UPDATE threads SET category = ?, category_source = ?, why = ?, latest_rule = ?"
                " WHERE id = ?",
                (
                    thread["category"],
                    thread["category_source"],
                    thread["why"],
                    thread["latest_rule"],
                    thread["id"],
                ),
            )
        if (
            state["made"]
            and not work.tx.execute(
                "SELECT 1 FROM threads WHERE category = ? LIMIT 1", (state["folder"],)
            ).fetchone()
        ):
            work.tx.execute("DELETE FROM mail_categories WHERE name = ?", (state["folder"],))
        work.tx.execute("DELETE FROM mail_hidden_undo WHERE id = ?", (identifier,))
        work.emit("mail.changed", {"reason": "categories"}, source="mail", trace_id=ctx.trace_id)
        work.emit("rules.changed", {"count": 1}, source="mail", trace_id=ctx.trace_id)
        work.emit("categories.changed", {}, source="mail", trace_id=ctx.trace_id)
