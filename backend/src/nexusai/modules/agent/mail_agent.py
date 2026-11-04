"""Judges every email that escapes the fixed rules, as a run in the Mail agent's own chat."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any, Literal

import structlog

from nexusai.contracts.agent import (
    DraftedReply,
    ThreadRuns,
    ThreadSummary,
    TriageEstimate,
    TriageRun,
)
from nexusai.contracts.mail import MergeCategories
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    category_names,
    channel,
    feedback,
    gateway,
    guard,
    memory,
    prompts_builder,
    providers,
    signals,
)
from nexusai.modules.agent.context import TurnRequest
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.providers import Message
from nexusai.modules.mail import accounts
from nexusai.modules.mail import module as mail
from nexusai.modules.mail.rules import BUILT_IN_RULES, NO_REPLY
from nexusai.modules.planner import module as planner

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_triage_001",
    """
CREATE TABLE triage_queue (
  message INTEGER PRIMARY KEY, thread INTEGER NOT NULL, added TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, answer TEXT);
CREATE TABLE triage_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, message INTEGER NOT NULL, thread INTEGER NOT NULL, time TEXT NOT NULL, status TEXT NOT NULL,
  summary TEXT, reason TEXT, facts TEXT NOT NULL DEFAULT '[]', suggested_action TEXT, provisional INTEGER NOT NULL DEFAULT 0, error TEXT, call_id INTEGER);
CREATE INDEX triage_runs_thread ON triage_runs (thread, id);
CREATE TABLE thread_summaries (thread INTEGER PRIMARY KEY, text TEXT NOT NULL, covered INTEGER NOT NULL, updated TEXT NOT NULL);
""",
)
TRIGGER_MIGRATION = Migration(
    "agent_triggers_001",
    """
CREATE TABLE trigger_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL, event TEXT NOT NULL, time TEXT NOT NULL, status TEXT NOT NULL,
  message INTEGER, thread INTEGER, answer TEXT, schedule INTEGER, session TEXT, turn INTEGER, error TEXT, UNIQUE (trigger, event));
CREATE INDEX trigger_runs_status ON trigger_runs (status, trigger, id);
CREATE INDEX trigger_runs_turn ON trigger_runs (turn);
INSERT INTO trigger_runs (trigger, event, time, status, message, thread, answer)
  SELECT 'mail-received', 'earlier-' || message, added, 'pending', message, thread, answer FROM triage_queue;
DROP TABLE triage_queue;
ALTER TABLE triage_runs ADD COLUMN turn INTEGER;
""",
)
AGENT = "mail"
EVIDENCE_MIGRATION = Migration(
    "agent_triage_evidence_001",
    "ALTER TABLE triage_runs ADD COLUMN confidence TEXT NOT NULL DEFAULT 'medium';"
    "ALTER TABLE triage_runs ADD COLUMN review_reason TEXT;"
    "ALTER TABLE triage_runs ADD COLUMN source_messages TEXT NOT NULL DEFAULT '[]';"
    "ALTER TABLE triage_runs ADD COLUMN input_version INTEGER;",
)
SESSION_ID = "mail-agent"
MAIL_TRIGGER = "mail-received"
IMPORTANCE = {"low", "normal", "high"}
STATUSES = {"waiting_on_you", "waiting_on_others", "resolved", "fyi"}
NEXT_ACTIONS = {"reply", "do", "decide", "read"}
# How notices open, so it's clear what the person is being asked for.
NOTICE_OPENING = {"reply": "Reply needed", "do": "To do", "decide": "Decision needed"}
SENT_PREFIX = "sent-"
SENT_ORIGIN = "mail"
# A person can only take so many open questions, so past this the agent goes with its best guess.
MOST_OPEN_ASKS = 3
# When a follow-up comes up if the agent can't say, and how far back one gets looked for.
LOOK_BACK_DAYS = 30
MOST_ON_THE_PLATE = 15
# Names it makes up appear in the sidebar. Past this it has to use the ones that are there.
MOST_AGENT_CATEGORIES = 12
# Measured on a real mailbox: instructions, what's known about the person, and the mail itself.
APPROX_TOKENS_PER_MESSAGE = 7000
MailMode = Literal["each", "hourly", "both"]
UNREADABLE = "The agent didn't record a judgement, so this stays uncategorized."


def _now() -> str:
    return datetime.now(UTC).isoformat()


def enabled(ctx: Context) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT enabled FROM agent_triggers WHERE id = ?", (MAIL_TRIGGER,))
    return not rows or bool(rows[0]["enabled"])


def mode(ctx: Context) -> MailMode:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = 'mail_mode'")
    return "both" if not rows else rows[0]["value"]


def enqueue(
    ctx: Context, message: int, thread: int, answer: str | None = None, event: str | None = None
) -> None:
    """Replaying an event can't judge a message twice, because each event only counts once."""
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO trigger_runs (trigger, event, time, status, message, thread, answer)"
            " VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (MAIL_TRIGGER, event or uuid.uuid4().hex, _now(), message, thread, answer),
        )


# Reading past mail to learn about the person: nothing yet, reading, wrapping up, done.
LEARN_PREFIX = "learn-"
LEARNING_STATE = "mail_learning"
LEARNING_TURN = "mail_learning_turn"
LEARNING_TOTAL = "mail_learning_total"
LEARN_COUNT = "mail_learn_emails"
LEARNING_ORIGIN = "mail-learn"
NOT_FROM_RULES = (
    "m.account = ? AND m.folder_role = 'inbox' AND m.rule IS NULL AND NOT EXISTS"
    " (SELECT 1 FROM triage_runs r WHERE r.message = m.id)"
)


def _setting(ctx: Context, key: str) -> str | None:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = ?", (key,))
    return str(rows[0]["value"]) if rows else None


def _set(ctx: Context, key: str, value: str) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_defaults (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def learn_count(ctx: Context) -> int:
    return int(_setting(ctx, LEARN_COUNT) or ctx.config.agent.learn_emails)


def set_learn_count(ctx: Context, count: int) -> None:
    _set(ctx, LEARN_COUNT, str(count))


def learning_state(ctx: Context) -> str:
    return _setting(ctx, LEARNING_STATE) or ""


def set_learning_state(ctx: Context, state: str) -> None:
    _set(ctx, LEARNING_STATE, state)


def learning_turn(ctx: Context) -> int | None:
    found = _setting(ctx, LEARNING_TURN)
    return int(found) if found else None


def set_learning_turn(ctx: Context, turn: int) -> None:
    _set(ctx, LEARNING_TURN, str(turn))


def unjudged_count(ctx: Context) -> int:
    account = accounts.current_account(ctx.config)
    return int(
        ctx.bus.db.fetch_all(
            f"SELECT COUNT(*) AS n FROM messages m WHERE {NOT_FROM_RULES}",  # noqa: S608
            (account,),
        )[0]["n"]
    )


def _conversations(ctx: Context, limit: int) -> list[Any]:
    """Conversations the person wrote in and nobody has read yet, newest first. One message each."""
    own = signals.own_addresses(ctx)
    if not own or limit < 1:
        return []
    marks = ", ".join("?" * len(own))
    return ctx.bus.db.fetch_all(
        "SELECT MAX(m.id) AS id, m.thread_id, MAX(m.date) AS date FROM messages m"  # noqa: S608
        " WHERE m.account = ? AND m.folder_role NOT IN ('trash', 'junk')"
        f" AND m.thread_id IN (SELECT thread_id FROM messages WHERE LOWER(from_addr) IN ({marks}))"
        " AND NOT EXISTS (SELECT 1 FROM triage_runs r WHERE r.thread = m.thread_id)"
        " GROUP BY m.thread_id ORDER BY date DESC, id DESC LIMIT ?",
        (accounts.current_account(ctx.config), *own, limit),
    )


def conversations_not_read(ctx: Context) -> int:
    return len(_conversations(ctx, 1 << 20))


def queue_learning(ctx: Context, count: int | None = None) -> int:
    """What says the most about someone is what they wrote, so up to half is their own
    conversations and the rest is the newest mail rules didn't catch. Handed over oldest first,
    so what's learned builds up towards today."""
    account = accounts.current_account(ctx.config)
    wanted = count or learn_count(ctx)
    # Asking for more means their own conversations, which is what the button says.
    theirs = _conversations(ctx, wanted if count else wanted // 2 or wanted)
    newest = ctx.bus.db.fetch_all(
        f"SELECT m.id, m.thread_id, m.date FROM messages m WHERE {NOT_FROM_RULES}"  # noqa: S608
        " ORDER BY m.date DESC, m.id DESC LIMIT ?",
        (account, wanted),
    )
    chosen = {row["id"]: row for row in theirs}
    for row in newest:
        if count or len(chosen) >= wanted:
            break
        chosen.setdefault(row["id"], row)
    rows = sorted(chosen.values(), key=lambda row: (row["date"], row["id"]))
    for row in rows:
        enqueue(ctx, row["id"], row["thread_id"], event=f"{LEARN_PREFIX}{row['id']}")
    _set(ctx, LEARNING_TOTAL, str(len(rows)))
    set_learning_state(ctx, "reading")
    return len(rows)


def learning_progress(ctx: Context) -> tuple[int, int]:
    """How many of the past emails it's been through, and how many it set out to read."""
    total = int(_setting(ctx, LEARNING_TOTAL) or 0)
    left = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM trigger_runs WHERE trigger = ? AND event LIKE ?"
        " AND status IN ('pending', 'running')",
        (MAIL_TRIGGER, f"{LEARN_PREFIX}%"),
    )[0]["n"]
    return max(0, total - left), total


def has_learning_waiting(ctx: Context) -> bool:
    return bool(
        ctx.bus.db.fetch_all(
            "SELECT 1 FROM trigger_runs WHERE trigger = ? AND event LIKE ? AND status = 'pending'"
            " LIMIT 1",
            (MAIL_TRIGGER, f"{LEARN_PREFIX}%"),
        )
    )


def wrap_up_turn(ctx: Context) -> TurnRequest:
    """Turns the running notes into something the person, and the Interview, can read."""
    notes = memory.learned(ctx.config.home)
    task = f"<untrusted>\n{notes or 'No notes.'}\n</untrusted>"
    samples = signals.writing_samples(ctx, "")
    if samples:
        joined = "\n---\n".join(samples)
        task += f"\n\nHow they write, from their sent mail:\n<untrusted>\n{joined}\n</untrusted>"
    return TurnRequest(
        SESSION_ID,
        _template("mail-learned"),
        LEARNING_ORIGIN,
        _template("mail-learned-model"),
        task,
    )


def interview_turn(ctx: Context, session: str) -> TurnRequest:
    notes = memory.learned(ctx.config.home)
    task = f"<untrusted>\n{notes}\n</untrusted>" if notes else ""
    return TurnRequest(
        session,
        _template("interview-start"),
        "setup",
        _template("interview-start-model"),
        task,
    )


def ensure_session(ctx: Context) -> None:
    """One chat for this agent. Each email is a message and a reply inside it."""
    now = _now()
    scratch_folder(ctx.config.home, SESSION_ID)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO agent_sessions (id, title, agent, status, untrusted, created, updated)"
            " VALUES (?, 'Mail agent', 'mail', 'done', 1, ?, ?)",
            (SESSION_ID, now, now),
        )


def _header(ctx: Context, row: Any, own: set[str]) -> str:
    """Who it's to, because being in To or only in Cc changes what's being asked of them."""
    me = " (the person)" if row["from_addr"].lower() in own else ""
    lines = [
        f"[message {row['id']}] From {row['from_name']} <{row['from_addr']}>{me} on {row['date']}"
    ]
    lines += signals.recipient_lines(row["to_json"], row["cc_json"], own)
    files = ctx.bus.db.fetch_all(
        "SELECT filename FROM message_parts WHERE message = ? AND kind = 'attachment' LIMIT 5",
        (row["id"],),
    )
    if files:
        lines.append("Attached: " + ", ".join(str(item["filename"]) for item in files))
    return "\n".join(lines)


def _thread_text(
    ctx: Context, thread: int, limit_messages: int, limit_chars: int
) -> tuple[str, str, str]:
    """Recent messages within a size limit, plus the stored summary if there is one."""
    rows = ctx.bus.db.fetch_all(
        "SELECT id, from_name, from_addr, to_json, cc_json, date, subject, clean_text, encrypted"
        " FROM messages WHERE thread_id = ? GROUP BY message_id ORDER BY date DESC LIMIT ?",
        (thread, limit_messages),
    )
    own = signals.own_addresses(ctx)
    blocks: list[str] = []
    used = 0
    for row in rows:
        body = "[Encrypted: can't be read]" if row["encrypted"] else row["clean_text"]
        block = f"{_header(ctx, row, own)}\n{body}"
        if used + len(block) > limit_chars and blocks:
            break
        blocks.append(block[:limit_chars])
        used += len(block)
    subject = rows[0]["subject"] if rows else ""
    theirs = next((row for row in rows if row["from_addr"].lower() not in own), None)
    first = theirs or (rows[0] if rows else None)
    sender = (first["from_name"] or first["from_addr"]) if first else ""
    summary = ctx.bus.db.fetch_all("SELECT text FROM thread_summaries WHERE thread = ?", (thread,))
    note = f"Summary of the earlier conversation:\n{summary[0]['text']}\n\n" if summary else ""
    return subject, sender, f"{note}" + "\n\n".join(reversed(blocks))


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _template(name: str, **values: Any) -> str:
    """Our own wording, filled in here. What came from outside is only ever put in, never read."""
    text = resources.files(__package__).joinpath("prompts", "triggers", f"{name}.md")
    filled = text.read_text("utf-8").strip()
    for key, value in values.items():
        filled = filled.replace(f"{{{key}}}", str(value))
    return filled


def live_instruction() -> str:
    return _template("mail-model")


def task_for(
    ctx: Context, thread: int, answers: list[str] | None = None, live: bool = True
) -> tuple[str, str, str]:
    """What the model is given about one conversation: the mail, and the facts around it."""
    db = ctx.bus.db
    config = ctx.config.agent
    subject, sender, text = _thread_text(
        ctx, thread, config.max_recent_thread_messages, config.max_thread_chars
    )
    if not text:
        return subject, sender, ""
    task = f"<untrusted>\nSubject: {subject}\n\n{text}\n</untrusted>"
    facts = signals.about_thread(ctx, thread)
    if facts:
        task += f"\n\n{facts}"
    board = db.fetch_all(
        "SELECT kind, title, due FROM work_board WHERE thread = ? AND done = 0 ORDER BY id",
        (thread,),
    )
    if board:
        lines = "\n".join(f"- {r['kind']}: {r['title']} (due {r['due']})" for r in board)
        task += f"\n\nAlready on the work board for this conversation:\n<untrusted>\n{lines}\n</untrusted>"
    # Including what rules file into, which has no entry of its own until someone edits it.
    known = db.fetch_all(
        "SELECT name FROM mail_categories WHERE proposed = 0 UNION"
        " SELECT DISTINCT category FROM threads WHERE category IS NOT NULL ORDER BY 1"
    )
    if known:
        task += "\n\nCategories that exist: " + ", ".join(row[0] for row in known)
    waiting = db.fetch_all("SELECT name FROM mail_categories WHERE proposed = 1 ORDER BY 1")
    if waiting:
        task += "\n\nCategories already suggested: " + ", ".join(row[0] for row in waiting)
    if live:
        task += _style_samples(ctx, thread)
    if answers:
        task += "\n\nThe person answered your earlier question: " + " ".join(answers)
    return subject, sender, task


def _style_samples(ctx: Context, thread: int) -> str:
    """Only when a reply is possible, so the cost is only paid for mail that might need a draft."""
    rows = ctx.bus.db.fetch_all(
        "SELECT from_addr FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1", (thread,)
    )
    if not rows or NO_REPLY.search(rows[0]["from_addr"]):
        return ""
    thread_account = ctx.bus.db.fetch_all("SELECT account FROM threads WHERE id=?", (thread,))
    samples = signals.writing_samples(
        ctx, rows[0]["from_addr"], thread_account[0]["account"] if thread_account else None
    )
    if not samples:
        return ""
    joined = "\n---\n".join(samples)
    return f"\n\nHow the person writes, from their sent mail:\n<untrusted>\n{joined}\n</untrusted>"


def next_turn(
    ctx: Context, origin: str, own: dict[str, Any] | None = None
) -> tuple[TurnRequest, list[int]] | None:
    """The next conversation with mail waiting. A burst is one judgement, on its latest state."""
    db = ctx.bus.db
    config = ctx.config.agent
    while True:
        # New mail goes ahead of past mail, so catching up never holds it back.
        first = db.fetch_all(
            "SELECT thread FROM trigger_runs WHERE trigger = ? AND status = 'pending'"
            " ORDER BY event LIKE ?, id LIMIT 1",
            (MAIL_TRIGGER, f"{LEARN_PREFIX}%"),
        )
        if not first:
            return None
        thread = first[0]["thread"]
        rows = db.fetch_all(
            "SELECT id, message, answer, event FROM trigger_runs WHERE trigger = ? AND status = 'pending' AND thread = ?"
            " ORDER BY id LIMIT ?",
            (MAIL_TRIGGER, thread, config.triage_batch),
        )
        answers = [row["answer"] for row in rows if row["answer"]]
        learning = all(str(row["event"]).startswith(LEARN_PREFIX) for row in rows)
        version = db.fetch_all("SELECT decision_version FROM threads WHERE id = ?", (thread,))
        subject, sender, task = task_for(ctx, thread, answers, live=not learning)
        if task:
            break
        # The conversation has gone, so there's nothing left to judge.
        settle(ctx, [row["id"] for row in rows], "skipped")
    shown_subject = subject or "no subject"
    sent = all(str(row["event"]).startswith(SENT_PREFIX) for row in rows)
    if sent:
        shown = _template("mail-sent", subject=shown_subject)
        told = _template("mail-sent-model")
    elif learning:
        done, total = learning_progress(ctx)
        shown = _template(
            "mail-learn", done=done + 1, total=total, sender=sender, subject=shown_subject
        )
        told = _template("mail-learn-model")
        origin = LEARNING_ORIGIN
    elif answers:
        shown = _template("mail-answer", subject=shown_subject, answer=" ".join(answers))
        told = _template("mail-answer-model")
    elif len(rows) > 1:
        shown = _template("mail-many", count=len(rows), sender=sender, subject=shown_subject)
        told = _template("mail-model")
    else:
        shown = _template("mail-one", sender=sender, subject=shown_subject)
        told = _template("mail-model")
    target = {
        "thread": thread,
        "decision_version": version[0]["decision_version"] if version else None,
        "subject": subject,
        "messages": [{"message": r["message"], "answer": r["answer"]} for r in rows],
        "learning": learning,
        "sent": sent,
    }
    request = TurnRequest(SESSION_ID, shown, origin, told, task, target, own)
    return request, [row["id"] for row in rows]


def _plate_rows(ctx: Context, where: str, *params: Any) -> list[Any]:
    return ctx.bus.db.fetch_all(
        f"SELECT id, subject, why, last_date, follow_up_on, next_action, importance FROM threads WHERE {where}"  # noqa: S608
        " ORDER BY importance = 'high' DESC, last_date DESC LIMIT ?",
        (*params, MOST_ON_THE_PLATE),
    )


def needs_them(ctx: Context) -> list[Any]:
    return _plate_rows(
        ctx,
        "account = ? AND in_trash = 0 AND (status = 'waiting_on_you' OR (importance = 'high'"
        " AND status IN ('none', 'fyi')))",
        accounts.current_account(ctx.config),
    )


def to_chase(ctx: Context) -> list[Any]:
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return _plate_rows(
        ctx,
        "account = ? AND status = 'waiting_on_others' AND follow_up_on IS NOT NULL"
        " AND follow_up_on <= ? AND in_trash = 0",
        accounts.current_account(ctx.config),
        today,
    )


def _plate_lines(rows: list[Any]) -> str:
    return "\n".join(
        f"- [thread {r['id']}] {r['importance']}, {r['next_action'] or 'no action set'}:"
        f" {r['subject']}: {r['why'] or ''}"
        for r in rows
    )


def on_the_plate(ctx: Context) -> str:
    """What's open, from what's already been judged, so a brief doesn't have to read it all again."""
    parts = []
    needs = needs_them(ctx)
    if needs:
        parts.append(f"Needs them:\n{_plate_lines(needs)}")
    chase = to_chase(ctx)
    if chase:
        parts.append(f"Waiting on others, and it's time to chase:\n{_plate_lines(chase)}")
    return "\n\n".join(parts)


def brief_task(ctx: Context) -> str:
    from nexusai.modules.agent import briefs

    plate = on_the_plate(ctx)
    task = (
        briefs.snapshot(ctx)
        + f"\n\nOn their plate today:\n<untrusted>\n{plate or 'Nothing open.'}\n</untrusted>"
    )
    decisions: list[str] = []
    for label, query in (
        ("Approvals", "SELECT id, summary AS text FROM tool_approvals WHERE status = 'pending'"),
        (
            "Questions",
            "SELECT id, text FROM channel_messages WHERE kind = 'ask' AND status = 'open'",
        ),
        (
            "Mail suggestions",
            "SELECT id, category AS text FROM mail_suggestions WHERE status = 'open'",
        ),
        (
            "Proposed categories",
            "SELECT name AS id, name AS text FROM mail_categories WHERE proposed = 1",
        ),
    ):
        rows = ctx.bus.db.fetch_all(query)
        if rows:
            lines = "\n".join(f"- [{label} {row['id']}] {row['text']}" for row in rows[:20])
            decisions.append(f"{label}: {len(rows)} pending\n{lines}")
    if decisions:
        task += (
            "\n\nDecisions waiting for them:\n<untrusted>\n"
            + "\n\n".join(decisions)
            + "\n</untrusted>"
        )
    past = feedback.briefs_with_reactions(ctx.bus.db)
    if past:
        task += f"\n\nEarlier briefs and how they took them:\n<untrusted>\n{past}\n</untrusted>"
    return task


def review_turn(ctx: Context) -> TurnRequest | None:
    """Where whole groups of mail should go. Nothing to say about means no run at all."""
    table = signals.sender_table(ctx)
    waiting = [
        str(row["name"])
        for row in ctx.bus.db.fetch_all(
            "SELECT name FROM mail_categories WHERE proposed = 1 ORDER BY name"
        )
    ]
    categories = signals.category_table(ctx)
    if not table and not waiting and not categories:
        return None
    # These names came from reading mail, so they stay marked as untrusted too.
    named = f"\n\nCategories already suggested: {', '.join(waiting)}" if waiting else ""
    if categories:
        named += f"\n\nCategories not in the Priority inbox:\n{categories}"
    return TurnRequest(
        SESSION_ID,
        _template("mail-review"),
        "mail-review",
        _template("mail-review-model"),
        f"<untrusted>\n{table}{named}\n</untrusted>",
    )


def person_replied(ctx: Context, thread: int) -> None:
    """They've answered, so it's off their plate at once. The agent then works out what's next."""
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE threads SET status = 'waiting_on_others', next_action = NULL,"
            " follow_up_on = NULL, followup_notified = NULL WHERE id = ?",
            (thread,),
        )
        work.emit(
            "mail.changed", {"threads": 1, "reason": "sent"}, source="agent", trace_id=ctx.trace_id
        )
    asks = ctx.bus.db.fetch_all(
        "SELECT id FROM channel_messages WHERE thread = ? AND kind = 'ask' AND status = 'open'",
        (thread,),
    )
    for ask in asks:
        channel.close(ctx, ask["id"], "dismissed", None)


def they_answered(ctx: Context, message: int, thread: int) -> None:
    """A reply to what was being chased. Moved over now, in case the agent can't look for a while."""
    rows = ctx.bus.db.fetch_all("SELECT from_addr, rule FROM messages WHERE id = ?", (message,))
    # An out-of-office or a system notice isn't anyone answering.
    if not rows or rows[0]["rule"] or rows[0]["from_addr"].lower() in signals.own_addresses(ctx):
        return
    with ctx.bus.unit_of_work() as work:
        changed = work.tx.execute(
            "UPDATE threads SET status = 'waiting_on_you', follow_up_on = NULL,"
            " followup_notified = NULL, why = 'They replied' WHERE id = ? AND status = 'waiting_on_others'",
            (thread,),
        ).rowcount
        if changed:
            work.emit(
                "mail.changed",
                {"threads": 1, "reason": "reply"},
                source="agent",
                trace_id=ctx.trace_id,
            )


def tidy_categories(ctx: Context) -> int:
    """Once, for what was named before overlaps were caught. Needs no model, and reads no mail.

    The agent's own folders in one area become one, and overlapping suggestions become one.
    Returns how many suggestions are left, since only a model can tell HR from People team.
    """
    db = ctx.bus.db
    rows = db.fetch_all("SELECT name, source, proposed FROM mail_categories")
    accepted = [row for row in rows if row["proposed"] == 0]
    for row in sorted(accepted, key=lambda item: len(item["name"]), reverse=True):
        others = [other["name"] for other in accepted if other["name"] != row["name"]]
        area = category_names.area_of(row["name"], others)
        if row["source"] == "agent" and area and len(area) < len(row["name"]):
            mail.merge_categories(MergeCategories(names=[row["name"]], into=area), ctx)
            accepted = [other for other in accepted if other["name"] != row["name"]]
    settled = [str(row["name"]) for row in accepted]
    left: list[str] = []
    with db.transaction() as tx:
        for row in sorted((r for r in rows if r["proposed"] == 1), key=lambda r: len(r["name"])):
            name = str(row["name"])
            area = category_names.area_of(name, settled + left)
            if area is None:
                left.append(name)
                continue
            tx.execute(
                "UPDATE OR IGNORE mail_category_votes SET name = ? WHERE name = ?", (area, name)
            )
            tx.execute("UPDATE mail_categories SET proposed = 2 WHERE name = ?", (name,))
    if rows:
        with ctx.bus.unit_of_work() as work:
            work.emit("categories.changed", {}, source="agent", trace_id=ctx.trace_id)
    return len(left)


def suggest_priority(ctx: Context, name: str, reason: str) -> str:
    return mail.suggest_priority(ctx, name, reason)


def fold_suggestions(ctx: Context, keep: str, names: list[str]) -> str:
    """Only suggestions, none of them in use, so the person still decides on the one that's left."""
    db = ctx.bus.db
    waiting = {
        str(row["name"])
        for row in db.fetch_all("SELECT name FROM mail_categories WHERE proposed = 1")
    }
    if keep not in waiting:
        return f"{keep} isn't waiting as a suggestion."
    folded = [name for name in names if name in waiting and name != keep]
    with db.transaction() as tx:
        for name in folded:
            tx.execute(
                "UPDATE OR IGNORE mail_category_votes SET name = ? WHERE name = ?", (keep, name)
            )
            tx.execute("UPDATE mail_categories SET proposed = 2 WHERE name = ?", (name,))
    with ctx.bus.unit_of_work() as work:
        work.emit("categories.changed", {}, source="agent", trace_id=ctx.trace_id)
    return f"Folded {len(folded)} into {keep}."


def look_for_open_loops(ctx: Context) -> int:
    """Once, for mail sent before this ran: conversations they wrote last, still with no answer."""
    own = signals.own_addresses(ctx)
    if not own:
        return 0
    since = (datetime.now(UTC) - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    marks = ", ".join("?" * len(own))
    rows = ctx.bus.db.fetch_all(
        "SELECT t.id AS thread, MAX(m.id) AS message FROM threads t JOIN messages m ON m.thread_id = t.id"  # noqa: S608
        f" WHERE t.account = ? AND t.last_date > ? AND t.status = 'none' AND LOWER(m.from_addr) IN ({marks})"
        " AND m.date = t.last_date GROUP BY t.id",
        (accounts.current_account(ctx.config), since, *own),
    )
    for row in rows:
        enqueue(ctx, row["message"], row["thread"], event=f"{SENT_PREFIX}{row['message']}")
    return len(rows)


def digest_turn(ctx: Context, after: int) -> tuple[TurnRequest, int] | None:
    """Cover at most 100 durable judgements, with a lossless ID cursor across outages."""
    account = accounts.current_account(ctx.config)
    rows = ctx.bus.db.fetch_all(
        "SELECT r.id,r.thread,r.summary,t.subject,t.importance FROM triage_runs r JOIN threads t ON t.id=r.thread"
        " LEFT JOIN agent_turns a ON a.id=r.turn WHERE r.status='done' AND r.id>? AND t.account=? AND COALESCE(a.origin,'')!='mail-learn' ORDER BY r.id LIMIT 100",
        (after, account),
    )
    if not rows:
        return None
    latest = {r["thread"]: r for r in rows}
    lines = "\n".join(
        f"- [thread {r['thread']}] {r['importance']}: {r['subject']}: {r['summary']}"
        for r in latest.values()
    )
    plate = on_the_plate(ctx)
    held = f"Judgements {rows[0]['id']} through {rows[-1]['id']} (bounded catch-up):\n{lines}" + (
        f"\n\nStill open:\n{plate}" if plate else ""
    )
    task = f"{prompts_builder.packaged('mail-digest.md')}\n\n<untrusted>\n{held}\n</untrusted>"
    return TurnRequest(
        SESSION_ID,
        _template("mail-digest", count=len(latest)),
        "mail-hourly",
        _template("mail-digest-model"),
        task,
        context={"account": account},
    ), int(rows[-1]["id"])


def settle(ctx: Context, runs: list[int], status: str, error: str | None = None) -> None:
    with ctx.bus.db.transaction() as tx:
        for run in runs:
            tx.execute(
                "UPDATE trigger_runs SET status = ?, error = ? WHERE id = ?", (status, error, run)
            )


def after_turn(ctx: Context, turn: int, runs: list[Any], error: str | None) -> None:
    """A run that ended without a judgement leaves that mail uncategorized, and says why."""
    judged = ctx.bus.db.fetch_all("SELECT 1 FROM triage_runs WHERE turn = ? LIMIT 1", (turn,))
    if judged or not runs:
        settle(ctx, [run["id"] for run in runs], "done")
        return
    reason = error or UNREADABLE
    Triage(ctx)._failed(runs[0]["thread"], runs, reason)
    settle(ctx, [run["id"] for run in runs], "failed", reason)


def record(ctx: Context, session: str, fields: dict[str, Any]) -> str:
    with ctx.bus.db.serialized():
        return _record_current(ctx, session, fields)


def _record_current(ctx: Context, session: str, fields: dict[str, Any]) -> str:
    """What the record_triage tool does. It only reaches the email this run was started for."""
    rows = ctx.bus.db.fetch_all(
        "SELECT id, target FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    target = json.loads(rows[0]["target"]) if rows and rows[0]["target"] else None
    if not target or "thread" not in target:
        return "There's no new email in hand to judge in this run."
    turn = rows[0]["id"]
    if ctx.bus.db.fetch_all("SELECT 1 FROM triage_runs WHERE turn = ? LIMIT 1", (turn,)):
        return "This email is already judged."
    version = ctx.bus.db.fetch_all(
        "SELECT decision_version FROM threads WHERE id = ?", (target["thread"],)
    )
    if not version or version[0]["decision_version"] != target.get("decision_version"):
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE trigger_runs SET status = 'pending', turn = NULL, session = NULL WHERE turn = ? AND status = 'running'",
                (turn,),
            )
        return "The conversation changed while I was reading. This judgement was discarded and queued again; no decision was overwritten."
    supplied = fields.get("source_messages") or [row["message"] for row in target["messages"]]
    valid = {
        row["id"]
        for row in ctx.bus.db.fetch_all(
            "SELECT id FROM messages WHERE thread_id=?", (target["thread"],)
        )
    }
    if not all(isinstance(identifier, int) and identifier in valid for identifier in supplied):
        return "Judgement not recorded: the source messages must belong to this conversation."
    fields = {**fields, "source_messages": supplied}
    Triage(ctx)._apply(
        target["thread"],
        target["messages"],
        target["subject"],
        fields,
        turn,
        learning=bool(target.get("learning")),
        sent=bool(target.get("sent")),
    )
    return f"Filed as {fields.get('category') or 'uncategorized'}, {fields.get('importance', 'normal')} importance."


class Triage:
    """Applies what the agent decided about one conversation."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def _failed(self, thread: int, rows: list[Any], error: str) -> None:
        """A flagged email stays uncategorized, and shows why."""
        message = f"Not triaged: {error}"
        with self.ctx.bus.unit_of_work() as work:
            for row in rows:
                work.tx.execute(
                    "INSERT INTO triage_runs (message, thread, time, status, error) VALUES (?, ?, ?, 'failed', ?)",
                    (row["message"], thread, _now(), error),
                )
            work.tx.execute(
                "UPDATE threads SET why = ? WHERE id = ? AND COALESCE(category_source, '') != 'user'",
                (message, thread),
            )
            work.emit(
                "mail.triaged",
                {"thread_id": thread, "status": "failed"},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
            work.emit(
                "mail.changed",
                {"threads": 1, "reason": "triage"},
                source="agent",
                trace_id=self.ctx.trace_id,
            )

    def _is_old(self, thread: int) -> bool:
        rows = self.ctx.bus.db.fetch_all("SELECT last_date FROM threads WHERE id = ?", (thread,))
        days = self.ctx.config.agent.learn_recent_days
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return not rows or str(rows[0]["last_date"]) < since

    def _apply(
        self,
        thread: int,
        rows: list[Any],
        subject: str,
        parsed: dict[str, Any],
        turn: int,
        *,
        learning: bool = False,
        sent: bool = False,
    ) -> None:
        ctx = self.ctx
        calls = ctx.bus.db.fetch_all(
            "SELECT MAX(id) AS id FROM model_calls WHERE session = ?", (SESSION_ID,)
        )
        call_id = calls[0]["id"]
        importance = (
            parsed.get("importance") if parsed.get("importance") in IMPORTANCE else "normal"
        )
        status = parsed.get("status") if parsed.get("status") in STATUSES else "fyi"
        category = str(parsed["category"])[:64] if parsed.get("category") else None
        reason = str(parsed.get("reason") or "")[:500]
        summary = str(parsed.get("summary") or "")[:1000]
        action = str(parsed["suggested_action"])[:500] if parsed.get("suggested_action") else None
        # Once the person has answered, the agent decides. Asking again could go on forever.
        answered = any(row["answer"] for row in rows)
        question = (
            str(parsed["question"])[:500] if parsed.get("question") and not answered else None
        )
        provisional = bool(question)
        why = f"{reason} (a best guess until you answer)" if provisional else reason
        category = self._settled_category(category, thread)
        next_action = parsed.get("next_action")
        next_action = next_action if next_action in NEXT_ACTIONS else None
        if status not in {"waiting_on_you", "fyi"} or (status == "fyi" and next_action != "read"):
            next_action = None
        follow_up = _valid_date(parsed.get("follow_up_on"))
        latest = max(row["message"] for row in rows)
        # A person can only take so many open questions. Past that it goes with its best guess.
        if question and self._open_asks() >= MOST_OPEN_ASKS:
            question = None
            provisional = False
            why = reason
        # Interrupting is decided apart from importance, but high means it if nothing's said.
        notify = parsed.get("notify")
        notify = importance == "high" if notify is None else bool(notify)
        # Past mail is read to learn from. It can't ask, notify or add work, however it reads.
        if learning:
            question = None
            provisional = False
            why = reason
            notify = False
            if self._is_old(thread):
                importance, status, next_action, follow_up = "normal", "fyi", None, None
        # Their own message: all that's left to say is what comes next.
        if sent:
            question = None
            provisional = False
            notify = False
            why = reason
            parsed = {**parsed, "draft": None, "memory": None, "suggest_category": None}
            if status not in {"waiting_on_others", "resolved"}:
                status = "waiting_on_others"
            if status != "waiting_on_others":
                follow_up = None
        with ctx.bus.unit_of_work() as work:
            for row in rows:
                work.tx.execute(
                    "INSERT INTO triage_runs (message, thread, time, status, summary, reason, facts, suggested_action, provisional, call_id, turn)"
                    " VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["message"],
                        thread,
                        _now(),
                        summary,
                        reason,
                        json.dumps(_strings(parsed.get("facts"))),
                        action,
                        int(provisional),
                        call_id,
                        turn,
                    ),
                )
                work.tx.execute("UPDATE messages SET why = ? WHERE id = ?", (why, row["message"]))
            work.tx.execute(
                "UPDATE triage_runs SET confidence=?,review_reason=?,source_messages=?,input_version=(SELECT decision_version FROM threads WHERE id=?) WHERE turn=?",
                (
                    parsed.get("confidence", "medium"),
                    parsed.get("review_reason"),
                    json.dumps(parsed.get("source_messages", [])),
                    thread,
                    turn,
                ),
            )
            # What the person chose stays, and so does what their rule filed.
            if not sent:
                # A header rule only guessed. In a conversation they're part of, the agent knows better.
                guessed = int(self._rule_only_guessed(thread))
                work.tx.execute(
                    "UPDATE threads SET category = ?, category_source = 'agent', why = ? WHERE id = ?"
                    " AND (COALESCE(category_source, '') NOT IN ('user', 'rule')"
                    " OR (category_source = 'rule' AND ? = 1))",
                    (category, why, thread, guessed),
                )
                work.tx.execute(
                    "UPDATE threads SET importance = ? WHERE id = ? AND (importance_user_message IS NULL OR importance_user_message < (SELECT MAX(id) FROM messages WHERE thread_id=?))",
                    (importance, thread, thread),
                )
            work.tx.execute(
                "UPDATE threads SET status = ?, next_action = ?, follow_up_on = ?,"
                " followup_notified = NULL WHERE id = ? AND (status_user_message IS NULL OR status_user_message < (SELECT MAX(id) FROM messages WHERE thread_id=?))",
                (
                    status,
                    next_action,
                    follow_up if status == "waiting_on_others" else None,
                    thread,
                    thread,
                ),
            )
            if sent:
                work.tx.execute("UPDATE threads SET why = ? WHERE id = ?", (why, thread))
            work.emit(
                "mail.triaged",
                {"thread_id": thread, "status": "done"},
                source="agent",
                trace_id=ctx.trace_id,
            )
            work.emit(
                "mail.changed",
                {"threads": 1, "reason": "triage"},
                source="agent",
                trace_id=ctx.trace_id,
            )
            if notify:
                opening = NOTICE_OPENING.get(next_action or "", "Important")
                channel.notify(
                    ctx,
                    work,
                    f"{opening}: {subject or 'new mail'}",
                    summary,
                    f"/mail/thread/{thread}",
                    "urgent-mail",
                    True,
                )
                work.emit(
                    "mail.urgent", {"thread_id": thread}, source="agent", trace_id=ctx.trace_id
                )
        if not sent:
            self._note_category(category)
        self._suggest_category(parsed.get("suggest_category"), thread)
        memory.add_learned(ctx.config.home, _strings(parsed.get("learned")), thread)
        if learning:
            return
        self._proposals(thread, parsed, subject)
        if question:
            channel.post(
                ctx,
                "ask",
                "Mail agent",
                question,
                session=SESSION_ID,
                thread=thread,
                urgent=importance == "high",
                triage_message=latest,
            )

    def _rule_only_guessed(self, thread: int) -> bool:
        db = self.ctx.bus.db
        own = signals.own_addresses(self.ctx)
        rows = db.fetch_all("SELECT from_addr, rule FROM messages WHERE thread_id = ?", (thread,))
        wrote = any(row["from_addr"].lower() in own for row in rows)
        applied = {row["rule"] for row in rows if row["rule"]}
        return wrote and applied <= BUILT_IN_RULES

    def _settled_category(self, category: str | None, thread: int) -> str | None:
        """So "Job Search" and "Job search" or "HR" and "HR feedback" don't become two folders."""
        if not category:
            return None
        db = self.ctx.bus.db
        waiting = [
            str(row["name"])
            for row in db.fetch_all("SELECT name FROM mail_categories WHERE proposed = 1")
        ]
        # Waiting on the person: filed under it already, and it appears if they say yes.
        if name := category_names.area_of(category, waiting):
            self._vote(name, thread)
            return name
        known = db.fetch_all(
            "SELECT name, source FROM mail_categories WHERE proposed = 0 UNION"
            " SELECT DISTINCT category, 'rule' FROM threads WHERE category IS NOT NULL"
        )
        if settled := category_names.area_of(category, [str(row["name"]) for row in known]):
            return settled
        made = sum(1 for row in known if row["source"] == "agent")
        return None if made >= MOST_AGENT_CATEGORIES else category.strip()

    def _vote(self, name: str, thread: int) -> None:
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT OR IGNORE INTO mail_category_votes (name, thread) VALUES (?, ?)",
                (name, thread),
            )
            work.emit("categories.changed", {}, source="agent", trace_id=self.ctx.trace_id)

    def _open_asks(self) -> int:
        return int(
            self.ctx.bus.db.fetch_all(
                "SELECT COUNT(*) AS n FROM channel_messages WHERE kind = 'ask' AND status = 'open'"
                " AND session = ?",
                (SESSION_ID,),
            )[0]["n"]
        )

    def _note_category(self, category: str | None) -> None:
        """A name the agent came up with appears in the sidebar, marked as the agent's."""
        if not category:
            return
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, created) VALUES (?, 'agent', ?)",
                (category, _now()),
            )

    def _suggest_category(self, suggestion: Any, thread: int) -> None:
        """Mail that keeps coming from one place. Once enough does, the person decides, on Today."""
        if not isinstance(suggestion, dict) or not suggestion.get("name"):
            return
        name = str(suggestion["name"]).strip()[:64]
        db = self.ctx.bus.db
        rows = db.fetch_all("SELECT name, proposed FROM mail_categories")
        taken = [str(row["name"]) for row in rows] + [
            str(row["category"])
            for row in db.fetch_all(
                "SELECT DISTINCT category FROM threads WHERE category IS NOT NULL"
            )
        ]
        area = category_names.area_of(name, taken)
        waiting = {str(row["name"]) for row in rows if row["proposed"] == 1}
        if area and area not in waiting:
            return
        if not area:
            with db.transaction() as tx:
                tx.execute(
                    "INSERT OR IGNORE INTO mail_categories"
                    " (name, source, proposed, needs_votes, why, sender, created)"
                    " VALUES (?, 'agent', 1, 1, ?, ?, ?)",
                    (
                        name,
                        str(suggestion.get("reason") or "")[:500],
                        str(suggestion.get("sender") or "")[:320] or None,
                        _now(),
                    ),
                )
        self._vote(area or name, thread)

    def _proposals(self, thread: int, parsed: dict[str, Any], subject: str) -> None:
        """The agent proposes. The person accepts tasks and reminders, and sends drafts."""
        ctx = self.ctx
        for item in parsed.get("deadlines") or []:
            if isinstance(item, dict) and item.get("what"):
                channel.board_add(
                    ctx,
                    "deadline",
                    str(item["what"])[:300],
                    thread,
                    _valid_date(item.get("due")),
                    "Mail agent",
                )
        for item in parsed.get("tasks") or []:
            if (
                isinstance(item, dict)
                and item.get("title")
                and not planner.has_task(ctx.bus.db, str(item["title"])[:500], thread)
            ):
                planner.add_task(
                    ctx,
                    str(item["title"])[:500],
                    _valid_date(item.get("due")),
                    thread,
                    "agent",
                    True,
                )
        for item in parsed.get("reminders") or []:
            if (
                isinstance(item, dict)
                and item.get("title")
                and _valid_moment(item.get("when"))
                and not planner.has_reminder(ctx.bus.db, str(item["title"])[:500], thread)
            ):
                planner.add_reminder(
                    ctx,
                    str(item["title"])[:500],
                    str(item["when"])[:16],
                    "none",
                    thread,
                    None,
                    "agent",
                    True,
                )
        if parsed.get("draft"):
            self._draft(thread, str(parsed["draft"]), subject)
        if parsed.get("memory"):
            memory.propose(
                ctx.bus.db, "Mail agent", str(parsed["memory"])[:2000], f"/mail/thread/{thread}"
            )

    def _draft(self, thread: int, body: str, subject: str) -> None:
        ctx = self.ctx
        rows = ctx.bus.db.fetch_all(
            "SELECT id, from_addr FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1",
            (thread,),
        )
        if not rows:
            return
        # Whatever is there may have the person's edits in it, so it's left alone.
        if ctx.bus.db.fetch_all(
            "SELECT id FROM mail_drafts WHERE json_extract(body, '$.thread_id') = ?", (thread,)
        ):
            return
        draft = {
            "thread_id": thread,
            "reply_to_message_id": rows[0]["id"],
            "to": [{"name": "", "address": rows[0]["from_addr"]}]
            if "@" in rows[0]["from_addr"]
            else [],
            "cc": [],
            "bcc": [],
            "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
            "body": body,
            "source": "agent",
        }
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO mail_drafts (body, updated) VALUES (?, ?)", (json.dumps(draft), _now())
            )
            work.emit("drafts.changed", {}, source="agent", trace_id=ctx.trace_id)


def _valid_date(value: Any) -> str | None:
    text = str(value or "")
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def _valid_moment(value: Any) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*", str(value or "")))


def thread_runs(ctx: Context, thread: int) -> ThreadRuns:
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM triage_runs WHERE thread = ? ORDER BY id DESC LIMIT 50", (thread,)
    )
    return ThreadRuns(
        runs=[
            TriageRun(
                id=r["id"], message=r["message"], thread=r["thread"], time=r["time"], status=r["status"],
                summary=r["summary"], reason=r["reason"], facts=json.loads(r["facts"]), suggested_action=r["suggested_action"],
                provisional=bool(r["provisional"]), error=r["error"], call_id=r["call_id"],
            )
            for r in rows
        ]
    )  # fmt: skip


def waiting_count(ctx: Context) -> int:
    rows = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM trigger_runs WHERE trigger = ? AND status IN ('pending', 'running')",
        (MAIL_TRIGGER,),
    )
    return int(rows[0]["n"])


def estimate(ctx: Context) -> TriageEstimate:
    account = accounts.current_account(ctx.config)
    rows = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM messages m WHERE m.account = ? AND m.folder_role = 'inbox' AND m.rule IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM triage_runs r WHERE r.message = m.id)"
        " AND NOT EXISTS (SELECT 1 FROM trigger_runs q WHERE q.message = m.id AND q.status IN ('pending', 'running'))",
        (account,),
    )
    queued = waiting_count(ctx)
    return TriageEstimate(
        untriaged=rows[0]["n"],
        queued=queued,
        approx_tokens=rows[0]["n"] * APPROX_TOKENS_PER_MESSAGE,
    )


def queue_existing(ctx: Context) -> None:
    account = accounts.current_account(ctx.config)
    rows = ctx.bus.db.fetch_all(
        "SELECT m.id, m.thread_id FROM messages m WHERE m.account = ? AND m.folder_role = 'inbox' AND m.rule IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM triage_runs r WHERE r.message = m.id)",
        (account,),
    )
    for row in rows:
        enqueue(ctx, row["id"], row["thread_id"], event=f"existing-{row['id']}")


def summary_view(ctx: Context, thread: int) -> ThreadSummary:
    from nexusai.modules.agent import summaries

    return summaries.view(ctx, thread)


def _ready_draft(ctx: Context, thread: int) -> DraftedReply | None:
    """What's already written for this conversation, unless mail has come in since."""
    rows = ctx.bus.db.fetch_all(
        "SELECT d.id, d.body FROM mail_drafts d JOIN threads t ON t.id = ?"
        " WHERE json_extract(d.body, '$.thread_id') = ? AND d.updated >= t.last_date"
        " ORDER BY d.updated DESC LIMIT 1",
        (thread, thread),
    )
    if not rows:
        return None
    body = str(json.loads(rows[0]["body"]).get("body") or "").strip()
    return DraftedReply(body=body, draft_id=rows[0]["id"]) if body else None


def draft_reply(ctx: Context, thread: int) -> DraftedReply:
    """Only when asked, and only words for the person to check. Nothing is saved or sent."""
    if ready := _ready_draft(ctx, thread):
        return ready
    version = ctx.bus.db.fetch_all("SELECT decision_version FROM threads WHERE id=?", (thread,))
    config = ctx.config.agent
    subject, _, text = _thread_text(
        ctx, thread, config.max_recent_thread_messages, config.max_thread_chars
    )
    if not text:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    latest = ctx.bus.db.fetch_all(
        "SELECT from_addr FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1", (thread,)
    )
    if latest and NO_REPLY.search(latest[0]["from_addr"]):
        raise CommandError(
            "draft.no_reply",
            "This came from an address nobody reads, so there's no one to reply to.",
            409,
        )
    task = (
        f"<untrusted>\nSubject: {subject}\n\n{text}\n</untrusted>{_style_samples(ctx, thread)}"
        "\n\nWrite the reply now."
    )
    from nexusai.modules.agent import knowledge

    thread_account = ctx.bus.db.fetch_all("SELECT account FROM threads WHERE id=?", (thread,))
    layers: list[Layer] = knowledge.layers_for(
        ctx, "draft-reply", task, account=thread_account[0]["account"] if thread_account else None
    )
    try:
        result = gateway.call_model(
            ctx, agent="draft-reply", session=None, layers=layers, messages=[Message("user", task)]
        )
    except (
        providers.ModelUnavailable,
        providers.ModelNotConfigured,
        providers.ModelFlagged,
        gateway.DailyCapReached,
        guard.GuardBlocked,
    ) as error:
        raise CommandError("draft.failed", str(error), 502) from error
    body = result.text.strip()
    if not body:
        raise CommandError("draft.failed", "The model didn't write anything. Try again.", 502)
    current = ctx.bus.db.fetch_all("SELECT decision_version FROM threads WHERE id=?", (thread,))
    if (
        not version
        or not current
        or current[0]["decision_version"] != version[0]["decision_version"]
    ):
        raise CommandError(
            "draft.changed",
            "This conversation changed while the reply was being written. Generate it again.",
            409,
        )
    return DraftedReply(body=body)


def summarize(ctx: Context, thread: int) -> ThreadSummary:
    from nexusai.modules.agent import summaries

    return summaries.generate(ctx, thread)
