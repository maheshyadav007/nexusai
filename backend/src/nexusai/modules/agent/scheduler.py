"""One timer for whatever's due next, so nothing polls. Missed work happens on the next wake."""

import threading
from datetime import datetime, timedelta

import structlog

from nexusai.contracts.agent import Schedule, ScheduleRow
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import channel
from nexusai.modules.planner import module as planner

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_schedule_001",
    """
CREATE TABLE schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, prompt TEXT NOT NULL, kind TEXT NOT NULL, every TEXT NOT NULL, time TEXT NOT NULL,
  weekday INTEGER NOT NULL DEFAULT 0, date TEXT, enabled INTEGER NOT NULL DEFAULT 1, token_limit INTEGER NOT NULL DEFAULT 0,
  next_run TEXT, last_run TEXT, last_session TEXT);
CREATE TABLE agent_defaults (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""",
)
# A closed laptop can skip any timer, so the wait is capped and the clock is re-read on waking.
LONGEST_SLEEP_SECONDS = 300
OVERDUE_NOTICE_KIND = "overdue"


def _local_now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None, second=0, microsecond=0)


def next_run_after(schedule: Schedule, after: datetime) -> str | None:
    hour, minute = map(int, schedule.time.split(":"))
    if schedule.every == "once":
        if not schedule.date:
            return None
        return f"{schedule.date}T{schedule.time}"
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if schedule.every == "week":
        candidate += timedelta(days=(schedule.weekday - candidate.weekday()) % 7)
        if candidate <= after:
            candidate += timedelta(weeks=1)
    elif candidate <= after:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%dT%H:%M")


def row_to_schedule(row: object) -> ScheduleRow:
    data = dict(row)  # type: ignore[call-overload]
    return ScheduleRow(**{**data, "enabled": bool(data["enabled"])})


def time_check_enabled(ctx: Context) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = 'time_check_enabled'")
    return not rows or rows[0]["value"] == "1"


def set_default(ctx: Context, key: str, value: bool) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_defaults (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, "1" if value else "0"),
        )


class Scheduler:
    def __init__(self, ctx: Context, run_prompt: object) -> None:
        self.ctx = ctx
        self.run_prompt = run_prompt
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=10)

    def poke(self) -> None:
        """Something changed, so the next due time may be sooner."""
        self.wake.set()

    def _next_due(self) -> datetime | None:
        rows = self.ctx.bus.db.fetch_all(
            "SELECT MIN(next_run) AS due FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL"
        )
        candidates = [rows[0]["due"], planner.next_reminder_due(self.ctx)]
        moments = [datetime.fromisoformat(value[:16]) for value in candidates if value]
        return min(moments) if moments else None

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.tick(_local_now())
            except Exception:
                log.exception("scheduler_failed")
            due = self._next_due()
            seconds = float(LONGEST_SLEEP_SECONDS)
            if due is not None:
                seconds = max(
                    1.0, min((due - datetime.now()).total_seconds(), LONGEST_SLEEP_SECONDS)
                )
            self.wake.wait(seconds)
            self.wake.clear()

    def tick(self, now: datetime) -> None:
        if time_check_enabled(self.ctx):
            planner.fire_due_reminders(self.ctx, now)
            self._overdue(now)
        self._run_due(now)

    def _overdue(self, now: datetime) -> None:
        """Work board deadlines that have passed. Uses no model, and tells the person once."""
        today = now.strftime("%Y-%m-%d")
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id, title, thread FROM work_board WHERE done = 0 AND due IS NOT NULL AND due < ? AND kind = 'deadline'",
            (today,),
        )
        for row in rows:
            with self.ctx.bus.unit_of_work() as work:
                work.tx.execute("UPDATE work_board SET done = 1 WHERE id = ?", (row["id"],))
                channel.notify(
                    self.ctx,
                    work,
                    f"Overdue: {row['title']}",
                    "",
                    f"/mail/thread/{row['thread']}" if row["thread"] else "/today",
                    OVERDUE_NOTICE_KIND,
                    False,
                )

    def _run_due(self, now: datetime) -> None:
        stamp = now.strftime("%Y-%m-%dT%H:%M")
        rows = self.ctx.bus.db.fetch_all(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ? ORDER BY next_run",
            (stamp,),
        )
        for row in rows:
            schedule = row_to_schedule(row)
            following = None if schedule.every == "once" else next_run_after(schedule, now)
            session = self.run_prompt(schedule)  # type: ignore[operator]
            with self.ctx.bus.unit_of_work() as work:
                work.tx.execute(
                    "UPDATE schedules SET next_run = ?, last_run = ?, last_session = ?, enabled = ? WHERE id = ?",
                    (following, stamp, session, int(schedule.every != "once"), schedule.id),
                )
                work.emit(
                    "schedule.ran",
                    {"id": schedule.id, "session": session},
                    source="agent",
                    trace_id=self.ctx.trace_id,
                )
