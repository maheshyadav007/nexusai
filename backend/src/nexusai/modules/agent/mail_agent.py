"""Judges every email that escapes the fixed rules, and keeps going when the model is away."""

import json
import re
import threading
from datetime import UTC, datetime
from typing import Any

import structlog

from nexusai.contracts.agent import ThreadRuns, ThreadSummary, TriageEstimate, TriageRun
from nexusai.contracts.events import AppEvent
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import channel, gateway, guard, memory, prompts_builder, providers
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
SESSION_ID = "mail-agent"
IMPORTANCE = {"low", "normal", "high"}
STATUSES = {"waiting_on_you", "waiting_on_others", "resolved", "fyi"}
PARSE_ATTEMPTS = 2
APPROX_TOKENS_PER_MESSAGE = 1200


def _now() -> str:
    return datetime.now(UTC).isoformat()


def enabled(ctx: Context) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = 'live_mail_enabled'")
    return not rows or rows[0]["value"] == "1"


def enqueue(ctx: Context, message: int, thread: int, answer: str | None = None) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO triage_queue (message, thread, added, answer) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (message) DO UPDATE SET answer = excluded.answer",
            (message, thread, _now(), answer),
        )


def _ensure_session(ctx: Context) -> None:
    """One entry in Sessions. Each email is a run inside it."""
    now = _now()
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO agent_sessions (id, title, agent, status, untrusted, created, updated)"
            " VALUES (?, 'Mail agent', 'mail', 'done', 1, ?, ?)",
            (SESSION_ID, now, now),
        )


def _record_turn(ctx: Context, text: str, reply: str) -> None:
    identifier = "run"
    with ctx.bus.db.transaction() as tx:
        cursor = tx.execute(
            "INSERT INTO agent_turns (session, text, closed) VALUES (?, ?, 1)", (SESSION_ID, text)
        )
        turn = cursor.lastrowid
        for part in (
            {"type": "start-step"},
            {"type": "text-start", "id": identifier},
            {"type": "text-delta", "id": identifier, "delta": reply},
            {"type": "text-end", "id": identifier},
        ):
            tx.execute(
                "INSERT INTO agent_parts (turn, part) VALUES (?, ?)", (turn, json.dumps(part))
            )


def _thread_text(
    ctx: Context, thread: int, limit_messages: int, limit_chars: int
) -> tuple[str, str]:
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
    summary = ctx.bus.db.fetch_all("SELECT text FROM thread_summaries WHERE thread = ?", (thread,))
    note = f"Summary of the earlier conversation:\n{summary[0]['text']}\n\n" if summary else ""
    return subject, f"{note}" + "\n\n".join(reversed(blocks))


def _parse(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


class MailAgent:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.config = ctx.config.agent
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.waiting_for_model: str | None = None
        self.thread = threading.Thread(target=self._loop, daemon=True, name="mail-agent")

    def start(self) -> None:
        _ensure_session(self.ctx)
        self.thread.start()
        self.wake.set()

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=10)

    def _loop(self) -> None:
        # A single email starts at once. Anything arriving during a run waits for the next one.
        while not self.stopping.is_set():
            self.wake.wait()
            self.wake.clear()
            while not self.stopping.is_set() and enabled(self.ctx):
                try:
                    worked = self._run_once()
                except (
                    providers.ModelUnavailable,
                    providers.ModelNotConfigured,
                    gateway.DailyCapReached,
                ) as error:
                    # Mail keeps working. Queued triage carries on when the model is back.
                    self.waiting_for_model = str(error)
                    log.info("triage_waiting", kind=type(error).__name__)
                    self.stopping.wait(self.config.triage_retry_seconds)
                    continue
                except Exception:
                    log.exception("triage_failed")
                    self.stopping.wait(self.config.triage_retry_seconds)
                    continue
                self.waiting_for_model = None
                if not worked:
                    break

    def _run_once(self) -> bool:
        db = self.ctx.bus.db
        pending = db.fetch_all(
            "SELECT * FROM triage_queue ORDER BY added, message LIMIT ?",
            (self.config.triage_batch,),
        )
        if not pending:
            return False
        # A burst is grouped by conversation: one judgement per thread, on its latest state.
        by_thread: dict[int, list[Any]] = {}
        for row in pending:
            by_thread.setdefault(row["thread"], []).append(row)
        for thread, rows in by_thread.items():
            self._triage_thread(thread, rows)
        return True

    def _clear(self, rows: list[Any]) -> None:
        with self.ctx.bus.db.transaction() as tx:
            for row in rows:
                tx.execute("DELETE FROM triage_queue WHERE message = ?", (row["message"],))

    def _triage_thread(self, thread: int, rows: list[Any]) -> None:
        ctx = self.ctx
        subject, text = _thread_text(
            ctx, thread, self.config.max_recent_thread_messages, self.config.max_thread_chars
        )
        if not text:
            self._clear(rows)
            return
        task = f"<untrusted>\nSubject: {subject}\n\n{text}\n</untrusted>"
        answers = [row["answer"] for row in rows if row["answer"]]
        if answers:
            task += "\n\nThe person answered your earlier question: " + " ".join(answers)
        recalled = memory.relevant(ctx.config.home, "mail", text, self.config.memory_max_chars)
        layers = prompts_builder.build_layers(ctx.config, "mail", memory=recalled)
        parsed = None
        try:
            for _ in range(PARSE_ATTEMPTS):
                result = gateway.call_model(
                    ctx,
                    agent="mail",
                    session=SESSION_ID,
                    layers=layers,
                    messages=[Message("user", task)],
                )
                parsed = _parse(result.text)
                if parsed:
                    break
        except (providers.ModelFlagged, guard.GuardBlocked) as error:
            self._failed(thread, rows, str(error))
            return
        if parsed is None:
            self._failed(
                thread, rows, "The agent's answer couldn't be read, so this stays uncategorized."
            )
            return
        self._apply(thread, rows, subject, parsed, result.call_id)

    def _failed(self, thread: int, rows: list[Any], error: str) -> None:
        """A flagged email stays uncategorized, and shows why."""
        message = f"Not triaged: {error}"
        with self.ctx.bus.unit_of_work() as work:
            for row in rows:
                work.tx.execute(
                    "INSERT INTO triage_runs (message, thread, time, status, error) VALUES (?, ?, ?, 'failed', ?)",
                    (row["message"], thread, _now(), error),
                )
                work.tx.execute("DELETE FROM triage_queue WHERE message = ?", (row["message"],))
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
        _record_turn(self.ctx, f"Triage failed for conversation {thread}", error)

    def _apply(
        self, thread: int, rows: list[Any], subject: str, parsed: dict[str, Any], call_id: int
    ) -> None:
        ctx = self.ctx
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
                    "INSERT INTO triage_runs (message, thread, time, status, summary, reason, facts, suggested_action, provisional, call_id)"
                    " VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, ?)",
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
                    ),
                )
                work.tx.execute("UPDATE messages SET why = ? WHERE id = ?", (why, row["message"]))
                work.tx.execute("DELETE FROM triage_queue WHERE message = ?", (row["message"],))
            # What the person chose stays. Only an agent or rule category can change.
            work.tx.execute(
                "UPDATE threads SET category = ?, category_source = 'agent', why = ? WHERE id = ? AND COALESCE(category_source, '') != 'user'",
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
        _record_turn(ctx, f"Triage: {subject}", f"{summary}\n\n{reason}".strip())

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


def estimate(ctx: Context) -> TriageEstimate:
    account = accounts.current_account(ctx.config)
    rows = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM messages m WHERE m.account = ? AND m.folder_role = 'inbox' AND m.rule IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM triage_runs r WHERE r.message = m.id)"
        " AND NOT EXISTS (SELECT 1 FROM triage_queue q WHERE q.message = m.id)",
        (account,),
    )
    queued = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM triage_queue")[0]["n"]
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
        enqueue(ctx, row["id"], row["thread_id"])


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


def on_needs_triage(event: AppEvent, ctx: Context, agent: MailAgent | None) -> None:
    if enabled(ctx):
        enqueue(ctx, int(event.payload["message_id"]), int(event.payload["thread_id"]))
        if agent:
            agent.wake.set()
