"""The agent's tools. Every call goes through one door: policy, approval, logging, then the work."""

import difflib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import structlog
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from nexusai.contracts.mail import SearchMail
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import Context
from nexusai.modules.agent import policy
from nexusai.modules.agent.policy import Action
from nexusai.modules.mail import accounts, store

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_tools_001",
    """
CREATE TABLE tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, tool_call_id TEXT NOT NULL, tool TEXT NOT NULL,
  input TEXT NOT NULL, result TEXT, status TEXT NOT NULL, approved_by TEXT, started TEXT NOT NULL, duration_ms INTEGER);
CREATE INDEX tool_calls_session ON tool_calls (session, id);
CREATE TABLE tool_approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, tool_call_id TEXT NOT NULL, tool TEXT NOT NULL, kind TEXT NOT NULL,
  summary TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT NOT NULL, undoable INTEGER NOT NULL, status TEXT NOT NULL, time TEXT NOT NULL,
  UNIQUE (session, tool_call_id));
CREATE TABLE activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, session TEXT, summary TEXT NOT NULL,
  undo_path TEXT, undo_snapshot TEXT, undo_existed INTEGER, undone INTEGER NOT NULL DEFAULT 0);
""",
)
DENIED = "The person declined this."


class RunControl:
    """Lets Stop reach a running command."""

    def __init__(self) -> None:
        self.stopped = threading.Event()
        self._process: subprocess.Popen[str] | None = None

    def attach(self, process: subprocess.Popen[str] | None) -> None:
        self._process = process

    def stop(self) -> None:
        self.stopped.set()
        process = self._process
        if process and process.poll() is None:
            _kill_tree(process)


def _kill_tree(process: subprocess.Popen[str]) -> None:
    try:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass


def _is_untrusted(ctx: Context, session: str) -> bool:
    rows = ctx.bus.db.fetch_all("SELECT untrusted FROM agent_sessions WHERE id = ?", (session,))
    return bool(rows and rows[0]["untrusted"])


def _mark_untrusted(ctx: Context, session: str) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE agent_sessions SET untrusted = 1 WHERE id = ?", (session,))


def _diff(before: str, after: str, name: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), f"{name} (now)", f"{name} (after)", lineterm=""
    )
    return "\n".join(lines)[:20000]


def _approval_row(ctx: Context, session: str, call_id: str) -> Any:
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM tool_approvals WHERE session = ? AND tool_call_id = ?", (session, call_id)
    )
    return rows[0] if rows else None


def _ask(
    ctx: Context,
    session: str,
    call_id: str,
    tool: str,
    kind: str,
    summary: str,
    reason: str,
    detail: str,
    undoable: bool,
) -> bool:
    """Pauses the run for a person's decision. The tool's code restarts from the top on resume,
    so this sits before anything happens, and the same call finds its earlier approval."""
    row = _approval_row(ctx, session, call_id)
    if row is None:
        with ctx.bus.unit_of_work() as work:
            cursor = work.tx.execute(
                "INSERT INTO tool_approvals (session, tool_call_id, tool, kind, summary, reason, detail, undoable, status, time)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    session,
                    call_id,
                    tool,
                    kind,
                    summary,
                    reason,
                    detail,
                    int(undoable),
                    datetime.now(UTC).isoformat(),
                ),
            )
            approval = int(cursor.lastrowid or 0)
            work.emit(
                "approval.changed",
                {"id": approval, "status": "pending"},
                source="agent",
                trace_id=ctx.trace_id,
            )
        row = _approval_row(ctx, session, call_id)
    if row["status"] != "pending":
        return bool(row["status"] == "approved")
    decision = interrupt({"approval": row["id"], "tool_call_id": call_id})
    return bool(decision == "approved")


def _guarded(
    ctx: Context,
    session: str,
    call_id: str,
    tool: str,
    action: Action,
    path: Path | None,
    summary: str,
    detail: str,
    undoable: bool,
    work: Callable[[], str],
    *,
    marks_untrusted: bool = False,
) -> str:
    db = ctx.bus.db
    kind = f"{tool}:{path.parent if path else ''}"
    decision = policy.decide(
        action,
        path=path,
        home=ctx.config.home,
        permissions=policy.load_permissions(db),
        untrusted=_is_untrusted(ctx, session),
        session_allowed=policy.allowed_for_session(db, session, kind),
    )
    approved_by = "settings"
    if decision.verdict == "deny":
        _log_call(
            ctx, session, call_id, tool, detail or summary, decision.reason, "refused", None, 0
        )
        return f"Not allowed: {decision.reason}"
    if decision.verdict == "ask":
        if not _ask(ctx, session, call_id, tool, kind, summary, decision.reason, detail, undoable):
            _log_call(ctx, session, call_id, tool, detail or summary, DENIED, "denied", "person", 0)
            return DENIED
        approved_by = "person"
    started = time.monotonic()
    try:
        result = work()
        status = "done"
    except OSError as error:
        result = f"That didn't work: {error.strerror or type(error).__name__}."
        status = "failed"
    if marks_untrusted:
        _mark_untrusted(ctx, session)
    limit = ctx.config.agent.max_tool_output_chars
    clipped = (
        result
        if len(result) <= limit
        else f"{result[:limit]}\n[Cut off: {len(result)} characters in all.]"
    )
    _log_call(
        ctx,
        session,
        call_id,
        tool,
        detail or summary,
        clipped,
        status,
        approved_by,
        int((time.monotonic() - started) * 1000),
    )
    return clipped


def _log_call(
    ctx: Context,
    session: str,
    call_id: str,
    tool: str,
    tool_input: str,
    result: str,
    status: str,
    approved_by: str | None,
    ms: int,
) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO tool_calls (session, tool_call_id, tool, input, result, status, approved_by, started, duration_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session,
                call_id,
                tool,
                tool_input,
                result,
                status,
                approved_by,
                datetime.now(UTC).isoformat(),
                ms,
            ),
        )
    log.info("tool_call", tool=tool, status=status, approved_by=approved_by, ms=ms, session=session)


def _resolve(ctx: Context, session: str, requested: str) -> Path:
    """Relative paths start in the session's scratch folder. The policy checks the real location."""
    candidate = Path(requested).expanduser()
    if not candidate.is_absolute():
        candidate = scratch_folder(ctx.config.home, session) / candidate
    return candidate.resolve()


def _snapshot(ctx: Context, session: str, path: Path, summary: str) -> None:
    """A copy before each change, so it can be undone."""
    folder = ctx.config.home / "system" / "snapshots" / session
    folder.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    stored = folder / uuid.uuid4().hex
    if existed:
        shutil.copy2(path, stored)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO activity (time, session, summary, undo_path, undo_snapshot, undo_existed) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), session, summary, str(path), str(stored), int(existed)),
        )
        work.emit("activity.added", {"session": session}, source="agent", trace_id=ctx.trace_id)


def _record(ctx: Context, session: str, summary: str) -> None:
    """Something that can't be undone, such as a command."""
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO activity (time, session, summary) VALUES (?, ?, ?)",
            (datetime.now(UTC).isoformat(), session, summary),
        )
        work.emit("activity.added", {"session": session}, source="agent", trace_id=ctx.trace_id)


def undo(ctx: Context, activity: int) -> str | None:
    """None if it worked, or why it couldn't."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM activity WHERE id = ?", (activity,))
    if not rows or not rows[0]["undo_path"]:
        return "This can't be undone."
    row = rows[0]
    if row["undone"]:
        return "This was already undone."
    path = Path(row["undo_path"])
    if row["undo_existed"]:
        shutil.copy2(row["undo_snapshot"], path)
    else:
        path.unlink(missing_ok=True)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("UPDATE activity SET undone = 1 WHERE id = ?", (activity,))
        work.emit("activity.added", {"undone": activity}, source="agent", trace_id=ctx.trace_id)
    return None


def run_shell(command: str, cwd: Path, timeout: float, control: RunControl) -> str:
    shell = (
        ["powershell", "-NoProfile", "-Command", command]
        if sys.platform == "win32"
        else ["/bin/zsh", "-c", command]
    )
    process = subprocess.Popen(
        shell,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=sys.platform != "win32",
    )
    control.attach(process)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        output, _ = process.communicate()
        return f"{output}\n[Stopped: it ran past the {int(timeout)} second limit.]"
    finally:
        control.attach(None)
    if control.stopped.is_set():
        return f"{output}\n[Stopped by the person.]"
    return f"{output}\n[Exit code {process.returncode}]"


class _Read(BaseModel):
    path: str = Field(description="File to read. Relative paths start in your scratch folder.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Write(BaseModel):
    path: str = Field(description="File to write. Relative paths start in your scratch folder.")
    content: str = Field(description="The file's whole new content.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Edit(BaseModel):
    path: str = Field(description="File to change.")
    old_text: str = Field(description="Exact text to replace. It must appear exactly once.")
    new_text: str = Field(description="What to put there.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Command(BaseModel):
    command: str = Field(description="The shell command to run.")
    why: str = Field(default="", description="One short sentence on why, shown to the person.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Search(BaseModel):
    query: str = Field(description="Words to find in mail and its attachments.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReadThread(BaseModel):
    thread_id: int = Field(description="The conversation's ID, from search results.")
    tool_call_id: Annotated[str, InjectedToolCallId]


def _untrusted(text: str) -> str:
    return f"<untrusted>\n{text}\n</untrusted>"


def build_tools(ctx: Context, session: str, control: RunControl) -> list[StructuredTool]:
    def read_file(path: str, tool_call_id: str) -> str:
        target = _resolve(ctx, session, path)

        def work() -> str:
            return target.read_text("utf-8", errors="replace")

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "read_file",
            "read",
            target,
            f"Read {target}",
            "",
            False,
            work,
        )

    def write_file(path: str, content: str, tool_call_id: str) -> str:
        target = _resolve(ctx, session, path)
        before = target.read_text("utf-8", errors="replace") if target.is_file() else ""
        summary = f"Write {target}"

        def work() -> str:
            _snapshot(ctx, session, target, summary)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, "utf-8")
            return f"Wrote {len(content)} characters to {target}."

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "write_file",
            "write",
            target,
            summary,
            _diff(before, content, target.name),
            True,
            work,
        )

    def edit_file(path: str, old_text: str, new_text: str, tool_call_id: str) -> str:
        target = _resolve(ctx, session, path)
        before = target.read_text("utf-8", errors="replace") if target.is_file() else ""
        after = before.replace(old_text, new_text, 1)
        summary = f"Edit {target}"

        def work() -> str:
            count = target.read_text("utf-8", errors="replace").count(old_text)
            if count != 1:
                return f"Nothing changed: that text appears {count} times, and it must appear exactly once."
            _snapshot(ctx, session, target, summary)
            target.write_text(after, "utf-8")
            return f"Edited {target}."

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "edit_file",
            "write",
            target,
            summary,
            _diff(before, after, target.name),
            True,
            work,
        )

    def run_command(command: str, tool_call_id: str, why: str = "") -> str:
        summary = why or f"Run a command: {command[:80]}"

        def work() -> str:
            _record(ctx, session, f"Ran: {command[:200]}")
            cwd = scratch_folder(ctx.config.home, session)
            return run_shell(command, cwd, ctx.config.agent.command_timeout_seconds, control)

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "run_command",
            "command",
            None,
            summary,
            command,
            False,
            work,
        )

    def search_mail(query: str, tool_call_id: str) -> str:
        def work() -> str:
            account = accounts.current_account(ctx.config)
            hits = store.search(ctx.bus.db, account, SearchMail(query=query, limit=20)).hits
            lines = [
                f"[thread {h.thread.id}] {h.thread.subject} | {', '.join(h.thread.participants[:3])} | {h.excerpt}"
                for h in hits
            ]
            return _untrusted("\n".join(lines) or "Nothing found.")

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "search_mail",
            "read",
            ctx.config.home / "memory",
            f"Search mail: {query}",
            "",
            False,
            work,
            marks_untrusted=True,
        )

    def read_thread(thread_id: int, tool_call_id: str) -> str:
        def work() -> str:
            view = store.thread_view(ctx.bus.db, thread_id)
            if view is None:
                return "That conversation no longer exists."
            recent = view.messages[-ctx.config.agent.max_recent_thread_messages :]
            body = "\n\n".join(
                f"From {m.from_name} <{m.from_addr}> on {m.date}\n{m.own_text}" for m in recent
            )
            skipped = len(view.messages) - len(recent)
            note = f"[{skipped} older messages not shown]\n\n" if skipped else ""
            limit = ctx.config.agent.max_thread_chars
            return _untrusted(f"Subject: {view.thread.subject}\n{note}{body}"[:limit])

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "read_thread",
            "read",
            ctx.config.home / "memory",
            f"Read conversation {thread_id}",
            "",
            False,
            work,
            marks_untrusted=True,
        )

    specs: list[tuple[Callable[..., str], type[BaseModel], str]] = [
        (read_file, _Read, "Read a text file."),
        (write_file, _Write, "Create or replace a text file."),
        (edit_file, _Edit, "Replace one exact piece of text in a file."),
        (run_command, _Command, "Run a shell command in your scratch folder."),
        (search_mail, _Search, "Search the person's mail and attachments."),
        (read_thread, _ReadThread, "Read a mail conversation."),
    ]
    return [
        StructuredTool.from_function(
            func=func, name=func.__name__, description=description, args_schema=schema
        )
        for func, schema, description in specs
    ]
