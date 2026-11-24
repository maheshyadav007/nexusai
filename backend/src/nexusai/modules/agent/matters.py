"""Matters: one record for each real thing going on, however many emails it takes.

A matter is a set of conversations plus a timeline of what happened to them. Everything else
(its state, due date, people, open work) is read from the conversations each time, so it can
never drift from them. Linking is done by code: a shared id like ECO-1104 or change 88213, or
the same sender writing about the same subject. See docs/MATTERS_PLAN.md.
"""

import json
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from nexusai.contracts.agent import (
    MatterChange,
    MatterDetail,
    MatterDue,
    MatterEvents,
    MatterFile,
    MatterItem,
    MatterLane,
    MatterLinkRow,
    MatterMark,
    MatterMarkKind,
    MatterRelated,
    MatterRow,
    MattersBrief,
    MattersWeek,
    MatterThread,
    MatterWork,
)
from nexusai.kernel import textmatch
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import conversations, links, signals
from nexusai.modules.agent.kinds import address, parse, ref
from nexusai.modules.mail import accounts
from nexusai.modules.mail.parse import normalize_subject
from nexusai.modules.mail.source import thread_source
from nexusai.modules.mail.store import hidden_from_ai
from nexusai.modules.planner import module as planner

MIGRATION = Migration(
    "agent_matters_001",
    """
CREATE TABLE matters (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, title TEXT NOT NULL,
  created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE matter_threads (
  thread INTEGER PRIMARY KEY, matter INTEGER NOT NULL, how TEXT NOT NULL, why TEXT NOT NULL,
  linked TEXT NOT NULL);
CREATE INDEX matter_threads_matter ON matter_threads (matter);
CREATE TABLE matter_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, matter INTEGER NOT NULL, time TEXT NOT NULL,
  kind TEXT NOT NULL, thread INTEGER, message INTEGER, by TEXT NOT NULL, text TEXT NOT NULL,
  why TEXT NOT NULL DEFAULT '', undo TEXT);
CREATE INDEX matter_events_matter ON matter_events (matter, time);
CREATE INDEX matter_events_time ON matter_events (time);
CREATE UNIQUE INDEX matter_events_message ON matter_events (matter, message, kind)
  WHERE message IS NOT NULL;
""",
)
# What the person chose to leave open when something else in the matter finished, so it isn't
# offered again for the same thing.
KEPT_MIGRATION = Migration(
    "agent_matters_kept_001",
    "CREATE TABLE matter_kept (trigger TEXT NOT NULL, item TEXT NOT NULL, PRIMARY KEY (trigger, item));",
)
BACKFILLED = "matters_backfilled"
# Changes on a matter's timeline come a page at a time, oldest at the top.
PAGE = 40
# What the AI is shown: a few matters, a few open items each, never further than one step.
CONTEXT_MATTERS = 3
CONTEXT_ITEMS = 5
CONTEXT_FROM = 3
# Open matters this recent are weighed for a new conversation; older ones have gone quiet.
LOOK_BACK_DAYS = 30
# A shared id alone is enough to join; the second-best must trail by this much.
JOIN_AT = 5
CLEAR_BY = 3
SOON_HOURS = 48
MOST_CHANGES = 12
# "ECO-1104", "INC-4471", "88213", "MODEM_NR_4519": an id, in any language. Years aren't ids,
# and neither is a username like "maheshyadav007": ticket prefixes are written in capitals.
ID = re.compile(r"\b(?:[A-Z][A-Z0-9_]*[-_#]?\d{3,}|\d{4,})\b")
YEAR = re.compile(r"^(19|20)\d{2}$")
NEEDS = "status IN ('waiting_on_you', 'waiting_on_others') OR importance = 'high'"
# A task the person kept makes its conversation something to do, whatever the AI judged.
KEPT_TASKS = (
    "SELECT thread FROM tasks WHERE status != 'done' AND proposed = 0 AND thread IS NOT NULL"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ids_in(text: str) -> set[str]:
    """Ticket, change and order numbers, written the same whatever the spacing or case."""
    found = set()
    for token in ID.findall(text or ""):
        if YEAR.match(token):
            continue
        found.add(re.sub(r"[-_ #]", "", token).lower())
        digits = re.sub(r"\D", "", token)
        if len(digits) >= 4:
            found.add(digits)
    return found


def _stem(address: str) -> str:
    local, _, domain = address.lower().partition("@")
    first = re.split(r"[^a-z]+", local)
    return f"{first[0] if first and first[0] else local}@{domain}"


def _title(subject: str) -> str:
    """A matter is named after what it started with, without Re: and list tags."""
    plain = re.sub(
        r"\[[^\]]{1,40}\]\s*",
        "",
        re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", subject or "", flags=re.I),
    )
    return (plain.strip() or subject or "No subject")[:200]


def _event(
    tx: Any,
    matter: int,
    kind: str,
    text: str,
    *,
    why: str = "",
    thread: int | None = None,
    message: int | None = None,
    by: str = "engine",
    time: str | None = None,
    undo: Any = None,
) -> None:
    tx.execute(
        "INSERT OR IGNORE INTO matter_events (matter, time, kind, thread, message, by, text, why, undo)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            matter,
            time or _now(),
            kind,
            thread,
            message,
            by,
            text[:500],
            why[:500],
            json.dumps(undo) if undo is not None else None,
        ),
    )
    tx.execute("UPDATE matters SET updated = ? WHERE id = ?", (_now(), matter))


def matter_of(db: Database, thread: int) -> int | None:
    rows = db.fetch_all("SELECT matter FROM matter_threads WHERE thread = ?", (thread,))
    return int(rows[0]["matter"]) if rows else None


def _adopt(tx: Any, matter: int, thread: int) -> None:
    """A conversation's work comes with it: its tasks, and its reminders that aren't a task's."""
    tx.execute("UPDATE tasks SET matter = ? WHERE thread = ?", (matter, thread))
    tx.execute(
        "UPDATE reminders SET matter = ? WHERE thread = ? AND task IS NULL", (matter, thread)
    )


def adopt_all(ctx: Context) -> None:
    """Work from before matters owned it takes its conversation's matter, once and quietly."""
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE tasks SET matter = (SELECT matter FROM matter_threads WHERE thread = tasks.thread)"
            " WHERE matter IS NULL AND thread IN (SELECT thread FROM matter_threads)"
        )
        tx.execute(
            "UPDATE reminders SET matter = (SELECT matter FROM matter_threads WHERE thread = reminders.thread)"
            " WHERE matter IS NULL AND task IS NULL AND thread IN (SELECT thread FROM matter_threads)"
        )
        # A deadline beside a to-do for the same thing showed twice. It becomes the to-do's date
        # when the to-do has none, and is put away; nothing is deleted.
        for deadline in tx.execute(
            "SELECT id, due, thread FROM work_board WHERE kind = 'deadline' AND done = 0 AND thread IS NOT NULL"
        ).fetchall():
            task = tx.execute(
                "SELECT id, due FROM tasks WHERE status != 'done' AND (thread = ? OR matter ="
                " (SELECT matter FROM matter_threads WHERE thread = ?)) ORDER BY thread = ? DESC, id LIMIT 1",
                (deadline["thread"], deadline["thread"], deadline["thread"]),
            ).fetchone()
            if task:
                if not task["due"] and deadline["due"]:
                    tx.execute(
                        "UPDATE tasks SET due = ? WHERE id = ?", (deadline["due"][:10], task["id"])
                    )
                tx.execute(
                    "UPDATE work_board SET done = 1, updated = ? WHERE id = ?",
                    (_now(), deadline["id"]),
                )
    links.tidy(ctx.bus.db)


def _facts(db: Database, threads: list[int], own: set[str]) -> dict[str, Any]:
    """What a set of conversations is about: ids, senders, people and subjects."""
    if not threads:
        return {"ids": set(), "senders": set(), "people": set(), "subjects": []}
    marks = ",".join("?" * len(threads))
    rows = db.fetch_all(
        f"SELECT subject, from_addr, to_json, cc_json, SUBSTR(own_text, 1, 600) AS opening"  # noqa: S608
        f" FROM messages WHERE thread_id IN ({marks})",
        tuple(threads),
    )
    ids: set[str] = set()
    senders: set[str] = set()
    people: set[str] = set()
    subjects: list[str] = []
    for row in rows:
        ids |= ids_in(f"{row['subject']}\n{row['opening']}")
        sender = row["from_addr"].lower()
        if sender not in own:
            senders.add(_stem(sender))
        people |= {
            address
            for address in [
                sender,
                *signals.addresses(row["to_json"]),
                *signals.addresses(row["cc_json"]),
            ]
            if address not in own
        }
        subjects.append(normalize_subject(row["subject"]))
    return {"ids": ids, "senders": senders, "people": people, "subjects": subjects}


def _score(this: dict[str, Any], other: dict[str, Any]) -> tuple[int, str, int]:
    """How alike two sets of conversations are, why in words, and how much of that code alone
    may join them on. A shared sender by itself is shown to the AI but never joins."""
    points, why, weak = 0, [], 0
    shared = sorted(this["ids"] & other["ids"], key=len, reverse=True)
    if shared:
        points += JOIN_AT
        why.append(f"Both mention {shared[0].upper()}")
    if this["senders"] & other["senders"] and any(
        textmatch.same(a, b, 0.6) for a in this["subjects"] for b in other["subjects"]
    ):
        points += 4
        why.append("Same sender, about the same subject")
    elif this["senders"] & other["senders"]:
        weak = CONTEXT_FROM
        why.append("Same sender")
    common = (this["people"] & other["people"]) - this["senders"]
    if len(common) >= 2:
        points += 2
        why.append(f"Same people ({len(common)})")
    return points + weak, "; ".join(why), points


def _candidates(
    db: Database, account: str, thread: int, own: set[str]
) -> list[tuple[int, int, str, int]]:
    """Open matters alike this conversation, most alike first: (points, matter, why, sure)."""
    since = (datetime.now(UTC) - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    this = _facts(db, [thread], own)
    scored = []
    for row in db.fetch_all(
        "SELECT m.id, GROUP_CONCAT(mt.thread) AS threads FROM matters m"
        " JOIN matter_threads mt ON mt.matter = m.id JOIN threads t ON t.id = mt.thread"
        " WHERE m.account = ? AND m.updated >= ? AND mt.thread != ?"
        " GROUP BY m.id HAVING SUM(t.status IN ('waiting_on_you', 'waiting_on_others')) > 0"
        " OR MAX(t.importance = 'high') = 1",
        (account, since, thread),
    ):
        threads = [int(value) for value in str(row["threads"]).split(",")]
        points, why, sure = _score(this, _facts(db, threads, own))
        if points:
            scored.append((points, int(row["id"]), why, sure))
    return sorted(scored, reverse=True)


def link(
    ctx: Context,
    thread: int,
    *,
    time: str | None = None,
    choose: int | None = None,
    because: str = "",
) -> int | None:
    """The conversation's matter, joined or started, and its newest email on the timeline.

    Only mail that needs something, or holds a task the person kept, starts a matter; a fyi
    conversation stays a conversation.
    What a folder keeps from the AI never joins one. `choose` is the matter the AI picked from
    the ones it was shown, which the caller has checked.
    """
    db = ctx.bus.db
    rows = db.fetch_all(
        f"SELECT id, account, subject, why, ({NEEDS} OR id IN ({KEPT_TASKS})) AS needs"  # noqa: S608
        f" FROM threads WHERE id = ? AND NOT {hidden_from_ai()}",
        (thread,),
    )
    existing = matter_of(db, thread)
    if not rows or (existing is None and not rows[0]["needs"]):
        return None
    own = signals.own_addresses(ctx)
    latest = db.fetch_all(
        "SELECT id, from_addr, from_name, subject, date FROM messages WHERE thread_id = ?"
        " ORDER BY date DESC, id DESC LIMIT 1",
        (thread,),
    )
    if not latest:
        return None
    message = latest[0]
    reason = rows[0]["why"] or ""
    with ctx.bus.unit_of_work() as work:
        matter = existing
        if matter is None:
            row = rows[0]
            found = _candidates(db, row["account"], thread, own)
            # Code joins only on what it's sure of; the second best must trail clearly.
            ranked = sorted(found, key=lambda item: item[3], reverse=True)
            best = ranked[0] if ranked else None
            second = ranked[1][3] if len(ranked) > 1 else 0
            if choose is not None:
                matter = choose
                work.tx.execute(
                    "INSERT INTO matter_threads (thread, matter, how, why, linked) VALUES (?, ?, 'ai', ?, ?)",
                    (thread, matter, because or "The AI put it with this", _now()),
                )
                _adopt(work.tx, matter, thread)
                _event(
                    work.tx, matter, "joined", _title(row["subject"]),
                    why=because or "The AI put it with this", thread=thread, message=message["id"],
                    time=time or message["date"],
                )  # fmt: skip
            elif best and best[3] >= JOIN_AT and second <= best[3] - CLEAR_BY:
                matter = best[1]
                work.tx.execute(
                    "INSERT INTO matter_threads (thread, matter, how, why, linked) VALUES (?, ?, 'rule', ?, ?)",
                    (thread, matter, best[2], _now()),
                )
                _adopt(work.tx, matter, thread)
                _event(
                    work.tx, matter, "joined", _title(row["subject"]),
                    why=best[2], thread=thread, message=message["id"], time=time or message["date"],
                )  # fmt: skip
            else:
                cursor = work.tx.execute(
                    "INSERT INTO matters (account, title, created, updated) VALUES (?, ?, ?, ?)",
                    (row["account"], _title(row["subject"]), _now(), _now()),
                )
                matter = int(cursor.lastrowid or 0)
                work.tx.execute(
                    "INSERT INTO matter_threads (thread, matter, how, why, linked) VALUES (?, ?, 'start', ?, ?)",
                    (thread, matter, "Started this matter", _now()),
                )
                _adopt(work.tx, matter, thread)
                # Alike, but not sure enough to be the same thing: shown side by side, never merged.
                # Only on evidence code trusts: a shared sender alone is shown to the AI, not here.
                alike = ranked[0] if ranked else None
                if alike and alike[3] >= CONTEXT_FROM:
                    best = alike
                    links.add(
                        work.tx,
                        ref("matter", matter),
                        ref("matter", best[1]),
                        "related",
                        "engine",
                        best[2],
                        "medium",
                    )
                # The line says what it needs; the email itself is the source beside it.
                _event(
                    work.tx, matter, "started", reason or _title(row["subject"]),
                    thread=thread, message=message["id"], time=time or message["date"],
                )  # fmt: skip
        elif not db.fetch_all(
            "SELECT 1 FROM matter_events WHERE matter = ? AND message = ?", (matter, message["id"])
        ):
            mine = message["from_addr"].lower() in own
            _event(
                work.tx, matter, "sent" if mine else "mail", reason or _title(message["subject"]),
                thread=thread, message=message["id"], time=time or message["date"],
            )  # fmt: skip
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)
    return matter


def note(
    ctx: Context,
    thread: int | None,
    kind: str,
    text: str,
    why: str = "",
    by: str = "engine",
    time: str | None = None,
) -> None:
    """A change to a conversation's work, on its matter's timeline. Nothing when there's none.

    `time` is when the email behind it was sent, so mail read late isn't today's news.
    """
    if not thread:
        return
    matter = matter_of(ctx.bus.db, thread)
    if matter is None:
        return
    with ctx.bus.unit_of_work() as work:
        _event(work.tx, matter, kind, text, why=why, thread=thread, by=by, time=time)
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)


def follow_kept_tasks(ctx: Context) -> int:
    """A conversation the person gave a task to becomes a matter now, not at its next email."""
    rows = ctx.bus.db.fetch_all(
        f"SELECT DISTINCT thread FROM ({KEPT_TASKS})"  # noqa: S608
        " WHERE thread NOT IN (SELECT thread FROM matter_threads)"
    )
    return sum(link(ctx, int(row["thread"])) is not None for row in rows)


def backfill(ctx: Context) -> int:
    """Once: what's open today becomes matters, oldest first, so joins find their earlier half."""
    db = ctx.bus.db
    if db.fetch_all("SELECT value FROM agent_defaults WHERE key = ?", (BACKFILLED,)):
        return 0
    account = accounts.current_account(ctx.config)
    rows = db.fetch_all(
        f"SELECT id FROM threads WHERE account = ? AND in_trash = 0 AND ({NEEDS}"  # noqa: S608
        " OR id IN (SELECT thread FROM tasks WHERE status != 'done' AND thread IS NOT NULL))"
        " AND id NOT IN (SELECT thread FROM matter_threads) ORDER BY last_date",
        (account,),
    )
    for row in rows:
        link(ctx, int(row["id"]))
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO agent_defaults (key, value) VALUES (?, ?)", (BACKFILLED, _now())
        )
    return len(rows)


# Reading -------------------------------------------------------------------------------------


def _threads_of(db: Database, matter: int) -> list[Any]:
    """Its conversations, less those a folder now keeps from the AI. Moved back, they return;
    a matter with none left drops out of the list."""
    return db.fetch_all(
        "SELECT t.*, mt.how, mt.why AS link_why FROM matter_threads mt JOIN threads t ON t.id = mt.thread"  # noqa: S608
        f" WHERE mt.matter = ? AND NOT {hidden_from_ai('t.category')} ORDER BY t.last_date",
        (matter,),
    )


def _work(db: Database, matter: int, threads: list[int]) -> list[MatterWork]:
    """What's open in the matter: its own work, and anything still filed only by conversation."""
    marks = ",".join("?" * len(threads)) or "NULL"
    tasks = db.fetch_all(
        f"SELECT * FROM tasks WHERE status != 'done' AND (matter = ? OR thread IN ({marks}))"  # noqa: S608
        " ORDER BY due IS NULL, due",
        (matter, *threads),
    )
    found = [
        MatterWork(kind="task", id=r["id"], title=r["title"], when=r["due"], thread=r["thread"],
                   proposed=bool(r["proposed"]))
        for r in tasks
    ]  # fmt: skip
    task_ids = [r["id"] for r in tasks]
    under = ",".join("?" * len(task_ids)) or "NULL"
    found += [
        MatterWork(kind="reminder", id=r["id"], title=r["title"], when=r["due_at"], thread=r["thread"],
                   proposed=bool(r["proposed"]), parent=r["task"] if r["task"] in task_ids else None)
        for r in db.fetch_all(
            f"SELECT * FROM reminders WHERE fired = 0 AND (matter = ? OR thread IN ({marks})"  # noqa: S608
            f" OR task IN ({under})) ORDER BY due_at",
            (matter, *threads, *task_ids),
        )
    ]  # fmt: skip
    found += [
        MatterWork(kind="deadline", id=r["id"], title=r["title"], when=r["due"], thread=r["thread"])
        for r in db.fetch_all(f"SELECT * FROM work_board WHERE done = 0 AND kind = 'deadline' AND thread IN ({marks})", tuple(threads))  # noqa: S608
    ]  # fmt: skip
    return found


def _done_work(db: Database, matter: int, threads: list[int]) -> list[MatterWork]:
    """What's finished in the matter, newest first, with when: tasks ticked and reminders gone off."""
    marks = ",".join("?" * len(threads)) or "NULL"
    found = [
        MatterWork(kind="task", id=r["id"], title=r["title"], when=r["completed"], thread=r["thread"])
        for r in db.fetch_all(
            f"SELECT * FROM tasks WHERE status = 'done' AND proposed = 0"  # noqa: S608
            f" AND (matter = ? OR thread IN ({marks}))",
            (matter, *threads),
        )
    ]  # fmt: skip
    found += [
        MatterWork(kind="reminder", id=r["id"], title=r["title"], when=r["due_at"], thread=r["thread"])
        for r in db.fetch_all(
            f"SELECT * FROM reminders WHERE fired = 1 AND proposed = 0"  # noqa: S608
            f" AND (matter = ? OR thread IN ({marks}))",
            (matter, *threads),
        )
    ]  # fmt: skip
    return sorted(found, key=lambda item: item.when or "", reverse=True)


def _people(db: Database, threads: list[int], own: set[str]) -> list[str]:
    if not threads:
        return []
    marks = ",".join("?" * len(threads))
    counted: Counter[str] = Counter()
    for row in db.fetch_all(
        f"SELECT from_name, from_addr FROM messages WHERE thread_id IN ({marks})",  # noqa: S608
        tuple(threads),
    ):
        if row["from_addr"].lower() not in own:
            counted[row["from_name"] or row["from_addr"]] += 1
    return [name for name, _ in counted.most_common(6)]


def _quiet(last: str) -> int:
    try:
        return max((datetime.now(UTC) - datetime.fromisoformat(last)).days, 0)
    except (TypeError, ValueError):
        return 0


ACTIONS = {"reply": "Reply", "do": "Do what it asks", "decide": "Decide", "read": "Read it"}


def row(ctx: Context, matter: Any) -> MatterRow:
    db = ctx.bus.db
    threads = _threads_of(db, matter["id"])
    ids = [t["id"] for t in threads]
    statuses = {t["status"] for t in threads}
    work = _work(db, matter["id"], ids)
    # Only what the person kept is theirs to do. Posty's suggestions wait in For your decision,
    # and don't move the matter, its next step or its date until they're accepted.
    kept = [w for w in work if not w.proposed]
    state = (
        "waiting_on_you"
        if "waiting_on_you" in statuses or any(w.kind == "task" for w in kept)
        else "waiting_on_others"
        if "waiting_on_others" in statuses
        else "fyi"
        if any(t["importance"] == "high" and t["status"] in {"none", "fyi"} for t in threads)
        else "done"
    )
    dates = sorted(w.when for w in kept if w.when)
    task = next((w for w in kept if w.kind == "task"), None)
    action = next((t["next_action"] for t in reversed(threads) if t["next_action"]), None)
    last = max((t["last_date"] for t in threads), default=matter["created"])
    return MatterRow(
        id=matter["id"],
        title=matter["title"],
        state=state,
        next=task.title if task else ACTIONS.get(action or ""),
        due=dates[0] if dates else None,
        importance="high" if any(t["importance"] == "high" for t in threads) else "normal",
        people=_people(db, ids, signals.own_addresses(ctx)),
        emails=sum(int(t["message_count"]) for t in threads),
        threads=len(threads),
        work=work,
        last_date=last,
        quiet_days=_quiet(last),
        # When its earliest email came, wherever that conversation joined from.
        started=db.fetch_all(
            f"SELECT MIN(date) AS t FROM messages WHERE thread_id IN ({','.join('?' * len(ids))})",  # noqa: S608
            ids,
        )[0]["t"]
        if ids
        else matter["created"],
        latest=thread_source(db, max(threads, key=lambda t: t["last_date"])["id"])
        if threads
        else None,
    )


def _matters(ctx: Context, include_done: bool = False) -> list[MatterRow]:
    account = accounts.current_account(ctx.config)
    rows = [
        row(ctx, m)
        for m in ctx.bus.db.fetch_all("SELECT * FROM matters WHERE account = ?", (account,))
    ]
    rows = [r for r in rows if r.threads and (include_done or r.state != "done")]
    return sorted(
        rows,
        key=lambda r: (r.due is None, r.due or "", r.importance != "high", r.last_date),
        reverse=False,
    )


def _change(db: Database, event: Any, titles: dict[int, str]) -> MatterChange:
    return MatterChange(
        id=event["id"],
        matter=event["matter"],
        title=titles.get(event["matter"], ""),
        time=event["time"],
        kind=event["kind"],
        text=event["text"],
        why=event["why"],
        source=thread_source(db, event["thread"], event["message"]) if event["thread"] else None,
    )


def brief(ctx: Context, seen: str | None) -> MattersBrief:
    db = ctx.bus.db
    rows = _matters(ctx)
    everything = _matters(ctx, include_done=True)
    titles = {m["id"]: m["title"] for m in db.fetch_all("SELECT id, title FROM matters")}
    # The day's changes stay listed; the page marks the ones that came after the person looked.
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    events = db.fetch_all(
        "SELECT * FROM matter_events WHERE time > ? AND (thread IS NULL OR thread NOT IN"  # noqa: S608
        f" (SELECT id FROM threads WHERE {hidden_from_ai()})) ORDER BY time DESC, id DESC LIMIT ?",
        (since, MOST_CHANGES),
    )
    soon = (datetime.now().astimezone() + timedelta(hours=SOON_HOURS)).strftime("%Y-%m-%dT%H:%M")
    upcoming = sorted(
        (
            MatterDue(matter=r.id, title=r.title, what=w.title, when=w.when, kind=w.kind)
            for r in rows
            for w in r.work
            if w.when and w.when <= soon and not w.proposed
        ),
        key=lambda item: item.when,
    )
    return MattersBrief(
        seen=seen,
        changes=[_change(db, e, titles) for e in events],
        needs_you=[r for r in rows if r.state == "waiting_on_you"],
        waiting=[r for r in rows if r.state == "waiting_on_others"],
        fyi=[r for r in rows if r.state == "fyi"],
        # Not waiting on them yet, but Posty has suggested something: shown when they ask to.
        suggested=[
            r for r in everything if r.state != "waiting_on_you" and any(w.proposed for w in r.work)
        ],
        next=upcoming,
    )


def week(ctx: Context, start: str | None, days: int = 7) -> MattersWeek:
    db = ctx.bus.db
    today = datetime.now().astimezone().date()
    monday = date.fromisoformat(start) if start else today - timedelta(days=today.weekday())
    begin, end = monday.isoformat(), (monday + timedelta(days=days)).isoformat()
    own = signals.own_addresses(ctx)
    lanes = []
    for matter in _matters(ctx, include_done=True):
        threads = [t["id"] for t in _threads_of(db, matter.id)]
        marks: list[MatterMark] = []
        marks_sql = ",".join("?" * len(threads))
        for m in db.fetch_all(
            f"SELECT date, from_addr, from_name, subject FROM messages WHERE thread_id IN ({marks_sql})"  # noqa: S608
            " AND date >= ? AND date < ? GROUP BY message_id ORDER BY date",
            (*threads, _utc(begin), _utc(end)),
        ):
            mine = m["from_addr"].lower() in own
            who = "You" if mine else (m["from_name"] or m["from_addr"])
            marks.append(
                MatterMark(
                    time=m["date"], kind="sent" if mine else "in", label=f"{who}: {m['subject']}"
                )
            )
        for w in matter.work:
            if w.when and begin <= w.when[:10] < end:
                marks.append(
                    MatterMark(
                        time=w.when,
                        kind="reminder" if w.kind == "reminder" else "due",
                        label=w.title,
                    )
                )
        # Every step the person or the AI took, not only closes: the emails are drawn above.
        for e in db.fetch_all(
            "SELECT time, kind, text FROM matter_events WHERE matter = ?"
            " AND kind NOT IN ('started', 'joined', 'mail', 'sent') AND time >= ? AND time < ?"
            " ORDER BY time, id",
            (matter.id, _utc(begin), _utc(end)),
        ):
            kind = e["kind"]
            look: MatterMarkKind = (
                "closed"
                if kind in {"closed", "done"}
                else "reopened"
                if kind == "reopened"
                else "step"
            )
            # The page names a close or a reopen; any other step says what it was itself.
            said = EVENT_WORDS.get(kind, kind)
            label = e["text"] if look != "step" else f"{said[:1].upper()}{said[1:]}: {e['text']}"
            marks.append(MatterMark(time=e["time"], kind=look, label=label))
        if marks or matter.state != "done":
            lanes.append(MatterLane(matter=matter, marks=sorted(marks, key=lambda mark: mark.time)))
    lanes = [lane for lane in lanes if lane.marks or lane.matter.state != "done"]
    return MattersWeek(start=begin, lanes=lanes)


def _utc(day: str) -> str:
    """Midnight local time on that day, as the UTC text messages are stored with."""
    local = datetime.fromisoformat(day).astimezone()
    return local.astimezone(UTC).isoformat()


def _family(db: Database, matter: int) -> list[int]:
    """The matter and those merged into it, whose history is now its history."""
    found, todo = [matter], [matter]
    while todo:
        for link in links.live(db, ref("matter", todo.pop()), "merged", reverse=True):
            other = parse(link["other"])
            if other and other[1] not in found:
                found.append(other[1])
                todo.append(other[1])
    return found


# What emails say on the timeline, worked out from the mail itself rather than stored.
EMAIL_KINDS = ("started", "joined", "mail", "sent")


def _story(db: Database, matter: int, titles: dict[int, str], own: set[str]) -> list[MatterChange]:
    """Everything that happened, in date order. Each email is at its own date: the earliest one
    started the matter, the first one of each conversation that came with it later linked it,
    with why. What was done is at the time it was done. Emails have negative ids, so a page can
    end before either kind."""
    family = _family(db, matter)
    marks = ",".join("?" * len(family))
    threads = {
        row["thread"]: row
        for row in db.fetch_all(
            "SELECT mt.thread, mt.how, mt.why FROM matter_threads mt JOIN threads t ON t.id = mt.thread"  # noqa: S608
            f" WHERE mt.matter IN ({marks}) AND NOT {hidden_from_ai('t.category')}",
            family,
        )
    }
    title = titles.get(matter, "")
    story: list[MatterChange] = []
    if threads:
        places = ",".join("?" * len(threads))
        emails = db.fetch_all(
            "SELECT MIN(id) AS id, thread_id, subject, from_addr, date FROM messages"  # noqa: S608
            f" WHERE thread_id IN ({places}) GROUP BY message_id ORDER BY date, id",
            list(threads),
        )
        begun: set[int] = set()
        # Why they're together is said by the conversation that joined. When the one that
        # started it isn't the earliest, the earliest joined it, and its reason is theirs.
        earliest = int(emails[0]["thread_id"]) if emails else None
        joined_why = (
            threads[earliest]["why"] if earliest and threads[earliest]["how"] != "start" else ""
        )
        for email in emails:
            thread = int(email["thread_id"])
            first = thread not in begun
            kind = (
                ("started" if not begun else "joined")
                if first
                else "sent"
                if email["from_addr"].lower() in own
                else "mail"
            )
            begun.add(thread)
            story.append(
                MatterChange(
                    id=-int(email["id"]),
                    matter=matter,
                    title=title,
                    time=email["date"],
                    kind=kind,
                    text=_title(email["subject"]),
                    why=(
                        (
                            joined_why
                            if threads[thread]["how"] == "start"
                            else threads[thread]["why"]
                        )
                        or ""
                    )
                    if kind == "joined"
                    else "",
                    source=thread_source(db, thread, int(email["id"])),
                )
            )
    actions = db.fetch_all(
        f"SELECT * FROM matter_events WHERE matter IN ({marks})"  # noqa: S608
        f" AND kind NOT IN {EMAIL_KINDS} AND (thread IS NULL OR thread NOT IN"
        f" (SELECT id FROM threads WHERE {hidden_from_ai()})) ORDER BY time, id",
        family,
    )
    story += [_change(db, event, titles) for event in actions]
    # The earliest email leads, however its time compares with an action on the same moment.
    return sorted(story, key=lambda change: (change.time, change.kind != "started"))


def _events(
    db: Database, matter: int, titles: dict[int, str], before: int | None, own: set[str]
) -> MatterEvents:
    """A page of the story, oldest first, ending just before `before` (or now)."""
    story = _story(db, matter, titles, own)
    end = next((at for at, change in enumerate(story) if change.id == before), len(story))
    page = story[max(0, end - PAGE) : end]
    return MatterEvents(events=page, earlier=end > PAGE)


def events(ctx: Context, matter: int, before: int) -> MatterEvents:
    db = ctx.bus.db
    titles = {m["id"]: m["title"] for m in db.fetch_all("SELECT id, title FROM matters")}
    return _events(db, matter, titles, before, signals.own_addresses(ctx))


def _related(ctx: Context, matter: int) -> list[MatterLinkRow]:
    db = ctx.bus.db
    me = ref("matter", matter)
    found: list[MatterLinkRow] = []
    for link in [*links.live(db, me, "related"), *links.live(db, me, "related", reverse=True)]:
        other = parse(link["other"])
        rows = db.fetch_all("SELECT * FROM matters WHERE id = ?", (other[1],)) if other else []
        if rows and not links.live(db, link["other"], "merged"):
            shown = row(ctx, rows[0])
            if shown.threads:
                found.append(
                    MatterLinkRow(
                        matter=shown.id, title=shown.title, state=shown.state, why=link["why"]
                    )
                )
    return found


def _files(db: Database, matter: int, threads: list[int]) -> list[MatterFile]:
    """Files that came with its emails, read from the mail, and documents someone linked to it."""
    marks = ",".join("?" * len(threads)) or "NULL"
    found = [
        MatterFile(ref=f"attachment:{r['message']}:{r['part_index']}", title=r["filename"],
                   source=thread_source(db, r["thread_id"], r["message"]))
        for r in db.fetch_all(
            "SELECT p.message, p.part_index, p.filename, m.thread_id FROM message_parts p"
            f" JOIN messages m ON m.id = p.message WHERE p.kind = 'attachment' AND m.thread_id IN ({marks})"  # noqa: S608
            " GROUP BY p.sha256 ORDER BY m.date DESC LIMIT 30",
            tuple(threads),
        )
    ]  # fmt: skip
    for link in links.live(db, ref("matter", matter), "uses"):
        doc = parse(link["other"])
        rows = db.fetch_all("SELECT name FROM documents WHERE id = ?", (doc[1],)) if doc else []
        if rows:
            found.append(MatterFile(ref=link["other"], title=rows[0]["name"]))
    return found


def detail(ctx: Context, matter: int) -> MatterDetail:
    db = ctx.bus.db
    found = db.fetch_all("SELECT * FROM matters WHERE id = ?", (matter,))
    if not found:
        raise CommandError("matter.not_found", "That matter no longer exists.", 404)
    threads = _threads_of(db, matter)
    titles = {m["id"]: m["title"] for m in db.fetch_all("SELECT id, title FROM matters")}
    page = _events(db, matter, titles, None, signals.own_addresses(ctx))
    return MatterDetail(
        matter=row(ctx, found[0]),
        events=page.events,
        earlier=page.earlier,
        threads=[
            MatterThread(
                id=t["id"],
                subject=t["subject"],
                status=t["status"],
                emails=t["message_count"],
                last_date=t["last_date"],
                how=t["how"],
                why=t["link_why"],
            )  # fmt: skip
            for t in threads
        ],
        people=_people(db, [t["id"] for t in threads], signals.own_addresses(ctx)),
        related=_related(ctx, matter),
        files=_files(db, matter, [t["id"] for t in threads]),
        done=_done_work(db, matter, [t["id"] for t in threads]),
    )


# Changing --------------------------------------------------------------------------------------


def done(ctx: Context, matter: int) -> int:
    """Every conversation in it done, and with them their tasks, reminders and deadlines."""
    db = ctx.bus.db
    threads = _threads_of(db, matter)
    before = {str(t["id"]): t["status"] for t in threads if t["status"] != "resolved"}
    closed = 0
    for thread, status in before.items():
        if conversations._set_status(ctx, int(thread), "resolved", status):
            closed += conversations.close_work(ctx, int(thread))
    with ctx.bus.unit_of_work() as work:
        _event(work.tx, matter, "done", "You marked it done", by="person", undo=before,
               why=f"Closed {closed} open item{'' if closed == 1 else 's'} with it" if closed else "")  # fmt: skip
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)
    return closed


def finished(tx: Any, matter: int) -> None:
    """A matter that finished by itself, with every conversation answered, gets its done step
    once, so it shows with what got done. Marked by the person, it has one already."""
    last = tx.execute(
        "SELECT kind FROM matter_events WHERE matter = ? AND kind IN ('done', 'reopened')"
        " ORDER BY time DESC, id DESC LIMIT 1",
        (matter,),
    ).fetchone()
    if last is None or last["kind"] != "done":
        _event(tx, matter, "done", "Nothing left to do", by="engine")


def reopen(ctx: Context, matter: int) -> None:
    """Undo for Done: each conversation back as it was, with what closing it closed."""
    db = ctx.bus.db
    rows = db.fetch_all(
        "SELECT undo FROM matter_events WHERE matter = ? AND kind = 'done' ORDER BY id DESC LIMIT 1",
        (matter,),
    )
    before: dict[str, str] = json.loads(rows[0]["undo"] or "{}") if rows else {}
    for thread, status in before.items():
        if conversations._set_status(ctx, int(thread), status, "resolved"):
            conversations.reopen_work(ctx, int(thread))
    with ctx.bus.unit_of_work() as work:
        _event(work.tx, matter, "reopened", "Opened again", by="person")
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)


def unlink(ctx: Context, thread: int) -> int:
    """Not part of this: the conversation starts a matter of its own, and code remembers why."""
    db = ctx.bus.db
    old = matter_of(db, thread)
    rows = db.fetch_all("SELECT account, subject FROM threads WHERE id = ?", (thread,))
    if old is None or not rows:
        raise CommandError("matter.not_linked", "That conversation isn't part of a matter.", 404)
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO matters (account, title, created, updated) VALUES (?, ?, ?, ?)",
            (rows[0]["account"], _title(rows[0]["subject"]), _now(), _now()),
        )
        new = int(cursor.lastrowid or 0)
        work.tx.execute(
            "UPDATE matter_threads SET matter = ?, how = 'person', why = ?, linked = ? WHERE thread = ?",
            (new, "You moved it out", _now(), thread),
        )
        # Work asked for in this conversation goes with it.
        _adopt(work.tx, new, thread)
        _event(
            work.tx,
            old,
            "moved",
            f'"{_title(rows[0]["subject"])}" moved out',
            by="person",
            thread=thread,
        )
        _event(
            work.tx,
            new,
            "started",
            _title(rows[0]["subject"]),
            why="You moved it out of another matter",
            by="person",
            thread=thread,
        )
        work.emit("matters.changed", {"matter": new}, source="agent", trace_id=ctx.trace_id)
    return new


# The rest of the matter -------------------------------------------------------------------------


def home(db: Database, kind: str, identifier: int) -> tuple[int | None, int | None, int | None]:
    """The matter something belongs to, the email that asked for it, and its conversation."""
    if kind == "thread":
        return matter_of(db, identifier), None, identifier
    if kind == "task":
        rows = db.fetch_all(
            "SELECT matter, source_message, thread FROM tasks WHERE id = ?", (identifier,)
        )
        if not rows:
            return None, None, None
        r = rows[0]
        return (
            r["matter"] or (matter_of(db, r["thread"]) if r["thread"] else None),
            r["source_message"],
            r["thread"],
        )
    if kind == "reminder":
        rows = db.fetch_all(
            "SELECT matter, task, thread FROM reminders WHERE id = ?", (identifier,)
        )
        if not rows:
            return None, None, None
        r = rows[0]
        if r["task"]:
            return home(db, "task", r["task"])
        return (
            r["matter"] or (matter_of(db, r["thread"]) if r["thread"] else None),
            None,
            r["thread"],
        )
    if kind == "deadline":
        rows = db.fetch_all("SELECT thread FROM work_board WHERE id = ?", (identifier,))
        thread = rows[0]["thread"] if rows else None
        return (matter_of(db, thread) if thread else None), None, thread
    return None, None, None


def related_open(ctx: Context, trigger: str) -> MatterRelated:
    """What else is open in the matter of something just finished, to ask about in one go.

    A thing's own children aren't here: they went with it. Items the same email asked for start
    ticked; anything with an ask of its own starts unticked. Ones the person kept open before for
    this same thing aren't offered again.
    """
    found = parse(trigger)
    if not found:
        return MatterRelated()
    db = ctx.bus.db
    kind, identifier = found
    matter, source, thread = home(db, kind, identifier)
    titled = db.fetch_all("SELECT title FROM matters WHERE id = ?", (matter,)) if matter else []
    if matter is None or not titled:
        return MatterRelated()
    kept = {
        r["item"]
        for r in db.fetch_all("SELECT item FROM matter_kept WHERE trigger = ?", (trigger,))
    }
    threads = [t["id"] for t in _threads_of(db, matter)]
    items: list[MatterItem] = []

    proposed = {
        ref("task", r["id"])
        for r in db.fetch_all("SELECT id FROM tasks WHERE proposed = 1 AND status != 'done'")
    } | {
        ref("reminder", r["id"])
        for r in db.fetch_all("SELECT id FROM reminders WHERE proposed = 1 AND fired = 0")
    }

    def offer(
        item: str,
        kind_of: str,
        title: str,
        when: str | None,
        from_email: int | None,
        in_thread: int | None,
    ) -> None:
        if item == trigger or item in kept:
            return
        same_email = bool(source and from_email == source)
        same_thread = bool(thread and in_thread == thread)
        why = (
            "The same email asked for it"
            if same_email
            else "In the same conversation"
            if same_thread
            else ""
        )
        items.append(
            MatterItem(
                ref=item,
                kind=kind_of,
                proposed=item in proposed,
                title=title,
                when=when,
                suggested=same_email or same_thread,
                why=why,
            )
        )

    for w in _work(db, matter, threads):
        if w.kind == "reminder" and w.parent is not None:
            continue
        if kind == "task" and w.kind == "reminder" and w.parent == identifier:
            continue
        email = None
        if w.kind == "task":
            email = db.fetch_all("SELECT source_message FROM tasks WHERE id = ?", (w.id,))[0][
                "source_message"
            ]
        offer(ref(w.kind, w.id), w.kind, w.title, w.when, email, w.thread)
    for t in _threads_of(db, matter):
        if t["status"] == "waiting_on_you":
            offer(ref("thread", t["id"]), "thread", t["subject"], None, None, t["id"])
    return MatterRelated(matter=matter, title=titled[0]["title"], items=items)


def _close_one(ctx: Context, kind: str, identifier: int) -> None:
    if kind == "task":
        planner.change_task(ctx, identifier, {"status": "done"})
    elif kind == "reminder":
        planner.change_reminder(ctx, identifier, {"fired": 1})
    elif kind == "deadline":
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE work_board SET done = 1, updated = ? WHERE id = ?", (_now(), identifier)
            )
            work.emit("board.changed", {}, source="agent", trace_id=ctx.trace_id)
    elif kind == "thread":
        rows = ctx.bus.db.fetch_all("SELECT status FROM threads WHERE id = ?", (identifier,))
        if (
            rows
            and rows[0]["status"] != "resolved"
            and conversations._set_status(ctx, identifier, "resolved", rows[0]["status"])
        ):
            conversations.close_work(ctx, identifier)


def close_items(ctx: Context, trigger: str, close: list[str], keep: list[str]) -> int:
    """The person's answer: close what they ticked, remember what they left open. Only items
    that were offered for this thing can be closed, so nothing outside the matter is touched."""
    offered = related_open(ctx, trigger)
    allowed = {item.ref: item for item in offered.items}
    closed = [item for item in close if item in allowed]
    for item in closed:
        kind, identifier = parse(item)  # type: ignore[misc]
        _close_one(ctx, kind, identifier)
    left = [item for item in keep if item in allowed]
    if offered.matter is None or not (closed or left):
        return 0
    with ctx.bus.unit_of_work() as work:
        for item in left:
            work.tx.execute(
                "INSERT OR IGNORE INTO matter_kept (trigger, item) VALUES (?, ?)", (trigger, item)
            )
        if closed:
            names = ", ".join(f'"{allowed[item].title}"' for item in closed)
            _event(
                work.tx,
                offered.matter,
                "closed",
                f"Also closed {names}"[:500],
                by=ctx.actor or "person",
                undo=closed,
            )
        if left:
            names = ", ".join(f'"{allowed[item].title}"' for item in left)
            _event(
                work.tx,
                offered.matter,
                "kept",
                f"Left open {names}"[:500],
                by=ctx.actor or "person",
            )
        work.emit(
            "matters.changed", {"matter": offered.matter}, source="agent", trace_id=ctx.trace_id
        )
    return len(closed)


def reopen_items(ctx: Context, items: list[str]) -> int:
    """Undo for closing: each thing open again, as it was."""
    opened = 0
    for item in items:
        found = parse(item)
        if not found:
            continue
        kind, identifier = found
        if kind == "task":
            planner.change_task(ctx, identifier, {"status": "todo"})
        elif kind == "reminder":
            planner.change_reminder(ctx, identifier, {"fired": 0})
        elif kind == "deadline":
            with ctx.bus.unit_of_work() as work:
                work.tx.execute(
                    "UPDATE work_board SET done = 0, updated = ? WHERE id = ?", (_now(), identifier)
                )
                work.emit("board.changed", {}, source="agent", trace_id=ctx.trace_id)
        elif kind == "thread":
            if conversations._set_status(ctx, identifier, "waiting_on_you", "resolved"):
                conversations.reopen_work(ctx, identifier)
        else:
            continue
        opened += 1
    return opened


def merge(ctx: Context, matter: int, into: int) -> None:
    """Two matters that turn out to be one thing: everything moves, and it can be undone."""
    db = ctx.bus.db
    rows = {
        r["id"]: r for r in db.fetch_all("SELECT * FROM matters WHERE id IN (?, ?)", (matter, into))
    }
    if matter == into or len(rows) < 2 or rows[matter]["account"] != rows[into]["account"]:
        raise CommandError("matter.merge", "Those two can't be merged.", 422)
    threads = [t["id"] for t in _threads_of(db, matter)]
    tasks = [r["id"] for r in db.fetch_all("SELECT id FROM tasks WHERE matter = ?", (matter,))]
    reminders = [
        r["id"] for r in db.fetch_all("SELECT id FROM reminders WHERE matter = ?", (matter,))
    ]
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("UPDATE matter_threads SET matter = ? WHERE matter = ?", (into, matter))
        work.tx.execute("UPDATE tasks SET matter = ? WHERE matter = ?", (into, matter))
        work.tx.execute("UPDATE reminders SET matter = ? WHERE matter = ?", (into, matter))
        links.end(work.tx, ref("matter", matter), ref("matter", into), "related", "merged")
        links.end(work.tx, ref("matter", into), ref("matter", matter), "related", "merged")
        links.add(
            work.tx,
            ref("matter", matter),
            ref("matter", into),
            "merged",
            ctx.actor or "person",
            "Merged by you",
        )
        undo = {"from": matter, "threads": threads, "tasks": tasks, "reminders": reminders}
        _event(
            work.tx,
            into,
            "merged",
            f'"{rows[matter]["title"]}" merged in',
            by=ctx.actor or "person",
            undo=undo,
        )
        _event(
            work.tx,
            matter,
            "merged",
            f'Merged into "{rows[into]["title"]}"',
            by=ctx.actor or "person",
        )
        work.emit("matters.changed", {"matter": into}, source="agent", trace_id=ctx.trace_id)


def unmerge(ctx: Context, matter: int) -> int:
    """Undo for merge: what came from the matter goes back to it. Returns where it was merged."""
    db = ctx.bus.db
    into = links.live(db, ref("matter", matter), "merged")
    target = parse(into[0]["other"]) if into else None
    if not target:
        raise CommandError("matter.not_merged", "That matter wasn't merged.", 404)
    rows = db.fetch_all(
        "SELECT undo FROM matter_events WHERE matter = ? AND kind = 'merged' AND undo IS NOT NULL ORDER BY id DESC",
        (target[1],),
    )
    undo = next((u for u in (json.loads(r["undo"]) for r in rows) if u.get("from") == matter), None)
    if undo is None:
        raise CommandError("matter.not_merged", "That merge can't be undone.", 404)
    with ctx.bus.unit_of_work() as work:
        for table, column, ids in (
            ("matter_threads", "thread", undo["threads"]),
            ("tasks", "id", undo["tasks"]),
            ("reminders", "id", undo["reminders"]),
        ):
            for identifier in ids:
                work.tx.execute(
                    f"UPDATE {table} SET matter = ? WHERE {column} = ?", (matter, identifier)
                )  # noqa: S608
        links.end(work.tx, ref("matter", matter), ref("matter", target[1]), "merged", "undone")
        _event(work.tx, matter, "reopened", "Taken back out", by=ctx.actor or "person")
        _event(
            work.tx,
            target[1],
            "moved",
            f"Merge undone: {db.fetch_all('SELECT title FROM matters WHERE id = ?', (matter,))[0]['title']}",
            by=ctx.actor or "person",
        )
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)
    return target[1]


def attach(ctx: Context, matter: int, item: str, why: str) -> None:
    """A document the matter uses. It isn't owned: another matter can use it too."""
    found = parse(item)
    if (
        not found
        or found[0] != "doc"
        or not ctx.bus.db.fetch_all("SELECT 1 FROM matters WHERE id = ?", (matter,))
    ):
        raise CommandError("matter.attach", "Only a document can be linked to a matter.", 422)
    if not ctx.bus.db.fetch_all("SELECT 1 FROM documents WHERE id = ?", (found[1],)):
        raise CommandError("matter.attach", "That document is gone.", 404)
    with ctx.bus.unit_of_work() as work:
        if links.add(work.tx, ref("matter", matter), item, "uses", ctx.actor or "person", why):
            name = work.tx.execute(
                "SELECT name FROM documents WHERE id = ?", (found[1],)
            ).fetchone()["name"]
            _event(work.tx, matter, "linked", f'Linked "{name}"', why=why, by=ctx.actor or "person")
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)


# What the AI is shown -------------------------------------------------------------------------


def shortlist(ctx: Context, thread: int) -> list[tuple[int, str]]:
    """The matters an email may belong to: its own, or the few code finds most alike."""
    db = ctx.bus.db
    existing = matter_of(db, thread)
    if existing is not None:
        return [(existing, "This conversation is already part of it")]
    rows = db.fetch_all("SELECT account FROM threads WHERE id = ?", (thread,))
    if not rows:
        return []
    found = _candidates(db, rows[0]["account"], thread, signals.own_addresses(ctx))
    return [
        (matter, why)
        for points, matter, why, _ in found[:CONTEXT_MATTERS]
        if points >= CONTEXT_FROM
    ]


def _short(text: str, size: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


# Words for each kind of change, as the matter page says them.
EVENT_WORDS = {
    "started": "started", "joined": "linked", "mail": "email in", "sent": "you wrote",
    "task": "added", "due": "date changed", "closed": "closed", "done": "done",
    "reopened": "opened again", "moved": "moved out", "merged": "merged", "linked": "file linked",
    "kept": "left open", "looks_done": "looks done",
    "suggested": "suggested",
    "accepted": "accepted",
    "declined": "declined",
}  # fmt: skip


def context_for(ctx: Context, thread: int) -> str:
    """Each matter as a few short lines with the ids the AI copies: what it is and why code
    thinks it's related, its conversations, what happened lately, and what's still open, each
    cut short with a count of what's left out, so a big matter never floods the prompt."""
    db = ctx.bus.db
    lines: list[str] = []
    for matter, why in shortlist(ctx, thread):
        found = db.fetch_all("SELECT * FROM matters WHERE id = ?", (matter,))
        if not found:
            continue
        shown = row(ctx, found[0])
        lines.append(
            f'[{matter}] "{shown.title}" · {shown.state} · due {shown.due or "none"}'
            f" · {shown.emails} emails in {shown.threads} conversations"
        )
        lines.append(f"   why: {why}")
        # What a folder keeps from the AI stays out of what the AI is told, here too.
        threads = db.fetch_all(
            "SELECT t.subject, t.status FROM matter_threads mt JOIN threads t ON t.id = mt.thread"  # noqa: S608
            f" WHERE mt.matter = ? AND NOT {hidden_from_ai('t.category')} ORDER BY t.last_date DESC",
            (matter,),
        )
        talks = [f'"{_short(t["subject"], 70)}" ({t["status"]})' for t in threads[:CONTEXT_MATTERS]]
        more = len(threads) - len(talks)
        lines.append(
            "   conversations: " + "; ".join(talks) + (f"; and {more} more" if more > 0 else "")
        )
        # The same story the person reads, in the same order, oldest first.
        titles = {matter: shown.title}
        happened = _story(db, matter, titles, signals.own_addresses(ctx))[-CONTEXT_MATTERS:]
        if happened:
            lines.append(
                "   lately: "
                + "; ".join(
                    f"{e.time[:10]} {EVENT_WORDS.get(e.kind, e.kind)}: {_short(e.text, 90)}"
                    for e in happened
                )
            )
        tasks = [w for w in shown.work if not (w.kind == "reminder" and w.parent is not None)]
        under = {w.parent: w for w in shown.work if w.kind == "reminder" and w.parent is not None}
        listed = []
        for w in tasks[:CONTEXT_ITEMS]:
            item = f'[{w.kind}:{w.id}] "{_short(w.title, 80)}"' + (
                f" due {w.when}" if w.when else ""
            )
            if w.kind == "task" and w.id in under:
                item += f" (its reminder {under[w.id].when})"
            listed.append(item)
        left = len(tasks) - len(listed)
        lines.append(
            "   open: "
            + (" · ".join(listed) or "nothing")
            + (f" · and {left} more" if left > 0 else "")
        )
    return "\n".join(lines)


# What the brief is given -------------------------------------------------------------------------

PLATE_MATTERS = 15
PLATE_LOOSE = 10


# Finished work stays in view this long, so an email isn't read as an open ask once it's done.
RECENTLY_DONE_DAYS = 2


def standing(ctx: Context, thread: int, most: int = 4) -> str:
    """Where a conversation stands, in a line, by address: its matter and state, its open work
    and what was finished in it lately."""
    db = ctx.bus.db
    matter = matter_of(db, thread)
    found = db.fetch_all("SELECT * FROM matters WHERE id = ?", (matter,)) if matter else []
    if not found:
        rows = db.fetch_all("SELECT status FROM threads WHERE id = ?", (thread,))
        return f"Where it stands: not part of a matter · {rows[0]['status'] if rows else 'gone'}"
    shown = row(ctx, found[0])
    since = (datetime.now(UTC) - timedelta(days=RECENTLY_DONE_DAYS)).isoformat()
    ids = [t["id"] for t in _threads_of(db, shown.id)]
    parts = [f"{address('matter', shown.id)} {shown.state}"]
    parts += [
        f"{'suggested' if w.proposed else 'open'} {address(w.kind, w.id)} {_short(w.title, 60)}"
        + (f" due {w.when}" if w.when else "")
        for w in shown.work[:most]
    ]
    parts += [
        f"done {address(w.kind, w.id)} {_short(w.title, 60)} {_local(w.when)}"
        for w in _done_work(db, shown.id, ids)
        if (w.when or "")[:16] >= since[:16]
    ][:most]
    return "Where it stands: " + " · ".join(parts)


def plate(ctx: Context) -> str:
    """What's going on, one matter at a time, then what isn't part of one and what finished since
    yesterday. Each list is cut short with a count, so a full mailbox never floods the brief, and
    nothing appears twice. Every object is written by its address, to open and to cite."""
    db = ctx.bus.db
    rows = _matters(ctx)
    parts: list[str] = []
    counts = Counter(r.state for r in rows)
    parts.append(
        f"Matters waiting on them: {counts['waiting_on_you']} · waiting on others:"
        f" {counts['waiting_on_others']} · worth knowing: {counts['fyi']}"
    )
    looks = {
        (kind, r["id"]): r["looks_done"]
        for kind, table in (("task", "tasks"), ("reminder", "reminders"))
        for r in db.fetch_all(f"SELECT id, looks_done FROM {table} WHERE looks_done IS NOT NULL")  # noqa: S608
    }
    lines: list[str] = []
    for shown in rows[:PLATE_MATTERS]:
        when = f" · due {shown.due}" if shown.due else ""
        quiet = (
            f" · quiet {shown.quiet_days} days"
            if shown.state == "waiting_on_others" and shown.quiet_days
            else ""
        )
        lines.append(
            f'{address("matter", shown.id)} "{_short(shown.title, 90)}" · {shown.state}{when}{quiet} · {shown.emails} emails'
        )
        if shown.next:
            lines.append(f"   next: {_short(shown.next, 100)}")
        work = [w for w in shown.work if not (w.kind == "reminder" and w.parent is not None)]
        for label, chosen in (
            ("open", [w for w in work if not w.proposed and (w.kind, w.id) not in looks]),
            ("suggested, not kept yet", [w for w in work if w.proposed]),
        ):
            listed = [
                f"{address(w.kind, w.id)} {_short(w.title, 70)}"
                + (f" due {w.when}" if w.when else "")
                for w in chosen[:CONTEXT_ITEMS]
            ]
            left = len(chosen) - len(listed)
            if listed:
                lines.append(
                    f"   {label}: "
                    + " · ".join(listed)
                    + (f" · and {left} more" if left > 0 else "")
                )
        for w in work:
            if (w.kind, w.id) in looks and not w.proposed:
                lines.append(
                    f"   looks done: {address(w.kind, w.id)} {_short(w.title, 70)}: {_short(looks[(w.kind, w.id)], 100)}"
                )
        if shown.latest:
            why = db.fetch_all("SELECT why FROM threads WHERE id = ?", (shown.latest.ref,))
            lines.append(
                f"   latest: {address('mail', shown.latest.ref)} {_short(shown.latest.detail or '', 40)}, "
                f"{(shown.latest.date or '')[:10]}: {_short((why[0]['why'] if why else '') or shown.latest.title, 140)}"
            )
    if lines:
        more = len(rows) - min(len(rows), PLATE_MATTERS)
        parts.append(
            "What's going on, one matter each:\n"
            + "\n".join(lines)
            + (f"\nand {more} more matters" if more > 0 else "")
        )
    account = accounts.current_account(ctx.config)
    loose = db.fetch_all(
        "SELECT id, title, due FROM tasks WHERE status != 'done' AND matter IS NULL"
        " AND (thread IS NULL OR thread NOT IN (SELECT thread FROM matter_threads)) ORDER BY due IS NULL, due, id"
    )
    if loose:
        listed = [
            f"[task:{t['id']}] {_short(t['title'], 80)}" + (f" due {t['due']}" if t["due"] else "")
            for t in loose[:PLATE_LOOSE]
        ]
        more = len(loose) - len(listed)
        parts.append(
            "Their own tasks, not part of a matter:\n"
            + "\n".join(f"- {line}" for line in listed)
            + (f"\n- and {more} more" if more > 0 else "")
        )
    mail = db.fetch_all(
        "SELECT id, subject, why, importance FROM threads WHERE account = ? AND in_trash = 0"
        " AND (status = 'waiting_on_you' OR (importance = 'high' AND status IN ('none', 'fyi')))"
        " AND id NOT IN (SELECT thread FROM matter_threads) ORDER BY importance = 'high' DESC, last_date DESC",
        (account,),
    )
    if mail:
        listed = [
            f"[mail:{m['id']}] {m['importance']}: {_short(m['subject'], 80)}: {_short(m['why'] or '', 120)}"
            for m in mail[:PLATE_LOOSE]
        ]
        more = len(mail) - len(listed)
        parts.append(
            "Other mail that may need them:\n"
            + "\n".join(f"- {line}" for line in listed)
            + (f"\n- and {more} more" if more > 0 else "")
        )
    from nexusai.modules.agent import briefs

    # The same list Today shows under the brief.
    finished = briefs.done_since(ctx, briefs.since_yesterday())
    if finished:
        listed = [
            f"- {item['address']} {_short(item['title'], 80)}, done {_local(item['when'])}"
            + (f": {_short(item['why'], 80)}" if item["why"] else "")
            for item in finished[:PLATE_LOOSE]
        ]
        more = len(finished) - len(listed)
        parts.append(
            "Done since yesterday:\n"
            + "\n".join(listed)
            + (f"\n- and {more} more" if more > 0 else "")
        )
    return "\n\n".join(parts)


def _local(moment: str | None) -> str:
    """A stored UTC time as the person's local day and time."""
    if not moment:
        return ""
    try:
        return datetime.fromisoformat(moment).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return moment[:16]
