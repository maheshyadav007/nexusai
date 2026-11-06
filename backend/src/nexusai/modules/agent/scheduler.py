"""One timer for whatever's due next, so nothing polls. Missed work happens on the next wake.

The clock only says something came due. Starting the agent is the same as for any other event.
"""

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from tzlocal import get_localzone_name

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
TIMES_MIGRATION = Migration(
    "agent_schedule_times_001",
    """
ALTER TABLE schedules ADD COLUMN created TEXT;
ALTER TABLE schedules ADD COLUMN updated TEXT;
""",
)
# A closed laptop can skip any timer, so the wait is capped and the clock is re-read on waking.
LONGEST_SLEEP_SECONDS = 300
OVERDUE_NOTICE_KIND = "overdue"
CONTEXT_MIGRATION = Migration(
    "agent_schedule_context_001",
    """
ALTER TABLE schedules ADD COLUMN context_mode TEXT;
ALTER TABLE schedules ADD COLUMN keep_messages INTEGER;
INSERT INTO schedules (title, prompt, kind, every, time, enabled) VALUES ('Mail agent, hourly', '', 'mail-hourly', 'hour', '00:00', 0);
""",
)


BUILT_IN_MIGRATION = Migration(
    "agent_schedule_built_in_001",
    """
INSERT INTO schedules (title, prompt, kind, every, time, enabled) VALUES ('Morning brief', '', 'mail-brief', 'day', '08:30', 1);
INSERT INTO schedules (title, prompt, kind, every, weekday, time, enabled) VALUES ('Inbox review', '', 'mail-review', 'week', 0, '09:00', 1);
""",
)
RELIABILITY_MIGRATION = Migration(
    "agent_schedule_reliability_001",
    "ALTER TABLE work_board ADD COLUMN overdue_notified_at TEXT;"
    "ALTER TABLE trigger_runs ADD COLUMN manual INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE trigger_runs ADD COLUMN completed_through TEXT;"
    "ALTER TABLE schedules ADD COLUMN timezone TEXT NOT NULL DEFAULT '';",
)
FOLLOW_UP_NOTICE_KIND = "follow-up"
BRIEF_KIND = "mail-brief"
REVIEW_KIND = "mail-review"
# What the Mail agent runs for itself, which the person turns on and off through its settings.
BUILT_IN_KINDS = ("mail-hourly", BRIEF_KIND, REVIEW_KIND)


def system_timezone() -> str:
    try:
        candidate = os.environ.get("TZ") or get_localzone_name()
        ZoneInfo(candidate)
        return candidate
    except (ZoneInfoNotFoundError, ValueError, OSError, RuntimeError, LookupError):
        return "UTC"


def next_scheduled_run(schedule: Schedule, after: datetime) -> str | None:
    zone = ZoneInfo(schedule.timezone or system_timezone())
    instant = after if after.tzinfo else after.replace(tzinfo=ZoneInfo(system_timezone()))
    local = instant.astimezone(zone).replace(tzinfo=None)
    candidate = next_run_after(schedule, local)
    if candidate is None:
        return None
    # Ambiguous times use the first occurrence. Nonexistent times advance by the DST gap.
    result = datetime.fromisoformat(candidate).replace(tzinfo=zone, fold=0).astimezone(UTC)
    while schedule.every != "once" and result <= instant.astimezone(UTC):
        next_value = next_run_after(schedule, datetime.fromisoformat(candidate))
        if next_value is None:
            return None
        candidate = next_value
        result = datetime.fromisoformat(candidate).replace(tzinfo=zone, fold=0).astimezone(UTC)
    return result.isoformat()


def initialize_timezones(ctx: Context) -> None:
    zone = system_timezone()
    with ctx.bus.db.transaction() as tx:
        for row in tx.execute("SELECT id,next_run FROM schedules WHERE timezone='' ").fetchall():
            value = datetime.fromisoformat(row["next_run"]) if row["next_run"] else None
            if value and value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo(zone))
            tx.execute(
                "UPDATE schedules SET timezone=?,next_run=? WHERE id=?",
                (zone, value.astimezone(UTC).isoformat() if value else None, row["id"]),
            )


def _local_now() -> datetime:
    # Preserve the OS offset: losing it can reinterpret local wall time as UTC.
    return datetime.now().astimezone().replace(second=0, microsecond=0)


def next_run_after(schedule: Schedule, after: datetime) -> str | None:
    hour, minute = map(int, schedule.time.split(":"))
    if schedule.every == "once":
        if not schedule.date:
            return None
        return f"{schedule.date}T{schedule.time}"
    if schedule.every == "hour":
        candidate = after.replace(minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(hours=1)
        return candidate.strftime("%Y-%m-%dT%H:%M")
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
    data["timezone"] = data.get("timezone") or system_timezone()
    return ScheduleRow(**{**data, "enabled": bool(data["enabled"])})


def time_check_enabled(ctx: Context) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key = 'time_check_enabled'")
    return not rows or rows[0]["value"] == "1"


def set_default(ctx: Context, key: str, value: bool | str) -> None:
    text = value if isinstance(value, str) else "1" if value else "0"
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_defaults (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, text),
        )


def start_built_ins(ctx: Context) -> None:
    """The ones that come with the app have no time set until they first run."""
    initialize_timezones(ctx)
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM schedules WHERE enabled = 1 AND next_run IS NULL AND kind IN (?, ?)",
        (BRIEF_KIND, REVIEW_KIND),
    )
    for row in rows:
        following = next_scheduled_run(row_to_schedule(row), datetime.now(UTC))
        with ctx.bus.db.transaction() as tx:
            tx.execute("UPDATE schedules SET next_run = ? WHERE id = ?", (following, row["id"]))


def built_in_on(ctx: Context, kind: str) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT enabled FROM schedules WHERE kind = ?", (kind,))
    return bool(rows and rows[0]["enabled"])


def set_built_in(ctx: Context, kind: str, enabled: bool) -> None:
    rows = ctx.bus.db.fetch_all("SELECT * FROM schedules WHERE kind = ?", (kind,))
    if not rows:
        return
    following = next_scheduled_run(row_to_schedule(rows[0]), datetime.now(UTC)) if enabled else None
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE schedules SET enabled = ?, next_run = ? WHERE id = ?",
            (int(enabled), following, rows[0]["id"]),
        )
        if not enabled:
            tx.execute(
                "UPDATE trigger_runs SET status='skipped',error='Schedule paused' WHERE schedule=? AND status='pending' AND manual=0",
                (rows[0]["id"],),
            )


def set_hourly(ctx: Context, enabled: bool) -> None:
    """The Mail agent's hourly run, which the person turns on through its setting."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM schedules WHERE kind = 'mail-hourly'")
    if not rows:
        return
    following = next_scheduled_run(row_to_schedule(rows[0]), datetime.now(UTC)) if enabled else None
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE schedules SET enabled = ?, next_run = ? WHERE id = ?",
            (int(enabled), following, rows[0]["id"]),
        )
        if not enabled:
            tx.execute(
                "UPDATE trigger_runs SET status='skipped',error='Schedule paused' WHERE schedule=? AND status='pending' AND manual=0",
                (rows[0]["id"],),
            )


class Scheduler:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self.pruned_on: str | None = None

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
        moments = []
        for value in candidates:
            if value:
                parsed = datetime.fromisoformat(value)
                moments.append(
                    (
                        parsed
                        if parsed.tzinfo
                        else parsed.replace(tzinfo=ZoneInfo(system_timezone()))
                    ).astimezone(UTC)
                )
        return min(moments) if moments else None

    def _loop(self) -> None:
        while not self.stopping.is_set():
            seconds = float(LONGEST_SLEEP_SECONDS)
            try:
                self.tick(_local_now())
                due = self._next_due()
                if due is not None:
                    seconds = max(
                        1.0, min((due - datetime.now(UTC)).total_seconds(), LONGEST_SLEEP_SECONDS)
                    )
            except Exception:
                # Reading the next due time can fail too; keep the timer alive.
                log.exception("scheduler_failed")
                seconds = min(60.0, LONGEST_SLEEP_SECONDS)
            self.wake.wait(seconds)
            self.wake.clear()

    def _prune_events(self, now: datetime) -> None:
        """Once a day, since the event log would otherwise grow forever."""
        day = now.strftime("%Y-%m-%d")
        if self.pruned_on == day:
            return
        keep = timedelta(days=self.ctx.config.log_retention_days)
        self.ctx.bus.prune((datetime.now(UTC) - keep).isoformat())
        self.pruned_on = day

    def tick(self, now: datetime) -> None:
        jobs: list[tuple[str, Callable[[datetime], object]]] = [("prune", self._prune_events)]
        if time_check_enabled(self.ctx):
            jobs.extend(
                [
                    ("reminders", lambda instant: planner.fire_due_reminders(self.ctx, instant)),
                    ("overdue", self._overdue),
                    ("follow-ups", self._follow_ups),
                ]
            )
        jobs.append(("schedules", self._run_due))
        for name, job in jobs:
            try:
                job(now)
            except Exception:
                # One broken reminder must not stop all scheduled agents.
                log.exception("scheduler_job_failed", job=name)

    def _overdue(self, now: datetime) -> None:
        """Work board deadlines that have passed. Uses no model, and tells the person once."""
        if channel.in_quiet_hours(channel.load_quiet(self.ctx.bus.db), now):
            return
        today = now.strftime("%Y-%m-%d")
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id, title, thread FROM work_board WHERE done = 0 AND due IS NOT NULL AND due < ? AND kind = 'deadline' AND overdue_notified_at IS NULL",
            (today,),
        )
        for row in rows:
            with self.ctx.bus.unit_of_work() as work:
                work.tx.execute(
                    "UPDATE work_board SET overdue_notified_at = ? WHERE id = ?", (today, row["id"])
                )
                channel.notify(
                    self.ctx,
                    work,
                    f"Overdue: {row['title']}",
                    "",
                    f"/mail/thread/{row['thread']}" if row["thread"] else "/today",
                    OVERDUE_NOTICE_KIND,
                    False,
                )

    def _follow_ups(self, now: datetime) -> None:
        """Nobody's answered by the day it was worth chasing. Uses no model, and tells them once."""
        if channel.in_quiet_hours(channel.load_quiet(self.ctx.bus.db), now):
            return
        today = now.strftime("%Y-%m-%d")
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id, subject FROM threads WHERE status = 'waiting_on_others' AND follow_up_on <= ?"
            " AND followup_notified IS NULL AND in_trash = 0",
            (today,),
        )
        for row in rows:
            with self.ctx.bus.unit_of_work() as work:
                work.tx.execute(
                    "UPDATE threads SET followup_notified = ? WHERE id = ?", (today, row["id"])
                )
                channel.notify(
                    self.ctx,
                    work,
                    f"No answer yet: {row['subject'] or 'your message'}",
                    "It's time to follow up.",
                    f"/mail/thread/{row['id']}",
                    FOLLOW_UP_NOTICE_KIND,
                    False,
                )
                work.emit(
                    "mail.changed",
                    {"threads": 1, "reason": "follow-up"},
                    source="agent",
                    trace_id=self.ctx.trace_id,
                )

    def _run_due(self, now: datetime) -> None:
        instant = now if now.tzinfo else now.replace(tzinfo=ZoneInfo(system_timezone()))
        stamp = instant.astimezone(UTC).isoformat()
        rows = self.ctx.bus.db.fetch_all(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ? ORDER BY next_run",
            (stamp,),
        )
        for row in rows:
            schedule = row_to_schedule(row)
            following = None if schedule.every == "once" else next_scheduled_run(schedule, instant)
            with self.ctx.bus.unit_of_work() as work:
                work.tx.execute(
                    "UPDATE schedules SET next_run = ?, last_run = ?, enabled = ? WHERE id = ?",
                    (following, stamp, int(schedule.every != "once"), schedule.id),
                )
                work.emit(
                    "schedule.due",
                    {"id": schedule.id},
                    source="agent",
                    trace_id=self.ctx.trace_id,
                )
