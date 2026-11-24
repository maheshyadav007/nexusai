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
from nexusai.kernel import textmatch
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    bulk_learning,
    cards,
    category_names,
    channel,
    citations,
    feedback,
    gateway,
    guard,
    kinds,
    matters,
    memory,
    prompts_builder,
    providers,
    signals,
)
from nexusai.modules.agent.context import TurnRequest
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.prompt_data import untrusted
from nexusai.modules.agent.providers import CONTEXT_HELP, Message
from nexusai.modules.mail import accounts, mentions
from nexusai.modules.mail import rules as mail_rules
from nexusai.modules.mail import store as mail_store
from nexusai.modules.mail.rules import FILED_BY_RULE, NO_REPLY
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
    # Judging each email is the default. An hourly digest is only wanted by those who choose it.
    return "each" if not rows else rows[0]["value"]


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
# Header-rule folders the agent may also use, for mail whose headers didn't say what it is.
FALLBACK_DESCRIPTIONS = {
    "Promotions": "Marketing, offers, sales and newsletters, including ones the header rules missed",
    "Updates": "Automated notices: receipts, statements, alerts and account or order updates",
}
NOT_FROM_RULES = (
    "m.account = ? AND m.folder_role = 'inbox' AND m.rule IS NULL AND NOT EXISTS"
    " (SELECT 1 FROM triage_runs r WHERE r.message = m.id) AND NOT EXISTS (SELECT 1 FROM threads t"
    f" WHERE t.id = m.thread_id AND {mail_store.hidden_from_ai('t.category')})"
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
    return bulk_learning.unseen_count(ctx)


def queue_learning(ctx: Context, count: int | None = None) -> int:
    """Imports learn all new groups; an explicit manual request can bound new groups per click."""
    return bulk_learning.queue(ctx, retry_failed=count is not None, limit_groups=count)


def learning_progress(ctx: Context) -> tuple[int, int]:
    """How many of the past emails it's been through, and how many it set out to read."""
    if _setting(ctx, "mail_group_learning") or ctx.bus.db.fetch_all(
        "SELECT 1 FROM mail_learning_batches LIMIT 1"
    ):
        rows = ctx.bus.db.fetch_all(
            "SELECT COUNT(*) AS total, SUM(learned) AS done FROM mail_learning_groups WHERE account=?",
            (accounts.current_account(ctx.config),),
        )[0]
        return int(rows["done"] or 0), int(rows["total"])
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
    task = untrusted(notes or "No notes.")
    samples = signals.writing_samples(ctx, "")
    if samples:
        joined = "\n---\n".join(samples)
        task += "\n\nHow they write, from their sent mail:\n" + untrusted(joined)
    return TurnRequest(
        SESSION_ID,
        _template("mail-learned"),
        LEARNING_ORIGIN,
        _template("mail-learned-model"),
        task,
    )


def interview_turn(ctx: Context, session: str) -> TurnRequest:
    from nexusai.modules.agent import facts

    account = accounts.current_account(ctx.config)
    notes = facts.layer(
        ctx, account, "mail priorities and uncertainties", ctx.config.agent.memory_max_chars
    )
    task = (
        "Learned context for this account (hypotheses remain unconfirmed):\n" + notes
        if notes
        else ""
    )
    return TurnRequest(
        session,
        _template("interview-start"),
        "setup",
        _template("interview-start-model"),
        task,
        context={"account": account},
    )


def ensure_session(ctx: Context) -> None:
    """One chat for this agent. Each email is a message and a reply inside it."""
    now = _now()
    scratch_folder(ctx.config.home, SESSION_ID)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO agent_sessions (id, title, agent, status, untrusted, created, updated)"
            " VALUES (?, ?, ?, 'done', 1, ?, ?)",
            (SESSION_ID, cards.name(ctx.bus.db, AGENT), AGENT, now, now),
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
    """Recent messages within a size limit, newest first, plus the stored summary if there is one."""
    rows = ctx.bus.db.fetch_all(
        "SELECT id, from_name, from_addr, to_json, cc_json, date, subject, clean_text, encrypted"
        " FROM messages WHERE thread_id = ? GROUP BY message_id ORDER BY date DESC LIMIT ?",
        (thread, limit_messages),
    )
    own = signals.own_addresses(ctx)
    blocks: list[str] = []
    used = 0
    # A reminder that repeats an earlier email word for word is said once: the oldest in full,
    # the rest as a pointer to it.
    first_with: dict[str, int] = {}
    for row in reversed(rows):
        first_with.setdefault(" ".join(str(row["clean_text"] or "").split()), row["id"])
    for row in rows:
        body = "[Encrypted: can't be read]" if row["encrypted"] else row["clean_text"]
        earlier = first_with.get(" ".join(str(row["clean_text"] or "").split()))
        if not row["encrypted"] and body and earlier is not None and earlier != row["id"]:
            body = f"[The same text as message {earlier}]"
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
    total = ctx.bus.db.fetch_all(
        "SELECT COUNT(DISTINCT message_id) AS n FROM messages WHERE thread_id = ?", (thread,)
    )[0]["n"]
    # The newest is what's being judged, so it comes first. The rest can be read when it matters.
    older = total - len(blocks)
    tail = (
        f"\n\n[{older} older emails not shown. read_thread with skip_newest={len(blocks)} reads them.]"
        if older > 0
        else ""
    )
    shown = "Emails, newest first:\n\n" if blocks else ""
    return subject, sender, f"{note}{shown}" + "\n\n".join(blocks) + tail


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
    ctx: Context,
    thread: int,
    answers: list[str] | None = None,
    live: bool = True,
    tight: bool = False,
) -> tuple[str, str, str]:
    """What the model is given about one conversation: the mail, and the facts around it.

    `tight` is the second try after a run ran out of room: half the mail, and told to stay small.
    """
    db = ctx.bus.db
    config = ctx.config.agent
    share = 2 if tight else 1
    subject, sender, text = _thread_text(
        ctx, thread, config.max_recent_thread_messages // share, config.max_thread_chars // share
    )
    if not text:
        return subject, sender, ""
    task = untrusted(f"Subject: {subject}\n\n{text}")
    latest = db.fetch_all(
        "SELECT account,from_addr,subject FROM messages WHERE thread_id=? ORDER BY date DESC,id DESC LIMIT 1",
        (thread,),
    )
    if latest:
        identifier = bulk_learning.group_id(
            latest[0]["account"], latest[0]["from_addr"], latest[0]["subject"]
        )
        groups = db.fetch_all(
            "SELECT note,importance,importance_confirmed FROM mail_learning_groups WHERE id=? AND learned=1",
            (identifier,),
        )
        if groups:
            group = groups[0]
            source = (
                "confirmed by the person"
                if group["importance_confirmed"]
                else "a guess from past mail"
            )
            task += (
                f"\n\nThis sender/subject group's usual importance is {group['importance']} ({source}). Use this context when judging the current message. Notes from this group remain guesses:\n"
                + untrusted(group["note"])
            )
    facts = signals.about_thread(ctx, thread)
    if facts:
        task += f"\n\n{facts}"
    who = signals.who_they_are(mentions.load(ctx.config.home))
    if who:
        task += f"\n\n{who}"
    # How the rules handled its newest email, in their own words, so the AI knows what code
    # already decided and doesn't undo it.
    task += "\n\nHow the person's rules handled it: " + untrusted(_rule_line(ctx, thread))
    related = matters.context_for(ctx, thread)
    if related:
        task += (
            "\n\nMatters this email may belong to (found by code; the why is reliable). If it's about"
            " the same thing as one of them, so finishing one would finish the other, put its number"
            " in matter. If an open task there already covers what this email asks, don't add a task:"
            " give that task's id in updates, with the new due date if it changed:\n"
            + untrusted(related)
        )
    # A conversation in a matter has its open work listed there already.
    open_work = "" if matters.matter_of(db, thread) is not None else open_work_lines(db, thread)
    if open_work:
        task += (
            "\n\nAlready open for this conversation. Don't add these again; a new task or"
            " reminder you give replaces the open one's date:\n" + untrusted(open_work)
        )
    known = [
        dict(row)
        for row in db.fetch_all(
            "SELECT name, description, in_priority FROM mail_categories WHERE proposed = 0 AND mode = 'smart' AND ai_reads = 1 ORDER BY position, name"
        )
    ]
    # Header rules only catch marketing and automated mail that says so in its headers. What they
    # miss reaches the agent, which could not file it there and so sent it to Broadcast or left
    # it in the inbox.
    known += [
        {"name": row["name"], "description": FALLBACK_DESCRIPTIONS[row["name"]], "in_priority": 0}
        for row in db.fetch_all(
            "SELECT name FROM mail_categories WHERE proposed = 0 AND name IN ('Promotions','Updates') ORDER BY name"
        )
    ]
    if known:
        descriptions = json.dumps(known, ensure_ascii=False)
        task += "\n\nSmart folders (use only these names, at most one):\n" + untrusted(descriptions)
    exact = db.fetch_all(
        "SELECT name, description, subject FROM mail_categories WHERE proposed = 0 AND mode = 'exact' AND name NOT IN ('Promotions','Updates') ORDER BY position, name"
    )
    if exact:
        # The person's own words and tags for each, without the sender addresses its rules use.
        described = [
            row["name"]
            + (
                f" — {row['description']}"
                if row["description"] and row["description"] != row["name"]
                else ""
            )
            + (f" (subject starts with {row['subject']})" if row["subject"] else "")
            for row in exact
        ]
        task += (
            "\n\nExact folders (rules file mail here; never assign these as Smart folders or"
            " override them):\n" + untrusted("\n".join(described))
        )
    if live:
        task += _style_samples(ctx, thread)
    if answers:
        task += "\n\nThe person answered your earlier question: " + " ".join(answers)
    if tight:
        task += (
            "\n\nThe last try at this email ran out of room. Judge it from what's here, without"
            " reading other mail or documents."
        )
    return subject, sender, task


def _rule_line(ctx: Context, thread: int) -> str:
    """The rule that matched the newest email, and whether it lets the AI read it, in words.
    Read from the rule itself: an email's why also holds the AI's own earlier judgement."""
    rows = ctx.bus.db.fetch_all(
        "SELECT rule FROM messages WHERE thread_id = ? ORDER BY date DESC, id DESC LIMIT 1",
        (thread,),
    )
    name = rows[0]["rule"] if rows else None
    if not name:
        return "No rule matched it, so it came to you to judge."
    found = next((r for r in mail_rules.load_rules(ctx.config.home) if r.name == name), None)
    if found is None:
        return f"Matched the rule “{name}”."
    where = f"filed in {found.actions.category}" if found.actions.category else "left in the Inbox"
    reads = "kept from you unless it names them" if found.actions.skip_agent else "for you to read"
    return f"Matched their rule “{name}”: {where}, {reads}."


def open_work_lines(db: Database, thread: int) -> str:
    """The conversation's open tasks, reminders and deadlines, one line each."""
    rows = [
        *db.fetch_all(
            "SELECT 'task' AS kind, id, title, due FROM tasks WHERE thread = ? AND status != 'done' ORDER BY id",
            (thread,),
        ),
        *db.fetch_all(
            "SELECT 'reminder' AS kind, id, title, due_at AS due FROM reminders WHERE thread = ? AND fired = 0 ORDER BY id",
            (thread,),
        ),
        *db.fetch_all(
            "SELECT kind, NULL AS id, title, due FROM work_board WHERE thread = ? AND done = 0 ORDER BY id",
            (thread,),
        ),
    ]
    # Tasks and reminders by id, so the agent can say which one a later email finished.
    return "\n".join(
        (f"- [{r['kind']}:{r['id']}] {r['title']}" if r["id"] else f"- {r['kind']}: {r['title']}")
        + (f" (due {r['due']})" if r["due"] else "")
        for r in rows
    )


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
    return "\n\nHow the person writes, from their sent mail:\n" + untrusted(joined)


def next_turn(
    ctx: Context, origin: str, own: dict[str, Any] | None = None
) -> tuple[TurnRequest, list[int]] | None:
    """The next conversation with mail waiting. A burst is one judgement, on its latest state."""
    db = ctx.bus.db
    config = ctx.config.agent
    while True:
        # New mail goes ahead of past mail, so catching up never holds it back.
        first = db.fetch_all(
            "SELECT id, thread, event FROM trigger_runs WHERE trigger = ? AND status = 'pending'"
            " ORDER BY event LIKE ?, id LIMIT 1",
            (MAIL_TRIGGER, f"{LEARN_PREFIX}%"),
        )
        if not first:
            return None
        if str(first[0]["event"]).startswith(bulk_learning.PREFIX):
            return bulk_learning.batch_request(ctx, first[0], own)
        thread = first[0]["thread"]
        rows = db.fetch_all(
            "SELECT id, message, answer, event, error FROM trigger_runs WHERE trigger = ? AND status = 'pending' AND thread = ?"
            " ORDER BY id LIMIT ?",
            (MAIL_TRIGGER, thread, config.triage_batch),
        )
        # The folder is the gate, checked again now: mail moved into Kept from the AI since it
        # was queued, or a reply in a conversation that's there, is never shown to the AI.
        if db.fetch_all(
            f"SELECT 1 FROM threads WHERE id = ? AND {mail_store.hidden_from_ai()}",  # noqa: S608
            (thread,),
        ):
            settle(ctx, [row["id"] for row in rows], "skipped")
            continue
        answers = [row["answer"] for row in rows if row["answer"]]
        filing_only = all(str(row["event"]).startswith("refile-") for row in rows)
        learning = filing_only or all(str(row["event"]).startswith(LEARN_PREFIX) for row in rows)
        version = db.fetch_all(
            "SELECT decision_version,account FROM threads WHERE id = ?", (thread,)
        )
        from nexusai.modules.agent import knowledge

        context_version = (
            knowledge.decision_context_version(ctx, AGENT, version[0]["account"])
            if version
            else None
        )
        tight = any(row["error"] == OUT_OF_ROOM for row in rows)
        subject, sender, task = task_for(ctx, thread, answers, live=not learning, tight=tight)
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
        told = _template("mail-refile-model") if filing_only else _template("mail-learn-model")
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
        "context_version": context_version,
        "account": version[0]["account"] if version else None,
        "subject": subject,
        "messages": [{"message": r["message"], "answer": r["answer"]} for r in rows],
        "learning": learning,
        "filing_only": filing_only,
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
        f"- {citations.mark(citations.MAIL, r['id'])} {r['importance']}, {r['next_action'] or 'no action set'}:"
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

    # One matter at a time, so the same thing isn't listed as a task, a deadline and an email.
    task = briefs.coverage(ctx) + "\n\n" + untrusted(matters.plate(ctx) or "Nothing open.")
    decisions: list[str] = []
    for label, query in (
        ("Approvals", "SELECT id, summary AS text FROM tool_approvals WHERE status = 'pending'"),
        (
            "Questions",
            "SELECT id, text FROM channel_messages WHERE kind = 'ask' AND status = 'open'",
        ),
        (
            "Work that looks done",
            "SELECT id, title || ': ' || looks_done AS text FROM tasks"
            " WHERE looks_done IS NOT NULL AND status != 'done'",
        ),
    ):
        rows = ctx.bus.db.fetch_all(query)
        if rows:
            lines = "\n".join(f"- [{label} {row['id']}] {row['text']}" for row in rows[:20])
            decisions.append(f"{label}: {len(rows)} pending\n{lines}")
    if decisions:
        task += "\n\nDecisions waiting for them:\n" + untrusted("\n\n".join(decisions))
    past = feedback.briefs_with_reactions(ctx.bus.db)
    if past:
        task += "\n\nEarlier briefs and how they took them:\n" + untrusted(past)
    return task


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
        # Events are handled in the background, so this can arrive after the person set the
        # status. Only a message newer than their choice, and the latest in the conversation,
        # can be an answer; an older one used to flip "waiting on others" back.
        changed = work.tx.execute(
            "UPDATE threads SET status = 'waiting_on_you', follow_up_on = NULL,"
            " followup_notified = NULL, why = 'They replied' WHERE id = ? AND status = 'waiting_on_others'"
            " AND (status_user_message IS NULL OR status_user_message < ?)"
            " AND ? = (SELECT MAX(id) FROM messages WHERE thread_id = ?)",
            (thread, message, message, thread),
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

    Only overlapping unaccepted suggestions can be combined here. Accepted folders stay for
    the person to merge from Today. Returns how many suggestions are left.
    """
    db = ctx.bus.db
    rows = db.fetch_all("SELECT name, source, proposed FROM mail_categories")
    accepted = [row for row in rows if row["proposed"] == 0]
    settled = [str(row["name"]) for row in accepted]
    left: list[str] = []
    changed = False
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
            changed = True
    if changed:
        with ctx.bus.unit_of_work() as work:
            work.emit("categories.changed", {}, source="agent", trace_id=ctx.trace_id)
    return len(left)


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
        f"- {citations.mark(citations.MAIL, r['thread'])} {r['importance']}: {r['subject']}: {r['summary']}"
        for r in latest.values()
    )
    plate = on_the_plate(ctx)
    held = f"Judgements {rows[0]['id']} through {rows[-1]['id']} (bounded catch-up):\n{lines}" + (
        f"\n\nStill open:\n{plate}" if plate else ""
    )
    task = f"{prompts_builder.packaged('mail-digest.md')}\n\n" + untrusted(held)
    return TurnRequest(
        SESSION_ID,
        _template("mail-digest", count=len(latest)),
        "mail-hourly",
        _template("mail-digest-model"),
        task,
        context={"account": account, "threads": list(latest)},
    ), int(rows[-1]["id"])


# Marks a run whose first try ran out of room, so its second try is smaller and its last.
OUT_OF_ROOM = "out-of-room"


def settle(ctx: Context, runs: list[int], status: str, error: str | None = None) -> None:
    with ctx.bus.db.transaction() as tx:
        for run in runs:
            tx.execute(
                "UPDATE trigger_runs SET status = ?, error = ? WHERE id = ?", (status, error, run)
            )


def after_turn(ctx: Context, turn: int, runs: list[Any], error: str | None) -> None:
    """A run that ended without a judgement leaves that mail uncategorized, and says why.

    One that ran out of room is tried once more, smaller, before it counts as failed.
    """
    if runs and str(runs[0]["event"]).startswith(bulk_learning.PREFIX):
        bulk_learning.after_turn(ctx, runs[0], turn, error)
        return
    judged = ctx.bus.db.fetch_all("SELECT 1 FROM triage_runs WHERE turn = ? LIMIT 1", (turn,))
    if judged or not runs:
        settle(ctx, [run["id"] for run in runs], "done")
        return
    if error == CONTEXT_HELP and not any(run["error"] == OUT_OF_ROOM for run in runs):
        with ctx.bus.db.transaction() as tx:
            for run in runs:
                tx.execute(
                    "UPDATE trigger_runs SET status = 'pending', turn = NULL, session = NULL,"
                    " error = ? WHERE id = ?",
                    (OUT_OF_ROOM, run["id"]),
                )
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
    if target and target.get("context_version"):
        from nexusai.modules.agent import knowledge

        if (
            knowledge.decision_context_version(ctx, AGENT, target["account"])
            != target["context_version"]
        ):
            with ctx.bus.db.transaction() as tx:
                tx.execute(
                    "UPDATE trigger_runs SET status='pending',turn=NULL,session=NULL WHERE turn=? AND status='running'",
                    (rows[0]["id"],),
                )
            return "Category settings or personalized instructions changed. This result was discarded and queued with fresh context."
    if target and "bulk_batch" in target:
        return bulk_learning.record(ctx, target["bulk_batch"], fields, rows[0]["id"])
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
        filing_only=bool(target.get("filing_only")),
        sent=bool(target.get("sent")),
    )
    saved = ctx.bus.db.fetch_all(
        "SELECT category,importance,extra_categories FROM threads WHERE id=?", (target["thread"],)
    )[0]
    folders = [
        *([saved["category"]] if saved["category"] else []),
        *json.loads(saved["extra_categories"]),
    ]
    return f"Filed as {', '.join(folders) or 'uncategorized'}, {saved['importance']} importance."


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
        filing_only: bool = False,
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
        allowed = {
            row["name"].casefold(): row["name"]
            for row in ctx.bus.db.fetch_all(
                "SELECT name FROM mail_categories WHERE proposed = 0 AND ai_reads = 1 AND (mode = 'smart' OR name IN ('Promotions','Updates'))"
            )
        }
        requested = parsed.get("smart_folders")
        if not isinstance(requested, list) or (not requested and category):
            requested = [category] if category else []
        smart = list(
            dict.fromkeys(
                allowed[name.casefold()]
                for name in requested
                if isinstance(name, str) and name.casefold() in allowed
            )
        )
        recipients = ctx.bus.db.fetch_all(
            "SELECT to_json, cc_json FROM messages WHERE thread_id = ? ORDER BY date DESC, id DESC LIMIT 1",
            (thread,),
        )
        if (
            recipients
            and "broadcast" in allowed
            and len(
                set(
                    signals.addresses(recipients[0]["to_json"])
                    + signals.addresses(recipients[0]["cc_json"])
                )
            )
            > signals.MOST_NAMED_RECIPIENTS
            # Only when nothing better fits: Broadcast used to go first even over Promotions.
            and not smart
        ):
            smart = [allowed["broadcast"]]
        category = smart[0] if smart else None
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
            parsed = {**parsed, "draft": None}
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
                current = work.tx.execute(
                    "SELECT category, category_source, extra_categories,"
                    f" {FILED_BY_RULE} AS ruled FROM threads t WHERE id = ?",
                    (thread,),
                ).fetchone()
                # A rule the person can see files it alone, with no folders added beside it.
                if current and current["category_source"] != "user" and not current["ruled"]:
                    # A folder headers guessed gives way to the one the AI chose: one per email.
                    primary = (
                        current["category"]
                        if current["category_source"] == "rule" and not smart
                        else category
                    )
                    exact_names = {
                        row["name"]
                        for row in work.tx.execute(
                            "SELECT name FROM mail_categories WHERE mode='exact' AND proposed=0"
                        )
                    }
                    kept_extras = [
                        name
                        for name in json.loads(current["extra_categories"])
                        if name in exact_names
                    ]
                    extras = kept_extras
                    work.tx.execute(
                        "UPDATE threads SET category = ?, category_source = ?, extra_categories = ?, why = ? WHERE id = ?",
                        (
                            primary,
                            "rule"
                            if current["category_source"] == "rule" and primary != category
                            else "agent",
                            json.dumps([name for name in extras if name != primary]),
                            why,
                            thread,
                        ),
                    )
                if not filing_only:
                    work.tx.execute(
                        "UPDATE threads SET importance = ? WHERE id = ? AND importance_user_message IS NULL",
                        (importance, thread),
                    )
            if not filing_only:
                work.tx.execute(
                    "UPDATE threads SET status = ?, next_action = ?, follow_up_on = ?,"
                    " followup_notified = NULL WHERE id = ? AND status_user_message IS NULL",
                    (
                        status,
                        next_action,
                        follow_up if status == "waiting_on_others" else None,
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
        if filing_only:
            parsed = {**parsed, "learned": []}
        memory.add_learned(ctx.config.home, _strings(parsed.get("learned")), thread)
        if learning:
            return
        # Before the work, so its matter's timeline shows the email first and the task after.
        if not filing_only:
            # The AI may only pick a matter it was shown; anything else is left to code.
            shown = dict(matters.shortlist(ctx, thread))
            chosen = str(parsed.get("matter") or "").strip().strip("[]")
            pick = int(chosen) if chosen.isdigit() and int(chosen) in shown else None
            matters.link(ctx, thread, choose=pick, because=reason if pick else "")
        self._proposals(thread, parsed, subject)
        if question:
            channel.post(
                ctx,
                "ask",
                cards.name(ctx.bus.db, AGENT),
                question,
                session=SESSION_ID,
                thread=thread,
                urgent=importance == "high",
                triage_message=latest,
            )

    def _open_asks(self) -> int:
        return int(
            self.ctx.bus.db.fetch_all(
                "SELECT COUNT(*) AS n FROM channel_messages WHERE kind = 'ask' AND status = 'open'"
                " AND session = ?",
                (SESSION_ID,),
            )[0]["n"]
        )

    def _proposals(self, thread: int, parsed: dict[str, Any], subject: str) -> None:
        """The agent proposes. The person accepts tasks and reminders, and sends drafts."""
        ctx = self.ctx
        why = str(parsed.get("reason") or "")[:500]
        db = ctx.bus.db
        matter = matters.matter_of(db, thread)
        asked = db.fetch_all(
            "SELECT id, date FROM messages WHERE thread_id = ? ORDER BY date DESC, id DESC LIMIT 1",
            (thread,),
        )
        source = asked[0]["id"] if asked else None
        # On the timeline when the email was sent, not when it was read: past mail stays past.
        sent_at = asked[0]["date"] if asked else None
        for item in parsed.get("tasks") or []:
            if not isinstance(item, dict) or not _title(item.get("title")):
                continue
            title, due = _title(item["title"]), _valid_date(item.get("due"))
            # One task per thing. The AI names the open task an email updates; otherwise the
            # conversation's own task, or one in its matter worded alike, is the same task. A
            # resend or a reminder email moves its date instead of adding a copy.
            current = _same_task(db, item.get("updates"), thread, matter, title)
            if current:
                if due and due != current["due"] and current["source"] == "agent":
                    planner.change_task(ctx, current["id"], {"due": due})
                    matters.note(
                        ctx, thread, "due", f'"{current["title"]}" now due {due}', why, time=sent_at
                    )
                continue
            if planner.has_task(db, title, thread) or planner.has_reminder(db, title, thread):
                continue
            planner.add_task(
                ctx, title, due, thread, "agent", True, matter=matter, source_message=source
            )
            matters.note(ctx, thread, "suggested", f'To-do: "{title}"', why, time=sent_at)
        for item in parsed.get("reminders") or []:
            if (
                not isinstance(item, dict)
                or not _title(item.get("title"))
                or not _valid_moment(item.get("when"))
            ):
                continue
            title, when = _title(item["title"]), str(item["when"])[:16]
            current = db.fetch_all(
                "SELECT id, due_at, source FROM reminders WHERE thread = ? AND fired = 0 ORDER BY id LIMIT 1",
                (thread,),
            )
            if current:
                if when != current[0]["due_at"] and current[0]["source"] == "agent":
                    planner.change_reminder(ctx, current[0]["id"], {"due_at": when})
                    matters.note(ctx, thread, "due", f"Reminder moved to {when}", why, time=sent_at)
                continue
            if planner.has_reminder(db, title, thread) or planner.has_task(db, title, thread):
                continue
            planner.add_reminder(
                ctx, title, when, "none", thread, None, "agent", True, matter=matter
            )
            matters.note(ctx, thread, "suggested", f'Reminder: "{title}"', why, time=sent_at)
        for item in parsed.get("deadlines") or []:
            if not isinstance(item, dict) or not _title(item.get("what")):
                continue
            due = _valid_date(item.get("due"))
            # With a task, the deadline is its due date. As a second line it showed twice.
            task = db.fetch_all(
                "SELECT id, due, source FROM tasks WHERE thread = ? AND status != 'done' ORDER BY id LIMIT 1",
                (thread,),
            )
            if task:
                if due and not task[0]["due"] and task[0]["source"] == "agent":
                    planner.change_task(ctx, task[0]["id"], {"due": due})
                    matters.note(ctx, thread, "due", f"Due date now {due}", why, time=sent_at)
                continue
            # A deadline is a to-do with a date, not a second kind of item beside it.
            what = _title(item["what"])[:300]
            if not planner.has_task(db, what, thread):
                planner.add_task(
                    ctx, what, due, thread, "agent", True, matter=matter, source_message=source
                )
                matters.note(ctx, thread, "suggested", f'To-do: "{what}"', why, time=sent_at)
        for ref in parsed.get("finished") or []:
            self._finished(thread, matter, str(ref), why, sent_at)
        if parsed.get("draft"):
            self._draft(thread, str(parsed["draft"]), subject)

    def _finished(
        self, thread: int, matter: int | None, ref: str, why: str, sent_at: str | None
    ) -> None:
        """A later email shows open work done. What it only suggested goes; what the person kept
        is marked, with why, for them to close."""
        ctx = self.ctx
        kind, _, number = ref.strip().strip("[]").partition(":")
        if kind not in {"task", "reminder"} or not number.isdigit():
            return
        # Only work it was shown: this conversation's, or its matter's.
        table, still_open = (
            ("tasks", "status != 'done'") if kind == "task" else ("reminders", "fired = 0")
        )
        rows = ctx.bus.db.fetch_all(
            f"SELECT id, title, proposed FROM {table} WHERE id = ? AND {still_open}"  # noqa: S608
            " AND (thread = ? OR (matter IS NOT NULL AND matter = ?))",
            (int(number), thread, matter),
        )
        if not rows:
            return
        item = rows[0]
        if item["proposed"]:
            remove = planner.remove_tasks if kind == "task" else planner.remove_reminders
            remove(ctx, [item["id"]])
            matters.note(
                ctx,
                thread,
                "closed",
                f'Suggestion "{item["title"]}" dropped: already done',
                why,
                time=sent_at,
            )
            return
        change = planner.change_task if kind == "task" else planner.change_reminder
        change(ctx, item["id"], {"looks_done": why or "A later email shows it done"})
        matters.note(ctx, thread, "looks_done", f'"{item["title"]}" looks done', why, time=sent_at)

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


def _same_task(db: Database, named: Any, thread: int, matter: int | None, title: str) -> Any:
    """The open task an email is about, if there is one: the one the AI named from its matter,
    the conversation's own, or one in the matter worded alike."""
    rows = db.fetch_all(
        "SELECT id, due, source, title, thread FROM tasks WHERE status != 'done' AND (thread = ? OR matter = ?)"
        " ORDER BY id",
        (thread, matter if matter is not None else -1),
    )
    found = kinds.parse(named)
    if found and found[0] == "task":
        picked = next((r for r in rows if r["id"] == found[1]), None)
        if picked:
            return picked
    return next((r for r in rows if r["thread"] == thread), None) or next(
        (r for r in rows if textmatch.same(r["title"], title)), None
    )


def _title(value: Any) -> str:
    """A task's title as the person reads it: a model sometimes left a [mail:N] marker in it."""
    return " ".join(citations.MARKER.sub("", str(value or "")).split())[:500]


def _valid_date(value: Any) -> str | None:
    """A real calendar day, so "2026-11-31" is dropped instead of stopping the rest."""
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return planner.due_of(text)
    except CommandError:
        return None


def _valid_moment(value: Any) -> bool:
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*", text):
        return False
    try:
        planner.when_of(text[:16])
    except CommandError:
        return False
    return True


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
        untrusted(f"Subject: {subject}\n\n{text}")
        + _style_samples(ctx, thread)
        + "\n\nWrite the reply now."
    )
    from nexusai.modules.agent import knowledge

    thread_account = ctx.bus.db.fetch_all("SELECT account FROM threads WHERE id=?", (thread,))
    layers: list[Layer] = knowledge.layers_for(
        ctx,
        "draft-reply",
        task,
        account=thread_account[0]["account"] if thread_account else None,
        senders=knowledge.sender_scope(ctx, [thread]),
        tools=(),
    )
    layers.append(
        Layer(
            "This run",
            f"The person requested a draft to review. Now: {datetime.now().astimezone().isoformat(timespec='minutes')}. Do not invent dates or commitments.",
        )
    )
    try:
        result = gateway.call_model(
            ctx, agent="draft-reply", session=None, layers=layers, messages=[Message("user", task)]
        )
    except (
        providers.ModelUnavailable,
        providers.ModelNotConfigured,
        providers.ModelFlagged,
        providers.ModelContextExceeded,
        providers.ModelResponseInvalid,
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
