"""Starts agents. A message, an event and the clock all arrive here as the same kind of start."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from nexusai.contracts.agent import SaveTrigger, Trigger, TriggerChoice, TriggerList
from nexusai.contracts.events import AppEvent
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import gateway, mail_agent, providers, scheduler
from nexusai.modules.agent.context import TurnRequest

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_triggers_table_001",
    """
CREATE TABLE agent_triggers (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, agent TEXT NOT NULL, event TEXT NOT NULL, prompt TEXT NOT NULL DEFAULT '',
  session TEXT, enabled INTEGER NOT NULL DEFAULT 1, token_limit INTEGER NOT NULL DEFAULT 0, context_mode TEXT, keep_messages INTEGER, created TEXT);
INSERT INTO agent_triggers (id, title, kind, agent, event, enabled) VALUES
  ('mail-received', 'Mail agent, on new mail', 'mail', 'mail', 'mail.needsTriage',
   COALESCE((SELECT value = '1' FROM agent_defaults WHERE key = 'live_mail_enabled'), 1));
DELETE FROM agent_defaults WHERE key = 'live_mail_enabled';
""",
)
EVENT_CHOICES = {
    "mail.received": "Any new mail arrives",
    "mail.urgent": "Important mail arrives",
}
CUSTOM = "custom"
CUSTOM_AGENT = "scheduled"
EVENT_ORIGIN = "event"
# A burst is one run, and it reads only this many of the conversations that set it off.
MOST_THREADS_PER_RUN = 3
SCHEDULE_TRIGGER = "schedule"
HOURLY_KIND = "mail-hourly"
SCHEDULE_AGENTS = {"daily-prep": "daily-prep", "prompt": "scheduled"}
SCHEDULE_ORIGIN = "schedule"
LAST_DIGEST = "last_digest"


class Triggers:
    """One thread hands out the waiting work. It never waits on a run: a finished run wakes it."""

    def __init__(self, ctx: Context, runtime: Any) -> None:
        self.ctx = ctx
        self.runtime = runtime
        self.config = ctx.config.agent
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.waiting_for_model: str | None = None
        self.retry_at = 0.0
        # Set when an hourly run comes due, so mail that's been held can go.
        self.release_mail = False
        self.thread = threading.Thread(target=self._loop, daemon=True, name="triggers")

    def start(self) -> None:
        mail_agent.ensure_session(self.ctx)
        self._requeue_unfinished()
        self.runtime.on_turn_end = self.turn_ended
        self.runtime.on_hold = self.hold_for_model
        self.thread.start()
        self.wake.set()

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=10)
        self.runtime.on_turn_end = None
        self.runtime.on_hold = None

    def _requeue_unfinished(self) -> None:
        """Runs that were started but whose turn never got going go back in line."""
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE trigger_runs SET status = 'pending', turn = NULL, session = NULL WHERE status = 'running'"
                " AND (turn IS NULL OR turn NOT IN (SELECT id FROM agent_turns WHERE closed = 0))"
            )

    # What sets work going

    def fire_schedule(self, event: str, schedule: int) -> None:
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO trigger_runs (trigger, event, time, status, schedule)"
                " VALUES (?, ?, ?, 'pending', ?)",
                (SCHEDULE_TRIGGER, event, mail_agent._now(), schedule),
            )
        self.wake.set()

    def on_event(self, event: AppEvent) -> None:
        """Whichever triggers people have set up for this event. Each event counts once."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id FROM agent_triggers WHERE kind = ? AND enabled = 1 AND event = ?",
            (CUSTOM, event.type),
        )
        if not rows:
            return
        with self.ctx.bus.db.transaction() as tx:
            for row in rows:
                tx.execute(
                    "INSERT OR IGNORE INTO trigger_runs (trigger, event, time, status, thread)"
                    " VALUES (?, ?, ?, 'pending', ?)",
                    (row["id"], event.id, mail_agent._now(), event.payload.get("thread_id")),
                )
        self.wake.set()

    def run_mail_now(self) -> str:
        """For the Run now button: does what the hourly run would, without waiting for the hour."""
        chosen = mail_agent.mode(self.ctx)
        if chosen == "hourly" or mail_agent.waiting_count(self.ctx):
            if not mail_agent.waiting_count(self.ctx):
                return "nothing"
            self.release_mail = True
            self.tick()
            return "started"
        return "started" if self._start_digest() else "nothing"

    # Handing out work

    def _loop(self) -> None:
        while not self.stopping.is_set():
            self.wake.wait(self.config.triage_retry_seconds if self.waiting_for_model else None)
            self.wake.clear()
            if self.stopping.is_set():
                return
            try:
                self.tick()
            except Exception:
                log.exception("triggers_failed")

    def tick(self) -> None:
        with self.lock:
            self._start_schedules()
            self._start_custom()
            self._start_mail()

    def _model_ready(self) -> bool:
        if self.waiting_for_model and time.monotonic() < self.retry_at:
            return False
        try:
            gateway.resolve_provider(self.ctx)
        except providers.ModelNotConfigured as error:
            self.hold_for_model(str(error))
            return False
        cap = gateway.daily_cap(self.ctx.bus.db, self.config.daily_token_cap)
        if cap and gateway.used_today(self.ctx.bus.db) >= cap:
            self.hold_for_model("Today's model limit is used up.")
            return False
        return True

    def hold_for_model(self, why: str) -> None:
        """Mail keeps working, and what's queued carries on when the model is back."""
        self.waiting_for_model = why
        self.retry_at = time.monotonic() + self.config.triage_retry_seconds
        log.info("triggers_waiting_for_model")
        self.wake.set()

    def model_changed(self) -> None:
        self.retry_at = 0.0
        self.wake.set()

    def _start_mail(self) -> None:
        if not mail_agent.enabled(self.ctx):
            return
        chosen = mail_agent.mode(self.ctx)
        if chosen == "hourly" and not self.release_mail:
            return
        if self.runtime.active_turn(mail_agent.SESSION_ID) is not None:
            return
        if not mail_agent.waiting_count(self.ctx):
            self.release_mail = False
            return
        if not self._model_ready():
            return
        origin = "mail-hourly" if chosen == "hourly" else "mail"
        own = self._mail_trigger()
        settings = {"mode": own["context_mode"], "keep_messages": own["keep_messages"]}
        prepared = mail_agent.next_turn(self.ctx, origin, settings)
        if prepared is None:
            self.release_mail = False
            return
        request, runs = prepared
        self._dispatch(request, runs, own["token_limit"] or self.config.triage_token_limit)

    def _mail_trigger(self) -> Any:
        return self.ctx.bus.db.fetch_all(
            "SELECT * FROM agent_triggers WHERE id = ?", (mail_agent.MAIL_TRIGGER,)
        )[0]

    def _start_custom(self) -> None:
        db = self.ctx.bus.db
        for trigger in db.fetch_all(
            "SELECT * FROM agent_triggers WHERE kind = ? AND enabled = 1", (CUSTOM,)
        ):
            runs = db.fetch_all(
                "SELECT id, thread FROM trigger_runs WHERE trigger = ? AND status = 'pending' ORDER BY id",
                (trigger["id"],),
            )
            if not runs:
                continue
            session = self._trigger_session(trigger)
            if self.runtime.active_turn(session) is not None or not self._model_ready():
                continue
            threads = list(dict.fromkeys(r["thread"] for r in runs if r["thread"]))
            task = self._threads_text(session, threads[:MOST_THREADS_PER_RUN])
            own = {"mode": trigger["context_mode"], "keep_messages": trigger["keep_messages"]}
            request = TurnRequest(session, trigger["prompt"], EVENT_ORIGIN, task=task, context=own)
            self._dispatch(request, [r["id"] for r in runs], trigger["token_limit"])

    def _trigger_session(self, trigger: Any) -> str:
        """One chat for each trigger, so its runs read as one conversation."""
        last = trigger["session"]
        if last and self.ctx.bus.db.fetch_all(
            "SELECT 1 FROM agent_sessions WHERE id = ? AND archived = 0", (last,)
        ):
            return str(last)
        session = str(self.runtime.create(trigger["title"], [], CUSTOM_AGENT).id)
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE agent_triggers SET session = ? WHERE id = ?", (session, trigger["id"])
            )
        return session

    def _threads_text(self, session: str, threads: list[int]) -> str:
        """The mail that set this off, as data. Reading it makes the session untrusted."""
        blocks = []
        for thread in threads:
            subject, _, text = mail_agent._thread_text(
                self.ctx,
                thread,
                self.config.max_recent_thread_messages,
                self.config.max_thread_chars,
            )
            if text:
                blocks.append(f"Conversation {thread}\nSubject: {subject}\n\n{text}")
        if not blocks:
            return ""
        with self.ctx.bus.db.transaction() as tx:
            tx.execute("UPDATE agent_sessions SET untrusted = 1 WHERE id = ?", (session,))
        joined = "\n\n".join(blocks)
        return f"This happened:\n<untrusted>\n{joined}\n</untrusted>"

    def _dispatch(self, request: TurnRequest, runs: list[int], token_limit: int) -> bool:
        gateway.set_run_limit(self.ctx.bus.db, request.session, token_limit)
        try:
            turn = self.runtime.dispatch(request)
        except CommandError:
            # Someone else started in this chat first. It goes when that finishes.
            return False
        with self.ctx.bus.db.transaction() as tx:
            for run in runs:
                tx.execute(
                    "UPDATE trigger_runs SET status = 'running', session = ?, turn = ? WHERE id = ?",
                    (request.session, turn, run),
                )
        return True

    def _start_schedules(self) -> None:
        db = self.ctx.bus.db
        rows = db.fetch_all(
            "SELECT id, schedule FROM trigger_runs WHERE trigger = ? AND status = 'pending' ORDER BY id",
            (SCHEDULE_TRIGGER,),
        )
        for run in rows:
            found = db.fetch_all("SELECT * FROM schedules WHERE id = ?", (run["schedule"],))
            if not found:
                mail_agent.settle(self.ctx, [run["id"]], "skipped")
            elif found[0]["kind"] == HOURLY_KIND:
                self._hourly(run["id"])
            else:
                self._start_schedule(run["id"], found[0])

    def _hourly(self, run: int) -> None:
        if mail_agent.mode(self.ctx) == "hourly":
            self.release_mail = bool(mail_agent.waiting_count(self.ctx))
            mail_agent.settle(self.ctx, [run], "done" if self.release_mail else "skipped")
            return
        if self.runtime.active_turn(mail_agent.SESSION_ID) is not None or not self._model_ready():
            return
        request = mail_agent.digest_turn(self.ctx, self._digest_since())
        if request is None:
            mail_agent.settle(self.ctx, [run], "skipped")
            return
        scheduler.set_default(self.ctx, LAST_DIGEST, mail_agent._now())
        self._dispatch(request, [run], self.config.triage_token_limit)

    def _digest_since(self) -> str:
        """Since the last digest, and never further back than an hour."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT value FROM agent_defaults WHERE key = ?", (LAST_DIGEST,)
        )
        hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        return max(rows[0]["value"], hour_ago) if rows else hour_ago

    def _start_digest(self) -> bool:
        request = mail_agent.digest_turn(self.ctx, self._digest_since())
        if request is None or self.runtime.active_turn(mail_agent.SESSION_ID) is not None:
            return False
        scheduler.set_default(self.ctx, LAST_DIGEST, mail_agent._now())
        event = uuid.uuid4().hex
        with self.ctx.bus.db.transaction() as tx:
            cursor = tx.execute(
                "INSERT INTO trigger_runs (trigger, event, time, status) VALUES (?, ?, ?, 'pending')",
                ("mail-digest", event, mail_agent._now()),
            )
            run = int(cursor.lastrowid or 0)
        return self._dispatch(request, [run], self.config.triage_token_limit)

    def _start_schedule(self, run: int, schedule: Any) -> None:
        """One chat for each schedule, so its runs read as one conversation."""
        session = self._schedule_session(schedule)
        if self.runtime.active_turn(session) is not None or not self._model_ready():
            return
        own = {"mode": schedule["context_mode"], "keep_messages": schedule["keep_messages"]}
        prompt = schedule["prompt"] or "Prepare my morning from the work board."
        request = TurnRequest(session, prompt, SCHEDULE_ORIGIN, context=own)
        if not self._dispatch(request, [run], schedule["token_limit"]):
            return
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE schedules SET last_session = ? WHERE id = ?", (session, schedule["id"])
            )
            work.emit(
                "schedule.ran",
                {"id": schedule["id"], "session": session},
                source="agent",
                trace_id=self.ctx.trace_id,
            )

    def _schedule_session(self, schedule: Any) -> str:
        last = schedule["last_session"]
        if last and self.ctx.bus.db.fetch_all(
            "SELECT 1 FROM agent_sessions WHERE id = ? AND archived = 0", (last,)
        ):
            return str(last)
        agent = SCHEDULE_AGENTS.get(schedule["kind"], "scheduled")
        session = self.runtime.create(schedule["title"], [], agent).id
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE schedules SET last_session = ? WHERE id = ?", (session, schedule["id"])
            )
        return str(session)

    # When a run ends

    def turn_ended(self, turn: int, error: str | None) -> None:
        db = self.ctx.bus.db
        self.waiting_for_model = None
        runs = db.fetch_all(
            "SELECT * FROM trigger_runs WHERE turn = ? AND status = 'running'", (turn,)
        )
        mail = [run for run in runs if run["trigger"] == mail_agent.MAIL_TRIGGER]
        if mail:
            mail_agent.after_turn(self.ctx, turn, mail, error)
        others = [run["id"] for run in runs if run["trigger"] != mail_agent.MAIL_TRIGGER]
        mail_agent.settle(self.ctx, others, "failed" if error else "done", error)
        self.wake.set()


def _row_to_trigger(row: Any) -> Trigger:
    return Trigger(
        id=row["id"],
        title=row["title"],
        kind=row["kind"],
        event=row["event"],
        prompt=row["prompt"],
        enabled=bool(row["enabled"]),
        token_limit=row["token_limit"],
        context_mode=row["context_mode"],
        keep_messages=row["keep_messages"],
        session=mail_agent.SESSION_ID if row["kind"] == "mail" else row["session"],
    )


def list_triggers(ctx: Context) -> TriggerList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM agent_triggers ORDER BY kind = 'mail' DESC, created")
    return TriggerList(
        triggers=[_row_to_trigger(row) for row in rows],
        events=[TriggerChoice(event=event, label=label) for event, label in EVENT_CHOICES.items()],
    )


def save_trigger(ctx: Context, command: SaveTrigger) -> TriggerList:
    values = (command.enabled, command.token_limit, command.context_mode, command.keep_messages)
    with ctx.bus.unit_of_work() as work:
        if command.id == mail_agent.MAIL_TRIGGER:
            # What sets it off and what it's told are built in. How it runs is the person's.
            work.tx.execute(
                "UPDATE agent_triggers SET enabled = ?, token_limit = ?, context_mode = ?, keep_messages = ? WHERE id = ?",
                (*values, command.id),
            )
        elif command.id:
            work.tx.execute(
                "UPDATE agent_triggers SET title = ?, event = ?, prompt = ?, enabled = ?, token_limit = ?, context_mode = ?, keep_messages = ?"
                " WHERE id = ? AND kind = ?",
                (command.title, command.event, command.prompt, *values, command.id, CUSTOM),
            )
        else:
            work.tx.execute(
                "INSERT INTO agent_triggers (id, title, kind, agent, event, prompt, enabled, token_limit, context_mode, keep_messages, created)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{CUSTOM}-{uuid.uuid4().hex[:12]}",
                    command.title,
                    CUSTOM,
                    CUSTOM_AGENT,
                    command.event,
                    command.prompt,
                    *values,
                    mail_agent._now(),
                ),
            )
        work.emit("triggers.changed", {}, source="agent", trace_id=ctx.trace_id)
    return list_triggers(ctx)


def remove_trigger(ctx: Context, identifier: str) -> TriggerList:
    with ctx.bus.unit_of_work() as work:
        removed = work.tx.execute(
            "DELETE FROM agent_triggers WHERE id = ? AND kind = ?", (identifier, CUSTOM)
        ).rowcount
        if not removed:
            raise CommandError("trigger.not_found", "That trigger can't be removed.", 404)
        work.tx.execute(
            "DELETE FROM trigger_runs WHERE trigger = ? AND status = 'pending'", (identifier,)
        )
        work.emit("triggers.changed", {}, source="agent", trace_id=ctx.trace_id)
    return list_triggers(ctx)
