"""Sorting mail before the AI reads it. The grouping engine suggests where each group goes; the
person settles it once, and what they keep from the AI becomes rules and filed categories.

Automated and Calendar are folders the AI ignores: their categories are filed by rules, left out
of meaning search and never learned from. Mail that names the person still reaches the AI.
"""

import threading
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from nexusai.contracts.mail import (
    ApplyMailSort,
    MailRule,
    MailSort,
    SortEmail,
    SortGroup,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import accounts, grouping, rules, sort_rules, sort_view
from nexusai.modules.mail.parse import SUBJECT_PREFIX, parse_message

log = structlog.get_logger()
MIGRATION = Migration(
    "mail_sorting_001",
    """
CREATE TABLE mail_sorting (
  id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT NOT NULL, updated TEXT NOT NULL);
ALTER TABLE mail_categories ADD COLUMN ai_reads INTEGER NOT NULL DEFAULT 1;
""",
)
# What the page shows is described in sort_view, which the Sort lab shares without the database.
QUIET = {"automated": "Automated", "calendar": "Calendar"}
RULE_PREFIX = sort_rules.PREFIX


@dataclass
class _Job:
    state: str = "preparing"
    done: int = 0
    total: int = 0
    error: str = ""
    found: dict[str, Any] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    # The groups that start as folders of their own: the biggest automated ones.
    own: frozenset[str] = frozenset()
    report: grouping.Report | None = None


_jobs: dict[str, _Job] = {}
_lock = threading.Lock()


def decided(ctx: Context) -> str:
    """ "done" or "skipped" once the person has dealt with it, else ""."""
    rows = ctx.bus.db.fetch_all("SELECT state FROM mail_sorting WHERE id = 1")
    return str(rows[0]["state"]) if rows else ""


def _decide(ctx: Context, state: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO mail_sorting (id, state, updated) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET state = excluded.state, updated = excluded.updated",
            (state, datetime.now(UTC).isoformat()),
        )
        # Learning waits for this, then starts by itself.
        work.emit("mail.sorted", {"state": state}, source="mail", trace_id=ctx.trace_id)


def prepare(ctx: Context) -> None:
    """Groups the stored mail in the background, once, so the page is ready when it's opened."""
    home = str(ctx.config.home)
    with _lock:
        job = _jobs.get(home)
        if decided(ctx) or (job is not None and job.state in {"preparing", "ready"}):
            return
        job = _jobs[home] = _Job()
    threading.Thread(target=_group, args=(ctx, job), daemon=True, name="mail-sorting").start()


def _group(ctx: Context, job: _Job) -> None:
    try:
        account = accounts.current_account(ctx.config)
        rows = ctx.bus.db.fetch_all(
            "SELECT m.id, r.data FROM messages m JOIN message_raw r ON r.message = m.id"
            " WHERE m.account = ? AND m.folder_role NOT IN ('junk', 'trash') ORDER BY m.id",
            (account,),
        )
        job.total = len(rows)
        mail = [(str(row["id"]), zlib.decompress(row["data"])) for row in rows]
        job.done = len(mail)
        report = grouping.group_mailbox(mail)
        raws = dict(mail)
        job.found, job.members = sort_view.describe(report, raws.__getitem__, _covered(ctx, mail))
        automated = [group for group in job.found["groups"] if group["folder"] == "automated"]
        biggest = sorted(automated, key=lambda group: -group["count"])[: sort_view.TOP_CATEGORIES]
        job.own = frozenset(group["id"] for group in biggest)
        job.report = report
        job.state = "ready"
    except Exception as error:
        log.warning("mail_sorting_failed", kind=type(error).__name__)
        job.state, job.error = "failed", f"{type(error).__name__}: {str(error)[:300]}"


def _covered(ctx: Context, mail: list[tuple[str, bytes]]) -> frozenset[str]:
    """Mail the person's own rules and categories already file. Sorting builds on them, so an
    imported archive or a second look never starts over."""
    # Imported here: the mail module imports this one.
    from nexusai.modules.mail.module import rule_engine

    engine = rule_engine(ctx, None)
    decisions = engine.decide([parse_message(raw) for _, raw in mail])
    return frozenset(
        key
        for (key, _), decision in zip(mail, decisions, strict=True)
        if decision.category and decision.rule not in rules.BUILT_IN_RULES
    )


def status(ctx: Context) -> MailSort:
    state = decided(ctx)
    if state:
        return MailSort(state=state)
    job = _jobs.get(str(ctx.config.home))
    if job is None:
        return MailSort(state="none")
    if job.state != "ready":
        return MailSort(state=job.state, done=job.done, total=job.total, error=job.error)
    found = job.found
    groups = [
        SortGroup(
            id=group["id"],
            label=group["label"] or (group["reasons"] or [""])[0],
            folder=group["folder"],
            count=group["count"],
            senders=group["senders"],
            reason=(group["reasons"] or [""])[0],
            names_you=0 if group["mentions_ignored"] else group["mentions"],
            emails=[_email(email) for email in group["emails"]],
            own=group["id"] in job.own,
        )
        for group in found["groups"]
    ] + [
        SortGroup(
            id=f"miss:{missed['sender']}",
            label=missed["label"],
            folder="inbox",
            count=missed["count"],
            senders=[missed["sender"]],
            reason="",
            names_you=sum(email["names_you"] for email in missed["emails"]),
            emails=[_email(email) for email in missed["emails"]],
            unsorted=True,
        )
        for missed in found["missed"]
    ]
    return MailSort(
        state="ready",
        owner_name=found["owner_name"],
        emails=found["total"],
        reach_ai=found["reach_ai"],
        conversations=found["ungrouped"] - sum(m["count"] for m in found["missed"]),
        already_sorted=found.get("already_sorted", 0),
        groups=groups,
    )


def _email(email: dict[str, Any]) -> SortEmail:
    return SortEmail(
        subject=email["subject"],
        sender=email["sender"],
        sender_name=email["from"],
        when=email["when"],
        snippet=email["snippet"],
        names_you=email["names_you"],
    )


def skip(ctx: Context) -> None:
    """Leaves everything as it is, so the AI reads it all, as before sorting existed."""
    _decide(ctx, "skipped")
    _jobs.pop(str(ctx.config.home), None)


def apply(ctx: Context, command: ApplyMailSort) -> int:
    """Files every category the person kept from the AI under its folder, with a rule for what's
    to come, and returns how many conversations moved. The Inbox stays the AI's to sort."""
    job = _jobs.get(str(ctx.config.home))
    if job is None or job.state != "ready" or job.report is None:
        raise CommandError("mail.sort_not_ready", "The mail isn't grouped yet.", 409)
    report = job.report
    chosen = {choice.id: choice for choice in command.choices if choice.id in job.members}

    def final(identifier: str) -> str:
        seen: set[str] = set()
        while (step := chosen.get(identifier)) and step.merged_into and identifier not in seen:
            seen.add(identifier)
            identifier = step.merged_into
        return identifier

    def folder_of(identifier: str) -> str:
        choice = chosen.get(identifier)
        if choice is not None:
            return choice.folder
        group = next((g for g in job.found["groups"] if g["id"] == identifier), None)
        return str(group["folder"]) if group else "inbox"

    gathered: dict[str, list[str]] = defaultdict(list)
    for identifier, keys in job.members.items():
        gathered[final(identifier)].extend(keys)
    raws = {
        str(row["id"]): row
        for row in ctx.bus.db.fetch_all(
            "SELECT id, thread_id, LOWER(from_addr) AS sender, subject, EXISTS (SELECT 1 FROM"
            " message_refs f WHERE f.message = messages.id) AS answers FROM messages"
            " WHERE account = ?",
            (accounts.current_account(ctx.config),),
        )
    }
    mailbox = [
        sort_rules.Seen(
            row["sender"],
            row["subject"] or "",
            bool(row["answers"] or SUBJECT_PREFIX.match(row["subject"] or "")),
        )
        for row in raws.values()
    ]
    ignored = {group.id for group in report.groups if group.mentions_ignored}
    named = {
        key
        for key, decision in report.decisions.items()
        if decision.named and decision.group not in ignored
    }
    # Which kept-out category each sender's mail went to, to know whose rules can cover a sender.
    home_of: dict[str, set[str]] = defaultdict(set)
    for identifier, keys in gathered.items():
        for key in keys:
            if key in raws:
                home_of[raws[key]["sender"]].add(identifier)
    new_rules: list[MailRule] = []
    moved = 0
    now = datetime.now(UTC).isoformat()
    with ctx.bus.unit_of_work() as work:
        for identifier, keys in gathered.items():
            place = folder_of(identifier)
            if place not in QUIET or not keys:
                continue
            choice = chosen.get(identifier)
            label = (choice.name if choice else "").strip() or _label(job.found, identifier)
            # The biggest tools, and any the person named, get a folder of their own; the rest
            # and all calendar mail go straight into the parent.
            own = place == "automated" and (identifier in job.own or bool(choice and choice.name))
            name = f"{QUIET[place]}/{label.replace('/', ' ')}"[:64] if own else QUIET[place]
            senders = sorted({raws[key]["sender"] for key in keys if key in raws})
            for parent in dict.fromkeys((QUIET[place], name)):
                work.tx.execute(
                    "INSERT INTO mail_categories (name, source, in_priority, proposed, why, sender,"
                    " created, mode, description, ai_reads) VALUES (?, 'user', 0, 0, ?, ?, ?,"
                    " 'exact', ?, 0) ON CONFLICT (name) DO UPDATE SET mode = 'exact', ai_reads = 0,"
                    " sender = COALESCE(mail_categories.sender, excluded.sender)",
                    (
                        parent,
                        "Sorted before the AI read it",
                        senders[0] if parent == name and senders else None,
                        now,
                        parent,
                    ),
                )
            # A sender whose mail all went here gets a rule for what's to come, and so does the
            # tag that marks it. One split across categories is filed as it is now, since its
            # pattern isn't a rule yet.
            new_rules += sort_rules.rules_for(
                name,
                [sender for sender in senders if home_of[sender] == {identifier}],
                mailbox,
                mentions=[report.owner, report.owner_name],
                owner=report.owner,
            )
            # A conversation with mail that names the person stays where the AI reads it.
            threads = {raws[key]["thread_id"] for key in keys if key in raws}
            spoken = {raws[key]["thread_id"] for key in named if key in raws}
            threads -= spoken
            quiet = [key for key in keys if key in raws and raws[key]["thread_id"] in threads]
            for start in range(0, len(threads), 500):
                chunk = sorted(threads)[start : start + 500]
                marks = ",".join("?" * len(chunk))
                moved += work.tx.execute(
                    f"UPDATE threads SET category = ?, category_source = 'rule', why = ? WHERE id"  # noqa: S608
                    f" IN ({marks}) AND COALESCE(category_source, '') != 'user'",
                    (name, f"Sorted into “{name}”", *chunk),
                ).rowcount
            for start in range(0, len(quiet), 500):
                chunk = quiet[start : start + 500]
                marks = ",".join("?" * len(chunk))
                work.tx.execute(
                    f"UPDATE messages SET rule = ?, why = ? WHERE id IN ({marks})",  # noqa: S608
                    (f"{RULE_PREFIX}{name}", f"Sorted into “{name}”", *(int(k) for k in chunk)),
                )
        work.tx.execute(
            "INSERT INTO mail_sorting (id, state, updated) VALUES (1, 'done', ?)"
            " ON CONFLICT (id) DO UPDATE SET state = 'done', updated = excluded.updated",
            (now,),
        )
        work.emit("rules.changed", {"count": len(new_rules)}, source="mail", trace_id=ctx.trace_id)
        work.emit(
            "mail.changed",
            {"threads": moved, "reason": "categories"},
            source="mail",
            trace_id=ctx.trace_id,
        )
        work.emit("mail.sorted", {"state": "done"}, source="mail", trace_id=ctx.trace_id)
    if new_rules:
        made = {rule.name for rule in new_rules}
        rules.change_rules(
            ctx.config.home,
            lambda existing: [*(rule for rule in existing if rule.name not in made), *new_rules],
        )
    _jobs.pop(str(ctx.config.home), None)
    return moved


def _label(found: dict[str, Any], identifier: str) -> str:
    for group in found.get("groups", []):
        if group["id"] == identifier:
            return str(group["label"] or "Sorted")
    for missed in found.get("missed", []):
        if f"miss:{missed['sender']}" == identifier:
            return str(missed["label"])
    return "Sorted"
