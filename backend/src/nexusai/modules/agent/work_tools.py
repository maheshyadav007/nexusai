"""Tools for the person's own data: tasks, reminders, mail, categories, the database and agents.

Every tool here goes through the same door as file and command tools, so its permission is set in
Settings. A session that has read mail always asks before changing anything.
"""

import re
import sqlite3
import time
from collections.abc import Callable
from typing import Annotated, Any, cast

from langchain_core.tools import InjectedToolCallId
from pydantic import BaseModel, Field

from nexusai.contracts.agent import RemoveSchedule, Schedule
from nexusai.contracts.mail import (
    CategorySaved,
    Draft,
    ListThreads,
    MoveThread,
    Recipient,
    SaveCategory,
    SendDraft,
    SetThreadCategory,
    ThreadList,
)
from nexusai.kernel.database import connect_raw
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import module as mail
from nexusai.modules.planner import module as planner

# What read_database can see. Masking tokens, approvals and the event log stay out of reach.
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
SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

Guard = Callable[..., str]
Spec = tuple[Callable[..., str], type[BaseModel], str]


class _Call(BaseModel):
    tool_call_id: Annotated[str, InjectedToolCallId]


class _NewTask(_Call):
    title: str = Field(description="What needs doing.")
    due: str | None = Field(default=None, description="YYYY-MM-DD, if it has a date.")
    notes: str = Field(default="", description="Any detail worth keeping.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")


class _NewReminder(_Call):
    title: str = Field(description="What to remind the person about.")
    when: str = Field(description="YYYY-MM-DDTHH:MM, in the person's local time.")
    repeat: str = Field(default="none", description="none, day or week.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")


class _TaskId(_Call):
    task_id: int = Field(description="The task's ID, from list_tasks.")


class _ListTasks(_Call):
    include_done: bool = Field(default=False, description="Include finished tasks too.")


class _Nothing(_Call):
    pass


class _ListMail(_Call):
    folder: str = Field(default="priority", description="priority, all, sent, archive or trash.")
    category: str | None = Field(default=None, description="Only this category.")
    limit: int = Field(default=30, description="How many conversations, up to 100.")


class _NewCategory(_Call):
    name: str = Field(description="A short name, like Invoices.")
    in_priority: bool = Field(default=False, description="Show this in the Priority inbox.")
    sender: str | None = Field(
        default=None, description="File mail from this sender or domain here automatically."
    )
    subject: str | None = Field(
        default=None, description="File mail whose subject contains this here automatically."
    )


class _FileThread(_Call):
    thread_id: int = Field(description="The conversation's ID.")
    category: str = Field(description="The category's name. Create it first if it's new.")


class _ThreadOnly(_Call):
    thread_id: int = Field(description="The conversation's ID.")


class _SendMail(_Call):
    to: list[str] = Field(description="Email addresses to send to.")
    subject: str = Field(description="The subject line.")
    body: str = Field(description="The message, as plain text.")
    cc: list[str] = Field(default_factory=list, description="Addresses to copy.")
    thread_id: int | None = Field(default=None, description="The conversation this replies in.")


class _Query(_Call):
    sql: str = Field(
        description=(
            "One read-only SELECT. Tables: messages, threads, message_parts, mail_categories,"
            " tasks, reminders, schedules, work_board, agent_sessions, notifications."
        )
    )


class _NewAgent(_Call):
    name: str = Field(description="What the agent is for, like Friday status writer.")
    instructions: str = Field(description="What it should do each time it runs.")
    every: str = Field(default="day", description="once, day or week.")
    time: str = Field(default="08:00", description="HH:MM, in the person's local time.")
    weekday: int = Field(default=0, description="For weekly agents: 0 is Monday, 6 is Sunday.")
    date: str | None = Field(default=None, description="For a one-time agent: YYYY-MM-DD.")
    token_limit: int = Field(default=0, description="Most tokens per run. 0 means no limit.")


class _AgentId(_Call):
    agent_id: int = Field(description="The agent's ID, from list_agents.")


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


def specs(ctx: Context, guard: Guard, wrap_untrusted: Callable[[str], str]) -> list[Spec]:
    db = ctx.bus.db
    documents = ctx.config.home / "documents"

    def create_task(
        title: str,
        tool_call_id: str,
        due: str | None = None,
        notes: str = "",
        thread_id: int | None = None,
    ) -> str:
        def work() -> str:
            identifier = planner.add_task(ctx, title, due, thread_id, "agent", False, notes)
            return f"Created task {identifier}: {title}"

        detail = f"Due {due}" if due else ""
        return guard(tool_call_id, "create_task", "data", f"Add task: {title}", detail, work)

    def create_reminder(
        title: str,
        when: str,
        tool_call_id: str,
        repeat: str = "none",
        thread_id: int | None = None,
    ) -> str:
        def work() -> str:
            planner.add_reminder(ctx, title, when[:16], repeat, thread_id, None, "agent", False)
            return f"Reminder set for {when[:16]}: {title}"

        summary = f"Remind you: {title}"
        return guard(tool_call_id, "create_reminder", "data", summary, when[:16], work)

    def list_tasks(tool_call_id: str, include_done: bool = False) -> str:
        def work() -> str:
            where = "" if include_done else "WHERE status != 'done'"
            rows = db.fetch_all(f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT 100")  # noqa: S608
            return wrap_untrusted(
                "\n".join(f"{r['id']}: {r['title']} ({r['status']}, due {r['due']})" for r in rows)
                or "No tasks."
            )

        return guard(tool_call_id, "list_tasks", "read", "Read your tasks", "", work, documents)

    def complete_task(task_id: int, tool_call_id: str) -> str:
        def work() -> str:
            with ctx.bus.unit_of_work() as run:
                run.tx.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
                run.emit("tasks.changed", {}, source="agent", trace_id=ctx.trace_id)
            return "Marked done."

        summary = f"Mark task {task_id} done"
        return guard(tool_call_id, "complete_task", "data", summary, "", work)

    def list_reminders(tool_call_id: str) -> str:
        def work() -> str:
            rows = db.fetch_all("SELECT * FROM reminders WHERE fired = 0 ORDER BY due_at LIMIT 100")
            return wrap_untrusted(
                "\n".join(f"{r['id']}: {r['title']} at {r['due_at']}" for r in rows)
                or "No reminders."
            )

        return guard(
            tool_call_id, "list_reminders", "read", "Read your reminders", "", work, documents
        )

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
                    f"{t.id}: {t.subject} | {t.category or 'no category'} | {t.last_date}"
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

    def list_categories(tool_call_id: str) -> str:
        def work() -> str:
            found = mail.category_rows(ctx)
            return (
                "\n".join(
                    f"{c.name}: {c.count} conversations"
                    f"{', in Priority inbox' if c.in_priority else ''}"
                    for c in found
                )
                or "No categories yet."
            )

        return guard(
            tool_call_id, "list_categories", "read", "Read your categories", "", work, documents
        )

    def create_category(
        name: str,
        tool_call_id: str,
        in_priority: bool = False,
        sender: str | None = None,
        subject: str | None = None,
    ) -> str:
        def work() -> str:
            command = SaveCategory(
                name=name, in_priority=in_priority, sender=sender, subject=subject, source="agent"
            )
            filed = cast(CategorySaved, mail.save_category(command, ctx)).filed
            return f"Created category {name}. Filed {filed} existing conversations."

        match = sender or subject
        detail = f"Files mail matching “{match}”" if match else ""
        return guard(
            tool_call_id, "create_category", "data", f"Create category: {name}", detail, work
        )

    def set_thread_category(thread_id: int, category: str, tool_call_id: str) -> str:
        def work() -> str:
            mail.set_category(SetThreadCategory(id=thread_id, category=category), ctx)
            return f"Filed under {category}."

        summary = f"File conversation {thread_id} under {category}"
        return guard(tool_call_id, "set_thread_category", "data", summary, "", work)

    def archive_thread(thread_id: int, tool_call_id: str) -> str:
        def work() -> str:
            mail.move_thread(MoveThread(id=thread_id, to="archive"), ctx)
            return "Archived."

        summary = f"Archive conversation {thread_id}"
        return guard(tool_call_id, "archive_thread", "data", summary, "", work)

    def send_mail(
        to: list[str],
        subject: str,
        body: str,
        tool_call_id: str,
        cc: list[str] | None = None,
        thread_id: int | None = None,
    ) -> str:
        draft = Draft(
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

        detail = f"To: {', '.join(to)}\nSubject: {subject}\n\n{body}"
        summary = f"Send mail to {', '.join(to)}: {subject}"
        return guard(tool_call_id, "send_mail", "send", summary, detail, work)

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

    def create_agent(
        name: str,
        instructions: str,
        tool_call_id: str,
        every: str = "day",
        time: str = "08:00",
        weekday: int = 0,
        date: str | None = None,
        token_limit: int = 0,
    ) -> str:
        from nexusai.modules.agent.module import save_schedule

        def work() -> str:
            command = Schedule.model_validate(
                {
                    "title": name,
                    "prompt": instructions,
                    "every": every,
                    "time": time,
                    "weekday": weekday,
                    "date": date,
                    "token_limit": token_limit,
                }
            )
            save_schedule(command, ctx)
            return f"Created {name}. It runs by itself from now on."

        detail = f"Runs: {every} at {time}\n\n{instructions}"
        return guard(tool_call_id, "create_agent", "data", f"Create agent: {name}", detail, work)

    def list_agents(tool_call_id: str) -> str:
        def work() -> str:
            rows = db.fetch_all("SELECT * FROM schedules ORDER BY id")
            return wrap_untrusted(
                "\n".join(
                    f"{r['id']}: {r['title']} ({r['every']} at {r['time']}, next {r['next_run']})"
                    for r in rows
                )
                or "No agents yet."
            )

        return guard(tool_call_id, "list_agents", "read", "Read your agents", "", work, documents)

    def remove_agent(agent_id: int, tool_call_id: str) -> str:
        from nexusai.modules.agent.module import remove_schedule

        def work() -> str:
            remove_schedule(RemoveSchedule(id=agent_id), ctx)
            return "Removed."

        return guard(tool_call_id, "remove_agent", "data", f"Remove agent {agent_id}", "", work)

    return [
        (create_task, _NewTask, "Add a task for the person. Use this when they ask for one."),
        (
            create_reminder,
            _NewReminder,
            "Set a reminder for the person. Use this when they ask for one.",
        ),
        (list_tasks, _ListTasks, "See the person's tasks."),
        (complete_task, _TaskId, "Mark a task done."),
        (list_reminders, _Nothing, "See upcoming reminders."),
        (list_mail, _ListMail, "List conversations in a mail folder or category."),
        (list_categories, _Nothing, "See the person's mail categories."),
        (
            create_category,
            _NewCategory,
            "Create a mail category, optionally filing matching mail into it automatically.",
        ),
        (set_thread_category, _FileThread, "File a conversation under a category."),
        (archive_thread, _ThreadOnly, "Archive a conversation."),
        (send_mail, _SendMail, "Send an email. The person always approves it first."),
        (read_database, _Query, "Answer a question from the person's data with one SELECT."),
        (
            create_agent,
            _NewAgent,
            "Create an agent that runs by itself on a schedule, with its own instructions.",
        ),
        (list_agents, _Nothing, "See the agents that run on a schedule."),
        (remove_agent, _AgentId, "Remove a scheduled agent."),
    ]
