"""The agent's tools. Every call goes through one door: policy, approval, logging, then the work."""

import contextlib
import difflib
import json
import os
import re
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
from typing import Annotated, Any, Literal, cast

import httpx
import psutil
import structlog
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from nexusai.contracts.documents import DocumentLibrary, DocumentPreview, GetDocument, ListDocuments
from nexusai.contracts.mail import FolderRole, SearchMail, SearchResults
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    briefs,
    bulk_learning,
    cards,
    channel,
    citations,
    mail_agent,
    memory,
    policy,
    prompts_builder,
    signals,
    skills,
    suggestions,
    team,
    work_tools,
)
from nexusai.modules.agent.policy import Action
from nexusai.modules.agent.prompt_data import untrusted
from nexusai.modules.connectors import module as connectors
from nexusai.modules.documents.module import get_document as _get_document
from nexusai.modules.documents.module import list_documents as _list_documents
from nexusai.modules.mail import accounts, store
from nexusai.modules.mail.module import run_search
from nexusai.modules.planner import module as planner
from nexusai.modules.semantic import module as semantic

log = structlog.get_logger()
MAX_LISTED = 500
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
        # Why it stopped, when the harness stopped it rather than the person.
        self.reason: str | None = None
        self._process: subprocess.Popen[str] | None = None

    def attach(self, process: subprocess.Popen[str] | None) -> None:
        self._process = process

    def stop(self) -> None:
        self.stopped.set()
        process = self._process
        if process and process.poll() is None:
            _kill_tree(process)


def _kill_children_too(process: subprocess.Popen[str]) -> None:
    """Without process groups, whatever a command started has to be found and stopped by name."""
    try:
        parent = psutil.Process(process.pid)
        family = [*parent.children(recursive=True), parent]
    except psutil.Error:
        family = []
    for member in family:
        with contextlib.suppress(psutil.Error):
            member.kill()


def _kill_tree(process: subprocess.Popen[str]) -> None:
    try:
        if sys.platform == "win32":
            _kill_children_too(process)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass


# The script comes in on stdin, because Windows caps a command line at about 32,000 characters and
# an agent can write a whole file in one command. Both directions need saying they're UTF-8.
AFTER_STOP_SECONDS = 5
POWERSHELL_RUNNER = (
    "$utf8 = New-Object System.Text.UTF8Encoding $false; "
    "[Console]::InputEncoding = $utf8; [Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
    "Invoke-Expression ([Console]::In.ReadToEnd()); "
    "$ok = $?; if ($LASTEXITCODE) { exit $LASTEXITCODE }; if (-not $ok) { exit 1 }"
)


def _after_stopping(process: subprocess.Popen[str], expired: subprocess.TimeoutExpired) -> str:
    """What it had said so far. Something that escaped can hold its output open, so this gives up."""
    try:
        return process.communicate(timeout=AFTER_STOP_SECONDS)[0]
    except subprocess.TimeoutExpired:
        for stream in (process.stdin, process.stdout):
            with contextlib.suppress(OSError):
                if stream:
                    stream.close()
        partial = expired.output
        return partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial or ""


def shell_command(command: str, windows: bool) -> tuple[list[str], str | None]:
    """How to start a command here, and what to send it on stdin."""
    if windows:
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            POWERSHELL_RUNNER,
        ], command
    return [prompts_builder.posix_shell(), "-c", command], None


def list_documents(query: ListDocuments, ctx: Context) -> DocumentLibrary:
    result = _list_documents(query, ctx)
    assert isinstance(result, DocumentLibrary)
    return result


def get_document(query: GetDocument, ctx: Context) -> DocumentPreview:
    result = _get_document(query, ctx)
    assert isinstance(result, DocumentPreview)
    return result


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
    # Context is pinned when a background run starts; a settings switch must not
    # make its read/search/write tools operate on a different mailbox halfway through.
    source = db.fetch_all(
        "SELECT target,context FROM agent_turns WHERE session=? AND closed=0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if source:
        target = json.loads(source[0]["target"] or "{}")
        run_context = json.loads(source[0]["context"] or "{}")
        account = target.get("account") or run_context.get("account")
        if account and account != accounts.current_account(ctx.config):
            return "Not run: this agent's mail account changed. Switch back to its account and retry; no action was taken."
    kind = f"{tool}:{path.parent if path else ''}"
    # A tool restarts from the top after a decision. A no stands, whatever was allowed since.
    decided = _approval_row(ctx, session, call_id)
    if decided is not None and decided["status"] == "denied":
        _log_call(ctx, session, call_id, tool, detail or summary, DENIED, "denied", "person", 0)
        return DENIED
    permissions = policy.load_permissions(db)
    if permissions.tools.get(tool) == "off":
        reason = "This tool is turned off in Settings."
        _log_call(ctx, session, call_id, tool, detail or summary, reason, "refused", None, 0)
        return f"Not allowed: {reason}"
    untrusted = _is_untrusted(ctx, session)
    granted = policy.allowed_for_session(db, session, kind)
    decision = policy.decide(
        action,
        path=path,
        home=ctx.config.home,
        permissions=policy.for_tool(permissions, tool),
        untrusted=untrusted,
        session_allowed=granted and policy.can_remember(tool, untrusted),
    )
    if decision.verdict == "ask" and granted and untrusted and action != "send":
        # Allowed for the session before it read mail; say why it asks again rather than seem broken.
        decision = policy.Decision(
            "ask", "Asking again: this chat has read mail or documents since you allowed it."
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
    if status in REFUSED:
        _after_refusal(ctx, session)


def record_call(
    ctx: Context, session: str, call_id: str, tool: str, args: dict[str, Any], result: str, ms: int
) -> None:
    """For tools that don't go through approval. Those that do are already recorded."""
    if not call_id or ctx.bus.db.fetch_all(
        "SELECT 1 FROM tool_calls WHERE session = ? AND tool_call_id = ?", (session, call_id)
    ):
        return
    shown = json.dumps(args, default=str)[:2000]
    # A tool that said it did nothing counts as refused, so a run refused again and again stops.
    # Other failures, such as a bad argument, are left for the model to fix.
    status = "refused" if result.startswith(NOTHING_DONE) else "done"
    _log_call(ctx, session, call_id, tool, shown, result[:2000], status, None, ms)


NOTHING_DONE = ("Not sent", "Not done")
REFUSED = frozenset({"refused", "denied"})
# Each live run's stop handle, so a run that keeps being refused can be stopped from its tools.
RUN_CONTROLS: dict[str, "RunControl"] = {}


def _after_refusal(ctx: Context, session: str) -> None:
    """Deny and carry on, until it's clearly stuck: then the run stops and the person is told."""
    db = ctx.bus.db
    turn = db.fetch_all(
        "SELECT created FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if not turn or not turn[0]["created"]:
        return
    statuses = [
        row["status"]
        for row in db.fetch_all(
            "SELECT status FROM tool_calls WHERE session = ? AND started >= ? ORDER BY id DESC",
            (session, turn[0]["created"]),
        )
    ]
    in_a_row = next(
        (i for i, status in enumerate(statuses) if status not in REFUSED), len(statuses)
    )
    total = sum(status in REFUSED for status in statuses)
    limits = ctx.config.team
    if in_a_row < limits.refusals_in_a_row and total < limits.refusals_per_run:
        return
    control = RUN_CONTROLS.get(session)
    if control is None or control.stopped.is_set():
        return
    control.reason = "refusals"
    control.stop()
    with ctx.bus.unit_of_work() as work:
        channel.notify(
            ctx,
            work,
            "An agent was refused too many times, so its run stopped. Check what it was trying to do.",
            "",
            f"/agent/sessions/{session}",
            "agent",
            False,
        )


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
    shell, script = shell_command(command, sys.platform == "win32")
    process = subprocess.Popen(
        shell,
        cwd=cwd,
        stdin=subprocess.PIPE if script is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
    )
    control.attach(process)
    try:
        # Stop may arrive while Popen is still creating the process, before attachment.
        if control.stopped.is_set():
            _kill_tree(process)
        output, _ = process.communicate(input=script, timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        _kill_tree(process)
        output = _after_stopping(process, expired)
        return f"{output}\n[Stopped: it ran past the {int(timeout)} second limit.]"
    finally:
        control.attach(None)
    if control.stopped.is_set():
        return f"{output}\n[Stopped by the person.]"
    return f"{output}\n[Exit code {process.returncode}]"


class _Read(BaseModel):
    path: str = Field(description="File to read. Relative paths start in your scratch folder.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Folder(BaseModel):
    path: str = Field(description="The folder. Relative paths start in your scratch folder.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Move(BaseModel):
    source: str = Field(description="The file now.")
    destination: str = Field(description="Where it should be, including its name.")
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
    query: str = Field(
        default="",
        description='Words to find in mail and its attachments. "Quotes" find an exact phrase.',
    )
    sender: str | None = Field(default=None, description="Part of who it's from: name or address.")
    after: str | None = Field(default=None, description="On or after this date, as YYYY-MM-DD.")
    before: str | None = Field(default=None, description="Before this date, as YYYY-MM-DD.")
    has_attachment: bool | None = Field(default=None, description="Only mail with attachments.")
    folder: Literal["inbox", "sent", "archive"] | None = Field(
        default=None, description="Only this folder. sent is what the person wrote."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


# How many conversations one read_thread call takes. They share one tool output, so each gets less.
MAX_THREADS_PER_READ = 10


class _ReadThread(BaseModel):
    thread_ids: list[int] = Field(
        min_length=1,
        max_length=MAX_THREADS_PER_READ,
        description=f"The conversations' IDs, from a search or list. Up to {MAX_THREADS_PER_READ}.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReadRecipients(BaseModel):
    thread_id: int = Field(description="The conversation's ID.")
    contains: str | None = Field(
        default=None, description="Only addresses containing this, like a name or a domain."
    )
    offset: int = Field(default=0, ge=0, description="Where to read on from in a long list.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _AskUser(BaseModel):
    question: str = Field(description="What you need to know.")
    options: list[str] = Field(
        default_factory=list,
        description="Choices to offer, when a few likely answers exist. They can always type one.",
    )
    multiple: bool = Field(default=False, description="Whether they can pick more than one.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Say(BaseModel):
    text: str = Field(description="What to tell the person, in one or two plain sentences.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Brief(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=6000,
        description="The whole brief in Markdown bullets. It replaces the one on Today.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _BoardWrite(BaseModel):
    kind: str = Field(description="deadline, task, status or note.")
    title: str = Field(description="Short description.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")
    due: str | None = Field(default=None, description="YYYY-MM-DD, if it has a date.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Nothing(BaseModel):
    tool_call_id: Annotated[str, InjectedToolCallId]


class _FindTools(BaseModel):
    query: str = Field(description='A few words for what you need to do, like "save a mail rule".')
    tool_call_id: Annotated[str, InjectedToolCallId]


class _TeamAssign(BaseModel):
    to: str = Field(description="Who does it: an @handle from the team, such as @mail.")
    objective: str = Field(
        min_length=1, max_length=1000, description="What to achieve, in one or two sentences."
    )
    expected_output: str = Field(
        default="",
        max_length=1000,
        description="Optional. What to send back, such as 'the ids of the threads moved and where'.",
    )
    done_criteria: str = Field(
        default="",
        max_length=1000,
        description="Optional. How you'll check it's done, using facts you can look up yourself.",
    )
    references: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Ids to work from, such as 'thread 291' or 'document notes/plan.md'. Never paste mail text.",
    )
    budget_tokens: int | None = Field(
        default=None, ge=1000, description="Tokens it may use. Leave empty for the usual amount."
    )
    due_minutes: int | None = Field(
        default=None, ge=1, le=10080, description="Minutes until it counts as late."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _TeamMessage(BaseModel):
    task: int = Field(description="The task id.")
    kind: Literal["ask", "answer", "note"] = Field(
        description="ask: you're doing the task and need something from whoever gave it. "
        "answer: you gave the task and are answering its question. note: anything else."
    )
    text: str = Field(min_length=1, max_length=4000)
    tool_call_id: Annotated[str, InjectedToolCallId]


class _LoadSkill(BaseModel):
    name: str = Field(description="A skill named in your prompt, such as drafting-replies.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReadSkillFile(BaseModel):
    name: str = Field(description="The skill.")
    path: str = Field(description="One of the files load_skill listed, such as examples.md.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ProposeSkill(BaseModel):
    url: str | None = Field(
        default=None,
        description="An https link the person gave: a SKILL.md, a GitHub folder, or a zip.",
    )
    text: str | None = Field(
        default=None,
        max_length=200_000,
        description="The whole SKILL.md, when the person pasted one or asked you to write one. "
        "Start with --- then name, description and agents lines, then ---, then the steps.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _TeamClose(BaseModel):
    task: int = Field(description="The task id.")
    action: Literal["report", "verify", "reject", "cancel"] = Field(
        description="report: you did it, here's the outcome. verify or reject: you gave it and "
        "checked the report; the first reject sends it back to redo, the next closes it. cancel: "
        "you gave it and it's no longer needed."
    )
    outcome: str = Field(
        default="",
        max_length=8000,
        description="For report: what you did and found. For verify, reject or cancel: why.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Ids that prove it, such as 'thread 291 moved to PLM'.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _PreferenceProposal(BaseModel):
    instruction: str = Field(
        min_length=1,
        max_length=4000,
        description='The lasting instruction, in their words, such as "File PLM mail, never in the inbox".',
    )
    purpose: Literal["all", "mail", "draft", "brief"] = Field(
        "mail", description="What it guides: judging mail, writing drafts, the brief, or all."
    )
    sender: str | None = Field(None, description="Only for mail from this address or domain.")
    topic: str | None = Field(None, description="Only for mail about this topic.")
    evidence: list[str] = Field(
        min_length=1,
        max_length=20,
        description="Where they said it: their exact words from this chat, quoted, or ids from read_feedback.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _Remember(BaseModel):
    facts: list[str] = Field(
        description="Lasting facts about the person, one short line each, such as "
        '"Manager is Priya Nair" or "Wants PLM mail filed, never in the inbox".'
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _TaskProposal(BaseModel):
    title: str = Field(description="What needs doing.")
    due: str | None = Field(default=None, description="YYYY-MM-DD, if it has a date.")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReminderProposal(BaseModel):
    title: str = Field(description="What to remind the person about.")
    when: str = Field(description="YYYY-MM-DDTHH:MM")
    thread_id: int | None = Field(default=None, description="The related conversation, if any.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _DraftReply(BaseModel):
    thread_id: int = Field(description="The conversation to reply in.")
    body: str = Field(description="The reply, as plain text.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _SavePrompt(BaseModel):
    name: str = Field(description="about-me, importance, categories, senders or topics.")
    content: str = Field(
        description="With mode add: only the new lines, in markdown. With mode replace: the "
        "prompt's whole new content."
    )
    mode: Literal["add", "replace"] = Field(
        default="add",
        description="add (default) keeps everything already there and adds new lines. replace "
        "rewrites the whole prompt: use it only when the person changed or removed something.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


def _prompt_line(line: str) -> str:
    """Two lines say the same thing when they differ only in bullets, case and spacing."""
    return " ".join(line.strip().lstrip("-*• ").split()).casefold()


def merge_prompt(existing: str, added: str) -> tuple[str, int]:
    """Existing text stays as it is; only lines it doesn't already say are added, in order."""
    if not existing.strip():
        return added, sum(1 for line in added.splitlines() if line.strip())
    known = {_prompt_line(line) for line in existing.splitlines() if line.strip()}
    new = []
    for line in added.splitlines():
        key = _prompt_line(line)
        if key and key not in known:
            known.add(key)
            new.append(line.rstrip())
    if not new:
        return existing, 0
    base = existing.rstrip("\n")
    return (f"{base}\n" if base else "") + "\n".join(new) + "\n", len(new)


def removed_lines(existing: str, replacement: str) -> list[str]:
    kept = {_prompt_line(line) for line in replacement.splitlines() if line.strip()}
    return [
        line.strip()
        for line in existing.splitlines()
        if line.strip() and _prompt_line(line) not in kept
    ]


class _SearchDocuments(BaseModel):
    query: str = Field(description="Words to find in documents.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReadDocument(BaseModel):
    key: str = Field(description="The document's key, from search results.")
    tool_call_id: Annotated[str, InjectedToolCallId]


MAX_DETAIL_CHARS = 4000


class _RecommendMail(BaseModel):
    category: str = Field(description="Where this mail should go, a short name.")
    senders: list[str] = Field(description="The exact sender addresses, from the list you have.")
    reason: str = Field(description="One plain sentence for the person. Don't add up totals.")
    quiet: bool = Field(
        default=False, description="True only for mail they plainly never read or reply to."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _RecommendPriority(BaseModel):
    category: str = Field(description="The category, as it's written in your list.")
    reason: str = Field(description="One plain sentence for the person. Don't add up totals.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _FoldSuggestions(BaseModel):
    keep: str = Field(description="The suggested category to keep, as it's written.")
    names: list[str] = Field(description="Suggested categories that mean the same, to fold in.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _LearningAnswers(BaseModel):
    answers: list[dict[str, str]] = Field(
        max_length=100,
        description="One item per explicit answer, with id and importance (low/normal/high). Copy the supplied short ids, such as q1, exactly.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _RecordTriage(BaseModel):
    confidence: Literal["high", "medium", "low"] = "medium"
    review_reason: str | None = Field(default=None, max_length=500)
    source_messages: list[int] = Field(
        default_factory=list,
        description="Message IDs actually read from this conversation. Never invent IDs.",
    )
    category: str | None = Field(
        default=None, description="An existing Smart folder name, or null."
    )
    smart_folders: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Zero or more existing Smart folder names. Never invent a folder.",
    )
    groups: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=30,
        description="For a grouped learning run only: one result per supplied group id, with id, note, importance, uncertain and optional folder {name, mode, description}.",
    )
    importance: Literal["low", "normal", "high"] = "normal"
    status: Literal["waiting_on_you", "waiting_on_others", "resolved", "fyi"] = "fyi"
    next_action: Literal["reply", "do", "decide", "read", "none"] = "none"
    follow_up_on: str | None = Field(
        default=None, description="With waiting_on_others, when to chase it, as YYYY-MM-DD."
    )
    notify: bool | None = Field(
        default=None, description="True only when it can't wait until they next look."
    )
    summary: str = Field(default="", description="One plain sentence on what this is.")
    reason: str = Field(
        default="", description="One plain sentence on what this judgement rests on."
    )
    facts: list[str] = Field(
        default_factory=list, description="Key facts, like deadlines or amounts."
    )
    suggested_action: str | None = Field(default=None, description="One short sentence.")
    deadlines: list[dict[str, Any]] = Field(
        default_factory=list, description='As {"what": ..., "due": "YYYY-MM-DD"}.'
    )
    tasks: list[dict[str, Any]] = Field(
        default_factory=list,
        description='What the person should do, as {"title": ..., "due": "YYYY-MM-DD" or null}.',
    )
    reminders: list[dict[str, Any]] = Field(
        default_factory=list, description='As {"title": ..., "when": "YYYY-MM-DDTHH:MM"}.'
    )
    draft: str | None = Field(default=None, description="A suggested reply as plain text.")
    memory: str | None = Field(default=None, description="A lasting fact about their work.")
    learned: list[str] = Field(
        default_factory=list,
        description="Short notes on anything lasting this shows about the person. Usually empty.",
    )
    suggest_category: dict[str, Any] | None = Field(
        default=None,
        description='For repeated mail from one place, {"name": ..., "sender": ..., "reason": ...}.',
    )
    question: str | None = Field(default=None, description="Something only the person can answer.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _SaveLearned(BaseModel):
    summary: str = Field(description="What you've learned about the person, in short sections.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ConnectorArguments(BaseModel):
    """Whatever the server asks for. It checks them itself, and the model sees its own schema."""

    model_config = ConfigDict(extra="allow")

    tool_call_id: Annotated[str, InjectedToolCallId]


# The Mail agent reads, proposes and drafts, even when the person types to it. Nothing here can
# send, change files or run commands, since what it reads comes from anyone who can email them.
MAIL_AGENT_TOOLS = frozenset(
    {
        "record_triage",
        "search_mail",
        "read_thread",
        "read_recipients",
        "list_mail",
        "semantic_search",
        "search_documents",
        "read_document",
        "list_documents",
        "read_work_board",
        "write_work_board",
        "team_roster",
        "team_inbox",
        "team_message",
        "team_close",
        "find_tools",
        "load_skill",
        "read_skill_file",
        "read_feedback",
        "propose_preference",
        "list_categories",
        "list_tasks",
        "list_reminders",
        "list_memory",
        "propose_task",
        "propose_reminder",
        "remember",
        "draft_reply",
        "suggest",
        "tell",
        "notify_person",
    }
)
# Judging one email takes only these, so every other tool's description isn't sent each time.
TRIAGE_TOOLS = frozenset(
    {
        "record_triage",
        "search_mail",
        "read_thread",
        "read_recipients",
        "semantic_search",
        "read_work_board",
        "read_document",
    }
)
# As many as the agent can use at once. It narrows the search for more.
SEARCH_SHOWN = 20
REVIEW_ORIGIN = "mail-review"
# It ends a run, so judging simple mail takes one model call.
ENDS_THE_RUN = frozenset({"record_triage"})
LEARNING_ORIGIN = "mail-learn"
MAIL_AGENT_ONLY = frozenset(
    {
        "record_triage",
        "save_what_i_learned",
        "recommend_mail_change",
        "fold_suggested_categories",
        "recommend_priority",
    }
)


# The brief agent reads and searches, then writes the brief. Nothing else is its job.
BRIEF_TOOLS = frozenset(
    {
        "read_plate",
        "update_brief",
        "read_thread",
        "read_recipients",
        "search_mail",
        "semantic_search",
        "list_mail",
        "list_tasks",
        "list_reminders",
        "read_work_board",
        "draft_reply",
        "read_feedback",
        "remember",
        "list_memory",
        "team_inbox",
        "team_message",
        "team_close",
    }
)
BRIEF_AGENT_ONLY = frozenset({"read_plate", "update_brief"})


# The Organizer keeps tasks and reminders. It reads mail only to link and date what it adds.
ORGANIZER_TOOLS = frozenset(
    {
        "list_tasks",
        "create_tasks",
        "update_tasks",
        "delete_tasks",
        "list_reminders",
        "create_reminders",
        "update_reminders",
        "delete_reminders",
        "search_mail",
        "read_thread",
        "read_work_board",
        "remember",
        "list_memory",
        "team_inbox",
        "team_message",
        "team_close",
    }
)
# Making and changing tasks and reminders is the Organizer's work, so the lead hands it over.
ORGANIZER_ONLY = frozenset(
    {
        "create_tasks",
        "update_tasks",
        "delete_tasks",
        "create_reminders",
        "update_reminders",
        "delete_reminders",
        "propose_task",
        "propose_reminder",
    }
)


INTERVIEW_TOOLS = frozenset(
    {
        "ask_user",
        "save_personal_prompt",
        "apply_mail_learning_answers",
        "remember",
        "list_memory",
        "read_work_board",
        "read_thread",
        "read_recipients",
        "search_mail",
        "semantic_search",
        "list_categories",
        "read_feedback",
    }
)


# Tool search. Each tool's description is sent with every model call, so an agent is shown the
# ones it uses most and finds the rest with find_tools. Memory is always at hand for every agent.
ALWAYS_SHOWN = frozenset({"ask_user", "remember", "list_memory", "load_skill"})
# What session.md has it reach for first is shown, so a smaller model needn't search for its steps:
# the work board, documents, and every list it checks before making something.
LEAD_SHOWN = ALWAYS_SHOWN | {
    "read_work_board", "search_mail", "semantic_search", "search_documents", "read_thread",
    "list_mail", "update_mail", "draft_reply", "list_drafts",
    "list_tasks", "list_reminders", "list_categories",
    "list_rules", "list_agents", "list_panels", "propose_preference",
    "team_assign", "team_inbox", "team_message", "team_close",
}  # fmt: skip
MAIL_SHOWN = ALWAYS_SHOWN | {
    "search_mail", "semantic_search", "read_thread", "read_recipients", "list_mail",
    "read_work_board", "update_mail", "draft_reply", "propose_task", "propose_reminder",
    "team_inbox", "team_message", "team_close", "tell",
}  # fmt: skip
FOUND_SHOWN = 5
CONNECTOR_PREFIX = connectors.PREFIX


def shown_for(agent: str, has_email: bool) -> frozenset[str] | None:
    """The tools a run starts with. None shows every allowed tool: small sets, or when it's off."""
    if os.environ.get("NEXUSAI_TOOL_SEARCH") == "off" or agent == "interview":
        return None
    if agent == "mail":
        return None if has_email else MAIL_SHOWN
    # Their whole sets are small enough to show.
    return None if agent in {"daily-prep", "organizer"} else LEAD_SHOWN


def other_tools(all_names: list[str], shown: frozenset[str] | None) -> str:
    """The names of the tools a run has but doesn't start with, grouped by what they act on.

    Only names, so it costs little; without it a small model never knows to look, and says it
    can't delete a task it has a tool for."""
    if shown is None:
        return ""
    hidden = sorted(
        name
        for name in all_names
        if name not in shown and name != "find_tools" and not name.startswith(CONNECTOR_PREFIX)
    )
    if not hidden:
        return ""

    def topic(name: str) -> str:
        # One group for "update_category" and "delete_categories".
        word = name.rsplit("_", 1)[-1]
        if word.endswith("ies"):
            return word[:-3] + "y"
        return word[:-1] if word.endswith("s") and not word.endswith("ss") else word

    groups: dict[str, list[str]] = {}
    for name in hidden:
        groups.setdefault(topic(name), []).append(name)
    lines = [f"- {topic}: {', '.join(names)}" for topic, names in sorted(groups.items())]
    return (
        "Yours too, not loaded yet. Load one with find_tools, naming it, before you use it.\n"
        + "\n".join(lines)
    )


def find(catalog: list[StructuredTool], query: str, shown: int = FOUND_SHOWN) -> str:
    """Tools by the words they share with the query, name words counting most."""
    words = set(re.findall(r"[a-z]{3,}", query.lower()))
    scored = []
    for tool in catalog:
        if tool.name == "find_tools":
            continue
        name = set(re.findall(r"[a-z]{3,}", tool.name.replace("_", " ").lower()))
        text = set(re.findall(r"[a-z]{3,}", tool.description.lower()))
        # "reminders" should find create_reminders when someone writes "reminder".
        stems = {w.rstrip("s") for w in words}
        score = 3 * len(stems & {w.rstrip("s") for w in name}) + len(
            stems & {w.rstrip("s") for w in text}
        )
        if score:
            scored.append((score, tool))
    scored.sort(key=lambda item: -item[0])
    lines = [
        f"- {tool.name}: {tool.description.split('. ')[0].rstrip('.')}."
        for _, tool in scored[:shown]
    ]
    names = ", ".join(sorted(tool.name for tool in catalog if tool.name != "find_tools"))
    if not lines:
        return f"No tool matches that. Every tool you have: {names}. Search again with its words."
    return "You can use these from your next step:\n" + "\n".join(lines)


def withheld_for(agent: str) -> frozenset[str]:
    """Tools another agent owns, kept from one that would otherwise have them all."""
    return ORGANIZER_ONLY if agent == "session" else frozenset()


def owners_of_withheld(db: Any, agent: str) -> dict[str, str]:
    """Each withheld tool's owner, by @handle, so a call to one is pointed the right way."""
    found = cards.card(db, "organizer")
    return {name: found.at for name in withheld_for(agent)} if found else {}


def allowed_for(agent: str, origin: str, has_email: bool) -> frozenset[str] | None:
    """None means every tool. Only someone typing can answer a question straight away, and
    there's only a judgement to record when the run was started for an email."""
    if agent == "interview":
        return INTERVIEW_TOOLS
    if agent == "daily-prep":
        return BRIEF_TOOLS | {"ask_user"} if origin == "person" else BRIEF_TOOLS
    if agent == "organizer":
        return ORGANIZER_TOOLS | {"ask_user"} if origin == "person" else ORGANIZER_TOOLS
    if agent != "mail":
        return None
    if has_email:
        return TRIAGE_TOOLS
    allowed = MAIL_AGENT_TOOLS | {"ask_user"} if origin == "person" else MAIL_AGENT_TOOLS
    # A task from another agent may be filing mail. Every change still asks the person first,
    # because this agent reads mail anyone can send.
    if origin == team.TASK_ORIGIN:
        allowed |= {"update_mail"}
    # Only the run that wraps up reading past mail can rewrite what it learned.
    if origin == LEARNING_ORIGIN:
        allowed |= {"save_what_i_learned"}
    if origin in {REVIEW_ORIGIN, "person"}:
        allowed |= {"recommend_mail_change", "fold_suggested_categories", "recommend_priority"}
    return allowed - {"record_triage"}


def _plain_words(text: str) -> str:
    """Words alone, without a "User:" label, quote marks, case or punctuation."""
    text = re.sub(r"^\s*(user|person|they said)\s*:\s*", "", text, flags=re.I)
    return " ".join(re.findall(r"[\w@.-]+", text.casefold()))


def _untrusted(text: str) -> str:
    return untrusted(text)


def _meaning_is_on() -> bool:
    """Skipping its model means this isn't offered, so the agent doesn't plan around it."""
    engine = semantic.engine()
    try:
        return engine is not None and engine.is_ready()
    except Exception:
        # Closing while Home switches or the app restarts: offer keyword search only.
        return False


def _connector_tool(ctx: Context, session: str, tool: connectors.AgentTool) -> StructuredTool:
    def use(tool_call_id: str, **arguments: Any) -> str:
        def work() -> str:
            return _untrusted(connectors.call(ctx, tool, arguments))

        return _guarded(
            ctx,
            session,
            tool_call_id,
            tool.id,
            "data",
            None,
            # Real values go to the server, so it matters more when someone else runs it.
            f"Use {tool.name} from {tool.connector_name}"
            + (", which someone outside your company runs" if tool.audience == "public" else ""),
            json.dumps(arguments, indent=1)[:MAX_DETAIL_CHARS],
            False,
            work,
            marks_untrusted=True,
        )

    return StructuredTool.from_function(
        func=use,
        name=tool.id,
        description=f"From the {tool.connector_name} connector. {tool.description}",
        args_schema=_ConnectorArguments,
        metadata={"parameters": tool.parameters},
    )


def _connector_tools(ctx: Context, session: str) -> list[StructuredTool]:
    """Anything turned off isn't offered, so the model doesn't plan around it."""
    settings = policy.load_permissions(ctx.bus.db).tools
    return [
        _connector_tool(ctx, session, tool)
        for tool in connectors.agent_tools(ctx)
        if settings.get(tool.id) != "off"
    ]


def build_tools(
    ctx: Context,
    session: str,
    control: RunControl,
    allowed: frozenset[str] | None = None,
    withheld: frozenset[str] = frozenset(),
) -> list[StructuredTool]:
    RUN_CONTROLS[session] = control

    def apply_mail_learning_answers(answers: list[dict[str, str]], tool_call_id: str) -> str:
        given = {
            str(answer.get("id", "")): str(answer.get("importance", ""))
            for answer in answers
            if isinstance(answer, dict)
        }
        importance, unknown = bulk_learning.interview_answers(ctx, session, given)

        def work() -> str:
            if unknown:
                return f"Unknown ids: {', '.join(unknown)}. Use only the supplied ids, such as q1. Nothing was saved."
            reviews = ctx.bus.db.fetch_all(
                "SELECT account FROM mail_learning_reviews WHERE interview=? AND state='asking'",
                (session,),
            )
            if not reviews:
                return "There is no active mail learning interview in this conversation."
            turns = ctx.bus.db.fetch_all(
                "SELECT origin FROM agent_turns WHERE session=? ORDER BY id DESC LIMIT 1",
                (session,),
            )
            if not turns or turns[0]["origin"] != "person":
                return "Wait for the person to answer before changing learned guesses."
            bulk_learning.save_answers(ctx, reviews[0]["account"], importance)
            return "Saved the person's answers. They can continue from the mail learning card on Today."

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "apply_mail_learning_answers",
            "data",
            None,
            "Apply your answers to uncertain mail groups",
            json.dumps(importance),
            False,
            work,
        )

    def record_triage(tool_call_id: str, **fields: Any) -> str:
        result = mail_agent.record(ctx, session, fields)
        _log_call(
            ctx,
            session,
            tool_call_id,
            "record_triage",
            fields.get("summary") or "",
            result,
            "done",
            None,
            0,
        )
        return result

    def recommend_mail_change(
        category: str, senders: list[str], reason: str, tool_call_id: str, quiet: bool = False
    ) -> str:
        result = suggestions.add(ctx, category, senders, reason, quiet)
        _log_call(
            ctx, session, tool_call_id, "recommend_mail_change", category, result, "done", None, 0
        )
        return result

    def recommend_priority(category: str, reason: str, tool_call_id: str) -> str:
        result = mail_agent.suggest_priority(ctx, category, reason)
        _log_call(
            ctx, session, tool_call_id, "recommend_priority", category, result, "done", None, 0
        )
        return result

    def fold_suggested_categories(keep: str, names: list[str], tool_call_id: str) -> str:
        result = mail_agent.fold_suggestions(ctx, keep, names)
        _log_call(
            ctx, session, tool_call_id, "fold_suggested_categories", keep, result, "done", None, 0
        )
        return result

    def save_what_i_learned(summary: str, tool_call_id: str) -> str:
        memory.replace_learned(ctx.config.home, summary)
        with ctx.bus.unit_of_work() as work:
            work.emit("memory.changed", {}, source="agent", trace_id=ctx.trace_id)
        _log_call(
            ctx,
            session,
            tool_call_id,
            "save_what_i_learned",
            summary[:200],
            "Saved.",
            "done",
            None,
            0,
        )
        return "Saved. The person can read and correct it on the Memory page."

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

    def list_folder(path: str, tool_call_id: str) -> str:
        target = _resolve(ctx, session, path)

        def work() -> str:
            if not target.is_dir():
                return f"{target} isn't a folder."
            entries = sorted(target.iterdir(), key=lambda item: item.name.lower())
            return (
                "\n".join(
                    f"{entry.name}{'/' if entry.is_dir() else ''}" for entry in entries[:MAX_LISTED]
                )
                or "Empty."
            )

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "list_folder",
            "read",
            target,
            f"List {target}",
            "",
            False,
            work,
        )

    def move_file(source: str, destination: str, tool_call_id: str) -> str:
        origin = _resolve(ctx, session, source)
        target = _resolve(ctx, session, destination)
        summary = f"Move {origin} to {target}"

        def work() -> str:
            if not origin.exists():
                return f"{origin} doesn't exist."
            if target.exists():
                return f"Not moved: {target} already exists."
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origin), str(target))
            return f"Moved to {target}."

        # Both ends have to be allowed, so a file can't be walked out of where it may be written.
        check = policy.decide(
            "write",
            path=origin,
            home=ctx.config.home,
            permissions=policy.for_tool(policy.load_permissions(ctx.bus.db), "move_file"),
            untrusted=_is_untrusted(ctx, session),
        )
        if check.verdict == "deny":
            return f"Not allowed: {check.reason}"
        return _guarded(
            ctx, session, tool_call_id, "move_file", "write", target, summary, "", False, work
        )

    def delete_file(path: str, tool_call_id: str) -> str:
        target = _resolve(ctx, session, path)
        summary = f"Delete {target}"

        def work() -> str:
            if not target.is_file():
                return f"{target} isn't a file."
            _snapshot(ctx, session, target, summary)
            target.unlink()
            return f"Deleted {target}."

        return _guarded(
            ctx, session, tool_call_id, "delete_file", "write", target, summary, "", True, work
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

    def search_mail(
        tool_call_id: str,
        query: str = "",
        sender: str | None = None,
        after: str | None = None,
        before: str | None = None,
        has_attachment: bool | None = None,
        folder: FolderRole | None = None,
    ) -> str:
        def work() -> str:
            wanted = SearchMail(
                query=query,
                limit=SEARCH_SHOWN,
                sender=sender,
                date_from=after,
                date_to=before,
                has_attachment=has_attachment,
                folder=folder,
            )
            found = cast(SearchResults, run_search(wanted, ctx))
            for hit in found.hits:
                citations.note(ctx.bus.db, session, citations.MAIL, str(hit.thread.id))
            lines = [
                f"[thread {h.thread.id}] {h.thread.last_date[:10]} | {h.thread.subject}"
                f" | {', '.join(h.thread.participants[:3])}"
                f"{' | ' + h.thread.category if h.thread.category else ''}"
                f"{' | related in meaning, not these words' if h.matched_by == 'meaning' else ''}"
                f" | {h.excerpt}"
                for h in found.hits
            ]
            if found.corrected:
                lines.insert(
                    0, f"Nothing matched as typed, so this searched for: {found.corrected}"
                )
            if len(found.hits) == SEARCH_SHOWN:
                lines.append("There may be more. Narrow it with sender, after or before.")
            return _untrusted(
                "\n".join(lines)
                or "Nothing has these words. Try fewer words, or semantic_search for the topic."
            )

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

    def read_recipients(
        thread_id: int, tool_call_id: str, contains: str | None = None, offset: int = 0
    ) -> str:
        def work() -> str:
            return _untrusted(signals.read_recipients(ctx, thread_id, contains, offset))

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "read_recipients",
            "read",
            ctx.config.home / "memory",
            f"Read who conversation {thread_id} went to",
            "",
            False,
            work,
            marks_untrusted=True,
        )

    def read_thread(thread_ids: list[int], tool_call_id: str) -> str:
        ids = list(dict.fromkeys(thread_ids))[:MAX_THREADS_PER_READ]

        def work() -> str:
            # One tool output holds them all, so each conversation gets an equal share of it.
            share = min(
                ctx.config.agent.max_thread_chars,
                ctx.config.agent.max_tool_output_chars // len(ids) - 100,
            )
            return _untrusted("\n\n---\n\n".join(_thread_text(thread, share) for thread in ids))

        def _thread_text(thread_id: int, budget: int) -> str:
            view = store.thread_view(ctx.bus.db, thread_id)
            if view is None:
                return f"Conversation {thread_id} no longer exists."
            citations.note(ctx.bus.db, session, citations.MAIL, str(thread_id), opened=True)
            recent = view.messages[-ctx.config.agent.max_recent_thread_messages :]
            attachments = [
                f"- {a.filename}: read_document key m:{m.id}:{a.index}"
                for m in recent
                for a in m.attachments
                if a.kind in {"attachment", "calendar"}
            ]
            manifest = (
                "Attachments (use read_document to read their extracted contents):\n"
                + "\n".join(attachments)
                + "\n\n"
                if attachments
                else ""
            )
            head = f"Conversation {thread_id}\nSubject: {view.thread.subject}\n{manifest}"
            # The newest messages matter most, so when space runs out the oldest go first.
            kept: list[str] = []
            room = budget - len(head)
            for message in reversed(recent):
                text = f"From {message.from_name} <{message.from_addr}> on {message.date}\n{message.own_text}"
                if kept and len(text) > room:
                    break
                kept.insert(0, text[: max(room, 0)])
                room -= len(text) + 2
            skipped = len(view.messages) - len(kept)
            note = f"[{skipped} older messages not shown]\n\n" if skipped else ""
            return f"{head}{note}" + "\n\n".join(kept)

        summary = (
            f"Read conversation {ids[0]}"
            if len(ids) == 1
            else f"Read {len(ids)} conversations: {', '.join(map(str, ids))}"
        )
        return _guarded(
            ctx,
            session,
            tool_call_id,
            "read_thread",
            "read",
            ctx.config.home / "memory",
            summary,
            "",
            False,
            work,
            marks_untrusted=True,
        )

    def ask_user(
        question: str,
        tool_call_id: str,
        options: list[str] | None = None,
        multiple: bool = False,
    ) -> str:
        """Waits for the answer. Other work carries on meanwhile."""
        # By call, because the same question can fairly be asked twice.
        row = ctx.bus.db.fetch_all(
            "SELECT id, status, answer FROM channel_messages WHERE session = ? AND tool_call = ?",
            (session, tool_call_id),
        )
        if row and row[0]["status"] == "answered":
            return f"They answered: {row[0]['answer']}"
        if row and row[0]["status"] == "dismissed":
            return "They skipped this. Use your best judgement, and say what you assumed."
        identifier = (
            row[0]["id"]
            if row
            else channel.post(
                ctx,
                "ask",
                "Session",
                question,
                session=session,
                options=options or [],
                multiple=multiple,
                tool_call=tool_call_id,
            )
        )
        answer = interrupt({"channel": identifier, "tool_call_id": tool_call_id})
        return f"They answered: {answer}"

    def suggest(text: str, tool_call_id: str) -> str:
        channel.post(ctx, "suggest", "Session", text, session=session)
        return "Posted."

    def tell(text: str, tool_call_id: str) -> str:
        channel.post(ctx, "tell", "Session", text, session=session)
        return "Posted."

    def read_plate(tool_call_id: str) -> str:
        return mail_agent.brief_task(ctx)

    def update_brief(text: str, tool_call_id: str) -> str:
        return briefs.save(ctx, session, text)

    def notify_person(text: str, tool_call_id: str) -> str:
        with ctx.bus.unit_of_work() as work:
            channel.notify(ctx, work, text, "", f"/agent/sessions/{session}", "agent", False)
        return "Sent."

    def read_work_board(tool_call_id: str) -> str:
        items = channel.board(ctx.bus.db).items
        return (
            "\n".join(
                f"{i.kind}: {i.title} (thread {i.thread}, due {i.due}, by {i.by})" for i in items
            )
            or "The board is empty."
        )

    def write_work_board(
        kind: str,
        title: str,
        tool_call_id: str,
        thread_id: int | None = None,
        due: str | None = None,
    ) -> str:
        channel.board_add(ctx, kind, title, thread_id, due, "Session")
        return "Added."

    def _speaker() -> str:
        """Who is talking in this run: the turn's own agent, or the chat's."""
        rows = ctx.bus.db.fetch_all(
            "SELECT t.agent AS turn_agent, s.agent FROM agent_sessions s LEFT JOIN agent_turns t"
            " ON t.session = s.id AND t.closed = 0 WHERE s.id = ? ORDER BY t.id DESC LIMIT 1",
            (session,),
        )
        return str(rows[0]["turn_agent"] or rows[0]["agent"]) if rows else ""

    def _speaker_name() -> str:
        found = cards.card(ctx.bus.db, _speaker())
        return found.name if found else "Session"

    def _reads_task(text: str, flagged: bool) -> str:
        # A task built from mail is data. Reading it makes this run untrusted too.
        if flagged:
            _mark_untrusted(ctx, session)
        return _untrusted(text) if flagged else text

    def load_skill(name: str, tool_call_id: str) -> str:
        return skills.load(ctx, session, _speaker(), name)

    def read_skill_file(name: str, path: str, tool_call_id: str) -> str:
        return skills.read_file(ctx, _speaker(), name, path)

    def propose_skill(tool_call_id: str, url: str | None = None, text: str | None = None) -> str:
        def made(files: dict[str, str], source: str) -> str:
            try:
                found = skills.propose(ctx, files, source, _speaker())
            except CommandError as error:
                return f"Not proposed: {error.message}"
            warned = f" It has {len(found.flags)} things to check." if found.flags else ""
            return (
                f"Proposed skill {found.name}.{warned} It does nothing until the person reads it "
                "and approves it on the Agent channel page, under Skills. Tell them so."
            )

        if text and not url:
            return made({skills.ENTRY: text}, "written in chat")
        if not url:
            return "Give the link the person shared, or the whole SKILL.md as text."

        def work() -> str:
            try:
                files = skills.fetch(url)
            except CommandError as error:
                return f"Not fetched: {error.message}"
            except httpx.HTTPError as error:
                return f"Not fetched: {type(error).__name__}. Check the link and the network."
            return made(files, url)

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "propose_skill",
            "send",
            None,
            f"Fetch a skill from {url}",
            f"{url}\n\nWhat comes back is only a proposal. You review it before it's used.",
            False,
            work,
        )

    def team_roster(tool_call_id: str) -> str:
        return team.roster(ctx, lambda _session: True)

    def team_inbox(tool_call_id: str) -> str:
        speaker = _speaker()
        flagged = bool(
            ctx.bus.db.fetch_all(
                "SELECT 1 FROM team_tasks WHERE (owner = ? OR assigner = ?) AND untrusted = 1"
                " AND state NOT IN ('verified','rejected','failed','canceled') LIMIT 1",
                (speaker, speaker),
            )
        )
        return _reads_task(team.inbox(ctx.bus.db, speaker), flagged)

    def team_assign(
        to: str,
        objective: str,
        tool_call_id: str,
        expected_output: str = "",
        done_criteria: str = "",
        references: list[str] | None = None,
        budget_tokens: int | None = None,
        due_minutes: int | None = None,
    ) -> str:
        given = team.assign(
            ctx,
            session=session,
            sender=_speaker(),
            to=to,
            objective=objective,
            # A small model gets the objective right and the rest wrong, so these have defaults.
            expected_output=expected_output.strip() or team.DEFAULT_OUTPUT,
            done_criteria=done_criteria.strip() or team.DEFAULT_DONE,
            references=references or [],
            budget_tokens=budget_tokens,
            due_minutes=due_minutes,
            tool_call=tool_call_id,
        )
        return team.await_result(ctx, given, ctx.config.team.assign_wait_seconds, control.stopped)

    def team_message(task: int, kind: str, text: str, tool_call_id: str) -> str:
        said = team.message(
            ctx, session=session, sender=_speaker(), task=task, kind=kind, text=text
        )
        if not said.startswith("Answered."):
            return said
        # As after a hand-over: a quick finish comes back here, so the giver doesn't act meanwhile.
        news = team.wait_for(ctx, task, ctx.config.team.assign_wait_seconds, control.stopped)
        return f"{said}\n{news}" if news else said

    def team_close(
        task: int,
        action: str,
        tool_call_id: str,
        outcome: str = "",
        evidence: list[str] | None = None,
    ) -> str:
        return team.close(
            ctx,
            session=session,
            sender=_speaker(),
            task=task,
            action=action,
            outcome=outcome,
            evidence=evidence or [],
        )

    def read_feedback(tool_call_id: str) -> str:
        from nexusai.modules.mail import accounts

        rows = ctx.bus.db.fetch_all(
            "SELECT id,time,action,artifact,artifact_id,new_value FROM interaction_events WHERE actor='person' AND (account=? OR account IS NULL) ORDER BY time DESC LIMIT 30",
            (accounts.current_account(ctx.config),),
        )
        return _untrusted(json.dumps([dict(r) for r in rows]))

    def propose_preference(
        instruction: str,
        evidence: list[str],
        tool_call_id: str,
        purpose: str = "mail",
        sender: str | None = None,
        topic: str | None = None,
    ) -> str:
        from nexusai.contracts.agent import SavePreference
        from nexusai.modules.agent import personalization
        from nexusai.modules.mail import accounts

        account = accounts.current_account(ctx.config)
        rows = ctx.bus.db.fetch_all(
            "SELECT id FROM interaction_events WHERE actor='person' AND (account=? OR account IS NULL)",
            (account,),
        )
        valid = {row["id"] for row in rows}
        # The person's own messages in this chat count as evidence, quoted. Mail and tool output
        # never do, so nothing read in an email can become a preference.
        said = _plain_words(
            " ".join(
                row["text"]
                for row in ctx.bus.db.fetch_all(
                    "SELECT text FROM agent_turns WHERE session = ? AND origin = 'person'",
                    (session,),
                )
            )
        )
        quoted = [item for item in evidence if item not in valid]
        if not evidence or not all(
            len(_plain_words(item)) >= 8 and _plain_words(item) in said for item in quoted
        ):
            return (
                "Not saved: evidence must be the person's own words from this chat, quoted "
                "exactly, or ids from read_feedback. For a fact rather than a rule, use remember."
            )
        proposal = SavePreference.model_validate(
            dict(
                purpose=purpose,
                account=account,
                sender=sender,
                topic=topic,
                instruction=instruction,
                evidence=evidence,
            )
        )
        item = personalization.save(ctx, proposal, proposed=True)
        return f"Proposed preference {item.id}. It will affect prompts only after the person approves it."

    def remember(facts: list[str], tool_call_id: str) -> str:
        untrusted = _is_untrusted(ctx, session)
        new, known = memory.remember_facts(
            ctx.config.home, ctx.bus.db, _speaker_name(), facts, untrusted,
            f"/agent/sessions/{session}",
        )  # fmt: skip
        with ctx.bus.unit_of_work() as run:
            run.emit("memory.changed", {}, source="agent", trace_id=ctx.trace_id)
        # Exactly what was kept, so the agent can tell the person in their own words.
        said = f"\nAlready known: {'; '.join(known)}." if known else ""
        if not new:
            return f"Nothing new: already known: {'; '.join(known)}."
        listed = "; ".join(new)
        if untrusted:
            return (
                f"Proposed, waiting for the person to approve in Prompts and memory, because this "
                f"conversation read mail or other outside text: {listed}.{said}"
            )
        return f"Saved to memory: {listed}.{said}"

    def propose_task(
        title: str, tool_call_id: str, due: str | None = None, thread_id: int | None = None
    ) -> str:
        if planner.has_task(ctx.bus.db, title, thread_id):
            return "Not proposed: a task about this already exists. Check list_tasks."
        planner.add_task(ctx, title, due, thread_id, "agent", True)
        return "Proposed. The person accepts it in Tasks."

    def propose_reminder(
        title: str, when: str, tool_call_id: str, thread_id: int | None = None
    ) -> str:
        planner.add_reminder(ctx, title, when[:16], "none", thread_id, None, "agent", True)
        return "Proposed. The person accepts it in Reminders."

    def draft_reply(thread_id: int, body: str, tool_call_id: str) -> str:
        rows = ctx.bus.db.fetch_all(
            "SELECT id, from_addr, subject FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1",
            (thread_id,),
        )
        if not rows:
            return "That conversation no longer exists."
        subject = rows[0]["subject"]
        draft = {
            "thread_id": thread_id,
            "reply_to_message_id": rows[0]["id"],
            "to": [{"name": "", "address": rows[0]["from_addr"]}],
            "cc": [],
            "bcc": [],
            "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
            "body": body,
            "source": "agent",
        }
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO mail_drafts (body, updated) VALUES (?, ?)",
                (json.dumps(draft), datetime.now(UTC).isoformat()),
            )
            work.emit("drafts.changed", {}, source="agent", trace_id=ctx.trace_id)
        return "Saved as a draft. Nothing was sent. The person reviews it in Drafts."

    def save_personal_prompt(name: str, content: str, tool_call_id: str, mode: str = "add") -> str:
        if not name.replace("-", "").isalnum():
            return "Not saved: that isn't a valid name."
        folder = ctx.config.home / "prompts" / "personal"
        path = folder / f"{name}.md"
        existing = path.read_text("utf-8") if path.exists() else ""
        # Adding is the default: a save used to replace the whole prompt, so a few new rules
        # silently wiped everything the person had before.
        if mode == "replace":
            result, added = content, 0
            removed = removed_lines(existing, content)
        else:
            result, added = merge_prompt(existing, content)
            removed = []
        if result == existing:
            return f"Nothing to save: {name} already says all of that."
        if mode == "replace":
            change = f"Replaces {name}" + (
                f", removing {len(removed)} line{'s' if len(removed) != 1 else ''}: "
                + "; ".join(removed[:10])
                if removed
                else ""
            )
        else:
            change = f"Adds {added} line{'s' if added != 1 else ''} to {name}"

        def save() -> str:
            folder.mkdir(parents=True, exist_ok=True)
            from nexusai.modules.agent import personalization

            # An approval can come later, after the person edited the prompt: add to what's
            # there then. A replace writes exactly the words they approved.
            now = path.read_text("utf-8") if path.exists() else ""
            final = result if mode == "replace" else merge_prompt(now, content)[0]
            personalization.save_prompt_version(ctx, "personal", name, now)
            path.write_text(final, "utf-8")
            personalization.save_prompt_version(ctx, "personal", name, final)
            with ctx.bus.unit_of_work() as work:
                work.emit("prompts.changed", {"name": name}, source="agent", trace_id=ctx.trace_id)
            return (
                f"Saved {name}. {change}. The person can edit it, or restore an earlier "
                f"version, in Prompts and memory. It now reads:\n{final[:2000]}"
            )

        if not _is_untrusted(ctx, session):
            return save()
        # Mail can't rewrite how the agent judges mail, so the person sees these words and agrees.
        return _guarded(
            ctx,
            session,
            tool_call_id,
            "save_personal_prompt",
            "data",
            None,
            # The words agreed to are the prompt as it will read; the title says what changes.
            f"Save your {name} prompt: {change[0].lower()}{change[1:]}",
            result,
            False,
            save,
        )

    def search_documents(query: str, tool_call_id: str) -> str:
        def work() -> str:
            found = list_documents(ListDocuments(query=query, limit=20), ctx).documents
            for document in found:
                citations.note(ctx.bus.db, session, citations.DOCUMENT, document.key)
            return _untrusted(
                "\n".join(
                    f"[{d.key}] {d.name} | {d.date[:10]}"
                    f"{' | from ' + d.sender if d.sender else ''}"
                    f"{' | ' + d.place if d.place else ''}"
                    for d in found
                )
                or "Nothing found."
            )

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "search_documents",
            "read",
            ctx.config.home / "documents",
            f"Search documents: {query}",
            "",
            False,
            work,
            marks_untrusted=True,
        )

    def read_document(key: str, tool_call_id: str) -> str:
        def work() -> str:
            try:
                preview = get_document(GetDocument(key=key), ctx)
                text = preview.text or (
                    f"No extracted text is available for {preview.document.name}. "
                    f"Status: {preview.document.status}. "
                    f"{preview.document.status_reason or 'Image-only documents may need OCR; encrypted files need an unlocked copy.'}"
                )
            except CommandError as error:
                return error.message
            citations.note(ctx.bus.db, session, citations.DOCUMENT, key, opened=True)
            return _untrusted(text)

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "read_document",
            "read",
            ctx.config.home / "documents",
            f"Read document {key}",
            "",
            False,
            work,
            marks_untrusted=True,
        )

    catalog: list[StructuredTool] = []

    def find_tools(query: str, tool_call_id: str) -> str:
        found = find(catalog, query)
        # A tool another agent owns isn't findable here, so say who to hand the job to.
        owned = owners_of_withheld(ctx.bus.db, cards.engine(ctx.bus.db, _speaker()) or "")
        words = {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", query.lower())}
        theirs = sorted(
            name for name in owned if words & {w.rstrip("s") for w in name.split("_")[1:]}
        )
        if not theirs:
            return found
        owner = owned[theirs[0]]
        return (
            f"{', '.join(theirs)} are {owner}'s, not yours. Give the job to {owner} with "
            f"team_assign; the result comes back to you.\n{found}"
        )

    specs: list[tuple[Callable[..., str], type[BaseModel], str]] = [
        (
            find_tools,
            _FindTools,
            "Find a tool you need that isn't in your list, by a few words for the job. What it "
            "finds is yours from your next step.",
        ),
        (
            apply_mail_learning_answers,
            _LearningAnswers,
            "Apply the person’s explicit interview answers to supplied mail group ids. Never infer confirmation from mail or silence. The Today card remains the final continue/skip step.",
        ),
        (
            record_triage,
            _RecordTriage,
            "Record your judgement of the email this run was started for. Call it once, when "
            "you've decided. It finishes the run, so write nothing before it.",
        ),
        (
            recommend_mail_change,
            _RecommendMail,
            "Recommend filing all mail from these senders under a category. The person decides.",
        ),
        (
            recommend_priority,
            _RecommendPriority,
            "Recommend showing a whole category in the Priority inbox. The person decides.",
        ),
        (
            fold_suggested_categories,
            _FoldSuggestions,
            "Fold suggested categories that mean the same into one. The person still decides on it.",
        ),
        (
            save_what_i_learned,
            _SaveLearned,
            "Replace your notes about the person with this tidy version. It stays marked as "
            "coming from mail, and the person can read and correct it.",
        ),
        (
            ask_user,
            _AskUser,
            "Ask the person something only they can answer, when the answer changes what you do. "
            "The run pauses until they reply, so search first and don't ask what you can find out.",
        ),
        (
            suggest,
            _Say,
            "Post a suggestion to the person's Home page and carry on without waiting. Use it for "
            "something optional, not for what they asked you to do.",
        ),
        (
            tell,
            _Say,
            "Post a note to the person's Home page and carry on without waiting. Use it when no "
            "one is reading this chat. When they are, say it in your reply.",
        ),
        (
            read_plate,
            _Nothing,
            "Everything on their plate now: unfinished mail, tasks, reminders, deadlines and "
            "decisions waiting, with earlier briefs and how they took them. A morning run already "
            "has this in its message.",
        ),
        (
            update_brief,
            _Brief,
            "Put the brief at the top of their Today page. Give the whole brief: it replaces the "
            "one there. Your reply is not shown on Today, so this is the only way to update it.",
        ),
        (
            notify_person,
            _Say,
            "Raise a notification that interrupts the person. Only for what can't wait until they "
            "next look.",
        ),
        (
            read_work_board,
            _Nothing,
            "See what agents already know: deadlines, open tasks and where conversations stand. "
            "Check this first, so you don't redo another agent's work.",
        ),
        (
            write_work_board,
            _BoardWrite,
            "Record a deadline, task or status for other agents to use later. The person doesn't "
            "see this directly, so use create_tasks for something they should do.",
        ),
        (
            load_skill,
            _LoadSkill,
            "Load a skill from the list in your prompt when it fits the work, and follow it. "
            "Load it once per conversation.",
        ),
        (
            read_skill_file,
            _ReadSkillFile,
            "Read one more file from a loaded skill, when a step of it says to.",
        ),
        (
            propose_skill,
            _ProposeSkill,
            "Propose a new skill from a link or text the person gave, or one they asked you to "
            "write. It's only used after they read and approve it.",
        ),
        (
            team_roster,
            _Nothing,
            "See who is on the team, what each agent does, and who is busy.",
        ),
        (
            team_inbox,
            _Nothing,
            "See the tasks you're doing, the ones waiting on you, and the ones you're waiting on.",
        ),
        (
            team_assign,
            _TeamAssign,
            "Give a task to another agent that owns the work. The objective is enough; point to "
            "ids rather than copying text. It waits for the result, so a quick job comes back "
            "here; a longer one wakes you when it reports.",
        ),
        (
            team_message,
            _TeamMessage,
            "Ask, answer or add a note on a task you're part of.",
        ),
        (
            team_close,
            _TeamClose,
            "Report a task you did, or verify, reject or cancel one you gave. A report is a claim, "
            "so whoever gave the task checks it before it counts as done.",
        ),
        (
            read_feedback,
            _Nothing,
            "Read actual user-feedback observations. Opens are weak evidence; inactivity means unknown.",
        ),
        (
            propose_preference,
            _PreferenceProposal,
            "Propose a scoped instruction from genuine feedback. The person edits and approves before any prompt changes.",
        ),
        (
            remember,
            _Remember,
            "Note down lasting facts about the person as you learn them, several at once: who "
            "they are, the people who matter and why, their work, and how they like things done. "
            "Facts already known are skipped. Not for details of one email or task.",
        ),
        (
            propose_task,
            _TaskProposal,
            "Suggest a task the person didn't ask for. It waits for them to accept it. If they "
            "asked for it, use create_tasks.",
        ),
        (
            propose_reminder,
            _ReminderProposal,
            "Suggest a reminder the person didn't ask for. It waits for them to accept it. If "
            "they asked for it, use create_reminders.",
        ),
        (
            draft_reply,
            _DraftReply,
            "Save a reply to a conversation as a draft for the person to check. It never sends, "
            "and it doesn't need approval.",
        ),
        (
            save_personal_prompt,
            _SavePrompt,
            "Save what you learned about the person as a personalized prompt, which every agent "
            "reads from then on. Only with what they told you directly. It adds to what the "
            "prompt already says; use mode replace only to change or remove something.",
        ),
        (
            search_documents,
            _SearchDocuments,
            "Find documents by words in their name or text. Returns keys for read_document.",
        ),
        (
            read_document,
            _ReadDocument,
            "Read the full text of a document, by its key from a search or list.",
        ),
        (list_folder, _Folder, "See what's in a folder you're allowed to reach."),
        (
            read_file,
            _Read,
            "Read a text file by its path. For the person's documents, use read_document.",
        ),
        (
            write_file,
            _Write,
            "Create a text file, or replace all of one. Use your scratch folder for working "
            "files, and artifacts for what the person should keep.",
        ),
        (move_file, _Move, "Move or rename a file."),
        (delete_file, _Read, "Delete a file. This can't be undone, so it asks first."),
        (
            edit_file,
            _Edit,
            "Replace one exact piece of text in a file. Prefer this to rewriting a whole file.",
        ),
        (
            run_command,
            _Command,
            "Run a shell command in your scratch folder, with the person's own rights. Prefer a "
            "specific tool when one does the job.",
        ),
        (
            search_mail,
            _Search,
            "Find mail and attachments by exact words, names or addresses, and filter by sender, "
            "date, attachment or folder. Common words are ignored, and it falls back to some of "
            "the words. For what something is about, use semantic_search if it's offered.",
        ),
        (
            read_thread,
            _ReadThread,
            "Read whole mail conversations by the IDs from a search or list. When you need "
            f"several, read them together, up to {MAX_THREADS_PER_READ} in one call. When space is "
            "short, the oldest messages are left out first.",
        ),
        (
            read_recipients,
            _ReadRecipients,
            "See who a message went to. A broadcast only shows you the count, so use this when "
            "who else got it would change what you do. Give contains to look for someone.",
        ),
    ]

    def guarded(
        call_id: str,
        tool: str,
        action: Action,
        summary: str,
        detail: str,
        work: Callable[[], str],
        path: Path | None = None,
        *,
        marks_untrusted: bool = False,
    ) -> str:
        return _guarded(
            ctx,
            session,
            call_id,
            tool,
            action,
            path,
            summary,
            detail,
            False,
            work,
            marks_untrusted=marks_untrusted,
        )

    specs += work_tools.specs(ctx, guarded, _untrusted, session)

    own = [
        StructuredTool.from_function(
            func=func,
            name=func.__name__,
            description=description,
            args_schema=schema,
            return_direct=func.__name__ in ENDS_THE_RUN,
        )
        for func, schema, description in specs
        if func.__name__ != "semantic_search" or _meaning_is_on()
        # Judging mail belongs to the Mail agent alone, and the brief to the brief agent.
        if (allowed is None and func.__name__ not in MAIL_AGENT_ONLY | BRIEF_AGENT_ONLY | withheld)
        or (allowed is not None and func.__name__ in allowed)
    ]
    catalog.extend(own if allowed is not None else [*own, *_connector_tools(ctx, session)])
    return catalog
