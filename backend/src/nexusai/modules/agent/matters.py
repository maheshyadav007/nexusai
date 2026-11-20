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
    MatterLane,
    MatterMark,
    MatterRow,
    MattersBrief,
    MattersWeek,
    MatterThread,
    MatterWork,
)
from nexusai.kernel import textmatch
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import conversations, signals
from nexusai.modules.mail import accounts
from nexusai.modules.mail.parse import normalize_subject
from nexusai.modules.mail.source import thread_source

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
BACKFILLED = "matters_backfilled"
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


def _score(this: dict[str, Any], other: dict[str, Any]) -> tuple[int, str]:
    """How sure code can be that two sets of conversations are one thing, and why, in words."""
    points, why = 0, []
    shared = sorted(this["ids"] & other["ids"], key=len, reverse=True)
    if shared:
        points += JOIN_AT
        why.append(f"Both mention {shared[0].upper()}")
    if this["senders"] & other["senders"] and any(
        textmatch.same(a, b, 0.6) for a in this["subjects"] for b in other["subjects"]
    ):
        points += 4
        why.append("Same sender, about the same subject")
    common = (this["people"] & other["people"]) - this["senders"]
    if len(common) >= 2:
        points += 2
        why.append(f"Same people ({len(common)})")
    return points, "; ".join(why)


def _candidates(
    db: Database, account: str, thread: int, own: set[str]
) -> list[tuple[int, int, str]]:
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
        points, why = _score(this, _facts(db, threads, own))
        if points:
            scored.append((points, int(row["id"]), why))
    return sorted(scored, reverse=True)


def link(ctx: Context, thread: int, *, time: str | None = None, start: bool = True) -> int | None:
    """The conversation's matter, joined or started, and its newest email on the timeline.

    Only mail that needs something starts a matter; a fyi conversation stays a conversation.
    Mail the rules kept from the agent (start=False), like a review tool's notice, can still
    join a matter code is sure of, but never starts one.
    """
    db = ctx.bus.db
    rows = db.fetch_all(
        f"SELECT id, account, subject, why, ({NEEDS}) AS needs FROM threads WHERE id = ?",  # noqa: S608
        (thread,),
    )
    existing = matter_of(db, thread)
    if not rows or (existing is None and start and not rows[0]["needs"]):
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
            best = found[0] if found else None
            second = found[1][0] if len(found) > 1 else 0
            if best and best[0] >= JOIN_AT and second <= best[0] - CLEAR_BY:
                matter = best[1]
                work.tx.execute(
                    "INSERT INTO matter_threads (thread, matter, how, why, linked) VALUES (?, ?, 'rule', ?, ?)",
                    (thread, matter, best[2], _now()),
                )
                _event(
                    work.tx, matter, "joined", _title(row["subject"]),
                    why=best[2], thread=thread, message=message["id"], time=time or message["date"],
                )  # fmt: skip
            elif not start:
                return None
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
    ctx: Context, thread: int | None, kind: str, text: str, why: str = "", by: str = "engine"
) -> None:
    """A change to a conversation's work, on its matter's timeline. Nothing when there's none."""
    if not thread:
        return
    matter = matter_of(ctx.bus.db, thread)
    if matter is None:
        return
    with ctx.bus.unit_of_work() as work:
        _event(work.tx, matter, kind, text, why=why, thread=thread, by=by)
        work.emit("matters.changed", {"matter": matter}, source="agent", trace_id=ctx.trace_id)


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
    return db.fetch_all(
        "SELECT t.*, mt.how, mt.why AS link_why FROM matter_threads mt JOIN threads t ON t.id = mt.thread"
        " WHERE mt.matter = ? ORDER BY t.last_date",
        (matter,),
    )


def _work(db: Database, threads: list[int]) -> list[MatterWork]:
    if not threads:
        return []
    marks = ",".join("?" * len(threads))
    found = [
        MatterWork(
            kind="task",
            id=r["id"],
            title=r["title"],
            when=r["due"],
            thread=r["thread"],
            proposed=bool(r["proposed"]),
        )
        for r in db.fetch_all(
            f"SELECT * FROM tasks WHERE status != 'done' AND thread IN ({marks}) ORDER BY due IS NULL, due",
            tuple(threads),
        )  # noqa: S608
    ]
    found += [
        MatterWork(
            kind="reminder",
            id=r["id"],
            title=r["title"],
            when=r["due_at"],
            thread=r["thread"],
            proposed=bool(r["proposed"]),
        )
        for r in db.fetch_all(
            f"SELECT * FROM reminders WHERE fired = 0 AND thread IN ({marks}) ORDER BY due_at",
            tuple(threads),
        )  # noqa: S608
    ]
    found += [
        MatterWork(kind="deadline", id=r["id"], title=r["title"], when=r["due"], thread=r["thread"])
        for r in db.fetch_all(f"SELECT * FROM work_board WHERE done = 0 AND kind = 'deadline' AND thread IN ({marks})", tuple(threads))  # noqa: S608
    ]  # fmt: skip
    return found


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
    work = _work(db, ids)
    state = (
        "waiting_on_you"
        if "waiting_on_you" in statuses or any(w.kind == "task" for w in work)
        else "waiting_on_others"
        if "waiting_on_others" in statuses
        else "fyi"
        if any(t["importance"] == "high" and t["status"] in {"none", "fyi"} for t in threads)
        else "done"
    )
    dates = sorted(w.when for w in work if w.when)
    task = next((w for w in work if w.kind == "task"), None)
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
        started=db.fetch_all(
            "SELECT MIN(time) AS t FROM matter_events WHERE matter = ?", (matter["id"],)
        )[0]["t"],
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
    titles = {m["id"]: m["title"] for m in db.fetch_all("SELECT id, title FROM matters")}
    # The day's changes stay listed; the page marks the ones that came after the person looked.
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    events = db.fetch_all(
        "SELECT * FROM matter_events WHERE time > ? ORDER BY time DESC, id DESC LIMIT ?",
        (since, MOST_CHANGES),
    )
    soon = (datetime.now().astimezone() + timedelta(hours=SOON_HOURS)).strftime("%Y-%m-%dT%H:%M")
    upcoming = sorted(
        (
            MatterDue(matter=r.id, title=r.title, what=w.title, when=w.when, kind=w.kind)
            for r in rows
            for w in r.work
            if w.when and w.when <= soon
        ),
        key=lambda item: item.when,
    )
    return MattersBrief(
        seen=seen,
        changes=[_change(db, e, titles) for e in events],
        needs_you=[r for r in rows if r.state == "waiting_on_you"],
        waiting=[r for r in rows if r.state == "waiting_on_others"],
        fyi=[r for r in rows if r.state == "fyi"],
        next=upcoming,
    )


def week(ctx: Context, start: str | None) -> MattersWeek:
    db = ctx.bus.db
    today = datetime.now().astimezone().date()
    monday = date.fromisoformat(start) if start else today - timedelta(days=today.weekday())
    begin, end = monday.isoformat(), (monday + timedelta(days=7)).isoformat()
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
        for e in db.fetch_all(
            "SELECT time, text FROM matter_events WHERE matter = ? AND kind IN ('closed', 'done') AND time >= ? AND time < ?",
            (matter.id, _utc(begin), _utc(end)),
        ):
            marks.append(MatterMark(time=e["time"], kind="closed", label=e["text"]))
        if marks or matter.state != "done":
            lanes.append(MatterLane(matter=matter, marks=sorted(marks, key=lambda mark: mark.time)))
    lanes = [lane for lane in lanes if lane.marks or lane.matter.state != "done"]
    return MattersWeek(start=begin, lanes=lanes)


def _utc(day: str) -> str:
    """Midnight local time on that day, as the UTC text messages are stored with."""
    local = datetime.fromisoformat(day).astimezone()
    return local.astimezone(UTC).isoformat()


def detail(ctx: Context, matter: int) -> MatterDetail:
    db = ctx.bus.db
    found = db.fetch_all("SELECT * FROM matters WHERE id = ?", (matter,))
    if not found:
        raise CommandError("matter.not_found", "That matter no longer exists.", 404)
    threads = _threads_of(db, matter)
    titles = {matter: found[0]["title"]}
    return MatterDetail(
        matter=row(ctx, found[0]),
        events=[
            _change(db, e, titles)
            for e in db.fetch_all(
                "SELECT * FROM matter_events WHERE matter = ? ORDER BY time DESC, id DESC LIMIT 200",
                (matter,),
            )
        ],
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
