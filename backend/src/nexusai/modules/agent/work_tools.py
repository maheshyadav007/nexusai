"""Tools for the person's own data, each able to create, change and remove, and to do many at once.

Every tool here goes through the same door as file and command tools, so its permission is set in
Settings. A session that has read mail always asks before changing anything.
"""

import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated, Any, Literal, cast, get_args

from langchain_core.tools import InjectedToolCallId
from pydantic import BaseModel, Field, ValidationError, model_validator

from nexusai.contracts.agent import RemoveSchedule, RunSchedule, Schedule
from nexusai.contracts.documents import ListDocuments, RemoveDocument, UpdateDocument
from nexusai.contracts.mail import (
    CategoryName,
    CategorySaved,
    Draft,
    DraftList,
    ListDrafts,
    ListThreads,
    MailRule,
    MergeCategories,
    MoveThread,
    Recipient,
    ReorderCategories,
    RuleActions,
    RuleCondition,
    SaveCategory,
    SearchMail,
    SearchResults,
    SendDraft,
    SetThreadCategory,
    SetThreadFlag,
    SetThreadRead,
    SetThreadStatus,
    ThreadList,
    UpdateCategory,
)
from nexusai.contracts.mail import RemoveDraft as RemoveDraftCommand
from nexusai.contracts.panels import GetPanelBoard, Panel, PanelBoard, PanelFilters
from nexusai.kernel.database import connect_raw
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import cards, citations, memory, scheduler, signals
from nexusai.modules.documents import module as documents_module
from nexusai.modules.mail import module as mail
from nexusai.modules.mail import rules as mail_rules
from nexusai.modules.mail import sorting as mail_sorting
from nexusai.modules.panels import module as panels
from nexusai.modules.planner import module as planner
from nexusai.modules.semantic import module as semantic

# What read_database can see. Masking tokens, approvals and the event log stay out of reach.
WEAK_MATCHES_SHOWN = 5
READABLE_TABLES = frozenset(
    {
        "messages",
        "threads",
        "message_parts",
        "mail_categories",
        "tasks",
        "reminders",
        "schedules",
        "work_board",
        "agent_sessions",
        "notifications",
    }
)
MAX_ROWS = 200
MAX_CELL = 2000
QUERY_SECONDS = 5.0
PROGRESS_STEPS = 10_000
SHOWN_IN_SUMMARY = 3
SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
MOVABLE = {"inbox", "archive"}

Guard = Callable[..., str]
Spec = tuple[Callable[..., str], type[BaseModel], str]


# Any web address in a message, listed on the approval so a link built from mail is seen.
LINK = re.compile(r"https?://[^\s<>\")\]]+")


class _Call(BaseModel):
    tool_call_id: Annotated[str, InjectedToolCallId]


# Tasks and reminders


class _TaskItem(BaseModel):
    title: str = Field(description="What needs doing.")
    due: str | None = Field(default=None, description="YYYY-MM-DD, if it has a date.")
    notes: str = Field(default="", description="Any detail worth keeping.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")


class _NewTasks(_Call):
    tasks: list[_TaskItem] = Field(description="One or many.")


class _TaskChange(BaseModel):
    task_id: int = Field(description="From list_tasks.")
    title: str | None = None
    due: str | None = Field(default=None, description="YYYY-MM-DD.")
    clear_due: bool = Field(default=False, description="Remove the due date.")
    notes: str | None = None
    status: str | None = Field(default=None, description="todo, in_progress or done.")
    accept: bool = Field(default=False, description="Accept a task that was only suggested.")


class _ChangeTasks(_Call):
    changes: list[_TaskChange] = Field(description="One or many.")


class _TaskIds(_Call):
    task_ids: list[int] = Field(description="From list_tasks. One or many.")


class _ListTasks(_Call):
    include_done: bool = Field(default=False, description="Include finished tasks too.")


class _ReminderItem(BaseModel):
    title: str = Field(description="What to remind the person about.")
    when: str = Field(description="YYYY-MM-DDTHH:MM, in the person's local time.")
    repeat: str = Field(default="none", description="none, day, week, month or year.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")


class _NewReminders(_Call):
    reminders: list[_ReminderItem] = Field(description="One or many.")


class _ReminderChange(BaseModel):
    reminder_id: int = Field(description="From list_reminders.")
    title: str | None = None
    when: str | None = Field(default=None, description="YYYY-MM-DDTHH:MM.")
    repeat: str | None = Field(default=None, description="none, day, week, month or year.")
    snooze_minutes: int | None = Field(default=None, description="Push it back this far from now.")
    accept: bool = Field(default=False, description="Accept a reminder that was only suggested.")


class _ChangeReminders(_Call):
    changes: list[_ReminderChange] = Field(description="One or many.")


class _ReminderIds(_Call):
    reminder_ids: list[int] = Field(description="From list_reminders. One or many.")


class _Nothing(_Call):
    pass


# Mail


class _ListMail(_Call):
    folder: str = Field(
        default="priority", description="priority, important, starred, all, sent, archive or trash."
    )
    category: str | None = Field(default=None, description="Only this category.")
    limit: int = Field(default=30, description="How many conversations, up to 100.")


class _ChangeMail(_Call):
    thread_ids: list[int] = Field(description="The conversations. One or many, all in one call.")
    category: str | None = Field(default=None, description="File under this category.")
    clear_category: bool = Field(default=False, description="Take them out of their category.")
    status: str | None = Field(
        default=None, description="none, waiting_on_you, waiting_on_others, resolved or fyi."
    )
    flagged: bool | None = None
    read: bool | None = None
    move_to: str | None = Field(default=None, description="archive or inbox.")


class _ThreadIds(_Call):
    thread_ids: list[int] = Field(description="The conversations. One or many.")


class _CategoryItem(BaseModel):
    name: str = Field(description="A short name, like Invoices.")
    in_priority: bool = Field(default=True, description="Show this in the Priority inbox.")
    mode: Literal["exact", "smart"] | None = None
    description: str = Field(default="", max_length=500)
    sender: str | None = Field(
        default=None, description="File mail from this exact email address here automatically."
    )
    subject: str | None = Field(
        default=None,
        description="File mail whose subject starts with this literal prefix here automatically.",
    )


class _NewCategories(_Call):
    categories: list[_CategoryItem] = Field(description="One or many.")


class _ChangeCategory(_Call):
    name: str = Field(description="The category as it's called now.")
    new_name: str | None = Field(default=None, description="Rename it. Its mail goes with it.")
    in_priority: bool | None = Field(default=None, description="Show it in the Priority inbox.")
    sender: str | None = Field(default=None, description="File mail from this sender here.")
    subject: str | None = Field(default=None, description="File mail with this subject here.")
    clear_rule: bool = Field(default=False, description="Stop filing mail here automatically.")
    mode: Literal["exact", "smart"] | None = None
    description: str | None = Field(default=None, max_length=500)


class _CategoryNames(_Call):
    names: list[str] = Field(description="One or many. Their mail stays, without the label.")


class _MergeCategories(_Call):
    names: list[str] = Field(description="The categories to fold in.")
    into: str = Field(description="The category they become. It's created if it's new.")


class _OrderCategories(_Call):
    names: list[str] = Field(description="Category names, in the order they should appear.")


class _Rule(_Call):
    name: str = Field(description="What to call the rule. Saving an existing name replaces it.")
    sender: str | None = Field(default=None, description="Matches this sender or domain.")
    subject: str | None = Field(default=None, description="Matches this in the subject.")
    body: str | None = Field(default=None, description="Matches this in the text.")
    category: str | None = Field(default=None, description="File matching mail here.")
    mark_read: bool = False
    skip_agent: bool = Field(default=False, description="Don't use the model on matching mail.")
    notify: bool = False
    enabled: bool = True


class _MoveSender(_Call):
    sender: str = Field(description="The sender's email address.")
    side: Literal["reads", "ignores"] = Field(
        description="reads: the AI reads its mail. ignores: it's kept from the AI."
    )
    folder: str | None = Field(
        default=None, description="Where to file it. Left out, it keeps its folder, or Automated."
    )


class _RuleNames(_Call):
    names: list[str] = Field(description="From list_rules. One or many.")


class _SendMail(_Call):
    to: list[str] = Field(description="Email addresses to send to.")
    subject: str = Field(description="The subject line.")
    body: str = Field(description="The message, as plain text.")
    cc: list[str] = Field(default_factory=list, description="Addresses to copy.")
    thread_id: int | None = Field(default=None, description="The conversation this replies in.")
    draft_id: int | None = Field(default=None, description="The draft this sends, if any.")


class _SaveDraft(_Call):
    draft_id: int | None = Field(
        default=None, description="Change this draft instead of a new one."
    )
    to: list[str] = Field(default_factory=list, description="Email addresses to send to.")
    cc: list[str] = Field(default_factory=list, description="Addresses to copy.")
    subject: str = Field(default="", description="The subject line.")
    body: str = Field(default="", description="The message, as plain text.")
    thread_id: int | None = Field(default=None, description="The conversation this replies in.")


class _DraftIds(_Call):
    draft_ids: list[int] = Field(description="From list_drafts. One or many.")


# Everything else


class _Query(_Call):
    sql: str = Field(
        description=(
            "One read-only SELECT. Tables: messages, threads, message_parts, mail_categories,"
            " tasks, reminders, schedules, work_board, agent_sessions, notifications."
        )
    )


class _MeaningSearch(_Call):
    query: str = Field(description="What you're looking for, in plain words.")
    scope: str = Field(default="all", description="all, mail or documents.")
    limit: int = Field(default=15, description="How many, up to 50.")


Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS: tuple[Weekday, ...] = cast("tuple[Weekday, ...]", Weekday.__args__)  # type: ignore[attr-defined]
Every = Literal["once", "hour", "day", "weekdays", "week", "month", "year"]
CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"
DAY = r"^\d{4}-\d{2}-\d{2}$"
EVERY_HELP = (
    "once (needs date), hour, day, weekdays (Monday to Friday), week (needs weekday),"
    " month (needs month_day) or year (needs month and month_day)."
)


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


class _When(_Call):
    """When a schedule runs. Checked before anything is shown to the person, so a wrong call is
    fixed by the model rather than approved and then failing."""

    every: Every | None = Field(default=None, description=EVERY_HELP)
    time: str | None = Field(
        default=None, pattern=CLOCK, description="24-hour HH:MM local time, like 17:00 for 5 pm."
    )
    weekday: Weekday | None = Field(default=None, description="For every=week, like Friday.")
    month_day: int | None = Field(
        default=None, ge=1, le=31, description="For month or year: 1 to 31. 31 means the last day."
    )
    month: int | None = Field(default=None, ge=1, le=12, description="For year: 1 to 12.")
    date: str | None = Field(default=None, pattern=DAY, description="For once: YYYY-MM-DD.")
    until: str | None = Field(
        default=None,
        pattern=DAY,
        description="Last day it runs, YYYY-MM-DD. Leave out to keep going.",
    )

    @model_validator(mode="after")
    def _complete(self) -> "_When":
        today = _today()
        if self.date and self.date < today:
            raise ValueError(f"date {self.date} is in the past; today is {today}")
        if self.until and self.until < today:
            raise ValueError(f"until {self.until} is in the past; today is {today}")
        return self


class _NewSchedule(_When):
    name: str = Field(min_length=1, max_length=200, description="Short, like Friday team status.")
    instructions: str = Field(
        min_length=1, description="What to do on each run, written as you'd ask the agent."
    )
    every: Every = Field(default="day", description=EVERY_HELP)
    time: str = Field(
        default="08:00", pattern=CLOCK, description="24-hour HH:MM local time, like 17:00 for 5 pm."
    )
    token_limit: int = Field(default=0, ge=0, description="Most tokens per run. 0 means no limit.")

    @model_validator(mode="after")
    def _needs(self) -> "_NewSchedule":
        needs = {
            "once": ("date", "date='2026-12-01'"),
            "week": ("weekday", "weekday='Friday'"),
            "month": ("month_day", "month_day=1"),
            "year": ("month", "month=4, month_day=1"),
        }.get(self.every)
        if needs and getattr(self, needs[0]) is None:
            raise ValueError(f"every='{self.every}' needs {needs[0]}, such as {needs[1]}")
        if self.every == "year" and self.month_day is None:
            raise ValueError("every='year' needs month_day as well, such as month=4, month_day=1")
        return self


class _ChangeSchedule(_When):
    schedule_id: int = Field(description="From list_schedules.")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, min_length=1)
    enabled: bool | None = Field(default=None, description="false pauses it, true resumes it.")
    token_limit: int | None = Field(default=None, ge=0)


class _ScheduleId(_Call):
    schedule_id: int = Field(description="From list_schedules.")


class _ScheduleIds(_Call):
    schedule_ids: list[int] = Field(min_length=1, description="From list_schedules. One or many.")


class _SearchMemory(_Call):
    query: str = Field(default="", description="Words to look for. Empty lists everything.")


class _ChangeMemory(_Call):
    path: str = Field(description="From list_memory.")
    content: str = Field(description="What it should say now.")


class _MemoryPaths(_Call):
    paths: list[str] = Field(description="From list_memory. One or many.")


class _ListDocuments(_Call):
    query: str = Field(default="", description="Words to look for. Empty lists recent ones.")


class _ChangeDocuments(_Call):
    keys: list[str] = Field(description="From list_documents. One or many.")
    folder: str | None = Field(default=None, description="Move them to this folder.")
    tags: list[str] | None = Field(default=None, description="Replace their tags with these.")


class _DocumentKeys(_Call):
    keys: list[str] = Field(description="From list_documents. Only uploaded ones can be removed.")


class _SavePanel(_Call):
    panel_id: str | None = Field(
        default=None, description="Change this panel instead of a new one."
    )
    title: str = Field(description="What the panel shows.")
    source: str = Field(default="threads", description="threads, documents, tasks or reminders.")
    sender: str | None = None
    subject: str | None = None
    category: str | None = None
    query: str | None = None
    unread_only: bool = False


class _PanelIds(_Call):
    panel_ids: list[str] = Field(description="From list_panels. One or many.")


def run_read_only(ctx: Context, sql: str) -> str:
    """Runs on its own connection that can't write, and can read only the listed tables."""
    if not SELECT_ONLY.match(sql) or ";" in sql.rstrip().rstrip(";"):
        return "Not run: only one SELECT statement is allowed."
    connection = connect_raw(ctx.config.database_path, ctx.config.database_key)
    began = time.monotonic()

    def authorize(action: int, first: str | None, second: str | None, *_: Any) -> int:
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if first in READABLE_TABLES else sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    try:
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(authorize)
        connection.set_progress_handler(
            lambda: int(time.monotonic() - began > QUERY_SECONDS), PROGRESS_STEPS
        )
        cursor = connection.execute(sql)
        names = [column[0] for column in cursor.description or []]
        rows = cursor.fetchmany(MAX_ROWS)
    except Exception as error:
        return f"That query didn't run: {error}"
    finally:
        connection.close()
    lines = [" | ".join(names)]
    lines += [" | ".join(str(value)[:MAX_CELL] for value in row) for row in rows]
    return "\n".join(lines)


def _brief(items: Iterable[str]) -> str:
    """A few by name, so a summary stays one line however many there are."""
    names = list(items)
    if len(names) <= SHOWN_IN_SUMMARY:
        return ", ".join(names)
    return f"{', '.join(names[:SHOWN_IN_SUMMARY])} and {len(names) - SHOWN_IN_SUMMARY} more"


def _lines(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def specs(
    ctx: Context, guard: Guard, wrap_untrusted: Callable[[str], str], session: str
) -> list[Spec]:
    ctx = replace(ctx, actor="agent")
    db = ctx.bus.db
    documents = ctx.config.home / "documents"

    def named(thread_id: int) -> str:
        """What the person would recognize a conversation by, since its number means nothing."""
        rows = db.fetch_all("SELECT subject FROM threads WHERE id = ?", (thread_id,))
        subject = str(rows[0]["subject"]) if rows else ""
        return f"“{subject}”" if subject else f"conversation {thread_id}"

    def _refused(checks: list[Callable[[], object]]) -> str | None:
        """Checked before anything is saved or asked, so a value the app can't use is never
        saved as if it worked. The agent hears what to use instead and can fix it."""
        for check in checks:
            try:
                check()
            except CommandError as error:
                return f"Not done: {error.message}"
        return None

    # Tasks

    def create_tasks(tasks: list[_TaskItem], tool_call_id: str) -> str:
        refused = _refused([partial(planner.due_of, t.due) for t in tasks])
        if refused:
            return refused

        def work() -> str:
            made = [
                f"{planner.add_task(ctx, t.title, t.due, t.thread_id, 'agent', False, t.notes)}: {t.title}"
                for t in tasks
            ]
            return "Created tasks:\n" + "\n".join(made)

        titles = [task.title for task in tasks]
        summary = f"Add {_brief(titles)}"
        return guard(tool_call_id, "create_tasks", "data", summary, _lines(titles), work)

    def update_tasks(changes: list[_TaskChange], tool_call_id: str) -> str:
        refused = _refused(
            [partial(planner.status_of, c.status) for c in changes if c.status is not None]
            + [partial(planner.due_of, c.due) for c in changes if c.due is not None]
        )
        if refused:
            return refused

        def work() -> str:
            for change in changes:
                values: dict[str, Any] = {}
                if change.title is not None:
                    values["title"] = change.title
                if change.due is not None or change.clear_due:
                    values["due"] = None if change.clear_due else change.due
                if change.notes is not None:
                    values["notes"] = change.notes
                if change.status is not None:
                    values["status"] = change.status
                if change.accept:
                    values["proposed"] = 0
                planner.change_task(ctx, change.task_id, values)
            return f"Updated {len(changes)} tasks."

        ids = [str(change.task_id) for change in changes]
        summary = f"Change tasks {_brief(ids)}"
        return guard(tool_call_id, "update_tasks", "data", summary, "", work)

    def delete_tasks(task_ids: list[int], tool_call_id: str) -> str:
        def work() -> str:
            planner.remove_tasks(ctx, task_ids)
            return f"Removed {len(task_ids)} tasks."

        titles = [str(r["title"]) for r in _rows("tasks", task_ids)]
        summary = f"Remove {_brief(titles) or 'tasks'}"
        return guard(tool_call_id, "delete_tasks", "data", summary, _lines(titles), work)

    def list_tasks(tool_call_id: str, include_done: bool = False) -> str:
        def work() -> str:
            where = "" if include_done else "WHERE status != 'done'"
            rows = db.fetch_all(f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT 200")  # noqa: S608
            return wrap_untrusted(
                "\n".join(
                    f"{r['id']}: {r['title']} ({r['status']}, due {r['due']},"
                    f" added {r['created'][:10]}, changed {(r['updated'] or r['created'])[:10]})"
                    f"{' from ' + citations.mark(citations.MAIL, r['thread']) if r['thread'] else ''}"
                    for r in rows
                )
                or "No tasks."
            )

        return guard(tool_call_id, "list_tasks", "read", "Read your tasks", "", work, documents)

    def _rows(table: str, ids: list[int]) -> list[Any]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return db.fetch_all(f"SELECT * FROM {table} WHERE id IN ({marks})", ids)  # noqa: S608

    # Reminders

    def create_reminders(reminders: list[_ReminderItem], tool_call_id: str) -> str:
        refused = _refused(
            [partial(planner.repeat_of, item.repeat) for item in reminders]
            + [partial(planner.when_of, item.when) for item in reminders]
        )
        if refused:
            return refused

        def work() -> str:
            for item in reminders:
                planner.add_reminder(
                    ctx,
                    item.title,
                    planner.when_of(item.when),
                    planner.repeat_of(item.repeat),
                    item.thread_id,
                    None,
                    "agent",
                    False,
                )
            return "Reminders set:\n" + "\n".join(
                f"{r.when[:16]}: {r.title}"
                + (
                    f", every {planner.repeat_of(r.repeat)}"
                    if planner.repeat_of(r.repeat) != "none"
                    else ""
                )
                for r in reminders
            )

        titles = [item.title for item in reminders]
        summary = f"Remind you: {_brief(titles)}"
        detail = _lines(f"{item.when[:16]}: {item.title}" for item in reminders)
        return guard(tool_call_id, "create_reminders", "data", summary, detail, work)

    def update_reminders(changes: list[_ReminderChange], tool_call_id: str) -> str:
        refused = _refused(
            [partial(planner.repeat_of, c.repeat) for c in changes if c.repeat is not None]
            + [partial(planner.when_of, c.when) for c in changes if c.when is not None]
        )
        if refused:
            return refused

        def work() -> str:
            for change in changes:
                values: dict[str, Any] = {}
                if change.title is not None:
                    values["title"] = change.title
                if change.when is not None:
                    values["due_at"] = change.when[:16]
                    values["fired"] = 0
                if change.repeat is not None:
                    values["repeat"] = change.repeat
                if change.snooze_minutes is not None:
                    later = datetime.now(UTC).astimezone() + timedelta(
                        minutes=change.snooze_minutes
                    )
                    values["due_at"] = later.strftime("%Y-%m-%dT%H:%M")
                    values["fired"] = 0
                if change.accept:
                    values["proposed"] = 0
                planner.change_reminder(ctx, change.reminder_id, values)
            return f"Updated {len(changes)} reminders."

        ids = [str(change.reminder_id) for change in changes]
        summary = f"Change reminders {_brief(ids)}"
        return guard(tool_call_id, "update_reminders", "data", summary, "", work)

    def delete_reminders(reminder_ids: list[int], tool_call_id: str) -> str:
        def work() -> str:
            planner.remove_reminders(ctx, reminder_ids)
            return f"Removed {len(reminder_ids)} reminders."

        titles = [str(r["title"]) for r in _rows("reminders", reminder_ids)]
        summary = f"Remove {_brief(titles) or 'reminders'}"
        return guard(tool_call_id, "delete_reminders", "data", summary, _lines(titles), work)

    def list_reminders(tool_call_id: str) -> str:
        def work() -> str:
            rows = db.fetch_all("SELECT * FROM reminders WHERE fired = 0 ORDER BY due_at LIMIT 200")
            return wrap_untrusted(
                "\n".join(
                    f"{r['id']}: {r['title']} at {r['due_at']}, repeats {r['repeat']}"
                    f"{' from ' + citations.mark(citations.MAIL, r['thread']) if r['thread'] else ''}"
                    for r in rows
                )
                or "No reminders."
            )

        return guard(
            tool_call_id, "list_reminders", "read", "Read your reminders", "", work, documents
        )

    # Mail

    def list_mail(
        tool_call_id: str, folder: str = "priority", category: str | None = None, limit: int = 30
    ) -> str:
        def work() -> str:
            query = ListThreads.model_validate(
                {"folder": folder, "category": category, "limit": max(1, min(limit, 100))}
            )
            found = cast(ThreadList, mail.list_threads(query, ctx)).threads
            return wrap_untrusted(
                "\n".join(
                    f"{citations.mark(citations.MAIL, t.id)} {t.subject} | {t.category or 'no category'}"
                    f" | {t.last_date}"
                    for t in found
                )
                or "Nothing here."
            )

        return guard(
            tool_call_id,
            "list_mail",
            "read",
            f"Read the {folder} folder",
            "",
            work,
            documents,
            marks_untrusted=True,
        )

    def update_mail(
        thread_ids: list[int],
        tool_call_id: str,
        category: str | None = None,
        clear_category: bool = False,
        status: str | None = None,
        flagged: bool | None = None,
        read: bool | None = None,
        move_to: str | None = None,
    ) -> str:
        if move_to is not None and move_to not in MOVABLE:
            return "Not done: move_to can be archive or inbox. Use trash_mail to delete."
        # Checked once up front, so a bad status can't stop a change halfway through the list.
        statuses = get_args(SetThreadStatus.model_fields["status"].annotation)
        if status is not None and status not in statuses:
            return f"Not done: a conversation's status can be one of: {', '.join(statuses)}."

        def work() -> str:
            for thread in thread_ids:
                if category is not None or clear_category:
                    command = SetThreadCategory(
                        id=thread, category=None if clear_category else category
                    )
                    mail.set_category(command, ctx)
                if status is not None:
                    mail.set_status(
                        SetThreadStatus.model_validate({"id": thread, "status": status}), ctx
                    )
                if flagged is not None:
                    mail.set_flag(SetThreadFlag(id=thread, flagged=flagged), ctx)
                if read is not None:
                    mail.set_read(SetThreadRead(id=thread, read=read), ctx)
                if move_to is not None:
                    mail.move_thread(MoveThread.model_validate({"id": thread, "to": move_to}), ctx)
            return f"Updated {len(thread_ids)} conversations."

        doing = [
            f"file under {category}" if category else "",
            "take out of their category" if clear_category else "",
            f"mark {status.replace('_', ' ')}" if status else "",
            ("flag" if flagged else "unflag") if flagged is not None else "",
            ("mark read" if read else "mark unread") if read is not None else "",
            f"move to {move_to}" if move_to else "",
        ]
        action = ", ".join(item for item in doing if item) or "change"
        names = [named(thread) for thread in thread_ids]
        summary = f"{action.capitalize()}: {_brief(names)}"
        return guard(tool_call_id, "update_mail", "data", summary, _lines(names), work)

    def trash_mail(thread_ids: list[int], tool_call_id: str) -> str:
        def work() -> str:
            for thread in thread_ids:
                mail.move_thread(MoveThread.model_validate({"id": thread, "to": "trash"}), ctx)
            return f"Moved {len(thread_ids)} conversations to Trash."

        names = [named(thread) for thread in thread_ids]
        summary = f"Move to Trash: {_brief(names)}"
        return guard(tool_call_id, "trash_mail", "data", summary, _lines(names), work)

    # Categories

    def list_categories(tool_call_id: str) -> str:
        def work() -> str:
            found = mail.category_rows(ctx)
            described = []
            for c in found:
                notes = [
                    f"{c.count} conversations",
                    f"made by {c.source}",
                    f"mode: {c.mode}",
                    f"description: {c.description}",
                ]
                if c.in_priority:
                    notes.append("in Priority inbox")
                if c.sender or c.subject:
                    notes.append(
                        f"exact sender: {c.sender or 'any'}; literal subject prefix: {c.subject or 'any'}"
                    )
                if c.proposed:
                    notes.append("only suggested so far")
                described.append(f"{c.name}: {', '.join(notes)}")
            return "\n".join(described) or "No categories yet."

        return guard(
            tool_call_id, "list_categories", "read", "Read your categories", "", work, documents
        )

    def create_categories(categories: list[_CategoryItem], tool_call_id: str) -> str:
        def work() -> str:
            filed = 0
            for item in categories:
                command = SaveCategory(
                    name=item.name,
                    in_priority=item.in_priority,
                    sender=item.sender,
                    subject=item.subject,
                    source="agent",
                    mode=item.mode,
                    description=item.description,
                )
                filed += cast(CategorySaved, mail.save_category(command, ctx)).filed
            return f"Created {len(categories)} categories. Filed {filed} existing conversations."

        names = [item.name for item in categories]
        detail = _lines(
            f"{item.name}, files mail matching “{item.sender or item.subject}”"
            if item.sender or item.subject
            else item.name
            for item in categories
        )
        summary = f"Create {_brief(names)}"
        return guard(tool_call_id, "create_categories", "data", summary, detail, work)

    def update_category(
        name: str,
        tool_call_id: str,
        new_name: str | None = None,
        in_priority: bool | None = None,
        sender: str | None = None,
        subject: str | None = None,
        clear_rule: bool = False,
        mode: Literal["exact", "smart"] | None = None,
        description: str | None = None,
    ) -> str:
        def work() -> str:
            command = UpdateCategory(
                name=name,
                new_name=new_name,
                in_priority=in_priority,
                **({"sender": sender} if sender is not None else {}),
                **({"subject": subject} if subject is not None else {}),
                clear_rule=clear_rule,
                mode=mode,
                description=description,
            )
            try:
                mail.update_category(command, ctx)
            except CommandError as error:
                return f"Not done: {error.message}"
            return f"Updated {new_name or name}."

        summary = f"Rename {name} to {new_name}" if new_name else f"Change {name}"
        if in_priority is not None and not new_name:
            summary = f"{'Show' if in_priority else 'Stop showing'} {name} in the Priority inbox"
        return guard(tool_call_id, "update_category", "data", summary, "", work)

    def delete_categories(names: list[str], tool_call_id: str) -> str:
        def work() -> str:
            for name in names:
                mail.remove_category(CategoryName(name=name), ctx)
            return f"Removed {len(names)} categories. Their mail stays, without the label."

        summary = f"Remove categories: {_brief(names)}"
        return guard(tool_call_id, "delete_categories", "data", summary, _lines(names), work)

    def merge_categories(names: list[str], into: str, tool_call_id: str) -> str:
        def work() -> str:
            mail.merge_categories(MergeCategories(names=names, into=into), ctx)
            return f"Merged into {into}."

        summary = f"Merge {_brief(names)} into {into}"
        return guard(tool_call_id, "merge_categories", "data", summary, "", work)

    def reorder_categories(names: list[str], tool_call_id: str) -> str:
        def work() -> str:
            mail.reorder_categories(ReorderCategories(names=names), ctx)
            return "Reordered."

        return guard(tool_call_id, "reorder_categories", "data", "Reorder categories", "", work)

    # Rules

    def list_rules(tool_call_id: str) -> str:
        def work() -> str:
            found = mail_rules.load_rules(ctx.config.home)
            return (
                "\n".join(
                    f"{r.name} ({'on' if r.enabled else 'off'}): "
                    + " and ".join(f"{c.field} has “{c.value}”" for c in r.conditions)
                    + f" -> {r.actions.model_dump(exclude_defaults=True)}"
                    for r in found
                )
                or "No rules yet."
            )

        return guard(
            tool_call_id, "list_rules", "read", "Read your mail rules", "", work, documents
        )

    def save_rule(
        name: str,
        tool_call_id: str,
        sender: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        category: str | None = None,
        mark_read: bool = False,
        skip_agent: bool = False,
        notify: bool = False,
        enabled: bool = True,
    ) -> str:
        conditions = [
            RuleCondition.model_validate({"field": field, "value": value})
            for field, value in (("sender", sender), ("subject", subject), ("body", body))
            if value
        ]
        if not conditions:
            return "Not saved: a rule needs a sender, subject or body to match."
        rule = MailRule(
            name=name,
            enabled=enabled,
            conditions=conditions,
            actions=RuleActions(
                category=category, mark_read=mark_read, skip_agent=skip_agent, notify=notify
            ),
        )

        def work() -> str:
            mail.upsert_rule(ctx, rule)
            return f"Saved the rule {name}."

        detail = " and ".join(f"{c.field} has “{c.value}”" for c in conditions)
        return guard(tool_call_id, "save_rule", "data", f"Save rule: {name}", detail, work)

    def move_sender(sender: str, side: str, tool_call_id: str, folder: str | None = None) -> str:
        def work() -> str:
            return mail_sorting.move_sender(ctx, sender, reads=side == "reads", folder=folder)

        where = "the AI reads it" if side == "reads" else "kept from the AI"
        detail = f"{sender}: {where}" + (f", filed in {folder}" if folder else "")
        return guard(tool_call_id, "move_sender", "data", f"Move a sender: {sender}", detail, work)

    def delete_rules(names: list[str], tool_call_id: str) -> str:
        def work() -> str:
            mail.delete_rules(ctx, names)
            return f"Removed {len(names)} rules."

        summary = f"Remove rules: {_brief(names)}"
        return guard(tool_call_id, "delete_rules", "data", summary, _lines(names), work)

    # Sending and drafts

    def send_mail(
        to: list[str],
        subject: str,
        body: str,
        tool_call_id: str,
        cc: list[str] | None = None,
        thread_id: int | None = None,
        draft_id: int | None = None,
    ) -> str:
        draft = Draft(
            id=draft_id,
            to=[Recipient(name="", address=item) for item in to],
            cc=[Recipient(name="", address=item) for item in cc or []],
            subject=subject,
            body=body,
            thread_id=thread_id,
            source="agent",
        )

        def work() -> str:
            try:
                mail.send_mail(SendDraft(draft=draft), ctx)
            except CommandError as error:
                return f"Not sent: {error.message}"
            return "Sent."

        limit = ctx.config.team.sends_per_hour
        since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        sent = ctx.bus.db.fetch_all(
            "SELECT COUNT(*) AS n FROM tool_calls WHERE tool = 'send_mail' AND status = 'done'"
            " AND started > ?",
            (since,),
        )[0]["n"]
        if sent >= limit:
            return (
                f"Not sent: agents have sent {limit} emails in the last hour, the most allowed. "
                "Save it as a draft for the person instead."
            )
        # The approval shows who each person is, and every link, so a recipient or link that came
        # from mail someone else wrote stands out before it's sent.
        who = signals.recipient_notes(ctx, [*to, *(cc or [])], thread_id)
        links = sorted(set(LINK.findall(body)))
        new = [note for note in who if "NEW" in note]
        detail = "\n".join(
            [
                "Recipients:",
                *(f"- {note}" for note in who),
                *(["Links in this message:", *(f"- {link}" for link in links)] if links else []),
                f"Subject: {subject}",
                "",
                body,
            ]
        )
        summary = f"Send mail to {', '.join(to)}: {subject}"
        if new:
            summary = f"Send mail to someone new ({len(new)}): {subject}"
        return guard(tool_call_id, "send_mail", "send", summary, detail, work)

    def list_drafts(tool_call_id: str) -> str:
        def work() -> str:
            rows = cast(DraftList, mail.list_drafts(ListDrafts(), ctx)).drafts
            return wrap_untrusted(
                "\n".join(
                    f"{d.id}: to {', '.join(p.address for p in d.to)} | {d.subject}" for d in rows
                )
                or "No drafts."
            )

        return guard(tool_call_id, "list_drafts", "read", "Read your drafts", "", work, documents)

    def save_draft(
        tool_call_id: str,
        draft_id: int | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        subject: str = "",
        body: str = "",
        thread_id: int | None = None,
    ) -> str:
        def work() -> str:
            draft = Draft(
                id=draft_id,
                to=[Recipient(name="", address=item) for item in to or []],
                cc=[Recipient(name="", address=item) for item in cc or []],
                subject=subject,
                body=body,
                thread_id=thread_id,
                source="agent",
            )
            mail.save_draft(draft, ctx)
            return "Saved as a draft. Nothing was sent."

        return guard(tool_call_id, "save_draft", "data", f"Save draft: {subject}", body, work)

    def delete_drafts(draft_ids: list[int], tool_call_id: str) -> str:
        def work() -> str:
            for draft in draft_ids:
                mail.remove_draft(RemoveDraftCommand(id=draft), ctx)
            return f"Removed {len(draft_ids)} drafts."

        return guard(
            tool_call_id, "delete_drafts", "data", f"Remove {len(draft_ids)} drafts", "", work
        )

    # Data

    def read_database(sql: str, tool_call_id: str) -> str:
        def work() -> str:
            return wrap_untrusted(run_read_only(ctx, sql))

        return guard(
            tool_call_id,
            "read_database",
            "read",
            "Look something up in your data",
            sql,
            work,
            documents,
            marks_untrusted=True,
        )

    def semantic_search(query: str, tool_call_id: str, scope: str = "all", limit: int = 15) -> str:
        def work() -> str:
            engine = semantic.engine()
            kinds = {"mail": {"mail"}, "documents": {"document"}}.get(scope, {"mail", "document"})
            size = max(1, min(limit, 50))
            if engine is None or not engine.is_ready():
                # It wasn't offered unless it was here, so it went during this run. Words still
                # find things, and the person hears why this may miss some.
                note = (
                    "Search by meaning isn't available yet, because its model isn't on this computer."
                    " These are keyword matches, so tell the person results may be incomplete.\n"
                )
                found = cast(
                    SearchResults, mail.run_search(SearchMail(query=query, limit=size), ctx)
                ).hits
                return wrap_untrusted(
                    note
                    + (
                        "\n".join(
                            f"{citations.mark(citations.MAIL, h.thread.id)} {h.thread.subject}: {h.excerpt}"
                            for h in found
                        )
                        or "Nothing found."
                    )
                )
            hits = engine.search(query, kinds, size)
            weak = not hits
            if weak:
                # Better to look and judge than be told there's nothing, when words may have missed it.
                hits = engine.search(query, kinds, WEAK_MATCHES_SHOWN, closest_anyway=True)
            coverage = engine.coverage(kinds)
            lines = [coverage] if coverage else []
            if weak and hits:
                lines.append(
                    "Nothing stands out as close in meaning. These are the nearest and may be"
                    " unrelated, so check them, or use search_mail for exact words."
                )
            seen: set[int] = set()
            for hit in hits:
                if hit.kind == "mail":
                    rows = db.fetch_all(
                        "SELECT thread_id, subject, date, from_addr FROM messages WHERE id = ?",
                        (int(hit.ref),),
                    )
                    # One conversation once, at its closest message.
                    if rows and rows[0]["thread_id"] in seen:
                        continue
                    name = (
                        f"{citations.mark(citations.MAIL, rows[0]['thread_id'])} {rows[0]['date'][:10]}"
                        f" | {rows[0]['subject']} | from {rows[0]['from_addr']}"
                        if rows
                        else hit.ref
                    )
                    if rows:
                        seen.add(rows[0]["thread_id"])
                        citations.note(db, session, citations.MAIL, str(rows[0]["thread_id"]))
                else:
                    name = citations.mark(citations.DOCUMENT, hit.ref) + (
                        f" in {hit.place}" if hit.place else ""
                    )
                    citations.note(db, session, citations.DOCUMENT, hit.ref)
                lines.append(f"{name} ({hit.score:.2f}): {hit.excerpt}")
            if not hits:
                lines.append(
                    "Nothing stands out as close in meaning. search_mail finds exact words."
                )
            return wrap_untrusted("\n".join(lines))

        return guard(
            tool_call_id,
            "semantic_search",
            "read",
            f"Search by meaning: {query}",
            "",
            work,
            documents,
            marks_untrusted=True,
        )

    # Schedules

    def _schedule_problem(error: ValidationError) -> str:
        reasons = "; ".join(str(item.get("msg", "")) for item in error.errors(include_url=False))
        return f"Not saved: {reasons}. Fix it and try again."

    def _when_lines(schedule: Schedule, next_run: str | None) -> str:
        zone = schedule.timezone or scheduler.system_timezone()
        lines = [f"When: {scheduler.describe(schedule)} ({zone})"]
        lines.append(
            f"Next run: {scheduler.local_time(next_run, zone)}"
            if next_run
            else "Next run: none, it's paused or finished"
        )
        if schedule.token_limit:
            lines.append(f"Token limit per run: {schedule.token_limit:,}")
        return "\n".join(lines)

    def _schedule_from(row: Any, **changes: Any) -> Schedule:
        values = {
            "id": row["id"],
            "title": row["title"],
            "prompt": row["prompt"],
            "kind": row["kind"],
            "every": row["every"],
            "time": row["time"],
            "weekday": row["weekday"],
            "month_day": row["month_day"],
            "month": row["month"],
            "date": row["date"],
            "until": row["until"],
            "enabled": bool(row["enabled"]),
            "token_limit": row["token_limit"],
            "timezone": row["timezone"] or None,
            "context_mode": row["context_mode"],
            "keep_messages": row["keep_messages"],
        }
        return Schedule.model_validate(
            {**values, **{k: v for k, v in changes.items() if v is not None}}
        )

    def _built_in(row: Any) -> str | None:
        if row["kind"] in scheduler.BUILT_IN_KINDS:
            owner = cards.name(db, "mail")
            return (
                f"Not changed: {row['title']} comes with the app. The person turns it on, off"
                f" or changes its time in Settings, {owner}."
            )
        return None

    def _same_name(name: str, other_than: int | None = None) -> Any:
        rows = db.fetch_all(
            "SELECT * FROM schedules WHERE lower(title)=lower(?) AND kind != 'mail-hourly' AND id IS NOT ?",
            (name.strip(), other_than),
        )
        return rows[0] if rows else None

    def create_schedule(
        name: str,
        instructions: str,
        tool_call_id: str,
        every: str = "day",
        time: str = "08:00",
        weekday: str | None = None,
        month_day: int | None = None,
        month: int | None = None,
        date: str | None = None,
        until: str | None = None,
        token_limit: int = 0,
    ) -> str:
        from nexusai.modules.agent.module import save_schedule

        existing = _same_name(name)
        if existing is not None:
            return (
                f"Not created: schedule {existing['id']} is already called {existing['title']} and runs"
                f" {scheduler.describe(_schedule_from(existing))}. Change it with update_schedule,"
                " or pick another name."
            )
        try:
            command = Schedule.model_validate(
                {
                    "title": name.strip(),
                    "prompt": instructions,
                    "every": every,
                    "time": time,
                    "weekday": WEEKDAYS.index(cast("Weekday", weekday)) if weekday else 0,
                    "month_day": month_day or 1,
                    "month": month or 1,
                    "date": date,
                    "until": until,
                    "token_limit": token_limit,
                    "timezone": scheduler.system_timezone(),
                }
            )
        except ValidationError as error:
            return _schedule_problem(error)
        first = scheduler.next_scheduled_run(command, datetime.now(UTC))
        if first is None:
            return "Not created: with that end date it would never run. Pick a later until, or leave it out."

        def work() -> str:
            save_schedule(command, ctx)
            row = _same_name(command.title)
            return (
                f"Created schedule {row['id'] if row else ''}: {command.title}. It runs"
                f" {scheduler.describe(command)}; first run {scheduler.local_time(first, command.timezone)}."
                " Each run happens in its own chat, which the person finds on the Schedules page."
            )

        detail = f"{_when_lines(command, first)}\n\n{instructions}"
        return guard(
            tool_call_id, "create_schedule", "data", f"New schedule: {command.title}", detail, work
        )

    def update_schedule(
        schedule_id: int,
        tool_call_id: str,
        name: str | None = None,
        instructions: str | None = None,
        every: str | None = None,
        time: str | None = None,
        weekday: str | None = None,
        month_day: int | None = None,
        month: int | None = None,
        date: str | None = None,
        until: str | None = None,
        enabled: bool | None = None,
        token_limit: int | None = None,
    ) -> str:
        from nexusai.modules.agent.module import save_schedule

        rows = _rows("schedules", [schedule_id])
        if not rows:
            return f"Not changed: there's no schedule {schedule_id}. See them with list_schedules."
        row = rows[0]
        if (refused := _built_in(row)) is not None:
            return refused
        if name is not None and (clash := _same_name(name, schedule_id)) is not None:
            return f"Not changed: schedule {clash['id']} is already called {clash['title']}."
        try:
            before = _schedule_from(row)
            command = _schedule_from(
                row,
                title=name.strip() if name else None,
                prompt=instructions,
                every=every,
                time=time,
                weekday=WEEKDAYS.index(cast("Weekday", weekday)) if weekday else None,
                month_day=month_day,
                month=month,
                date=date,
                until=until,
                enabled=enabled,
                token_limit=token_limit,
            )
        except ValidationError as error:
            return _schedule_problem(error)
        if command.every == "once" and not command.date:
            return "Not changed: every='once' needs date, such as date='2026-12-01'."
        following = (
            scheduler.next_scheduled_run(command, datetime.now(UTC)) if command.enabled else None
        )
        if command.enabled and following is None:
            return "Not changed: with that end date it would never run again. Pick a later until, or pause it with enabled=false."
        changes = []
        if command.title != before.title:
            changes.append(f"Name: {before.title} → {command.title}")
        if scheduler.describe(command) != scheduler.describe(before):
            changes.append(f"When: {scheduler.describe(before)} → {scheduler.describe(command)}")
        if command.enabled != before.enabled:
            changes.append("Paused" if not command.enabled else "Resumed")
        if command.token_limit != before.token_limit:
            changes.append(f"Token limit: {before.token_limit:,} → {command.token_limit:,}")
        if command.prompt != before.prompt:
            changes.append(f"Instructions:\n{command.prompt}")
        if not changes:
            return f"Nothing to change: {before.title} already runs {scheduler.describe(before)}."

        def work() -> str:
            save_schedule(command, ctx)
            if not command.enabled:
                return f"Paused schedule {schedule_id}: {command.title}. Nothing runs until it's resumed."
            return (
                f"Updated schedule {schedule_id}: {command.title}. It runs {scheduler.describe(command)};"
                f" next run {scheduler.local_time(following, command.timezone)}."
            )

        detail = "\n".join(changes)
        return guard(
            tool_call_id,
            "update_schedule",
            "data",
            f"Change schedule: {before.title}",
            detail,
            work,
        )

    def run_schedule(schedule_id: int, tool_call_id: str) -> str:
        from nexusai.modules.agent.module import run_schedule_now

        rows = _rows("schedules", [schedule_id])
        if not rows:
            return f"Not run: there's no schedule {schedule_id}. See them with list_schedules."
        title = rows[0]["title"]

        def work() -> str:
            run_schedule_now(RunSchedule(id=schedule_id), ctx)
            return f"Started {title} now, in its own chat. Its result shows on the Schedules page; its next regular run doesn't change."

        return guard(tool_call_id, "run_schedule", "data", f"Run now: {title}", "", work)

    def list_schedules(tool_call_id: str) -> str:
        def work() -> str:
            rows = db.fetch_all("SELECT * FROM schedules WHERE kind != 'mail-hourly' ORDER BY id")
            lines = []
            for row in rows:
                schedule = _schedule_from(row)
                state = (
                    f"next {scheduler.local_time(row['next_run'], schedule.timezone)}"
                    if row["enabled"] and row["next_run"]
                    else "paused"
                )
                owner = (
                    ", comes with the app (changed in Settings)"
                    if row["kind"] in scheduler.BUILT_IN_KINDS
                    else ""
                )
                lines.append(
                    f"{row['id']}: {row['title']} — {scheduler.describe(schedule)} — {state}{owner}"
                )
            return wrap_untrusted("\n".join(lines) or "No schedules yet.")

        return guard(
            tool_call_id, "list_schedules", "read", "Read your schedules", "", work, documents
        )

    def remove_schedules(schedule_ids: list[int], tool_call_id: str) -> str:
        from nexusai.modules.agent.module import remove_schedule

        rows = _rows("schedules", schedule_ids)
        missing = sorted(set(schedule_ids) - {row["id"] for row in rows})
        if missing:
            return f"Not removed: there's no schedule {', '.join(map(str, missing))}. See them with list_schedules."
        for row in rows:
            if (refused := _built_in(row)) is not None:
                return refused.replace("Not changed", "Not removed")
        titles = [str(row["title"]) for row in rows]

        def work() -> str:
            for schedule in schedule_ids:
                remove_schedule(RemoveSchedule(id=schedule), ctx)
            return f"Removed {_brief(titles)}. They won't run again."

        summary = f"Remove schedules: {_brief(titles)}"
        return guard(tool_call_id, "remove_schedules", "data", summary, _lines(titles), work)

    # Memory

    def list_memory(tool_call_id: str, query: str = "") -> str:
        def work() -> str:
            found = memory.list_files(ctx.config.home, query)
            return wrap_untrusted(
                "\n\n".join(f"{f.path}:\n{f.content}" for f in found) or "Nothing remembered yet."
            )

        return guard(
            tool_call_id, "list_memory", "read", "Read what's remembered", "", work, documents
        )

    def update_memory(path: str, content: str, tool_call_id: str) -> str:
        def work() -> str:
            memory.save_file(ctx.config.home, path, "", "user", None, content)
            with ctx.bus.unit_of_work() as run:
                run.emit("memory.changed", {}, source="agent", trace_id=ctx.trace_id)
            return "Updated."

        return guard(tool_call_id, "update_memory", "data", f"Change memory: {path}", content, work)

    def forget_memory(paths: list[str], tool_call_id: str) -> str:
        def work() -> str:
            for path in paths:
                memory.remove_file(ctx.config.home, path)
            with ctx.bus.unit_of_work() as run:
                run.emit("memory.changed", {}, source="agent", trace_id=ctx.trace_id)
            return f"Forgot {len(paths)} items."

        summary = f"Forget: {_brief(paths)}"
        return guard(tool_call_id, "forget_memory", "data", summary, _lines(paths), work)

    # Documents

    def list_documents(tool_call_id: str, query: str = "") -> str:
        def work() -> str:
            found = cast(
                Any, documents_module.list_documents(ListDocuments(query=query, limit=50), ctx)
            ).documents
            return wrap_untrusted(
                "\n".join(f"{d.key}: {d.name} ({d.folder or 'no folder'})" for d in found)
                or "No documents found."
            )

        return guard(
            tool_call_id,
            "list_documents",
            "read",
            "List documents",
            "",
            work,
            documents,
            marks_untrusted=True,
        )

    def update_documents(
        keys: list[str],
        tool_call_id: str,
        folder: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        def work() -> str:
            for key in keys:
                current = next(
                    (
                        row
                        for row in cast(
                            Any,
                            documents_module.list_documents(ListDocuments(limit=500), ctx),
                        ).documents
                        if row.key == key
                    ),
                    None,
                )
                command = UpdateDocument(
                    key=key,
                    folder=folder if folder is not None else (current.folder if current else None),
                    tags=tags if tags is not None else (current.tags if current else []),
                )
                documents_module.update_document(command, ctx)
            return f"Updated {len(keys)} documents."

        summary = f"File {len(keys)} documents"
        return guard(tool_call_id, "update_documents", "data", summary, _lines(keys), work)

    def delete_documents(keys: list[str], tool_call_id: str) -> str:
        def work() -> str:
            for key in keys:
                try:
                    documents_module.remove_document(RemoveDocument(key=key), ctx)
                except CommandError as error:
                    return f"Stopped at {key}: {error.message}"
            return f"Removed {len(keys)} documents."

        summary = f"Remove {len(keys)} documents"
        return guard(tool_call_id, "delete_documents", "data", summary, _lines(keys), work)

    # Panels

    def list_panels(tool_call_id: str) -> str:
        def work() -> str:
            board = cast(PanelBoard, panels.get_board(GetPanelBoard(), ctx))
            return (
                "\n".join(f"{p.id}: {p.title} ({p.source})" for p in board.panels)
                or "No panels yet."
            )

        return guard(tool_call_id, "list_panels", "read", "Read your panels", "", work, documents)

    def save_panel(
        title: str,
        tool_call_id: str,
        panel_id: str | None = None,
        source: str = "threads",
        sender: str | None = None,
        subject: str | None = None,
        category: str | None = None,
        query: str | None = None,
        unread_only: bool = False,
    ) -> str:
        def work() -> str:
            board = cast(PanelBoard, panels.get_board(GetPanelBoard(), ctx))
            identifier = panel_id or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:64]
            panel = Panel.model_validate(
                {
                    "id": identifier or "panel",
                    "title": title,
                    "source": source,
                    "filters": PanelFilters(
                        sender=sender,
                        subject=subject,
                        category=category,
                        query=query,
                        unread_only=unread_only,
                    ),
                }
            )
            others = [item for item in board.panels if item.id != panel.id]
            panels.save_board(PanelBoard(panels=[*others, panel]), ctx)
            return f"Saved the panel {title}."

        return guard(tool_call_id, "save_panel", "data", f"Save panel: {title}", "", work)

    def remove_panels(panel_ids: list[str], tool_call_id: str) -> str:
        def work() -> str:
            board = cast(PanelBoard, panels.get_board(GetPanelBoard(), ctx))
            kept = [item for item in board.panels if item.id not in panel_ids]
            panels.save_board(PanelBoard(panels=kept), ctx)
            return f"Removed {len(board.panels) - len(kept)} panels."

        summary = f"Remove panels: {_brief(panel_ids)}"
        return guard(tool_call_id, "remove_panels", "data", summary, "", work)

    return [
        (
            create_tasks,
            _NewTasks,
            "Add tasks the person asked for, all in one call. If they didn't ask, use propose_task.",
        ),
        (
            update_tasks,
            _ChangeTasks,
            "Change tasks in one call: title, due date, notes, or status such as done.",
        ),
        (delete_tasks, _TaskIds, "Remove tasks in one call. To finish one, use update_tasks."),
        (list_tasks, _ListTasks, "See the person's tasks, with their IDs and due dates."),
        (
            create_reminders,
            _NewReminders,
            "Set reminders the person asked for, all in one call. If they didn't ask, use "
            "propose_reminder.",
        ),
        (update_reminders, _ChangeReminders, "Change, reschedule or snooze reminders in one call."),
        (delete_reminders, _ReminderIds, "Remove reminders in one call."),
        (list_reminders, _Nothing, "See upcoming reminders, with their IDs."),
        (
            list_mail,
            _ListMail,
            "Browse conversations in a mail folder or category, newest first. To find something "
            "specific, search instead.",
        ),
        (
            update_mail,
            _ChangeMail,
            "Change conversations in one call: category, status, flag, read or archive. Use a "
            "list, so the person has one thing to approve.",
        ),
        (
            trash_mail,
            _ThreadIds,
            "Move conversations to Trash in one call, which asks first. To clear them away "
            "without deleting, archive with update_mail.",
        ),
        (
            list_categories,
            _Nothing,
            "See the mail categories, their rules and how much is in each. Check this before "
            "creating one.",
        ),
        (
            create_categories,
            _NewCategories,
            "Create categories in one call, optionally filing matching mail automatically. Only "
            "when none of the existing ones fit.",
        ),
        (
            update_category,
            _ChangeCategory,
            "Change one category in place: rename it, change its Priority setting, mode or personalized description, or set "
            "or clear its exact sender / literal subject-prefix rule. Prefer this to creating a new one and moving mail across.",
        ),
        (
            delete_categories,
            _CategoryNames,
            "Remove categories in one call. Their mail stays, without a category.",
        ),
        (
            merge_categories,
            _MergeCategories,
            "Fold categories into one, moving all their mail and removing the old ones.",
        ),
        (reorder_categories, _OrderCategories, "Set the order categories appear in."),
        (list_rules, _Nothing, "See the mail rules. They run before any agent sees the mail."),
        (
            save_rule,
            _Rule,
            "Create or replace a rule that handles matching mail with no model involved. Good for "
            "mail that's always handled the same way.",
        ),
        (
            move_sender,
            _MoveSender,
            "Move one sender to the side the AI reads or the side it ignores, as the Sort page "
            "does. Its rules are replaced by one, so it never has two. Mail already filed stays.",
        ),
        (delete_rules, _RuleNames, "Remove mail rules in one call."),
        (
            send_mail,
            _SendMail,
            "Send an email. The person always sees it and approves it first. To prepare one "
            "without sending, use save_draft.",
        ),
        (list_drafts, _Nothing, "See the saved drafts, with their IDs."),
        (save_draft, _SaveDraft, "Create or change a draft. Nothing is sent."),
        (delete_drafts, _DraftIds, "Remove drafts in one call."),
        (
            semantic_search,
            _MeaningSearch,
            "Find mail and documents by what they're about, in any language, even with no shared "
            "words. Best for a topic, in a few words rather than a sentence. For an exact name or "
            "number, use search_mail.",
        ),
        (
            read_database,
            _Query,
            "Answer a counting or comparing question from the person's data with one SELECT. "
            "It can't change anything.",
        ),
        (
            create_schedule,
            _NewSchedule,
            "Make something run by itself at set times, like a Friday status or a morning check."
            " Only when the person wants it to repeat or happen later. It asks the person first.",
        ),
        (
            update_schedule,
            _ChangeSchedule,
            "Change a schedule's name, instructions or timing, or pause and resume it."
            " Give only what changes.",
        ),
        (run_schedule, _ScheduleId, "Run a schedule now, in its own chat."),
        (list_schedules, _Nothing, "See the schedules with their IDs, timing and next run."),
        (remove_schedules, _ScheduleIds, "Remove schedules in one call."),
        (list_memory, _SearchMemory, "See what's remembered about the person and their work."),
        (update_memory, _ChangeMemory, "Change something remembered, when it's out of date."),
        (forget_memory, _MemoryPaths, "Forget remembered things in one call."),
        (
            list_documents,
            _ListDocuments,
            "List documents with their keys and folders, or filter them by a query.",
        ),
        (update_documents, _ChangeDocuments, "Move or tag documents in one call."),
        (
            delete_documents,
            _DocumentKeys,
            "Remove uploaded documents in one call. Mail attachments stay with their mail.",
        ),
        (list_panels, _Nothing, "See the panels on the Panels screen, with their IDs."),
        (save_panel, _SavePanel, "Create or change a panel, when the person asks for one."),
        (remove_panels, _PanelIds, "Remove panels in one call."),
    ]
