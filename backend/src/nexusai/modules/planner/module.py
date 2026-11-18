"""The person's own to-dos and reminders. The agent may only propose them."""

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any, cast, get_args

from nexusai.contracts.notifications import NotificationRequested
from nexusai.contracts.planner import (
    ListReminders,
    ListTasks,
    PlannerDone,
    Reminder,
    ReminderAction,
    ReminderList,
    Repeat,
    SaveReminder,
    SaveTask,
    SnoozeReminder,
    Task,
    TaskAction,
    TaskList,
    TaskStatus,
)
from nexusai.kernel import textmatch
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail.source import thread_source

planner_module = Module(
    name="planner",
    migrations=[
        Migration(
            "planner_001",
            """
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  due TEXT, thread INTEGER, source TEXT NOT NULL, proposed INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
CREATE TABLE reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, due_at TEXT NOT NULL, repeat TEXT NOT NULL, thread INTEGER,
  task INTEGER, source TEXT NOT NULL, proposed INTEGER NOT NULL DEFAULT 0, fired INTEGER NOT NULL DEFAULT 0);
CREATE INDEX reminders_due ON reminders (fired, proposed, due_at);
""",
        ),
        Migration(
            "planner_times_001",
            """
ALTER TABLE tasks ADD COLUMN updated TEXT;
ALTER TABLE tasks ADD COLUMN completed TEXT;
ALTER TABLE reminders ADD COLUMN created TEXT;
ALTER TABLE reminders ADD COLUMN updated TEXT;
""",
        ),
        Migration(
            "planner_repeats_001",
            # A repeat word the app didn't know made the whole list fail to load. Known
            # spellings become what they meant; anything else stops repeating.
            """
ALTER TABLE reminders ADD COLUMN repeat_day INTEGER;
UPDATE reminders SET repeat = CASE LOWER(TRIM(repeat))
  WHEN 'daily' THEN 'day' WHEN 'weekly' THEN 'week' WHEN 'monthly' THEN 'month'
  WHEN 'yearly' THEN 'year' WHEN 'annually' THEN 'year' WHEN 'annual' THEN 'year'
  WHEN 'day' THEN 'day' WHEN 'week' THEN 'week' WHEN 'month' THEN 'month' WHEN 'year' THEN 'year'
  ELSE 'none' END;
UPDATE reminders SET repeat_day = CAST(SUBSTR(due_at, 9, 2) AS INTEGER)
  WHERE repeat IN ('month', 'year');
""",
        ),
        Migration(
            "planner_task_status_001",
            # The same for a task status an agent once wrote in its own words.
            """
UPDATE tasks SET status = CASE
  WHEN LOWER(TRIM(status)) IN ('done', 'complete', 'completed', 'finished', 'closed') THEN 'done'
  WHEN LOWER(TRIM(status)) IN ('in_progress', 'in progress', 'in-progress', 'doing', 'started')
    THEN 'in_progress'
  ELSE 'todo' END
  WHERE status NOT IN ('todo', 'in_progress', 'done');
""",
        ),
    ],
)
REPEATS = {"day": timedelta(days=1), "week": timedelta(weeks=1)}
KNOWN_REPEATS: tuple[str, ...] = get_args(Repeat)
# What models and people often write instead.
REPEAT_WORDS = {
    "": "none", "never": "none", "once": "none", "no": "none",
    "daily": "day", "every day": "day", "weekly": "week", "every week": "week",
    "monthly": "month", "every month": "month",
    "yearly": "year", "annually": "year", "annual": "year", "every year": "year",
}  # fmt: skip


def repeat_of(value: str | None) -> Repeat:
    """How often it repeats, from the words used, or a plain error naming the choices."""
    word = (value or "none").strip().lower()
    word = REPEAT_WORDS.get(word, word)
    if word not in KNOWN_REPEATS:
        raise CommandError(
            "reminder.repeat",
            f"A reminder can't repeat {value!r}. Use one of: {', '.join(KNOWN_REPEATS)}.",
            422,
        )
    return cast(Repeat, word)


STATUS_WORDS = {
    "to do": "todo", "open": "todo", "pending": "todo", "not started": "todo", "new": "todo",
    "in progress": "in_progress", "in-progress": "in_progress", "doing": "in_progress",
    "started": "in_progress", "done": "done", "complete": "done", "completed": "done",
    "finished": "done", "closed": "done",
}  # fmt: skip
KNOWN_STATUSES: tuple[str, ...] = get_args(TaskStatus)


def status_of(value: str) -> TaskStatus:
    word = value.strip().lower()
    word = STATUS_WORDS.get(word, word)
    if word not in KNOWN_STATUSES:
        raise CommandError(
            "task.status",
            f"A task can't be {value!r}. Use one of: {', '.join(KNOWN_STATUSES)}.",
            422,
        )
    return cast(TaskStatus, word)


def when_of(value: str) -> str:
    """A reminder's time as the app stores it. Anything else would never come due, silently."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise CommandError(
            "reminder.when",
            f"{value!r} isn't a time. Use YYYY-MM-DDTHH:MM in their local time, "
            "like 2031-05-01T09:00.",
            422,
        ) from None
    return parsed.strftime("%Y-%m-%dT%H:%M")


def due_of(value: str | None) -> str | None:
    """A task's due date as the app stores it, or None for no date."""
    if value is None or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).strftime("%Y-%m-%d")
    except ValueError:
        raise CommandError(
            "task.due", f"{value!r} isn't a date. Use YYYY-MM-DD, like 2031-05-01.", 422
        ) from None


def _day_for(repeat: str, due_at: str) -> int | None:
    """The day of the month a monthly or yearly reminder keeps, so the 31st stays the 31st
    after a shorter month."""
    return int(due_at[8:10]) if repeat in {"month", "year"} and len(due_at) >= 10 else None


def next_due(due: datetime, repeat: str, day: int | None) -> datetime:
    step = REPEATS.get(repeat)
    if step:
        return due + step
    if repeat == "month":
        year, month = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
    else:
        year, month = due.year + 1, due.month
    wanted = day or due.day
    return due.replace(year=year, month=month, day=min(wanted, calendar.monthrange(year, month)[1]))


def _emit(ctx: Context, kind: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit(f"{kind}.changed", {}, source="planner", trace_id=ctx.trace_id)


def _task(db: Database, row: object) -> Task:
    data = dict(row)  # type: ignore[call-overload]
    # One bad row mustn't stop the whole list from loading.
    if data["status"] not in KNOWN_STATUSES:
        data["status"] = "todo"
    return Task(
        **{
            **data,
            "proposed": bool(data["proposed"]),
            "updated": data["updated"] or data["created"],
            "source_ref": thread_source(db, data["thread"]),
        }
    )


def _reminder(db: Database, row: object) -> Reminder:
    data = dict(row)  # type: ignore[call-overload]
    return Reminder(
        source_ref=thread_source(db, data["thread"]),
        id=data["id"],
        title=data["title"],
        when=data["due_at"],
        # One bad row mustn't stop the whole list from loading.
        repeat=data["repeat"] if data["repeat"] in KNOWN_REPEATS else "none",
        thread=data["thread"],
        task=data["task"],
        source=data["source"],
        proposed=bool(data["proposed"]),
        fired=bool(data["fired"]),
        created=data["created"],
        updated=data["updated"] or data["created"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


TASK_FIELDS = {"title", "notes", "status", "due", "proposed"}
REMINDER_FIELDS = {"title", "due_at", "repeat", "repeat_day", "proposed", "fired"}


def _change(ctx: Context, table: str, identifier: int, values: dict[str, Any], kind: str) -> None:
    """Only the named columns of a fixed list, so what a tool passes can't reach the SQL."""
    allowed = TASK_FIELDS if table == "tasks" else REMINDER_FIELDS
    named = {name: value for name, value in values.items() if name in allowed}
    if table == "reminders" and "repeat" in named:
        named["repeat"] = repeat_of(named["repeat"])
    if table == "reminders" and named.get("due_at") is not None:
        named["due_at"] = when_of(named["due_at"])
    if table == "tasks" and "status" in named:
        named["status"] = status_of(named["status"])
    if table == "tasks" and "due" in named:
        named["due"] = due_of(named["due"])
    named["updated"] = _now()
    if table == "tasks" and "status" in named:
        named["completed"] = _now() if named["status"] == "done" else None
    with ctx.bus.unit_of_work() as work:
        before = work.tx.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()  # noqa: S608
        if table == "reminders" and before and ({"repeat", "due_at"} & named.keys()):
            named["repeat_day"] = _day_for(
                named.get("repeat", before["repeat"]), named.get("due_at", before["due_at"])
            )
        columns = ", ".join(f"{name} = ?" for name in named)
        changed = work.tx.execute(
            f"UPDATE {table} SET {columns} WHERE id = ?",  # noqa: S608
            (*named.values(), identifier),
        ).rowcount
        if not changed:
            raise CommandError(
                f"{kind}.not_found", f"{kind.capitalize()} {identifier} is gone.", 404
            )
        work.emit(
            f"{table}.changed",
            {
                "id": identifier,
                "by": ctx.actor,
                "changes": values,
                "old": {key: before[key] for key in values} if before else {},
                "thread": before["thread"] if before else None,
            },
            source="planner",
            trace_id=ctx.trace_id,
        )


def change_task(ctx: Context, identifier: int, values: dict[str, Any]) -> None:
    _change(ctx, "tasks", identifier, values, "task")


def change_reminder(ctx: Context, identifier: int, values: dict[str, Any]) -> None:
    _change(ctx, "reminders", identifier, values, "reminder")


def remove_tasks(ctx: Context, identifiers: list[int]) -> None:
    with ctx.bus.db.transaction() as tx:
        for identifier in identifiers:
            tx.execute("DELETE FROM tasks WHERE id = ?", (identifier,))
    _emit(ctx, "tasks")


def remove_reminders(ctx: Context, identifiers: list[int]) -> None:
    with ctx.bus.db.transaction() as tx:
        for identifier in identifiers:
            tx.execute("DELETE FROM reminders WHERE id = ?", (identifier,))
    _emit(ctx, "reminders")


def has_task(db: Database, title: str, thread: int | None) -> bool:
    """Whether this conversation already led to this task, including one that's finished, in
    any wording. Only exact titles used to count, so a re-judged email added "Respond to Priya
    re budget" beside "Reply to Priya about the budget"."""
    if thread is None:
        # Without a conversation, only open suggestions are compared, not the whole task list.
        rows = db.fetch_all(
            "SELECT title FROM tasks WHERE thread IS NULL AND (proposed = 1 OR title = ?)",
            (title,),
        )
    else:
        rows = db.fetch_all("SELECT title FROM tasks WHERE thread = ?", (thread,))
    return any(row["title"] == title or textmatch.same(row["title"], title) for row in rows)


def has_reminder(db: Database, title: str, thread: int | None) -> bool:
    return bool(
        db.fetch_all("SELECT id FROM reminders WHERE title = ? AND thread IS ?", (title, thread))
    )


def add_task(
    ctx: Context,
    title: str,
    due: str | None,
    thread: int | None,
    source: str,
    proposed: bool,
    notes: str = "",
) -> int:
    due = due_of(due)
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO tasks (title, notes, status, due, thread, source, proposed, created, updated)"
            " VALUES (?, ?, 'todo', ?, ?, ?, ?, ?, ?)",
            (title, notes, due, thread, source, int(proposed), _now(), _now()),
        )
        work.emit("tasks.changed", {}, source="planner", trace_id=ctx.trace_id)
    return int(cursor.lastrowid or 0)


def add_reminder(
    ctx: Context,
    title: str,
    when: str,
    repeat: str,
    thread: int | None,
    task: int | None,
    source: str,
    proposed: bool,
) -> int:
    repeat = repeat_of(repeat)
    when = when_of(when)
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO reminders (title, due_at, repeat, repeat_day, thread, task, source,"
            " proposed, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                when,
                repeat,
                _day_for(repeat, when),
                thread,
                task,
                source,
                int(proposed),
                _now(),
                _now(),
            ),
        )
        work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return int(cursor.lastrowid or 0)


@planner_module.query("tasks.list")
def list_tasks(query: ListTasks, ctx: Context) -> TaskList:
    where = "" if query.include_done else "WHERE status != 'done'"
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM tasks {where} ORDER BY proposed DESC, due IS NULL, due, id DESC"
    )  # noqa: S608
    return TaskList(tasks=[_task(ctx.bus.db, row) for row in rows])


@planner_module.command("tasks.save")
def save_task(command: SaveTask, ctx: Context) -> PlannerDone:
    if command.id is None:
        add_task(ctx, command.title, command.due, command.thread, "user", False, command.notes)
        return PlannerDone()
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE tasks SET title = ?, notes = ?, status = ?, due = ?, thread = ?, proposed = ?,"
            " updated = ?, completed = CASE WHEN ? = 'done' THEN COALESCE(completed, ?) END"
            " WHERE id = ?",
            (
                command.title,
                command.notes,
                command.status,
                command.due,
                command.thread,
                int(command.proposed),
                _now(),
                command.status,
                _now(),
                command.id,
            ),
        )
        work.emit("tasks.changed", {}, source="planner", trace_id=ctx.trace_id)
    return PlannerDone()


@planner_module.command("tasks.remove")
def remove_task(command: TaskAction, ctx: Context) -> PlannerDone:
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM tasks WHERE id = ?", (command.id,))
    _emit(ctx, "tasks")
    return PlannerDone()


@planner_module.query("reminders.list")
def list_reminders(query: ListReminders, ctx: Context) -> ReminderList:
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM reminders WHERE fired = 0 ORDER BY proposed DESC, due_at"
    )
    return ReminderList(reminders=[_reminder(ctx.bus.db, row) for row in rows])


@planner_module.command("reminders.save")
def save_reminder(command: SaveReminder, ctx: Context) -> PlannerDone:
    if command.id is None:
        add_reminder(
            ctx,
            command.title,
            command.when,
            command.repeat,
            command.thread,
            command.task,
            "user",
            False,
        )
        return PlannerDone()
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE reminders SET title = ?, due_at = ?, repeat = ?, repeat_day = ?, thread = ?,"
            " task = ?, proposed = ?, fired = 0, updated = ? WHERE id = ?",
            (
                command.title,
                command.when,
                command.repeat,
                _day_for(command.repeat, command.when),
                command.thread,
                command.task,
                int(command.proposed),
                _now(),
                command.id,
            ),
        )
        work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return PlannerDone()


@planner_module.command("reminders.snooze")
def snooze_reminder(command: SnoozeReminder, ctx: Context) -> PlannerDone:
    when = (datetime.now().astimezone() + timedelta(minutes=command.minutes)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    with ctx.bus.unit_of_work() as work:
        changed = work.tx.execute(
            "UPDATE reminders SET due_at = ?, fired = 0, updated = ? WHERE id = ?",
            (when, _now(), command.id),
        ).rowcount
        if not changed:
            raise CommandError("reminder.not_found", "That reminder no longer exists.", 404)
        work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return PlannerDone()


@planner_module.command("reminders.remove")
def remove_reminder(command: ReminderAction, ctx: Context) -> PlannerDone:
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM reminders WHERE id = ?", (command.id,))
    _emit(ctx, "reminders")
    return PlannerDone()


def next_reminder_due(ctx: Context) -> str | None:
    rows = ctx.bus.db.fetch_all(
        "SELECT MIN(due_at) AS due FROM reminders WHERE fired = 0 AND proposed = 0"
    )
    due = rows[0]["due"]
    return str(due) if due else None


def fire_due_reminders(ctx: Context, now: datetime) -> int:
    """Everything that came due, including while the computer was asleep."""
    stamp = now.strftime("%Y-%m-%dT%H:%M")
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM reminders WHERE fired = 0 AND proposed = 0 AND due_at <= ? ORDER BY due_at",
        (stamp,),
    )
    for row in rows:
        link = f"/mail/thread/{row['thread']}" if row["thread"] else "/planner/reminders"
        with ctx.bus.unit_of_work() as work:
            if row["repeat"] in REPEATS or row["repeat"] in {"month", "year"}:
                # The next one still in the future, however long the computer was off.
                due = datetime.fromisoformat(row["due_at"])
                while due.replace(tzinfo=None) <= now.replace(tzinfo=None):
                    due = next_due(due, row["repeat"], row["repeat_day"])
                work.tx.execute(
                    "UPDATE reminders SET due_at = ? WHERE id = ?",
                    (due.strftime("%Y-%m-%dT%H:%M"), row["id"]),
                )
            else:
                work.tx.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))
            work.emit(
                "notification.requested",
                NotificationRequested(
                    kind="reminder", title=row["title"], detail="", link=link
                ).model_dump(),
                source="planner",
                trace_id=ctx.trace_id,
            )
            work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return len(rows)
