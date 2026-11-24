from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexusai.contracts.agent import SourceRef

TaskStatus = Literal["todo", "in_progress", "done"]


class Task(BaseModel):
    id: int
    title: str
    notes: str
    status: TaskStatus
    due: str | None
    thread: int | None
    source: Literal["user", "agent"]
    proposed: bool
    created: str
    updated: str | None = None
    completed: str | None = None
    # The email it came from, named from the database.
    source_ref: SourceRef | None = None
    # Why a later email shows it done, until the person closes it or keeps it.
    looks_done: str | None = None


class ListTasks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_done: bool = False


class TaskList(BaseModel):
    tasks: list[Task]


class SaveTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    title: str = Field(min_length=1, max_length=500)
    notes: str = Field(default="", max_length=20000)
    status: TaskStatus = "todo"
    due: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    thread: int | None = None
    proposed: bool = False


class TaskAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


Repeat = Literal["none", "day", "week", "month", "year"]


class Reminder(BaseModel):
    id: int
    title: str
    when: str
    repeat: Repeat
    thread: int | None
    task: int | None
    source: Literal["user", "agent"]
    proposed: bool
    fired: bool
    created: str | None = None
    source_ref: SourceRef | None = None
    updated: str | None = None
    looks_done: str | None = None


class ListReminders(BaseModel):
    # Those that went off lately too, to show as done.
    include_done: bool = False


class ReminderList(BaseModel):
    reminders: list[Reminder]


class SaveReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    title: str = Field(min_length=1, max_length=500)
    when: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    repeat: Repeat = "none"
    thread: int | None = None
    task: int | None = None
    proposed: bool = False


class SnoozeReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    minutes: int = Field(default=60, ge=1, le=100000)


class ReminderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class PlannerDone(BaseModel):
    ok: bool = True
