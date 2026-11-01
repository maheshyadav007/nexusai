"""The person's own to-dos and reminders. The agent may only propose them."""

from datetime import UTC, datetime, timedelta

from nexusai.contracts.notifications import NotificationRequested
from nexusai.contracts.planner import (
    ListReminders,
    ListTasks,
    PlannerDone,
    Reminder,
    ReminderAction,
    ReminderList,
    SaveReminder,
    SaveTask,
    SnoozeReminder,
    Task,
    TaskAction,
    TaskList,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module

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
        )
    ],
)
REPEATS = {"day": timedelta(days=1), "week": timedelta(weeks=1)}


def _emit(ctx: Context, kind: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit(f"{kind}.changed", {}, source="planner", trace_id=ctx.trace_id)


def _task(row: object) -> Task:
    data = dict(row)  # type: ignore[call-overload]
    return Task(**{**data, "proposed": bool(data["proposed"])})


def _reminder(row: object) -> Reminder:
    data = dict(row)  # type: ignore[call-overload]
    return Reminder(
        id=data["id"],
        title=data["title"],
        when=data["due_at"],
        repeat=data["repeat"],
        thread=data["thread"],
        task=data["task"],
        source=data["source"],
        proposed=bool(data["proposed"]),
        fired=bool(data["fired"]),
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
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO tasks (title, notes, status, due, thread, source, proposed, created) VALUES (?, ?, 'todo', ?, ?, ?, ?, ?)",
            (title, notes, due, thread, source, int(proposed), datetime.now(UTC).isoformat()),
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
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO reminders (title, due_at, repeat, thread, task, source, proposed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, when, repeat, thread, task, source, int(proposed)),
        )
        work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return int(cursor.lastrowid or 0)


@planner_module.query("tasks.list")
def list_tasks(query: ListTasks, ctx: Context) -> TaskList:
    where = "" if query.include_done else "WHERE status != 'done'"
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM tasks {where} ORDER BY proposed DESC, due IS NULL, due, id DESC"
    )  # noqa: S608
    return TaskList(tasks=[_task(row) for row in rows])


@planner_module.command("tasks.save")
def save_task(command: SaveTask, ctx: Context) -> PlannerDone:
    if command.id is None:
        add_task(ctx, command.title, command.due, command.thread, "user", False, command.notes)
        return PlannerDone()
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE tasks SET title = ?, notes = ?, status = ?, due = ?, thread = ?, proposed = ? WHERE id = ?",
            (
                command.title,
                command.notes,
                command.status,
                command.due,
                command.thread,
                int(command.proposed),
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
    return ReminderList(reminders=[_reminder(row) for row in rows])


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
            "UPDATE reminders SET title = ?, due_at = ?, repeat = ?, thread = ?, task = ?, proposed = ?, fired = 0 WHERE id = ?",
            (
                command.title,
                command.when,
                command.repeat,
                command.thread,
                command.task,
                int(command.proposed),
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
            "UPDATE reminders SET due_at = ?, fired = 0 WHERE id = ?", (when, command.id)
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
            step = REPEATS.get(row["repeat"])
            if step:
                # The next one still in the future, however long the computer was off.
                due = datetime.fromisoformat(row["due_at"])
                while due.replace(tzinfo=None) <= now.replace(tzinfo=None):
                    due += step
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
