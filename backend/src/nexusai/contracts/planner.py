from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class Reminder(BaseModel):
    id: int
    title: str
    when: str
    repeat: Literal["none", "day", "week"]
    thread: int | None
    task: int | None
    source: Literal["user", "agent"]
    proposed: bool
    fired: bool


class ListReminders(BaseModel):
    pass


class ReminderList(BaseModel):
    reminders: list[Reminder]


class SaveReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    title: str = Field(min_length=1, max_length=500)
    when: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    repeat: Literal["none", "day", "week"] = "none"
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
