"""The kinds of thing a matter holds or links to, declared once.

Each kind says where it lives, how to read its title and date, and, if it can be finished, how
it's closed and opened again. Everything that walks a matter (closing, asking about the rest,
the AI's context, the chat's tools) reads this list, so a new kind is one entry here. Objects are
named the same way everywhere, on screen, in prompts and in links: "task:88", "doc:12".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    table: str
    title: str
    when: str | None = None
    # SQL for a row that's still open, and the SET clauses that close and reopen it. A kind
    # without them, like a document, is never finished.
    still_open: str | None = None
    close: str | None = None
    reopen: str | None = None
    event: str = ""


KINDS: dict[str, Kind] = {
    "task": Kind("tasks", "title", "due", "status != 'done'",
                 "status = 'done', completed = ?2", "status = 'todo', completed = NULL", "tasks.changed"),
    "reminder": Kind("reminders", "title", "due_at", "fired = 0", "fired = 1", "fired = 0", "reminders.changed"),
    "deadline": Kind("work_board", "title", "due", "done = 0 AND kind = 'deadline'", "done = 1", "done = 0",
                     "board.changed"),
    "thread": Kind("threads", "subject", "last_date"),
    "doc": Kind("documents", "name", "added"),
    "matter": Kind("matters", "title", "updated"),
}  # fmt: skip

# What can be finished, in the order a matter lists its work.
WORK = ("task", "reminder", "deadline")


def ref(kind: str, identifier: int) -> str:
    return f"{kind}:{identifier}"


def parse(value: object) -> tuple[str, int] | None:
    """A name like "task:88", or None for anything else, so what a model writes can't reach SQL."""
    kind, _, number = str(value or "").strip().partition(":")
    if kind not in KINDS or not number.isdigit():
        return None
    return kind, int(number)
