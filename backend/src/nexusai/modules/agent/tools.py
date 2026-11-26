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
from nexusai.contracts.mail import (
    Draft,
    DraftAttachment,
    FolderRole,
    Recipient,
    SearchMail,
    SearchResults,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    briefs,
    bulk_learning,
    cards,
    channel,
    citations,
    installs,
    jobs,
    kinds,
    mail_agent,
    matters,
    memory,
    policy,
    prompts_builder,
    signals,
    skills,
    sources,
    team,
    work_tools,
)
from nexusai.modules.agent.policy import Action
from nexusai.modules.agent.prompt_data import untrusted
from nexusai.modules.connectors import module as connectors
from nexusai.modules.documents.module import get_document as _get_document
from nexusai.modules.documents.module import list_documents as _list_documents
from nexusai.modules.mail import accounts, outgoing, store
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
    citations.shown_in_session(ctx.bus.db, session, result)
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


# How many times one run may call remember before it's told to stop.
MOST_REMEMBERS_PER_RUN = 3
# How many conversations one read_thread call takes. They share one tool output, so each gets less.
MAX_THREADS_PER_READ = 10


class _OpenItem(BaseModel):
    address: str = Field(
        description="What to open, by its address as shown: [matter:12], [task:88], "
        "[reminder:5], [mail:123] or [doc:KEY]."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _FindMatters(BaseModel):
    words: str = Field(
        default="", description="Words from its title or the people in it. Empty lists them all."
    )
    state: Literal["open", "waiting_on_you", "waiting_on_others", "fyi", "done"] = Field(
        default="open", description="open is every matter not done."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _ReadThread(BaseModel):
    thread_ids: list[int] = Field(
        min_length=1,
        max_length=MAX_THREADS_PER_READ,
        description=f"The conversations' IDs, from a search or list. Up to {MAX_THREADS_PER_READ}.",
    )
    skip_newest: int = Field(
        default=0,
        ge=0,
        description="Leave out this many of the newest emails, to read further back.",
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
    lead: str = Field(
        min_length=1,
        max_length=600,
        description="One sentence: the single most important thing today, and why.",
    )
    new: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="What's new or changed since the last brief, one line per matter, each"
        " ending with its marker like [mail:123].",
    )
    still_open: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="What was already known and is now urgent or overdue, one line per matter,"
        " each ending with its marker.",
    )
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


class _ProposePlugin(BaseModel):
    source: str = Field(
        description="The https link the person gave (a GitHub folder or a zip), or a folder path on"
        " this computer."
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _AddMcpServer(BaseModel):
    name: str = Field(description="A short name for it, such as Jira or Company wiki.")
    url: str = Field(description="The server's address the person gave, starting with https://.")
    tool_call_id: Annotated[str, InjectedToolCallId]


class _AddPluginServers(BaseModel):
    name: str = Field(description="The plugin's name, from list_plugins.")
    values: dict[str, str] = Field(
        default_factory=dict,
        description="The settings its servers ask for, by name, such as an API key the person gave.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _PluginName(BaseModel):
    name: str = Field(description="The plugin's name, from list_plugins.")
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
        description="Ids that prove it, such as [mail:291] for an email, or 'thread 291 moved to PLM'.",
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
    attachments: list[str] = Field(
        default_factory=list,
        description="Files to attach, by their marker as read_thread or search_documents shows"
        " it, such as [doc:m:123:2].",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


class _DraftForward(BaseModel):
    thread_id: int = Field(description="The conversation whose latest email to forward.")
    to: list[str] = Field(min_length=1, description="Email addresses to forward it to.")
    note: str = Field(default="", description="A short note above the forwarded email.")
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
    key: str = Field(description="The document's marker, as shown, such as [doc:m:123:2].")
    tool_call_id: Annotated[str, InjectedToolCallId]


MAX_DETAIL_CHARS = 4000


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
        description="At most one existing Smart folder name: the best fit. Never invent a folder.",
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
    matter: int | None = Field(
        default=None,
        description="The number of the listed matter this email is about, or null when none is.",
    )
    tasks: list[dict[str, Any]] = Field(
        default_factory=list,
        description='What the person should do, as {"title": ..., "due": "YYYY-MM-DD" or null,'
        ' "updates": "task:88" when it is an open task already listed}.',
    )
    reminders: list[dict[str, Any]] = Field(
        default_factory=list, description='As {"title": ..., "when": "YYYY-MM-DDTHH:MM"}.'
    )
    finished: list[str] = Field(
        default_factory=list,
        description='Open work listed with this email that it shows is now done, like "task:88"'
        ' or "reminder:12". Only what the mail says is done.',
    )
    draft: str | None = Field(default=None, description="A suggested reply as plain text.")
    learned: list[str] = Field(
        default_factory=list,
        description="Short notes on anything lasting this shows about the person. Usually empty.",
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
        "open_item",
        "find_matters",
        "read_recipients",
        "list_mail",
        "semantic_search",
        "search_documents",
        "read_document",
        "list_documents",
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
        "draft_forward",
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
        "read_document",
    }
)
# As many as the agent can use at once. It narrows the search for more.
SEARCH_SHOWN = 20
# It ends a run, so judging simple mail takes one model call.
ENDS_THE_RUN = frozenset({"record_triage"})
LEARNING_ORIGIN = "mail-learn"
# Owned by the Mail agent (jobs.py). Kept as a name, since other modules read it.
MAIL_AGENT_ONLY = jobs.JOBS["triage"].tools


# The brief agent reads and searches, then writes the brief. Nothing else is its job.
BRIEF_TOOLS = frozenset(
    {
        "read_plate",
        "update_brief",
        "read_thread",
        "open_item",
        "find_matters",
        "read_recipients",
        "search_mail",
        "semantic_search",
        "list_mail",
        "list_tasks",
        "list_reminders",
        "draft_reply",
        "read_feedback",
        "remember",
        "list_memory",
        "team_inbox",
        "team_message",
        "team_close",
    }
)
BRIEF_AGENT_ONLY = jobs.JOBS["brief"].tools


# The Routines agent sets up, changes, runs and removes routines, reading enough to write them well.
ROUTINES_TOOLS = frozenset(
    {
        "list_schedules",
        "create_schedule",
        "update_schedule",
        "remove_schedules",
        "run_schedule",
        "search_mail",
        "read_thread",
        "open_item",
        "find_matters",
        "list_mail",
        "list_tasks",
        "list_reminders",
        "list_categories",
        "remember",
        "list_memory",
        "load_skill",
        "read_skill_file",
        "team_roster",
        "team_inbox",
        "team_message",
        "team_close",
    }
)


INTERVIEW_TOOLS = frozenset(
    {
        "ask_user",
        "save_personal_prompt",
        "apply_mail_learning_answers",
        "remember",
        "list_memory",
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
# matters, documents, and every list it checks before making something.
LEAD_SHOWN = ALWAYS_SHOWN | {
    "open_item", "find_matters", "search_mail", "semantic_search", "search_documents", "read_thread",
    "list_mail", "update_mail", "draft_reply", "draft_forward", "list_drafts",
    "list_tasks", "list_reminders", "create_tasks", "create_reminders", "list_categories",
    "list_rules", "list_schedules", "list_panels", "propose_preference",
    "team_assign", "team_inbox", "team_message", "team_close",
}  # fmt: skip
MAIL_SHOWN = ALWAYS_SHOWN | {
    "search_mail", "semantic_search", "read_thread", "read_recipients", "list_mail",
    "update_mail", "draft_reply", "draft_forward", "propose_task",
    "propose_reminder",
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
    return None if agent in {"daily-prep", "routines"} else LEAD_SHOWN


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
    """Tools another agent owns (jobs.py), kept from one that would otherwise have them all."""
    return jobs.withheld_for(agent)


def owners_of_withheld(db: Any, agent: str) -> dict[str, str]:
    """Each withheld tool's owner, by @handle, so a call to one is pointed the right way."""
    owners: dict[str, str] = {}
    for tool, owner in jobs.handed_over_tools(agent).items():
        found = cards.card(db, owner)
        if found is not None:
            owners[tool] = found.at
    return owners


def allowed_for(agent: str, origin: str, has_email: bool) -> frozenset[str] | None:
    """None means every tool. Only someone typing can answer a question straight away, and
    there's only a judgement to record when the run was started for an email."""
    if agent == "interview":
        return INTERVIEW_TOOLS
    if agent == "daily-prep":
        return BRIEF_TOOLS | {"ask_user"} if origin == "person" else BRIEF_TOOLS
    if agent == "routines":
        return ROUTINES_TOOLS | {"ask_user"} if origin == "person" else ROUTINES_TOOLS
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
            return "Saved the person's answers. The rest keep their guesses, which they can confirm from Getting started on Today."

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
            # What a folder keeps from the AI is never shown to an agent running by itself;
            # when the person asks, it is, and says so.
            hidden = signals.hidden_threads(ctx, [hit.thread.id for hit in found.hits])
            asked = signals.asked_by_person(ctx, session)
            hits = [hit for hit in found.hits if asked or hit.thread.id not in hidden]
            for hit in hits:
                citations.note(ctx.bus.db, session, citations.MAIL, str(hit.thread.id))
            lines = [
                f"{citations.mark(citations.MAIL, h.thread.id)} {h.thread.last_date[:10]} | {h.thread.subject}"
                f" | {', '.join(h.thread.participants[:3])}"
                f"{' | ' + h.thread.category if h.thread.category else ''}"
                f"{' | ' + signals.HIDDEN_NOTE if h.thread.id in hidden else ''}"
                f"{' | related in meaning, not these words' if h.matched_by == 'meaning' else ''}"
                f" | {matters.standing(ctx, h.thread.id, most=2)}"
                f" | {h.excerpt}"
                for h in hits
            ]
            if found.corrected:
                lines.insert(
                    0, f"Nothing matched as typed, so this searched for: {found.corrected}"
                )
            if len(hits) == SEARCH_SHOWN:
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

    def read_thread(thread_ids: list[int], tool_call_id: str, skip_newest: int = 0) -> str:
        ids = list(dict.fromkeys(thread_ids))[:MAX_THREADS_PER_READ]

        def work() -> str:
            # One tool output holds them all, so each conversation gets an equal share of it.
            share = min(
                ctx.config.agent.max_thread_chars,
                ctx.config.agent.max_tool_output_chars // len(ids) - 100,
            )
            hidden = signals.hidden_threads(ctx, ids)
            asked = signals.asked_by_person(ctx, session)
            return _untrusted(
                "\n\n---\n\n".join(_thread_text(thread, share, hidden, asked) for thread in ids)
            )

        def _thread_text(thread_id: int, budget: int, hidden: set[int], asked: bool) -> str:
            if thread_id in hidden and not asked:
                return f"Conversation {thread_id} is hidden from the AI by its folder."
            view = store.thread_view(ctx.bus.db, thread_id)
            if view is None:
                return f"Conversation {thread_id} no longer exists."
            citations.note(ctx.bus.db, session, citations.MAIL, str(thread_id), opened=True)
            # Paging back from the newest, so a long conversation can be read to its start.
            before = view.messages[: max(len(view.messages) - skip_newest, 0)]
            recent = before[-ctx.config.agent.max_recent_thread_messages :]
            attachments = [
                f"- {a.filename}: {citations.mark(citations.DOCUMENT, f'm:{m.id}:{a.index}')}"
                for m in recent
                for a in m.attachments
                if a.kind in {"attachment", "calendar"}
            ]
            manifest = (
                "Attachments (read_document reads them; draft_reply and draft_forward attach them by marker):\n"
                + "\n".join(attachments)
                + "\n\n"
                if attachments
                else ""
            )
            shown = f" ({signals.HIDDEN_NOTE})" if thread_id in hidden else ""
            head = (
                f"Conversation {citations.mark(citations.MAIL, thread_id)}{shown}\nSubject: {view.thread.subject}\n"
                f"{matters.standing(ctx, thread_id)}\n{manifest}"
            )
            # The newest messages matter most, so when space runs out the oldest go first.
            kept: list[str] = []
            room = budget - len(head)
            for message in reversed(recent):
                # Each message has its own marker, so a statement can point to the one it came from.
                cite = citations.mark(citations.MAIL, f"{thread_id}#m{message.id}")
                text = f"{cite} From {message.from_name} <{message.from_addr}> on {message.date}\n{message.own_text}"
                if kept and len(text) > room:
                    break
                kept.insert(0, text[: max(room, 0)])
                room -= len(text) + 2
            skipped = len(before) - len(kept)
            reached = skip_newest + len(kept)
            note = (
                f"[{skipped} older messages not shown. skip_newest={reached} reads them.]\n\n"
                if skipped
                else ""
            )
            newer = f"\n\n[{skip_newest} newer messages left out]" if skip_newest else ""
            return f"{head}{note}" + "\n\n".join(kept) + newer

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

    def update_brief(
        lead: str,
        tool_call_id: str,
        new: list[str] | None = None,
        still_open: list[str] | None = None,
    ) -> str:
        return briefs.save(ctx, session, lead, new or [], still_open or [])

    def notify_person(text: str, tool_call_id: str) -> str:
        with ctx.bus.unit_of_work() as work:
            channel.notify(ctx, work, text, "", f"/agent/sessions/{session}", "agent", False)
        return "Sent."

    def open_item(address: str, tool_call_id: str) -> str:
        kind, _, rest = address.strip().strip("[]").partition(":")
        if kind in ("matter", "task", "reminder") and rest.isdigit():
            return _untrusted(matters.open_text(ctx, kind, int(rest)))
        if kind in ("mail", "thread") and rest.partition("#")[0].isdigit():
            thread = int(rest.partition("#")[0])
            hidden = signals.hidden_threads(ctx, [thread])
            if hidden and not signals.asked_by_person(ctx, session):
                return f"Conversation {thread} is hidden from the AI by its folder."
            view = store.thread_view(ctx.bus.db, thread)
            if view is None:
                return f"Conversation {thread} no longer exists."
            citations.note(ctx.bus.db, session, citations.MAIL, str(thread))
            return _untrusted(
                f"{citations.mark(citations.MAIL, thread)} {view.thread.subject}\n"
                f"{matters.standing(ctx, thread)}\nread_thread reads its messages."
            )
        if kind == "doc" and rest:
            key = kinds.key_of(rest)
            found = sources.describe(ctx, citations.DOCUMENT, key)
            if found is None:
                return "That document no longer exists."
            citations.note(ctx.bus.db, session, citations.DOCUMENT, key)
            return _untrusted(
                f"{citations.mark(citations.DOCUMENT, key)} {found.title}\nread_document reads it."
            )
        return "That isn't an address. Copy one as it was shown, such as [matter:12] or [task:88]."

    def find_matters(tool_call_id: str, words: str = "", state: str = "open") -> str:
        return _untrusted(matters.find(ctx, words, state))

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

    def _plugin_line(plugin: Any) -> str:
        servers = ", ".join(
            f"{s.name}" + (f" (needs {', '.join(s.needs)})" if s.needs else "")
            for s in plugin.servers
        )
        return (
            f"{plugin.name}: skills {', '.join(plugin.skills) or 'none'}; servers {servers or 'none'};"
            f" connectors added {', '.join(plugin.connector_ids) or 'none'}"
            + (f"; not used here: {', '.join(plugin.skipped)}" if plugin.skipped else "")
        )

    def propose_plugin(source: str, tool_call_id: str) -> str:
        def work() -> str:
            try:
                found = installs.propose(ctx, source, _speaker())
            except CommandError as error:
                return f"Not proposed: {error.message}"
            except httpx.HTTPError as error:
                return f"Not fetched: {type(error).__name__}. Check the link and the network."
            servers = (
                " Its servers aren't added yet: once the person agrees, add them with"
                " add_plugin_servers"
                + (
                    ", asking first for what they need"
                    if any(s.needs for s in found.servers)
                    else ""
                )
                + "."
                if found.servers
                else ""
            )
            return (
                f"Proposed plugin {found.name}. {_plugin_line(found)}. Its skills do nothing until the"
                f" person reads and approves each on the Agent channel page, under Skills.{servers}"
            )

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "propose_plugin",
            "send",
            None,
            f"Fetch a plugin from {source}",
            f"{source}\n\nIts skills come back only as proposals you review. Its servers are added"
            " only when you agree, and nothing in it runs on this computer.",
            False,
            work,
        )

    def add_plugin_servers(
        name: str, tool_call_id: str, values: dict[str, str] | None = None
    ) -> str:
        def work() -> str:
            try:
                found = installs.add_servers(ctx, name, values or {})
            except CommandError as error:
                return f"Not added: {error.message}"
            return f"Added. {_plugin_line(found)}. New tools wait for the person's yes before use."

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "add_plugin_servers",
            "data",
            None,
            f"Add the servers of the plugin {name}",
            f"Connects to the MCP servers the plugin {name} brings. Their tools are listed and"
            " checked like any connector's.",
            False,
            work,
        )

    def add_mcp_server(name: str, url: str, tool_call_id: str) -> str:
        def work() -> str:
            from nexusai.contracts.connectors import AddConnector

            try:
                connectors.add_connector(
                    AddConnector(name=name.strip()[:60], url=url.strip(), audience="internal"), ctx
                )
            except CommandError as error:
                return (
                    f"Not added: {error.message} If it needs a key or token, the person adds it"
                    " on the Connectors page (Add, then the token or a header), not in chat."
                )
            return (
                f"Added {name}. Its tools show on the Connectors page, and each new tool asks the"
                " person before its first use."
            )

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "add_mcp_server",
            "data",
            None,
            f"Connect to the MCP server {name}",
            f"{url}\n\nIts tools are listed and checked like any connector's. A key or token is"
            " added on the Connectors page, never in chat.",
            False,
            work,
        )

    def list_plugins(tool_call_id: str) -> str:
        found = installs.listing(ctx).plugins
        return "\n".join(_plugin_line(p) for p in found) or "No plugins are installed."

    def remove_plugin(name: str, tool_call_id: str) -> str:
        def work() -> str:
            try:
                installs.remove(ctx, name)
            except CommandError as error:
                return f"Not removed: {error.message}"
            return f"Removed the plugin {name}, with its skills and connectors."

        return _guarded(
            ctx,
            session,
            tool_call_id,
            "remove_plugin",
            "data",
            None,
            f"Remove the plugin {name}",
            f"Takes out the plugin {name}: its skills and the connectors it added.",
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
        # The evidence is the person's own words or actions, so it's theirs to remove, not approve.
        item = personalization.save(ctx, proposal)
        return f"Saved preference {item.id}. It applies from now on, and they can change or remove it in Prompts and memory. Nothing more to do."

    # A small model can call remember again and again on the same few facts. Past a few calls in
    # one run, it's told plainly that everything is kept and to answer.
    remembered = [0]

    def remember(facts: list[str], tool_call_id: str) -> str:
        remembered[0] += 1
        if remembered[0] > MOST_REMEMBERS_PER_RUN:
            return (
                "Not run: remember was already called in this run and everything is kept. Don't"
                " call it again; carry on with the task or answer the person."
            )
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
            return f"Nothing new to save, it's all known already: {'; '.join(known)}. Nothing more to do."
        listed = "; ".join(new)
        if untrusted:
            return (
                f"Saved as notes learned from mail: {listed}.{said} They can see or remove them in"
                " Prompts and memory. Nothing more to do."
            )
        return f"Saved to memory: {listed}.{said} Nothing more to do."

    def propose_task(
        title: str, tool_call_id: str, due: str | None = None, thread_id: int | None = None
    ) -> str:
        if planner.has_task(ctx.bus.db, title, thread_id):
            return "Not proposed: a task about this already exists. Check list_tasks."
        try:
            planner.add_task(ctx, title, due, thread_id, "agent", True)
        except CommandError as error:
            return f"Not proposed: {error.message}"
        return "Proposed. The person accepts it in Tasks."

    def propose_reminder(
        title: str, when: str, tool_call_id: str, thread_id: int | None = None
    ) -> str:
        try:
            planner.add_reminder(ctx, title, when, "none", thread_id, None, "agent", True)
        except CommandError as error:
            return f"Not proposed: {error.message}"
        return "Proposed. The person accepts it in Reminders."

    def _keep_draft(draft: Draft) -> None:
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO mail_drafts (body, updated) VALUES (?, ?)",
                (draft.model_dump_json(exclude={"id"}), datetime.now(UTC).isoformat()),
            )
            work.emit("drafts.changed", {}, source="agent", trace_id=ctx.trace_id)

    def _attached(keys: list[str]) -> tuple[list[DraftAttachment], str]:
        found, missing = outgoing.attachments_from_keys(ctx, [kinds.key_of(key) for key in keys])
        note = (
            f" These couldn't be attached, so check the keys: {', '.join(missing)}."
            if missing
            else ""
        )
        if found:
            note = f" Attached: {', '.join(item.name for item in found)}.{note}"
        return found, note

    def draft_reply(
        thread_id: int, body: str, tool_call_id: str, attachments: list[str] | None = None
    ) -> str:
        rows = ctx.bus.db.fetch_all(
            "SELECT id, from_addr, subject FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1",
            (thread_id,),
        )
        if not rows:
            return "That conversation no longer exists."
        subject = rows[0]["subject"]
        files, note = _attached(attachments or [])
        try:
            to = [Recipient(address=rows[0]["from_addr"])]
        except ValueError:
            to = []
        _keep_draft(
            Draft(
                thread_id=thread_id,
                reply_to_message_id=rows[0]["id"],
                to=to,
                subject=subject if subject.lower().startswith("re:") else f"Re: {subject}",
                body=outgoing.with_signature(ctx, body),
                source="agent",
                attachments=files,
            )
        )
        return f"Saved as a draft. Nothing was sent. The person reviews it in Drafts.{note}"

    def draft_forward(thread_id: int, to: list[str], tool_call_id: str, note: str = "") -> str:
        rows = ctx.bus.db.fetch_all(
            "SELECT id FROM messages WHERE thread_id = ? ORDER BY date DESC LIMIT 1", (thread_id,)
        )
        if not rows:
            return "That conversation no longer exists."
        people, bad = [], []
        for address in to:
            try:
                people.append(Recipient(address=address.strip()))
            except ValueError:
                bad.append(address)
        if bad or not people:
            return f"Not saved: these aren't email addresses: {', '.join(bad) or 'none given'}."
        forwarded = outgoing.forward(ctx, rows[0]["id"])
        body = outgoing.with_signature(ctx, note.strip()) if note.strip() else ""
        _keep_draft(
            forwarded.model_copy(
                update={"to": people, "body": f"{body}{forwarded.body}", "source": "agent"}
            )
        )
        files = (
            f" Its attachments go with it: {', '.join(a.name for a in forwarded.attachments)}."
            if forwarded.attachments
            else ""
        )
        return (
            f"Saved as a draft forward. Nothing was sent. The person reviews it in Drafts.{files}"
        )

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
                    f"{citations.mark(citations.DOCUMENT, d.key)} {d.name} | {d.date[:10]}"
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
        key = kinds.key_of(key)

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
            "Everything on their plate now: matters, unfinished mail, tasks, reminders and "
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
            open_item,
            _OpenItem,
            "Open anything by its address: a matter with its conversations, work, links and what "
            "happened; a task or reminder with its matter; a conversation with where it stands. "
            "Everything it names is an address you can open next.",
        ),
        (
            find_matters,
            _FindMatters,
            "List matters, the real things going on, by words or state, each by its address. Use "
            "it when you don't have a matter's address yet.",
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
            add_mcp_server,
            _AddMcpServer,
            "Connect one MCP server by the address the person gave. For a folder or link with a"
            " plugin or MCP settings, use propose_plugin instead.",
        ),
        (
            propose_plugin,
            _ProposePlugin,
            "Install a plugin from a link or folder the person gave: its skills come back as proposals"
            " they review, and its MCP servers are added later with add_plugin_servers.",
        ),
        (
            add_plugin_servers,
            _AddPluginServers,
            "Add the MCP servers a proposed plugin brings, with any settings they need from the person.",
        ),
        (
            list_plugins,
            _Nothing,
            "See the installed plugins: their skills, servers and connectors.",
        ),
        (remove_plugin, _PluginName, "Remove a plugin with its skills and connectors."),
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
            "Save a scoped instruction from genuine feedback. It applies at once; the person can edit or remove it.",
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
            "Save a reply to a conversation as a draft for the person to check, with files "
            "attached if asked. It never sends, and it doesn't need approval.",
        ),
        (
            draft_forward,
            _DraftForward,
            "Save a forward of a conversation's latest email, with its attachments, as a draft "
            "for the person to check. It never sends, and it doesn't need approval.",
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
            "short, the oldest messages are left out first; skip_newest reads further back.",
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
        # A job another agent owns (jobs.py) is withheld. Judging mail and the brief are never in
        # a full set, even if a caller forgets to pass what's withheld.
        if (allowed is None and func.__name__ not in MAIL_AGENT_ONLY | BRIEF_AGENT_ONLY | withheld)
        or (allowed is not None and func.__name__ in allowed)
    ]
    catalog.extend(own if allowed is not None else [*own, *_connector_tools(ctx, session)])
    return catalog
