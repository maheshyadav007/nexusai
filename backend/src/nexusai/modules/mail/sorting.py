"""Sorting mail before the AI reads it, one sender at a time, the same way the Sort lab does.

Every sender gets a score for how automated it looks and starts on the side the AI reads or the
side it ignores; the person moves any across. Ignored senders are filed in Kept from the AI:
the biggest in folders of their own, the rest in Automated, its catch-all, with rules for what's
to come. Invitations go to Calendar.
Both folders are kept from the AI, left out of meaning search and never learned from: whatever
an email says, the AI never sees what its folder keeps away.
"""

import threading
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from nexusai.contracts.mail import (
    ApplyMailSort,
    MailRule,
    MailSort,
    RuleActions,
    RuleCondition,
    SortEmail,
    SortSender,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import accounts, grouping, rules, sort_rules, sort_view
from nexusai.modules.mail import folders as folder_tree
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
    # Opened again after sorting, rather than for the first time.
    again: bool = False
    # Senders a rule already files, as (folder, kept from the AI). They start where it puts them.
    current: dict[str, tuple[str, bool]] = field(default_factory=dict)
    # The rules it was scored against; a change to them means the page would be out of date.
    rules: str = ""


_jobs: dict[str, _Job] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def decided(ctx: Context) -> str:
    """ "done" or "skipped" once the person has dealt with it, else ""."""
    rows = ctx.bus.db.fetch_all("SELECT state FROM mail_sorting WHERE id = 1")
    return str(rows[0]["state"]) if rows else ""


def record_past_sorting(ctx: Context) -> bool:
    """A mailbox already sorted sender by sender, before sorting saved that it was, counts as
    sorted, so the page opens to change what's sorted rather than to sort or skip. Only once
    learning has started, so this never starts it."""
    if decided(ctx):
        return False
    learning = ctx.bus.db.fetch_all(
        "SELECT value FROM agent_defaults WHERE key = 'mail_learning' AND value != ''"
    )
    by_sender = any(
        rule.enabled
        and rule.actions.category
        and any(
            condition.field in {"sender", "sender_exact"} and "@" in condition.value
            for condition in rule.conditions
        )
        for rule in rules.load_rules(ctx.config.home)
    )
    if not (learning and by_sender):
        return False
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO mail_sorting (id, state, updated) VALUES (1, 'done', ?)",
            (_now(),),
        )
    return True


def _decide(ctx: Context, state: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO mail_sorting (id, state, updated) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET state = excluded.state, updated = excluded.updated",
            (state, datetime.now(UTC).isoformat()),
        )
        # Learning waits for this, then starts by itself.
        work.emit("mail.sorted", {"state": state}, source="mail", trace_id=ctx.trace_id)


def _rules_now(ctx: Context) -> str:
    return "\n".join(rule.model_dump_json() for rule in rules.load_rules(ctx.config.home))


def prepare(ctx: Context, again: bool = False) -> None:
    """Scores the stored mail in the background, once, so the page is ready when it's opened.
    Opened again after sorting, it looks again whenever mail or rules changed since."""
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
        # A score from before newer mail came in, or before the rules changed, is scored again,
        # so the page never shows a sender where it no longer is.
        reviewing = bool(again and decided(ctx))
        current = (
            job is not None
            and job.state == "ready"
            and job.newest >= newest
            and job.again == reviewing
            and job.rules == _rules_now(ctx)
        )
        if downloading or (decided(ctx) and not reviewing) or busy or current:
            return
        job = _jobs[home] = _Job(again=reviewing, rules=_rules_now(ctx))
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
        # Every sender is on the page, the first time and every time after; one a rule already
        # files starts where its rule puts it, so the page shows what's true now.
        covered, job.current = _covered(ctx, mail)
        job.done = job.total
        report = grouping.score_senders(mail)
        raws = dict(mail)
        job.found = sort_view.describe_senders(report, raws.__getitem__)
        for row in job.found["senders"]:
            if row["sender"] in job.current:
                folder, kept = job.current[row["sender"]]
                row.update(folder=folder, side="ignores" if kept else "reads", own=False)
        job.report, job.covered = report, len(covered)
        job.state = "ready"
    except Exception as error:
        log.warning("mail_sorting_failed", kind=type(error).__name__)
        job.state, job.error = "failed", f"{type(error).__name__}: {str(error)[:300]}"
    _announce(ctx, job.state)


def _covered(
    ctx: Context, mail: list[tuple[str, bytes]]
) -> tuple[frozenset[str], dict[str, tuple[str, bool]]]:
    """Mail the person's own rules and categories already file, and for each sender the folder
    its rule files it into and whether that keeps it from the AI. Sorting builds on them, so an
    imported archive or a second look never starts over."""
    # Imported here: the mail module imports this one.
    from nexusai.modules.mail.module import rule_engine

    engine = rule_engine(ctx, None)
    parsed = [parse_message(raw) for _, raw in mail]
    decisions = engine.decide(parsed)
    covered: set[str] = set()
    seen: dict[str, Counter[tuple[str, bool]]] = defaultdict(Counter)
    for (key, _), message, decision in zip(mail, parsed, decisions, strict=True):
        if decision.match and decision.category and decision.rule not in rules.BUILT_IN_RULES:
            covered.add(key)
            filing = (decision.category, decision.match.actions.skip_agent)
            seen[message.from_addr.lower()][filing] += 1
        elif decision.rule and decision.rule.startswith(sort_rules.READS_PREFIX):
            # Let through on purpose: on the side the AI reads, in no folder.
            seen[message.from_addr.lower()][("", False)] += 1
    # A sender's most usual filing is where it stands.
    current = {sender: counts.most_common(1)[0][0] for sender, counts in seen.items()}
    return frozenset(covered), current


def status(ctx: Context) -> MailSort:
    state = decided(ctx)
    view = _view(_jobs.get(str(ctx.config.home)))
    if not state:
        return view
    # Sorted or skipped already: the page can be opened again, from a fresh look at the mail.
    review = view.state if view.state in {"none", "preparing", "ready", "failed"} else "none"
    return view.model_copy(update={"state": state, "review": review})


def _view(job: "_Job | None") -> MailSort:
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
    )


def skip(ctx: Context) -> None:
    """Leaves everything as it is, so the AI reads it all, as before sorting existed."""
    _decide(ctx, "skipped")
    _jobs.pop(str(ctx.config.home), None)


def plan(
    found: dict[str, Any], command: ApplyMailSort, taken: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """Which ignored senders go into which folder: one of their own at the top of Kept from the
    AI, or Automated, its catch-all. Senders given the same name share a folder. `taken` maps a
    name the AI's side already uses to the free one a kept folder gets instead."""
    taken = taken or {}
    chosen = {choice.sender: choice for choice in command.senders}
    folders: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for row in found["senders"]:
        choice = chosen.get(row["sender"])
        if (choice.side if choice else row["side"]) != "ignores":
            continue
        own = choice.own if choice else row["own"]
        label = " ".join(
            ((choice.name.strip() if choice else "") or row["label"] or "Sorted")
            .replace("/", " ")
            .split()
        )[:64]
        if own:
            # The first spelling of a name is the one the folder keeps, and one the AI reads
            # already has gets another: a folder lives on one side.
            label = names.setdefault(label.casefold(), taken.get(label.casefold(), label))
        folder = label if own else AUTOMATED
        folders.setdefault(folder, []).append(row["sender"])
    return folders


def _taken_by_reads(ctx: Context, found: dict[str, Any], command: ApplyMailSort) -> dict[str, str]:
    """Names the person's folders on the AI's side already have, each with a free one for a
    folder of kept senders that would be called the same."""
    reads = {
        row["name"].casefold(): row["name"]
        for row in ctx.bus.db.fetch_all(
            "SELECT name FROM mail_categories WHERE ai_reads = 1 AND proposed = 0"
        )
    }
    if not reads:
        return {}
    chosen = {choice.sender: choice for choice in command.senders}
    taken: dict[str, str] = {}
    for row in found["senders"]:
        choice = chosen.get(row["sender"])
        name = ((choice.name.strip() if choice else "") or row["label"] or "").casefold()
        if name in reads and name not in taken:
            taken[name] = folder_tree.suggest_kept_name(ctx.bus.db, reads[name], [row["sender"]])
    return taken


def _about(rule: MailRule, senders: set[str]) -> bool:
    return any(
        c.field in {"sender", "sender_exact"} and (c.value or "").lower() in senders
        for c in rule.conditions
    )


def apply(ctx: Context, command: ApplyMailSort) -> int:
    """Files every sender the person kept from the AI, with a rule for what's to come, and
    returns how many conversations moved. What the AI reads stays in the Inbox."""
    job = _jobs.get(str(ctx.config.home))
    if job is None or job.state != "ready" or job.report is None:
        raise CommandError("mail.sort_not_ready", "The mail isn't scored yet.", 409)
    report = job.report
    by_sender = {row.sender: row for row in report.senders}
    found = job.found
    # A sender a rule already files only changes sides, in its rule; the rest are sorted as
    # they always were. Nothing the person didn't move changes.
    flips: dict[str, bool] = {}
    # Put in an exact folder, or the Inbox: each goes there on its own, mail and all.
    placed = {c.sender: c for c in command.senders if c.folder is not None}
    command = ApplyMailSort(senders=[c for c in command.senders if c.folder is None])
    found = {**found, "senders": [r for r in found["senders"] if r["sender"] not in placed]}
    # Let through by an "AI reads" rule and moved back: that rule goes, and it's sorted afresh.
    unlet: set[str] = set()
    if job.current:
        chosen = {choice.sender: choice for choice in command.senders}
        for sender, (folder, kept) in job.current.items():
            choice = chosen.get(sender)
            if choice is None or sender in placed or (choice.side == "ignores") == kept:
                continue
            if folder:
                flips[sender] = choice.side == "ignores"
            else:
                unlet.add(sender)
        settled = {s for s in job.current if s not in unlet}
        command = ApplyMailSort(senders=[c for c in command.senders if c.sender not in settled])
        found = {**found, "senders": [r for r in found["senders"] if r["sender"] not in settled]}
    folders = plan(found, command, _taken_by_reads(ctx, found, command))
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
    filing = [(name, by_sender[s].members) for name, senders in folders.items() for s in senders]
    filing += [(CALENDAR, report.calendar)] if report.calendar else []
    new_rules: list[MailRule] = []
    moved = 0
    now = datetime.now(UTC).isoformat()
    with ctx.bus.unit_of_work() as work:
        # Kept from the AI's catch-all is always there, even with nothing in it yet.
        for name in dict.fromkeys([AUTOMATED, *(name for name, _ in filing)]):
            senders = folders.get(name, [])
            work.tx.execute(
                "INSERT INTO mail_categories (name, source, in_priority, proposed, why, sender,"
                " created, mode, description, ai_reads) VALUES (?, 'user', 0, 0, ?, ?, ?,"
                " 'exact', ?, 0) ON CONFLICT (name) DO UPDATE SET mode = 'exact', ai_reads = 0,"
                " sender = COALESCE(mail_categories.sender, excluded.sender)",
                (
                    name,
                    "Sorted before the AI read it",
                    senders[0] if senders and name != AUTOMATED else None,
                    now,
                    name,
                ),
            )
        for name, senders in folders.items():
            new_rules += sort_rules.rules_for(
                name,
                senders,
                mailbox,
                owner=report.owner,
            )
        for name, keys in filing:
            threads = {raws[key]["thread_id"] for key in keys if key in raws}
            quiet = [key for key in keys if key in raws]
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
    if unlet:
        rules.change_rules(
            ctx.config.home,
            lambda existing: [
                rule
                for rule in existing
                if not (rule.name.startswith(sort_rules.READS_PREFIX) and _about(rule, unlet))
            ],
        )
    if new_rules:
        made = {rule.name for rule in new_rules}
        # One rule per sender: whatever else matched these senders goes.
        filed = {sender for senders in folders.values() for sender in senders}
        rules.change_rules(
            ctx.config.home,
            lambda existing: [
                *(r for r in existing if r.name not in made and not _about(r, filed)),
                *new_rules,
            ],
        )
    for sender, kept in flips.items():
        move_sender(ctx, sender, reads=not kept, folder=job.current[sender][0])
    for sender, choice in placed.items():
        move_sender(
            ctx,
            sender,
            reads=choice.side == "reads",
            folder=choice.folder or None,
            keep_folder=False,
            refile=True,
        )
    _jobs.pop(str(ctx.config.home), None)
    return moved


def _refile(ctx: Context, tx: Any, sender: str, rule: MailRule) -> None:
    """The sender's mail goes where its new rule files it: its emails carry that rule, and their
    conversations its folder, or the Inbox. What the person filed by hand stays put."""
    account = accounts.current_account(ctx.config)
    tx.execute(
        "UPDATE messages SET rule = ? WHERE account = ? AND LOWER(from_addr) = ?",
        (rule.name, account, sender),
    )
    threads = "SELECT DISTINCT thread_id FROM messages WHERE account = ? AND LOWER(from_addr) = ?"
    folder = rule.actions.category
    tx.execute(
        "UPDATE threads SET category = ?, category_source = 'rule', why = ?"  # noqa: S608
        f" WHERE id IN ({threads}) AND COALESCE(category_source, '') != 'user'",
        (folder, f"Sorted into “{folder}”" if folder else "Sorted into the Inbox", account, sender),
    )
    tx.execute(
        "UPDATE threads SET latest_rule = (SELECT rule FROM messages m WHERE m.thread_id ="  # noqa: S608
        f" threads.id ORDER BY m.date DESC, m.id DESC LIMIT 1) WHERE id IN ({threads})",
        (account, sender),
    )


def move_sender(
    ctx: Context,
    sender: str,
    *,
    reads: bool,
    folder: str | None = None,
    keep_folder: bool = True,
    refile: bool = False,
    strict: bool = True,
) -> str:
    """One sender to the side the AI reads or the side it ignores, the one way every screen
    and agent does it. A sender has one rule, so whatever rules it had are replaced:

    - to the AI, into a folder the AI reads: its rule files it there and lets the AI read it;
    - to the AI, from a folder the AI skips as a whole, or from none: a rule lets it through;
    - away from the AI: its rule files it in `folder`, its old folder, or Automated.

    A folder lives on one side, so a folder of the other side isn't kept: the sender goes to the
    Inbox, or to Automated. `strict=False` allows it, only to put a split back.

    Mail already filed stays where it is, unless `refile`, when it moves with the sender; the
    rule decides what's to come. Says what it did."""
    sender = sender.strip().lower()
    if "@" not in sender:
        raise CommandError("mail.sender", "That isn't an email address.", 422)
    existing = rules.load_rules(ctx.config.home)
    mine = [rule for rule in existing if _about(rule, {sender})]
    was = next((rule.actions.category for rule in mine if rule.actions.category), None)
    skipped = {
        row["name"]
        for row in ctx.bus.db.fetch_all("SELECT name FROM mail_categories WHERE ai_reads = 0")
    }
    target = (folder or (was if keep_folder else "") or "").strip()[:64]
    known = folder_tree.find(ctx.bus.db, target) if target else None
    if known is not None:
        target = known["name"]
    # A folder lives on one side, so a sender moved across leaves a folder of the other side:
    # to the Inbox itself, or to Automated. Only putting a split back undoes that.
    if strict and known is not None and bool(known["ai_reads"]) != reads:
        target = ""
    if reads:
        if target and (target not in skipped or not strict):
            rule = MailRule(
                name=f"{target}: {sender}"[:120],
                conditions=[RuleCondition(field="sender_exact", value=sender)],
                actions=RuleActions(category=target),
            )
            with ctx.bus.unit_of_work() as work:
                # A new folder for it, one the AI reads.
                if known is None:
                    target = folder_tree.check_name(work.tx, target)
                    rule = rule.model_copy(
                        update={
                            "name": f"{target}: {sender}"[:120],
                            "actions": RuleActions(category=target),
                        }
                    )
                work.tx.execute(
                    "INSERT OR IGNORE INTO mail_categories (name, source, in_priority, proposed,"
                    " why, created, mode, description, ai_reads)"
                    " VALUES (?, 'user', 0, 0, ?, ?, 'exact', ?, 1)",
                    (target, "Made on the Sort page", _now(), target),
                )
            said = f"{sender}: filed in {target}, and the AI reads it"
        else:
            rule = MailRule(
                name=f"{sort_rules.READS_PREFIX}{sender}"[:120],
                conditions=[RuleCondition(field="sender_exact", value=sender)],
                actions=RuleActions(),
            )
            said = f"{sender}: stays in the Inbox, and the AI reads it"
    else:
        target = target or AUTOMATED
        rule = MailRule(
            name=f"{sort_rules.PREFIX}{target}: {sender}"[:120],
            conditions=[RuleCondition(field="sender_exact", value=sender)],
            actions=RuleActions(category=target, skip_agent=True),
        )
        with ctx.bus.unit_of_work() as work:
            # A new folder for it, at the top of Kept from the AI.
            if known is None and target != AUTOMATED:
                target = folder_tree.check_name(work.tx, target)
            work.tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, in_priority, proposed, why,"
                " created, mode, description, ai_reads)"
                " VALUES (?, 'user', 0, 0, ?, ?, 'exact', ?, 0)",
                (target, "Sorted before the AI read it", _now(), target),
            )
        said = f"{sender}: filed in {target}, kept from the AI"
    rules.change_rules(
        ctx.config.home,
        lambda current: [*(r for r in current if not _about(r, {sender})), rule],
    )
    with ctx.bus.unit_of_work() as work:
        # A folder named after its first sender makes a rule of its own for it; this one
        # replaces it, so the sender still has exactly one.
        work.tx.execute(
            "UPDATE mail_categories SET sender = NULL WHERE LOWER(sender) = ?", (sender,)
        )
        if refile:
            _refile(ctx, work.tx, sender, rule)
            work.emit(
                "mail.changed", {"reason": "categories"}, source="mail", trace_id=ctx.trace_id
            )
        work.emit("rules.changed", {"count": 1}, source="mail", trace_id=ctx.trace_id)
        work.emit("categories.changed", {}, source="mail", trace_id=ctx.trace_id)
    _jobs.pop(str(ctx.config.home), None)
    return said
