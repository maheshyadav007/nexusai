"""Runs sessions in the background, so work carries on when the person looks away or restarts."""

import asyncio
import json
import sqlite3
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from nexusai.contracts.agent import ApprovalList, SessionRow, SessionView, ToolApproval
from nexusai.kernel.database import Migration
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    gateway,
    guard,
    policy,
    prompts_builder,
    providers,
    tools,
    ui_stream,
)
from nexusai.modules.agent.model import GatewayChatModel

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_sessions_001",
    """
CREATE TABLE agent_sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, agent TEXT NOT NULL, status TEXT NOT NULL, step TEXT, error TEXT,
  untrusted INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  created TEXT NOT NULL, updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, context TEXT NOT NULL DEFAULT '[]');
CREATE TABLE agent_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, text TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX agent_turns_session ON agent_turns (session, id);
CREATE TABLE agent_parts (id INTEGER PRIMARY KEY AUTOINCREMENT, turn INTEGER NOT NULL, part TEXT NOT NULL);
CREATE INDEX agent_parts_turn ON agent_parts (turn, id);
""",
)
FINISHED = {"done", "failed", "stopped"}
RESUMABLE = {"queued", "running"}
KEEPALIVE_SECONDS = 15
TITLE_LENGTH = 60


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TurnNotifier:
    """Wakes streams when a turn gets new parts, without them asking over and over."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[int, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}

    def wake(self, turn: int) -> None:
        with self._lock:
            for loop, event in self._waiters.get(turn, []):
                loop.call_soon_threadsafe(event.set)

    def register(self, turn: int) -> tuple[asyncio.Event, Any]:
        entry = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._waiters.setdefault(turn, []).append(entry)

        def remove() -> None:
            with self._lock:
                self._waiters[turn].remove(entry)
                if not self._waiters[turn]:
                    del self._waiters[turn]

        return entry[1], remove


@dataclass
class _Live:
    control: tools.RunControl = field(default_factory=tools.RunControl)


class SessionRuntime:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.db = ctx.bus.db
        self.notifier = TurnNotifier()
        self.pool = ThreadPoolExecutor(
            ctx.config.agent.max_running_sessions, thread_name_prefix="session"
        )
        self.live: dict[str, _Live] = {}
        self.lock = threading.Lock()
        path = ctx.config.home / "system" / "checkpoints.db"
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.saver = SqliteSaver(self.connection)
        self.closing = False

    def close(self) -> None:
        self.closing = True
        with self.lock:
            controls = [live.control for live in self.live.values()]
        for control in controls:
            control.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.connection.close()

    # Records

    def _set(self, session: str, **values: Any) -> None:
        assignments = ", ".join(f"{name} = ?" for name in values)
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                f"UPDATE agent_sessions SET {assignments}, updated = ? WHERE id = ?",  # noqa: S608
                (*values.values(), _now(), session),
            )
            work.emit(
                "session.changed",
                {"id": session, **{k: v for k, v in values.items() if k == "status"}},
                source="agent",
                trace_id=self.ctx.trace_id,
            )

    def _append(self, turn: int, parts: list[dict[str, Any]]) -> None:
        if not parts:
            return
        with self.db.transaction() as tx:
            for part in parts:
                tx.execute(
                    "INSERT INTO agent_parts (turn, part) VALUES (?, ?)",
                    (turn, json.dumps(part, default=str)),
                )
        self.notifier.wake(turn)

    def _close_turn(self, turn: int) -> None:
        with self.db.transaction() as tx:
            tx.execute("UPDATE agent_turns SET closed = 1 WHERE id = ?", (turn,))
        self.notifier.wake(turn)

    def row(self, session: str) -> SessionRow:
        rows = self.db.fetch_all("SELECT * FROM agent_sessions WHERE id = ?", (session,))
        if not rows:
            raise CommandError("session.not_found", "That session no longer exists.", 404)
        return _row(rows[0])

    def create(self, title: str | None, context: list[str], agent: str = "session") -> SessionRow:
        session = uuid.uuid4().hex
        scratch_folder(self.ctx.config.home, session)
        now = _now()
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO agent_sessions (id, title, agent, status, created, updated, context) VALUES (?, ?, ?, 'done', ?, ?, ?)",
                (session, title or "New session", agent, now, now, json.dumps(context)),
            )
            work.emit(
                "session.changed", {"id": session}, source="agent", trace_id=self.ctx.trace_id
            )
        return self.row(session)

    def view(self, session: str) -> SessionView:
        row = self.row(session)
        turns = self.db.fetch_all(
            "SELECT * FROM agent_turns WHERE session = ? ORDER BY id", (session,)
        )
        assembled = []
        active = False
        for turn in turns:
            if not turn["closed"]:
                # The open turn comes through the stream, so it isn't drawn twice.
                active = True
                assembled.append({"id": turn["id"], "text": turn["text"], "parts": []})
                continue
            parts = self.db.fetch_all(
                "SELECT part FROM agent_parts WHERE turn = ? ORDER BY id", (turn["id"],)
            )
            assembled.append(
                {
                    "id": turn["id"],
                    "text": turn["text"],
                    "parts": [json.loads(p["part"]) for p in parts],
                }
            )
        return SessionView(
            session=row, messages=ui_stream.assemble_messages(assembled), active=active
        )

    def active_turn(self, session: str) -> int | None:
        rows = self.db.fetch_all(
            "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
            (session,),
        )
        return int(rows[0]["id"]) if rows else None

    # Running

    def send(self, session: str, text: str) -> int:
        row = self.row(session)
        with self.lock:
            if self.active_turn(session) is not None:
                raise CommandError(
                    "session.busy", "This session is still working. Wait for it, or stop it.", 409
                )
            with self.db.transaction() as tx:
                cursor = tx.execute(
                    "INSERT INTO agent_turns (session, text) VALUES (?, ?)", (session, text)
                )
                turn = int(cursor.lastrowid or 0)
        values: dict[str, Any] = {"status": "queued", "error": None}
        if row.title == "New session":
            values["title"] = (
                text.strip().splitlines()[0][:TITLE_LENGTH] if text.strip() else row.title
            )
        self._set(session, **values)
        self._submit(session, turn, {"messages": [{"role": "user", "content": text}]})
        return turn

    def _submit(self, session: str, turn: int, payload: Any) -> None:
        self.pool.submit(self._run, session, turn, payload)

    def _agent(self, session: str, row: SessionRow, control: tools.RunControl) -> Any:
        context = self.ctx.config
        layers = prompts_builder.build_layers(
            context,
            "session",
            scratch=str(context.home / "scratch" / session),
        )
        model = GatewayChatModel(ctx=self.ctx, agent=row.agent, session=session, layers=layers)
        return create_agent(
            model, tools.build_tools(self.ctx, session, control), checkpointer=self.saver
        )

    def _run(self, session: str, turn: int, payload: Any) -> None:
        if self.closing:
            return
        live = _Live()
        with self.lock:
            self.live[session] = live
        started = bool(
            self.db.fetch_all("SELECT 1 FROM agent_parts WHERE turn = ? LIMIT 1", (turn,))
        )
        translator = ui_stream.UiTranslator(started=started)
        self._append(turn, translator.start())
        self._set(session, status="running", step=None)
        config = {
            "configurable": {"thread_id": session},
            "recursion_limit": self.ctx.config.agent.max_steps * 2,
        }
        try:
            agent = self._agent(session, self.row(session), live.control)
            stream = agent.stream_events(payload, config, version="v3")
            for event in stream:
                if live.control.stopped.is_set():
                    stream.abort()
                    break
                self._append(turn, translator.feed(event))
            if live.control.stopped.is_set():
                if not self.closing:
                    self._finish(session, turn, translator, "stopped", None, "abort")
                return
            pending = list(stream.interrupts or [])
            if pending:
                self._append(turn, translator.close_open_blocks())
                self._record_usage(session)
                self._announce_approvals(turn, pending)
                self._set(session, status="waiting", step="Waiting for your approval")
                return
            self._finish(session, turn, translator, "done", None, "finish")
        except (
            providers.ModelUnavailable,
            providers.ModelNotConfigured,
            providers.ModelFlagged,
            gateway.DailyCapReached,
            guard.DamagedToken,
            guard.GuardBlocked,
        ) as error:
            self._finish(session, turn, translator, "failed", str(error), "error")
        except GraphRecursionError:
            self._finish(
                session,
                turn,
                translator,
                "failed",
                "This session took too many steps, so it stopped. Ask it to continue if needed.",
                "error",
            )
        except Exception:
            log.exception("session_failed", session=session)
            self._finish(
                session,
                turn,
                translator,
                "failed",
                "The session hit a problem. You can try again.",
                "error",
            )
        finally:
            with self.lock:
                self.live.pop(session, None)

    def _record_usage(self, session: str) -> None:
        totals = self.db.fetch_all(
            "SELECT COALESCE(SUM(input_tokens), 0) AS i, COALESCE(SUM(output_tokens), 0) AS o FROM model_calls WHERE session = ?",
            (session,),
        )[0]
        self._set(session, input_tokens=totals["i"], output_tokens=totals["o"])

    def _finish(
        self,
        session: str,
        turn: int,
        translator: ui_stream.UiTranslator,
        status: str,
        error: str | None,
        ending: str,
    ) -> None:
        parts = translator.close_open_blocks()
        if ending == "error":
            parts.append({"type": "error", "errorText": error or "Something went wrong."})
        elif ending == "abort":
            parts.append({"type": "abort"})
        else:
            parts.append({"type": "finish"})
        self._append(turn, parts)
        self._close_turn(turn)
        self._record_usage(session)
        self._set(session, status=status, error=error, step=None)

    def _announce_approvals(self, turn: int, pending: list[Any]) -> None:
        parts = []
        for item in pending:
            value = item.value if isinstance(item.value, dict) else {}
            if "approval" in value:
                parts.append(
                    {
                        "type": "tool-approval-request",
                        "approvalId": str(value["approval"]),
                        "toolCallId": value["tool_call_id"],
                    }
                )
        self._append(turn, parts)

    def decide(self, approval: int, choice: str) -> None:
        rows = self.db.fetch_all("SELECT * FROM tool_approvals WHERE id = ?", (approval,))
        if not rows:
            raise CommandError("approval.not_found", "That approval no longer exists.", 404)
        row = rows[0]
        if row["status"] != "pending":
            raise CommandError("approval.decided", "That has already been decided.", 409)
        approved = choice != "deny"
        status = "approved" if approved else "denied"
        session = row["session"]
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute("UPDATE tool_approvals SET status = ? WHERE id = ?", (status, approval))
            work.emit(
                "approval.changed",
                {"id": approval, "status": status},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
        if choice == "session":
            policy.allow_for_session(self.db, session, row["kind"])
        turn = self.active_turn(session)
        if turn is None:
            return
        self._append(
            turn,
            [
                {
                    "type": "tool-approval-response",
                    "approvalId": str(approval),
                    "approved": approved,
                    "toolCallId": row["tool_call_id"],
                }
            ],
        )
        if not approved:
            self._append(turn, [{"type": "tool-output-denied", "toolCallId": row["tool_call_id"]}])
        # Other approvals from the same step still wait. The run continues once they're all decided.
        waiting = self.db.fetch_all(
            "SELECT COUNT(*) AS n FROM tool_approvals WHERE session = ? AND status = 'pending'",
            (session,),
        )[0]["n"]
        if waiting:
            return
        interrupts = self._pending_interrupts(session)
        answers = {item_id: self._answer_for(value) for item_id, value in interrupts}
        self._set(session, status="queued", step=None)
        self._submit(session, turn, Command(resume=answers))

    def _pending_interrupts(self, session: str) -> list[tuple[str, dict[str, Any]]]:
        agent = self._agent(session, self.row(session), tools.RunControl())
        snapshot = agent.get_state({"configurable": {"thread_id": session}})
        return [(item.id, item.value) for task in snapshot.tasks for item in task.interrupts]

    def _answer_for(self, value: dict[str, Any]) -> str:
        rows = self.db.fetch_all(
            "SELECT status FROM tool_approvals WHERE id = ?", (value.get("approval"),)
        )
        return str(rows[0]["status"]) if rows else "denied"

    def stop(self, session: str) -> None:
        with self.lock:
            live = self.live.get(session)
        if live:
            live.control.stop()
            return
        # Queued or waiting: nothing is running to interrupt.
        row = self.row(session)
        turn = self.active_turn(session)
        if turn is not None and row.status not in FINISHED:
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE tool_approvals SET status = 'denied' WHERE session = ? AND status = 'pending'",
                    (session,),
                )
            translator = ui_stream.UiTranslator(started=True)
            self._finish(session, turn, translator, "stopped", None, "abort")
            with self.ctx.bus.unit_of_work() as work:
                work.emit(
                    "approval.changed",
                    {"session": session},
                    source="agent",
                    trace_id=self.ctx.trace_id,
                )

    def resume_after_restart(self) -> None:
        """Running work carries on from its last checkpoint. Waiting work keeps waiting for a person."""
        rows = self.db.fetch_all(
            "SELECT id, status FROM agent_sessions WHERE status IN ('queued', 'running')"
        )
        for row in rows:
            turn = self.active_turn(row["id"])
            if turn is None:
                self._set(row["id"], status="done")
                continue
            has_checkpoint = (
                self.saver.get_tuple({"configurable": {"thread_id": row["id"]}}) is not None
            )
            turn_text = self.db.fetch_all("SELECT text FROM agent_turns WHERE id = ?", (turn,))[0][
                "text"
            ]
            payload = (
                None if has_checkpoint else {"messages": [{"role": "user", "content": turn_text}]}
            )
            self._submit(row["id"], turn, payload)

    async def stream_turn(self, turn: int, disconnected: Any) -> AsyncIterator[str]:
        """Everything in the turn so far, then new parts as they arrive. It's safe to reopen."""
        event, remove = self.notifier.register(turn)
        last = 0
        try:
            while not await disconnected():
                event.clear()
                rows = await asyncio.to_thread(
                    self.db.fetch_all,
                    "SELECT id, part FROM agent_parts WHERE turn = ? AND id > ? ORDER BY id",
                    (turn, last),
                )
                for row in rows:
                    last = row["id"]
                    yield f"data: {row['part']}\n\n"
                closed = await asyncio.to_thread(
                    self.db.fetch_all, "SELECT closed FROM agent_turns WHERE id = ?", (turn,)
                )
                if not closed or closed[0]["closed"]:
                    remaining = await asyncio.to_thread(
                        self.db.fetch_all,
                        "SELECT part FROM agent_parts WHERE turn = ? AND id > ? ORDER BY id",
                        (turn, last),
                    )
                    for row in remaining:
                        yield f"data: {row['part']}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                try:
                    await asyncio.wait_for(event.wait(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            remove()


def _row(row: Any) -> SessionRow:
    return SessionRow(
        id=row["id"],
        title=row["title"],
        agent=row["agent"],
        status=row["status"],
        step=row["step"],
        error=row["error"],
        untrusted=bool(row["untrusted"]),
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        created=row["created"],
        updated=row["updated"],
        archived=bool(row["archived"]),
    )


def approvals_view(db: Any) -> ApprovalList:
    rows = db.fetch_all(
        "SELECT a.*, s.title AS session_title FROM tool_approvals a JOIN agent_sessions s ON s.id = a.session"
        " WHERE a.status = 'pending' ORDER BY a.id"
    )
    return ApprovalList(
        approvals=[
            ToolApproval(
                id=row["id"],
                session=row["session"],
                session_title=row["session_title"],
                tool_call_id=row["tool_call_id"],
                tool=row["tool"],
                summary=row["summary"],
                reason=row["reason"],
                detail=row["detail"],
                undoable=bool(row["undoable"]),
                status=row["status"],
                time=row["time"],
            )
            for row in rows
        ]
    )
