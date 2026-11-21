"""Sorting mail before the AI reads it, one sender at a time, the same way the Sort lab does.

Every sender gets a score for how automated it looks and starts on the side the AI reads or the
side it ignores; the person moves any across. Ignored senders are filed under Automated, the
biggest in categories of their own, and get rules for what's to come. Invitations go to Calendar.
Both folders are kept from the AI, left out of meaning search and never learned from. Mail that
names the person, or that a person answered, still reaches the AI.
"""

import threading
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from nexusai.contracts.mail import ApplyMailSort, MailRule, MailSort, SortEmail, SortSender
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
AUTOMATED = "Automated"
CALENDAR = "Calendar"
RULE_PREFIX = sort_rules.PREFIX


@dataclass
class _Job:
    state: str = "preparing"
    done: int = 0
    total: int = 0
    error: str = ""
    found: dict[str, Any] = field(default_factory=dict)
    report: grouping.SenderReport | None = None
    # Mail the person's own rules already file, left out of the list.
    covered: int = 0
    # The newest email scored, so mail that came after it gets scored too.
    newest: int = 0


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
    """Scores the stored mail in the background, once, so the page is ready when it's opened."""
    home = str(ctx.config.home)
    # Scoring half a mailbox would put senders on the wrong side, so it waits for the download.
    downloading = ctx.bus.db.fetch_all(
        "SELECT 1 FROM mail_sync_settings WHERE account = ? AND history_finished IS NULL",
        (accounts.current_account(ctx.config),),
    )
    newest = int(ctx.bus.db.fetch_all("SELECT COALESCE(MAX(id), 0) AS n FROM messages")[0]["n"])
    with _lock:
        job = _jobs.get(home)
        busy = job is not None and job.state == "preparing"
        # A score from before newer mail came in is scored again, so nothing is left off the list.
        current = job is not None and job.state == "ready" and job.newest >= newest
        if downloading or decided(ctx) or busy or current:
            return
        job = _jobs[home] = _Job()
    _announce(ctx, job.state)
    threading.Thread(target=_score, args=(ctx, job), daemon=True, name="mail-sorting").start()


def _announce(ctx: Context, state: str) -> None:
    """Tells the page the scoring started, ended or failed, so it never has to keep asking."""
    with ctx.bus.unit_of_work() as work:
        work.emit("mail.sortChanged", {"state": state}, source="mail", trace_id=ctx.trace_id)


def _score(ctx: Context, job: _Job) -> None:
    try:
        account = accounts.current_account(ctx.config)
        rows = ctx.bus.db.fetch_all(
            "SELECT m.id, r.data FROM messages m JOIN message_raw r ON r.message = m.id"
            " WHERE m.account = ? AND m.folder_role NOT IN ('junk', 'trash') ORDER BY m.id",
            (account,),
        )
        job.total = len(rows)
        job.newest = max((int(row["id"]) for row in rows), default=0)
        mail = [(str(row["id"]), zlib.decompress(row["data"])) for row in rows]
        covered = _covered(ctx, mail)
        mail = [(key, raw) for key, raw in mail if key not in covered]
        job.done = job.total
        report = grouping.score_senders(mail)
        raws = dict(mail)
        job.found = sort_view.describe_senders(report, raws.__getitem__)
        job.report, job.covered = report, len(covered)
        job.state = "ready"
    except Exception as error:
        log.warning("mail_sorting_failed", kind=type(error).__name__)
        job.state, job.error = "failed", f"{type(error).__name__}: {str(error)[:300]}"
    _announce(ctx, job.state)


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
    return MailSort(
        state="ready",
        owner_name=found["owner_name"],
        emails=found["total"],
        reach_ai=found["reach_ai"],
        calendar=found["calendar"],
        already_sorted=job.covered,
        senders=[
            SortSender(
                **{key: row[key] for key in SortSender.model_fields if key != "emails"},
                emails=[_email(email) for email in row["emails"]],
            )
            for row in found["senders"]
        ],
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


def plan(found: dict[str, Any], command: ApplyMailSort) -> dict[str, list[str]]:
    """Which ignored senders go into which folder: a category of their own under Automated, or
    Automated itself. Senders given the same name share a category."""
    chosen = {choice.sender: choice for choice in command.senders}
    folders: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for row in found["senders"]:
        choice = chosen.get(row["sender"])
        if (choice.side if choice else row["side"]) != "ignores":
            continue
        own = choice.own if choice else row["own"]
        label = ((choice.name.strip() if choice else "") or row["label"] or "Sorted").replace(
            "/", " "
        )
        if own:
            # The first spelling of a name is the one the folder keeps.
            label = names.setdefault(label.casefold(), label)
        folder = f"{AUTOMATED}/{label}"[:64] if own else AUTOMATED
        folders.setdefault(folder, []).append(row["sender"])
    return folders


def apply(ctx: Context, command: ApplyMailSort) -> int:
    """Files every sender the person kept from the AI, with a rule for what's to come, and
    returns how many conversations moved. What the AI reads stays in the Inbox."""
    job = _jobs.get(str(ctx.config.home))
    if job is None or job.state != "ready" or job.report is None:
        raise CommandError("mail.sort_not_ready", "The mail isn't scored yet.", 409)
    report = job.report
    by_sender = {row.sender: row for row in report.senders}
    folders = plan(job.found, command)
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
    # Mail that names the person, or that a person answered, keeps its conversation with the AI.
    ignored = {sender for senders in folders.values() for sender in senders}
    spoken = {
        raws[key]["thread_id"]
        for sender in ignored
        for key in by_sender[sender].through
        if key in raws
    }
    filing = [(name, by_sender[s].members) for name, senders in folders.items() for s in senders]
    filing += [(CALENDAR, report.calendar)] if report.calendar else []
    new_rules: list[MailRule] = []
    moved = 0
    now = datetime.now(UTC).isoformat()
    with ctx.bus.unit_of_work() as work:
        for name in dict.fromkeys(name for name, _ in filing):
            for folder in dict.fromkeys((name.partition("/")[0], name)):
                senders = folders.get(name, [])
                work.tx.execute(
                    "INSERT INTO mail_categories (name, source, in_priority, proposed, why, sender,"
                    " created, mode, description, ai_reads) VALUES (?, 'user', 0, 0, ?, ?, ?,"
                    " 'exact', ?, 0) ON CONFLICT (name) DO UPDATE SET mode = 'exact', ai_reads = 0,"
                    " sender = COALESCE(mail_categories.sender, excluded.sender)",
                    (
                        folder,
                        "Sorted before the AI read it",
                        senders[0] if folder == name and senders and folder != AUTOMATED else None,
                        now,
                        folder,
                    ),
                )
        for name, senders in folders.items():
            new_rules += sort_rules.rules_for(
                name,
                senders,
                mailbox,
                mentions=[report.owner, report.owner_name],
                owner=report.owner,
            )
        for name, keys in filing:
            threads = {raws[key]["thread_id"] for key in keys if key in raws} - spoken
            quiet = [key for key in keys if key in raws and raws[key]["thread_id"] in threads]
            ordered = sorted(threads)
            for start in range(0, len(ordered), 500):
                chunk = ordered[start : start + 500]
                marks = ",".join("?" * len(chunk))
                moved += work.tx.execute(
                    f"UPDATE threads SET category = ?, category_source = 'rule', why = ? WHERE id"  # noqa: S608
                    f" IN ({marks}) AND COALESCE(category_source, '') != 'user'",
                    (name, f"Sorted into “{name}”", *chunk),
                ).rowcount
            for start in range(0, len(quiet), 500):
                part = quiet[start : start + 500]
                marks = ",".join("?" * len(part))
                work.tx.execute(
                    f"UPDATE messages SET rule = ?, why = ? WHERE id IN ({marks})",  # noqa: S608
                    (f"{RULE_PREFIX}{name}", f"Sorted into “{name}”", *(int(k) for k in part)),
                )
            # The Inbox goes by the newest email's rule. The thread was filed above, before its
            # emails had one, so it stayed in the Inbox though the AI ignores its folder.
            for start in range(0, len(ordered), 500):
                chunk = ordered[start : start + 500]
                marks = ",".join("?" * len(chunk))
                work.tx.execute(
                    f"UPDATE threads SET latest_rule = (SELECT rule FROM messages m WHERE"  # noqa: S608
                    f" m.thread_id = threads.id ORDER BY m.date DESC, m.id DESC LIMIT 1)"
                    f" WHERE id IN ({marks})",
                    chunk,
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
