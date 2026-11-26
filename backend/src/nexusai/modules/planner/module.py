"""The person's own to-dos and reminders. The agent may only propose them."""

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
            "planner_matters_001",
            # Work belongs to a matter, and remembers the email that asked for it. A reminder
            # that goes with a task keeps its task as its parent instead.
            """
ALTER TABLE tasks ADD COLUMN matter INTEGER;
ALTER TABLE tasks ADD COLUMN source_message INTEGER;
ALTER TABLE reminders ADD COLUMN matter INTEGER;
CREATE INDEX tasks_matter ON tasks (matter);
CREATE INDEX reminders_matter ON reminders (matter);
CREATE INDEX reminders_task ON reminders (task);
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
        Migration(
            "planner_repeat_rules_001",
            # Reminders that repeat every so many minutes, on chosen days, between two times,
            # until a date: "every hour, 10:00 to 20:00, Monday to Friday" is one reminder.
            """
ALTER TABLE reminders ADD COLUMN every_minutes INTEGER;
ALTER TABLE reminders ADD COLUMN days TEXT;
ALTER TABLE reminders ADD COLUMN window_start TEXT;
ALTER TABLE reminders ADD COLUMN window_end TEXT;
ALTER TABLE reminders ADD COLUMN until TEXT;
""",
        ),
        Migration(
            "planner_looks_done_001",
            # A later email showed it done. Why, kept until the person closes it or keeps it.
            """
ALTER TABLE tasks ADD COLUMN looks_done TEXT;
ALTER TABLE reminders ADD COLUMN looks_done TEXT;
""",
        ),
    ],
)
REPEATS = {"day": timedelta(days=1), "week": timedelta(weeks=1)}
# How far back reminders that went off are still listed, as done.
DONE_SHOWN_DAYS = 30
KNOWN_REPEATS: tuple[str, ...] = get_args(Repeat)
# What models and people often write instead.
REPEAT_WORDS = {
    "": "none", "never": "none", "once": "none", "no": "none",
    "daily": "day", "every day": "day", "weekly": "week", "every week": "week",
    "monthly": "month", "every month": "month",
    "yearly": "year", "annually": "year", "annual": "year", "every year": "year",
}  # fmt: skip


INTERVAL = re.compile(r"^(?:every\s+)?(\d+\s*)?(minutes?|mins?|hours?|hrs?)$")
# A reminder more often than this is noise, and one a day or rarer is a daily repeat.
FEWEST_MINUTES = 5
MOST_MINUTES = 1440
DAY_WORDS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}  # fmt: skip
DAY_GROUPS = {"weekdays": (0, 1, 2, 3, 4), "weekends": (5, 6), "every day": tuple(range(7))}
DAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class Rule:
    """What narrows a repeat: how far apart, which days, which hours, until when."""

    every_minutes: int | None = None
    days: tuple[int, ...] | None = None
    window_start: str | None = None
    window_end: str | None = None
    until: str | None = None


def interval_of(value: str | None) -> int | None:
    """Minutes apart, from words like "hourly", "every hour" or "every 30 minutes"."""
    word = (value or "").strip().lower()
    if word == "hourly":
        return 60
    match = INTERVAL.match(word)
    if not match:
        return None
    count = int(match.group(1)) if match.group(1) else 1
    return count * (60 if match.group(2).startswith("h") else 1)


def repeat_of(value: str | None) -> Repeat:
    """How often it repeats, from the words used, or a plain error naming the choices."""
    word = (value or "none").strip().lower()
    if interval_of(word) is not None:
        return "interval"
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


def _clock(value: str, what: str) -> str:
    text = value.strip()
    if len(text) == 4 and text[1] == ":":
        text = f"0{text}"
    if not CLOCK.match(text):
        raise CommandError(
            "reminder.window", f"{value!r} isn't a time for {what}. Use HH:MM, like 09:30.", 422
        )
    return text


def days_of(values: list[str | int] | None) -> tuple[int, ...] | None:
    """Days by name or number (Monday is 0), or "weekdays" and "weekends"."""
    if not values:
        return None
    found: set[int] = set()
    for value in values:
        if isinstance(value, int) and 0 <= value <= 6:
            found.add(value)
            continue
        word = str(value).strip().lower()
        if word.isdigit() and 0 <= int(word) <= 6:
            # As kept in the database: Monday is 0.
            found.add(int(word))
        elif word in DAY_GROUPS:
            found.update(DAY_GROUPS[word])
        elif word in DAY_WORDS:
            found.add(DAY_WORDS[word])
        else:
            raise CommandError(
                "reminder.days",
                f"{value!r} isn't a day. Use day names like monday, or weekdays or weekends.",
                422,
            )
    return None if len(found) == 7 else tuple(sorted(found))


def rule_of(
    repeat: str | None,
    every_minutes: int | None = None,
    days: list[str | int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    until: str | None = None,
) -> tuple[Repeat, Rule]:
    """The repeat and its rule, checked, with an error that says how to fix it."""
    kind = repeat_of(repeat)
    minutes = every_minutes or (interval_of(repeat) if kind == "interval" else None)
    if minutes is not None and kind == "none":
        kind = "interval"
    if kind == "interval":
        if minutes is None or not FEWEST_MINUTES <= minutes <= MOST_MINUTES:
            raise CommandError(
                "reminder.every",
                f"A reminder can repeat every {FEWEST_MINUTES} to {MOST_MINUTES} minutes. Give"
                " every_minutes, such as 60 for hourly, or use day for once a day.",
                422,
            )
    else:
        minutes = None
    if (window_start is None) != (window_end is None):
        raise CommandError(
            "reminder.window", "Give both ends of the hours it goes off, like 10:00 and 20:00.", 422
        )
    start = _clock(window_start, "the first one") if window_start else None
    end = _clock(window_end, "the last one") if window_end else None
    if start and end and start >= end:
        raise CommandError(
            "reminder.window",
            f"The hours run from {start} to {end}: the start must come first.",
            422,
        )
    last = due_of(until) if until else None
    if (days or start or last) and kind == "none":
        raise CommandError(
            "reminder.repeat",
            "Days, hours and an end date are for a repeating reminder. Set repeat too.",
            422,
        )
    return kind, Rule(minutes, days_of(days), start, end, last)


def rule_from_row(row: Any) -> Rule:
    keys = row.keys() if hasattr(row, "keys") else ()
    days = row["days"] if "days" in keys else None
    return Rule(
        every_minutes=row["every_minutes"] if "every_minutes" in keys else None,
        days=tuple(int(d) for d in days.split(",")) if days else None,
        window_start=row["window_start"] if "window_start" in keys else None,
        window_end=row["window_end"] if "window_end" in keys else None,
        until=row["until"] if "until" in keys else None,
    )


def rule_columns(rule: Rule) -> tuple[int | None, str | None, str | None, str | None, str | None]:
    days = ",".join(str(d) for d in rule.days) if rule.days else None
    return rule.every_minutes, days, rule.window_start, rule.window_end, rule.until


def fit(when: datetime, rule: Rule) -> datetime | None:
    """The first time at or after `when` the rule allows, or None once it's past its end date."""
    at = when
    # Enough for a year of skipped days; a rule that allows nothing ends the repeat.
    for _ in range(800):
        if rule.until and at.date().isoformat() > rule.until:
            return None
        clock = at.strftime("%H:%M")
        if rule.window_start and rule.window_end:
            start_h, start_m = (int(part) for part in rule.window_start.split(":"))
            if clock < rule.window_start:
                at = at.replace(hour=start_h, minute=start_m)
                continue
            if clock > rule.window_end:
                at = (at + timedelta(days=1)).replace(hour=start_h, minute=start_m)
                continue
        if rule.days is not None and at.weekday() not in rule.days:
            at = at + timedelta(days=1)
            if rule.window_start:
                start_h, start_m = (int(part) for part in rule.window_start.split(":"))
                at = at.replace(hour=start_h, minute=start_m)
            continue
        return at
    return None


def describe_repeat(repeat: str, rule: Rule) -> str:
    """The rule in words, such as "every 60 minutes, 10:00 to 20:00, Mon to Fri"."""
    if repeat == "none":
        return "once"
    parts = [f"every {rule.every_minutes} minutes" if repeat == "interval" else f"every {repeat}"]
    if rule.window_start and rule.window_end:
        parts.append(f"{rule.window_start} to {rule.window_end}")
    if rule.days:
        days = list(rule.days)
        consecutive = days == list(range(days[0], days[-1] + 1)) and len(days) > 2
        parts.append(
            f"{DAY_SHORT[days[0]]} to {DAY_SHORT[days[-1]]}"
            if consecutive
            else ", ".join(DAY_SHORT[d] for d in days)
        )
    if rule.until:
        parts.append(f"until {rule.until}")
    return ", ".join(parts)


def _day_for(repeat: str, due_at: str) -> int | None:
    """The day of the month a monthly or yearly reminder keeps, so the 31st stays the 31st
    after a shorter month."""
    return int(due_at[8:10]) if repeat in {"month", "year"} and len(due_at) >= 10 else None


def next_due(
    due: datetime, repeat: str, day: int | None, rule: Rule | None = None
) -> datetime | None:
    """The next time it goes off, or None when its rule has ended."""
    rule = rule or Rule()
    if repeat == "interval":
        return fit(due + timedelta(minutes=rule.every_minutes or MOST_MINUTES), rule)
    following = _next_plain(due, repeat, day)
    return fit(following, rule) if rule != Rule() else following


def _next_plain(due: datetime, repeat: str, day: int | None) -> datetime:
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
        looks_done=data["looks_done"],
        created=data["created"],
        updated=data["updated"] or data["created"],
        every_minutes=data.get("every_minutes"),
        days=[int(d) for d in data["days"].split(",")] if data.get("days") else None,
        window_start=data.get("window_start"),
        window_end=data.get("window_end"),
        until=data.get("until"),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


TASK_FIELDS = {"title", "notes", "status", "due", "proposed", "looks_done"}
RULE_FIELDS = {"every_minutes", "days", "window_start", "window_end", "until"}
REMINDER_FIELDS = {
    "title", "due_at", "repeat", "repeat_day", "proposed", "fired", "looks_done",
    "every_minutes", "days", "window_start", "window_end", "until",
}  # fmt: skip


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
        if table == "reminders" and before and (RULE_FIELDS | {"due_at", "repeat"}) & named.keys():
            # A new rule or time moves it into the rule, as a new reminder is.
            merged = {**dict(before), **named}
            named["due_at"] = _first_time(merged["due_at"], merged["repeat"], rule_from_row(merged))
        columns = ", ".join(f"{name} = ?" for name in named)
        changed = work.tx.execute(
            f"UPDATE {table} SET {columns} WHERE id = ?",  # noqa: S608
            (*named.values(), identifier),
        ).rowcount
        if not changed:
            raise CommandError(
                f"{kind}.not_found", f"{kind.capitalize()} {identifier} is gone.", 404
            )
        if table == "tasks" and before:
            _children_follow(work, identifier, dict(before), named)
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


def _children_follow(work: Any, task: int, before: dict[str, Any], after: dict[str, Any]) -> None:
    """A task's reminders go with it: finished with it, back with it, and moved by as many days
    as its due date moved. Nobody is asked, since they were only ever about this task."""
    status = after.get("status")
    if status == "done" and before["status"] != "done":
        moved = work.tx.execute(
            "UPDATE reminders SET fired = 1, updated = ? WHERE task = ? AND fired = 0",
            (_now(), task),
        ).rowcount
    elif status not in {None, "done"} and before["status"] == "done":
        # Only the ones still ahead: one that's passed would only ring at once.
        moved = work.tx.execute(
            "UPDATE reminders SET fired = 0, updated = ? WHERE task = ? AND fired = 1 AND due_at > ?",
            (_now(), task, datetime.now().strftime("%Y-%m-%dT%H:%M")),
        ).rowcount
    elif after.get("due") and before["due"] and after["due"] != before["due"]:
        try:
            days = (
                date.fromisoformat(after["due"][:10]) - date.fromisoformat(before["due"][:10])
            ).days
        except ValueError:
            return
        moved = 0
        for row in work.tx.execute(
            "SELECT id, due_at FROM reminders WHERE task = ? AND fired = 0", (task,)
        ).fetchall():
            shifted = (datetime.fromisoformat(row["due_at"]) + timedelta(days=days)).strftime(
                "%Y-%m-%dT%H:%M"
            )
            moved += work.tx.execute(
                "UPDATE reminders SET due_at = ?, updated = ? WHERE id = ?",
                (shifted, _now(), row["id"]),
            ).rowcount
    else:
        return
    if moved:
        work.emit("reminders.changed", {}, source="planner")


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
    matter: int | None = None,
    source_message: int | None = None,
) -> int:
    due = due_of(due)
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO tasks (title, notes, status, due, thread, source, proposed, created, updated,"
            " matter, source_message) VALUES (?, ?, 'todo', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                notes,
                due,
                thread,
                source,
                int(proposed),
                _now(),
                _now(),
                matter,
                source_message,
            ),
        )
        # Which conversation it's for, so whatever follows that conversation can follow this.
        work.emit(
            "tasks.changed",
            {"id": cursor.lastrowid, "thread": thread, "proposed": proposed},
            source="planner",
            trace_id=ctx.trace_id,
        )
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
    matter: int | None = None,
    rule: Rule | None = None,
) -> int:
    rule = rule or Rule()
    repeat = "interval" if rule.every_minutes else repeat_of(repeat)
    when = _first_time(when_of(when), repeat, rule)
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO reminders (title, due_at, repeat, repeat_day, thread, task, source,"
            " proposed, created, updated, matter, every_minutes, days, window_start, window_end,"
            " until) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                None if task else matter,
                *rule_columns(rule),
            ),
        )
        work.emit("reminders.changed", {}, source="planner", trace_id=ctx.trace_id)
    return int(cursor.lastrowid or 0)


def _first_time(when: str, repeat: str, rule: Rule) -> str:
    """A repeating reminder's first time moved into its rule, as "every hour from 10:00" asked
    at 21:00 starts tomorrow at 10:00. One whose rule never allows a time is refused."""
    if repeat == "none" or rule == Rule():
        return when
    first = fit(datetime.fromisoformat(when), rule)
    if first is None:
        raise CommandError(
            "reminder.until", "With that end date it would never go off. Pick a later one.", 422
        )
    return first.strftime("%Y-%m-%dT%H:%M")


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
        before = work.tx.execute("SELECT * FROM tasks WHERE id = ?", (command.id,)).fetchone()
        work.tx.execute(
            # Saved by the person, so a "looks done" mark has had its answer either way.
            "UPDATE tasks SET title = ?, notes = ?, status = ?, due = ?, thread = ?, proposed = ?,"
            " updated = ?, completed = CASE WHEN ? = 'done' THEN COALESCE(completed, ?) END,"
            " looks_done = NULL WHERE id = ?",
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
        if before:
            _children_follow(
                work, command.id, dict(before), {"status": command.status, "due": command.due}
            )
        # What changed, like a tool's change says, so ticking the last task of a conversation
        # can finish the conversation too.
        changes = {"status": command.status, "proposed": command.proposed}
        work.emit(
            "tasks.changed",
            {
                "id": command.id,
                "by": ctx.actor,
                "changes": changes,
                "old": {key: before[key] for key in changes} if before else {},
                "thread": before["thread"] if before else None,
            },
            source="planner",
            trace_id=ctx.trace_id,
        )
    return PlannerDone()


@planner_module.command("tasks.remove")
def remove_task(command: TaskAction, ctx: Context) -> PlannerDone:
    with ctx.bus.unit_of_work() as work:
        gone = work.tx.execute(
            "SELECT title, thread, proposed FROM tasks WHERE id = ?", (command.id,)
        ).fetchone()
        work.tx.execute("DELETE FROM tasks WHERE id = ?", (command.id,))
        # What went, so a suggestion turned down shows as declined where it was made.
        removed = dict(gone) if gone else None
        work.emit(
            "tasks.changed",
            {"removed": removed, "by": ctx.actor},
            source="planner",
            trace_id=ctx.trace_id,
        )
    return PlannerDone()


@planner_module.query("reminders.list")
def list_reminders(query: ListReminders, ctx: Context) -> ReminderList:
    since = (datetime.now(UTC) - timedelta(days=DONE_SHOWN_DAYS)).isoformat()[:16]
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM reminders WHERE fired = 0 OR (? AND proposed = 0 AND due_at >= ?)"
        " ORDER BY fired, proposed DESC, due_at",
        (int(query.include_done), since),
    )
    return ReminderList(reminders=[_reminder(ctx.bus.db, row) for row in rows])


@planner_module.command("reminders.save")
def save_reminder(command: SaveReminder, ctx: Context) -> PlannerDone:
    repeat, rule = rule_of(
        command.repeat,
        command.every_minutes,
        list(command.days) if command.days else None,
        command.window_start,
        command.window_end,
        command.until,
    )
    if command.id is None:
        add_reminder(
            ctx,
            command.title,
            command.when,
            repeat,
            command.thread,
            command.task,
            "user",
            False,
            rule=rule,
        )
        return PlannerDone()
    # Seconds or an offset would make it come due a minute late, so it's stored like a new one.
    when = _first_time(when_of(command.when), repeat, rule)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE reminders SET title = ?, due_at = ?, repeat = ?, repeat_day = ?, thread = ?,"
            " task = ?, proposed = ?, fired = 0, updated = ?, looks_done = NULL,"
            " every_minutes = ?, days = ?, window_start = ?, window_end = ?, until = ? WHERE id = ?",
            (
                command.title,
                when,
                repeat,
                _day_for(repeat, when),
                command.thread,
                command.task,
                int(command.proposed),
                _now(),
                *rule_columns(rule),
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
            following: datetime | None = None
            if row["repeat"] in REPEATS or row["repeat"] in {"month", "year", "interval"}:
                # The next one still in the future, however long the computer was off. Those
                # missed while it slept aren't repeated: this one notification stands for them.
                rule = rule_from_row(row)
                following = datetime.fromisoformat(row["due_at"])
                while following is not None and following.replace(tzinfo=None) <= now.replace(
                    tzinfo=None
                ):
                    following = next_due(following, row["repeat"], row["repeat_day"], rule)
            if following is not None:
                work.tx.execute(
                    "UPDATE reminders SET due_at = ? WHERE id = ?",
                    (following.strftime("%Y-%m-%dT%H:%M"), row["id"]),
                )
            else:
                # Done for good: it didn't repeat, or its rule has passed its end date.
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
