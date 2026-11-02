"""Judges every email that escapes the fixed rules, as a run in the Mail agent's own chat."""

import json
import re
import uuid
from datetime import UTC, datetime
from importlib import resources
from typing import Any, Literal

import structlog

from nexusai.contracts.agent import ThreadRuns, ThreadSummary, TriageEstimate, TriageRun
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import channel, gateway, guard, memory, prompts_builder, providers
from nexusai.modules.agent.context import TurnRequest
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.providers import Message
from nexusai.modules.mail import accounts
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
SESSION_ID = "mail-agent"
MAIL_TRIGGER = "mail-received"
IMPORTANCE = {"low", "normal", "high"}
STATUSES = {"waiting_on_you", "waiting_on_others", "resolved", "fyi"}
APPROX_TOKENS_PER_MESSAGE = 1200
MailMode = Literal["each", "hourly", "both"]
UNREADABLE = "The agent didn't record a judgement, so this stays uncategorized."


def _now() -> str:
    return datetime.now(UTC).isoformat()


def enabled(ctx: Context) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT enabled FROM agent_triggers WHERE id = ?", (MAIL_TRIGGER,))
    return not rows or bool(rows[0]["enabled"])


def mode(ctx: Context) -> MailMode:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = 'mail_mode'")
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


def _thread_text(
    ctx: Context, thread: int, limit_messages: int, limit_chars: int
) -> tuple[str, str, str]:
    """Recent messages within a size limit, plus the stored summary if there is one."""
    rows = ctx.bus.db.fetch_all(
        "SELECT from_name, from_addr, date, subject, clean_text, encrypted FROM messages WHERE thread_id = ?"
        " GROUP BY message_id ORDER BY date DESC LIMIT ?",
        (thread, limit_messages),
    )
    blocks: list[str] = []
    used = 0
    for row in rows:
        body = "[Encrypted: can't be read]" if row["encrypted"] else row["clean_text"]
        block = f"From {row['from_name']} <{row['from_addr']}> on {row['date']}\n{body}"
        if used + len(block) > limit_chars and blocks:
            break
        blocks.append(block[:limit_chars])
        used += len(block)
    subject = rows[0]["subject"] if rows else ""
    sender = (rows[0]["from_name"] or rows[0]["from_addr"]) if rows else ""
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


def next_turn(
    ctx: Context, origin: str, own: dict[str, Any] | None = None
) -> tuple[TurnRequest, list[int]] | None:
    """The next conversation with mail waiting. A burst is one judgement, on its latest state."""
    db = ctx.bus.db
    config = ctx.config.agent
    while True:
        first = db.fetch_all(
            "SELECT thread FROM trigger_runs WHERE trigger = ? AND status = 'pending' ORDER BY id LIMIT 1",
            (MAIL_TRIGGER,),
        )
        if not first:
            return None
        thread = first[0]["thread"]
        rows = db.fetch_all(
            "SELECT id, message, answer FROM trigger_runs WHERE trigger = ? AND status = 'pending' AND thread = ?"
            " ORDER BY id LIMIT ?",
            (MAIL_TRIGGER, thread, config.triage_batch),
        )
        subject, sender, text = _thread_text(
            ctx, thread, config.max_recent_thread_messages, config.max_thread_chars
        )
        if text:
            break
        # The conversation has gone, so there's nothing left to judge.
        settle(ctx, [row["id"] for row in rows], "skipped")
    answers = [row["answer"] for row in rows if row["answer"]]
    shown_subject = subject or "no subject"
    if answers:
        shown = _template("mail-answer", subject=shown_subject, answer=" ".join(answers))
        told = _template("mail-answer-model")
    elif len(rows) > 1:
        shown = _template("mail-many", count=len(rows), sender=sender, subject=shown_subject)
        told = _template("mail-model")
    else:
        shown = _template("mail-one", sender=sender, subject=shown_subject)
        told = _template("mail-model")
    task = f"<untrusted>\nSubject: {subject}\n\n{text}\n</untrusted>"
    board = db.fetch_all(
        "SELECT kind, title, due FROM work_board WHERE thread = ? AND done = 0 ORDER BY id",
        (thread,),
    )
    if board:
        lines = "\n".join(f"- {r['kind']}: {r['title']} (due {r['due']})" for r in board)
        task += f"\n\nAlready on the work board for this conversation:\n<untrusted>\n{lines}\n</untrusted>"
    known = db.fetch_all("SELECT name FROM mail_categories WHERE proposed = 0 ORDER BY name")
    if known:
        task += "\n\nCategories that exist: " + ", ".join(row["name"] for row in known)
    if answers:
        task += "\n\nThe person answered your earlier question: " + " ".join(answers)
    target = {
        "thread": thread,
        "subject": subject,
        "messages": [{"message": r["message"], "answer": r["answer"]} for r in rows],
    }
    request = TurnRequest(SESSION_ID, shown, origin, told, task, target, own)
    return request, [row["id"] for row in rows]


def digest_turn(ctx: Context, since: str) -> TurnRequest | None:
    """What came in over the last hour. Nothing new means no run, so no model call and no message."""
    rows = ctx.bus.db.fetch_all(
        "SELECT r.thread, r.summary, t.subject, t.importance FROM triage_runs r"
        " JOIN threads t ON t.id = r.thread WHERE r.status = 'done' AND r.time > ? ORDER BY r.id",
        (since,),
    )
    if not rows:
        return None
    lines = "\n".join(
        f"- [thread {r['thread']}] {r['importance']}: {r['subject']}: {r['summary']}" for r in rows
    )
    task = f"{prompts_builder.packaged('mail-digest.md')}\n\n<untrusted>\n{lines}\n</untrusted>"
    return TurnRequest(
        SESSION_ID,
        _template("mail-digest", count=len(rows)),
        "mail-hourly",
        _template("mail-digest-model"),
        task,
    )


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
    Triage(ctx)._apply(target["thread"], target["messages"], target["subject"], fields, turn)
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

    def _apply(
        self, thread: int, rows: list[Any], subject: str, parsed: dict[str, Any], turn: int
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
        latest = max(row["message"] for row in rows)
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
            # What the person chose stays, and so does what their rule filed.
            work.tx.execute(
                "UPDATE threads SET category = ?, category_source = 'agent', why = ? WHERE id = ? AND COALESCE(category_source, '') NOT IN ('user', 'rule')",
                (category, why, thread),
            )
            work.tx.execute(
                "UPDATE threads SET importance = ?, status = ? WHERE id = ?",
                (importance, status, thread),
            )
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
            if importance == "high":
                channel.notify(
                    ctx,
                    work,
                    f"Important: {subject or 'new mail'}",
                    summary,
                    f"/mail/thread/{thread}",
                    "urgent-mail",
                    True,
                )
                work.emit(
                    "mail.urgent", {"thread_id": thread}, source="agent", trace_id=ctx.trace_id
                )
        self._note_category(category)
        self._suggest_category(parsed.get("suggest_category"))
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

    def _note_category(self, category: str | None) -> None:
        """A name the agent came up with appears in the sidebar, marked as the agent's."""
        if not category:
            return
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, created) VALUES (?, 'agent', ?)",
                (category, _now()),
            )

    def _suggest_category(self, suggestion: Any) -> None:
        """Mail that keeps coming from one place. The person decides, on Today."""
        if not isinstance(suggestion, dict) or not suggestion.get("name"):
            return
        name = str(suggestion["name"])[:64]
        with self.ctx.bus.unit_of_work() as work:
            cursor = work.tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, proposed, why, sender, created)"
                " VALUES (?, 'agent', 1, ?, ?, ?)",
                (
                    name,
                    str(suggestion.get("reason") or "")[:500],
                    str(suggestion.get("sender") or "")[:320] or None,
                    _now(),
                ),
            )
            if cursor.rowcount:
                work.emit("categories.changed", {}, source="agent", trace_id=self.ctx.trace_id)

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
    db = ctx.bus.db
    count = db.fetch_all(
        "SELECT COUNT(DISTINCT message_id) AS n FROM messages WHERE thread_id = ?", (thread,)
    )[0]["n"]
    rows = db.fetch_all("SELECT * FROM thread_summaries WHERE thread = ?", (thread,))
    if not rows:
        return ThreadSummary(thread=thread, text=None, covered=0, new_messages=count, updated=None)
    return ThreadSummary(
        thread=thread,
        text=rows[0]["text"],
        covered=rows[0]["covered"],
        new_messages=max(count - rows[0]["covered"], 0),
        updated=rows[0]["updated"],
    )


def summarize(ctx: Context, thread: int) -> ThreadSummary:
    """Only when asked. An update reads just the messages since the last summary."""
    db = ctx.bus.db
    current = summary_view(ctx, thread)
    messages = db.fetch_all(
        "SELECT from_name, from_addr, date, clean_text, encrypted FROM messages WHERE thread_id = ? GROUP BY message_id ORDER BY date",
        (thread,),
    )
    if not messages:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    new = messages[current.covered :] if current.text else messages
    limit = ctx.config.agent.max_thread_chars
    blocks = [
        f"From {m['from_name']} <{m['from_addr']}> on {m['date']}\n{'[Encrypted]' if m['encrypted'] else m['clean_text']}"
        for m in new
    ]
    text = "\n\n".join(blocks)[-limit:]
    task = f"<untrusted>\n{text}\n</untrusted>"
    if current.text:
        task = f"Earlier summary:\n{current.text}\n\nNew messages:\n{task}"
    layers: list[Layer] = prompts_builder.build_layers(ctx.config, "summary")
    try:
        result = gateway.call_model(
            ctx, agent="summary", session=None, layers=layers, messages=[Message("user", task)]
        )
    except (
        providers.ModelUnavailable,
        providers.ModelNotConfigured,
        providers.ModelFlagged,
        gateway.DailyCapReached,
        guard.GuardBlocked,
    ) as error:
        raise CommandError("summary.failed", str(error), 502) from error
    now = _now()
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO thread_summaries (thread, text, covered, updated) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (thread) DO UPDATE SET text = excluded.text, covered = excluded.covered, updated = excluded.updated",
            (thread, result.text.strip(), len(messages), now),
        )
        work.emit("summary.ready", {"thread_id": thread}, source="agent", trace_id=ctx.trace_id)
    return summary_view(ctx, thread)
