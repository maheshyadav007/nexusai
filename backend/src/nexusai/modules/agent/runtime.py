"""Runs sessions in the background, so work carries on when the person looks away or restarts."""

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command

from nexusai.contracts.agent import (
    ApprovalList,
    ContextProfile,
    SessionCompaction,
    SessionRow,
    SessionView,
    ToolApproval,
)
from nexusai.contracts.documents import GetDocument
from nexusai.kernel.database import Migration, StandardErrorsConnection, connect_raw
from nexusai.kernel.home import scratch_folder
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import (
    approval_view,
    channel,
    citations,
    context,
    gateway,
    guard,
    knowledge,
    policy,
    prompts_builder,
    providers,
    tools,
    ui_stream,
)
from nexusai.modules.agent.context import PERSON, TurnRequest
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.model import GatewayChatModel
from nexusai.modules.mail import accounts, store
from nexusai.modules.semantic import module as semantic

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
EDIT_MIGRATION = Migration(
    "agent_turns_edit_001",
    """
ALTER TABLE agent_turns ADD COLUMN created TEXT;
ALTER TABLE agent_turns ADD COLUMN checkpoint TEXT;
""",
)
COMPACTIONS_MIGRATION = Migration(
    "agent_compactions_001",
    """
CREATE TABLE session_compactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, after_turn INTEGER NOT NULL, time TEXT NOT NULL,
  before_tokens INTEGER NOT NULL, after_tokens INTEGER NOT NULL, how TEXT NOT NULL);
CREATE INDEX session_compactions_session ON session_compactions (session);
""",
)
RETRY_MIGRATION = Migration(
    "agent_turns_retry_001",
    """
ALTER TABLE agent_turns ADD COLUMN retry_of INTEGER;
ALTER TABLE agent_turns ADD COLUMN chosen INTEGER NOT NULL DEFAULT 1;
ALTER TABLE agent_turns ADD COLUMN end_checkpoint TEXT;
ALTER TABLE agent_turns ADD COLUMN attached TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_turns ADD COLUMN last_call INTEGER;
ALTER TABLE agent_sessions ADD COLUMN model TEXT;
CREATE TABLE message_feedback (turn INTEGER PRIMARY KEY, value TEXT NOT NULL, time TEXT NOT NULL);
""",
)
TRIGGER_MIGRATION = Migration(
    "agent_turns_trigger_001",
    """
ALTER TABLE agent_turns ADD COLUMN origin TEXT NOT NULL DEFAULT 'person';
ALTER TABLE agent_turns ADD COLUMN model_text TEXT;
ALTER TABLE agent_turns ADD COLUMN task TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_turns ADD COLUMN target TEXT;
ALTER TABLE agent_turns ADD COLUMN context TEXT;
""",
)
FINISHED = {"done", "failed", "stopped"}
ORIGIN_NOTES = {
    PERSON: "The person sent this message, and they're there to reply.",
    "mail": "New mail arrived, and this run started by itself. Nobody is waiting in the chat.",
    "mail-hourly": "The hourly check started this run by itself. Nobody is waiting in the chat.",
    "mail-review": "The inbox review came due, and this run started by itself. Nobody is waiting in the chat.",
    "mail-learn": "You're reading past mail to learn about the person. Nobody is waiting in the chat.",
    "schedule": "A schedule came due, and this run started by itself. Nobody is waiting in the chat.",
    "event": "Something happened that the person asked to hear about, and this run started by itself. Nobody is waiting in the chat.",
}
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
        self.connection = connect_raw(
            path, ctx.config.database_key, factory=StandardErrorsConnection
        )
        self.saver = SqliteSaver(self.connection)
        self.closing = False
        # Set by what hands out triggered work, which needs to know when a run is over.
        self.on_turn_end: Any = None
        self.on_hold: Any = None

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

    def create(
        self,
        title: str | None,
        context: list[str],
        agent: str = "session",
        model: str | None = None,
    ) -> SessionRow:
        session = uuid.uuid4().hex
        scratch_folder(self.ctx.config.home, session)
        now = _now()
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO agent_sessions (id, title, agent, status, created, updated, context, model) VALUES (?, ?, ?, 'done', ?, ?, ?, ?)",
                (session, title or "New session", agent, now, now, json.dumps(context), model),
            )
            work.emit(
                "session.changed", {"id": session}, source="agent", trace_id=self.ctx.trace_id
            )
        return self.row(session)

    def view(self, session: str) -> SessionView:
        row = self.row(session)
        turns = self.db.fetch_all(
            "SELECT t.*, f.value AS feedback FROM agent_turns t"
            " LEFT JOIN message_feedback f ON f.turn = t.id"
            " WHERE t.session = ? AND t.chosen = 1 ORDER BY t.id",
            (session,),
        )
        assembled = []
        active = False
        for turn in turns:
            if not turn["closed"]:
                # The open turn comes through the stream, so it isn't drawn twice.
                active = True
                assembled.append(
                    {
                        "id": turn["id"],
                        "text": turn["text"],
                        "created": turn["created"],
                        "origin": turn["origin"],
                        "parts": [],
                    }
                )
                continue
            parts = self.db.fetch_all(
                "SELECT part FROM agent_parts WHERE turn = ? ORDER BY id", (turn["id"],)
            )
            assembled.append(
                {
                    "id": turn["id"],
                    "text": turn["text"],
                    "created": turn["created"],
                    "parts": [json.loads(p["part"]) for p in parts],
                    "feedback": turn["feedback"],
                    "origin": turn["origin"],
                    "thread": _thread_of(turn["target"]),
                }
            )
        if assembled:
            assembled[-1]["versions"] = self._versions(session, assembled[-1]["id"])
        compactions = self.db.fetch_all(
            "SELECT after_turn, time, before_tokens, after_tokens, how FROM session_compactions"
            " WHERE session = ? ORDER BY id",
            (session,),
        )
        return SessionView(
            session=row,
            messages=ui_stream.assemble_messages(assembled),
            active=active,
            compactions=[SessionCompaction(**dict(entry)) for entry in compactions],
        )

    def active_turn(self, session: str) -> int | None:
        rows = self.db.fetch_all(
            "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
            (session,),
        )
        return int(rows[0]["id"]) if rows else None

    # Running

    def context_text(self, session: str) -> str:
        """What the person attached, as data for the model. Reading it counts as reading mail."""
        rows = self.db.fetch_all("SELECT context FROM agent_sessions WHERE id = ?", (session,))
        refs = json.loads(rows[0]["context"]) if rows else []
        blocks = [resolve_context(self.ctx, ref) for ref in refs]
        if not blocks:
            return ""
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE agent_sessions SET untrusted = 1, context = '[]' WHERE id = ?", (session,)
            )
        return "<untrusted>\n" + "\n\n".join(blocks) + "\n</untrusted>\n\n"

    def _latest_checkpoint(self, session: str) -> str | None:
        found = self.saver.get_tuple({"configurable": {"thread_id": session}})
        return str(found.config["configurable"]["checkpoint_id"]) if found else None

    def _versions(self, session: str, turn: int) -> dict[str, Any] | None:
        """The other answers to this message, once it has been tried again."""
        rows = self.db.fetch_all(
            "SELECT COALESCE(retry_of, id) AS root FROM agent_turns WHERE id = ?", (turn,)
        )
        if not rows:
            return None
        found = self.db.fetch_all(
            "SELECT id FROM agent_turns WHERE session = ? AND (id = ? OR retry_of = ?) ORDER BY id",
            (session, rows[0]["root"], rows[0]["root"]),
        )
        turns = [row["id"] for row in found]
        return {"turns": turns, "current": turns.index(turn)} if len(turns) > 1 else None

    def _last_chosen(self, session: str) -> Any | None:
        rows = self.db.fetch_all(
            "SELECT * FROM agent_turns WHERE session = ? AND chosen = 1 ORDER BY id DESC LIMIT 1",
            (session,),
        )
        return rows[0] if rows else None

    def require_personal(self, session: str) -> SessionRow:
        """Managed histories only change through their triggers, questions and approvals."""
        row = self.row(session)
        if row.agent != "session":
            raise CommandError(
                "session.managed",
                "This agent chat is protected. Answer its questions here, or start a new chat.",
                409,
            )
        return row

    def send(self, session: str, text: str, retry: bool = False) -> int:
        self.require_personal(session)
        return self.dispatch(TurnRequest(session, text), retry)

    def dispatch(self, request: TurnRequest, retry: bool = False) -> int:
        """The one way an agent starts, for a typed message, an event or the clock."""
        session = request.session
        row = self.row(session)
        with self.lock:
            if self.active_turn(session) is not None:
                raise CommandError(
                    "session.busy", "This session is still working. Wait for it, or stop it.", 409
                )
            last = self._last_chosen(session)
            retry_of: int | None = None
            messages: list[Any] = []
            if retry:
                if last is None:
                    raise CommandError("session.no_message", "There's nothing to try again.", 404)
                retry_of = int(last["retry_of"] or last["id"])
                request = TurnRequest(
                    session,
                    last["text"],
                    last["origin"],
                    last["model_text"],
                    last["task"],
                    json.loads(last["target"]) if last["target"] else None,
                    json.loads(last["context"]) if last["context"] else None,
                )
                attached = last["attached"]
                start_from = last["checkpoint"]
                checkpoint = start_from
                # It was the first message, so there's nothing earlier to go back to.
                if start_from is None:
                    messages.append(RemoveMessage(id=REMOVE_ALL_MESSAGES))
            else:
                attached = self.context_text(session)
                # Always from the end of the answer on screen. That may not be the newest thing
                # saved, after going back to an earlier answer or holding a run for the model.
                start_from = last["end_checkpoint"] if last else None
                checkpoint = start_from or self._latest_checkpoint(session)
                if last is None and checkpoint is not None:
                    messages.append(RemoveMessage(id=REMOVE_ALL_MESSAGES))
                    checkpoint = None
            with self.db.transaction() as tx:
                if retry_of is not None:
                    tx.execute(
                        "UPDATE agent_turns SET chosen = 0 WHERE session = ? AND (id = ? OR retry_of = ?)",
                        (session, retry_of, retry_of),
                    )
                cursor = tx.execute(
                    "INSERT INTO agent_turns (session, text, created, checkpoint, retry_of, attached,"
                    " origin, model_text, task, target, context)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session,
                        request.text,
                        _now(),
                        checkpoint,
                        retry_of,
                        attached,
                        request.origin,
                        request.model_text,
                        request.task,
                        json.dumps(request.target) if request.target else None,
                        json.dumps(request.context) if request.context else None,
                    ),
                )
                turn = int(cursor.lastrowid or 0)
        values: dict[str, Any] = {"status": "queued", "error": None}
        text = request.text
        if row.title == "New session":
            values["title"] = (
                text.strip().splitlines()[0][:TITLE_LENGTH] if text.strip() else row.title
            )
        self._set(session, **values)
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "agent.triggered",
                {"session": session, "turn": turn, "origin": request.origin},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
        told = attached + (request.model_text or text)
        payload = {"messages": [*messages, HumanMessage(content=told)]}
        self._submit(session, turn, payload, start_from)
        return turn

    def _auto_compacted(self, session: str, before: int, after: int) -> None:
        turn = self.active_turn(session)
        if turn is None:
            return
        self.note_compaction(session, turn, before, after, "auto")
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "session.compacted",
                {"session": session},
                source="agent",
                trace_id=self.ctx.trace_id,
            )

    def note_compaction(self, session: str, turn: int, before: int, after: int, how: str) -> None:
        """So the chat can show it happened, where it happened, even after a reload."""
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO session_compactions (session, after_turn, time, before_tokens,"
                " after_tokens, how) VALUES (?, ?, ?, ?, ?, ?)",
                (session, turn, datetime.now(UTC).isoformat(), before, after, how),
            )

    def compact(self, session: str) -> bool:
        """When asked, summarizes what's older than the messages kept. The chat shows it all still."""
        row = self.require_personal(session)
        with self.lock:
            if self.active_turn(session) is not None:
                raise CommandError(
                    "session.busy", "This session is still working. Wait for it, or stop it.", 409
                )
            last = self._last_chosen(session)
            if last is None:
                return False
            agent = self._agent(session, row, tools.RunControl())
            model = GatewayChatModel(
                ctx=self.ctx,
                agent=row.agent,
                session=session,
                layers=prompts_builder.build_layers(self.ctx.config, row.agent),
                model_override=row.model,
            )
            config: dict[str, Any] = {"configurable": {"thread_id": session, "checkpoint_ns": ""}}
            if last["end_checkpoint"]:
                config["configurable"]["checkpoint_id"] = last["end_checkpoint"]
            messages = agent.get_state(config).values.get("messages", [])
            settings = context.load_settings(self.db, self.ctx.config)
            update = context.compact_now(model, settings, messages)
            if update is None:
                return False
            before = context.approximate_tokens(messages)
            saved = agent.update_state(config, update, as_node=context.COMPACT_AS_NODE)
            after = context.approximate_tokens(agent.get_state(saved).values.get("messages", []))
            self.note_compaction(session, last["id"], before, after, "asked")
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE agent_turns SET end_checkpoint = ? WHERE id = ?",
                    (saved["configurable"]["checkpoint_id"], last["id"]),
                )
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "session.compacted",
                {"session": session},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
        return True

    def choose_version(self, session: str, turn: int) -> None:
        self.require_personal(session)
        row = self.db.fetch_all(
            "SELECT COALESCE(retry_of, id) AS root FROM agent_turns WHERE id = ? AND session = ?",
            (turn, session),
        )
        if not row:
            raise CommandError("session.no_message", "That answer no longer exists.", 404)
        with self.lock:
            if self.active_turn(session) is not None:
                raise CommandError(
                    "session.busy", "This session is still working. Wait for it, or stop it.", 409
                )
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE agent_turns SET chosen = (id = ?) WHERE session = ? AND (id = ? OR retry_of = ?)",
                    (turn, session, row[0]["root"], row[0]["root"]),
                )

    def rate(self, turn: int, value: str | None) -> None:
        """Only recorded for now. Nothing changes how the agent behaves because of it."""
        if not self.db.fetch_all("SELECT 1 FROM agent_turns WHERE id = ?", (turn,)):
            raise CommandError("session.no_message", "That answer no longer exists.", 404)
        with self.ctx.bus.unit_of_work() as work:
            if value is None:
                work.tx.execute("DELETE FROM message_feedback WHERE turn = ?", (turn,))
            else:
                work.tx.execute(
                    "INSERT INTO message_feedback (turn, value, time) VALUES (?, ?, ?)"
                    " ON CONFLICT (turn) DO UPDATE SET value = excluded.value, time = excluded.time",
                    (turn, value, _now()),
                )
            work.emit(
                "message.rated",
                {"turn": turn, "value": value},
                source="agent",
                trace_id=self.ctx.trace_id,
            )

    def answer(self, session: str, answer: str) -> None:
        """From the question's card, or typed into the message box while it waits."""
        ask = channel.open_ask(self.db, session)
        if ask is None:
            raise CommandError("session.no_question", "This session isn't asking anything.", 409)
        channel.close(self.ctx, ask["id"], "answered", answer)
        self.answered(session)

    def _submit(self, session: str, turn: int, payload: Any, checkpoint: str | None = None) -> None:
        self.pool.submit(self._run, session, turn, payload, checkpoint)

    def _capabilities(self) -> str:
        """So the agent plans around what's there, rather than finding out from a refused tool."""
        _, accounts_found = accounts.read_accounts(self.ctx.config)
        engine = semantic.engine()
        status = engine.status() if engine is not None else None
        if status is None or not status.ready:
            meaning = (
                "Search by meaning is off, so search by keyword. Say results may be incomplete."
            )
        else:
            parts = [f"{index.indexed} of {index.total} {index.kind}s" for index in status.indexes]
            meaning = f"Search by meaning is on, covering {' and '.join(parts)} so far."
        mail = "Mail is connected." if accounts_found else "No mail account is connected yet."
        return f"Available right now:\n- {mail}\n- {meaning}"

    def _agent(self, session: str, row: SessionRow, control: tools.RunControl) -> Any:
        config = self.ctx.config
        latest = self.db.fetch_all(
            "SELECT text, task, origin, context, target FROM agent_turns WHERE session = ? ORDER BY id DESC LIMIT 1",
            (session,),
        )
        turn = latest[0] if latest else None
        origin = turn["origin"] if turn else PERSON
        task = turn["task"] if turn else ""
        layers = knowledge.layers_for(
            self.ctx,
            row.agent,
            f"{turn['text']}\n{task}" if turn else "",
            self._capabilities(),
            scratch=str(config.home / "scratch" / session),
        )
        now = datetime.now().astimezone()
        note = ORIGIN_NOTES.get(origin, ORIGIN_NOTES["schedule"])
        layers.append(
            Layer("This run", f"{note}\nNow: {now.strftime('%A %d %B %Y %H:%M')} ({now.tzname()})")
        )
        model = GatewayChatModel(
            ctx=self.ctx, agent=row.agent, session=session, layers=layers, model_override=row.model
        )
        settings = context.load_settings(self.db, config)
        own = json.loads(turn["context"]) if turn and turn["context"] else None
        profile: ContextProfile = context.profile_for(settings, origin, own)
        return create_agent(
            model,
            tools.build_tools(
                self.ctx,
                session,
                control,
                tools.allowed_for(row.agent, origin, bool(turn and turn["target"])),
            ),
            middleware=context.middleware(
                model,
                settings,
                profile,
                task,
                on_compacted=lambda before, after: self._auto_compacted(session, before, after),
            ),
            checkpointer=self.saver,
        )

    def _run(self, session: str, turn: int, payload: Any, checkpoint: str | None = None) -> None:
        if self.closing:
            return
        live = _Live()
        with self.lock:
            self.live[session] = live
        started = bool(
            self.db.fetch_all("SELECT 1 FROM agent_parts WHERE turn = ? LIMIT 1", (turn,))
        )
        translator = ui_stream.UiTranslator(
            started=started,
            declined_text=tools.DENIED,
            citations=citations.Citations(self.ctx, turn),
            metadata={
                "turn": turn,
                "versions": self._versions(session, turn),
                "thread": self._turn_thread(turn),
            },
        )
        self._append(turn, translator.start())
        self._set(session, status="running", step=None)
        configurable = {"thread_id": session}
        if checkpoint:
            configurable["checkpoint_id"] = checkpoint
        config = {
            "configurable": configurable,
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
                self._set(session, status="waiting", step="Waiting for you")
                return
            self._finish(session, turn, translator, "done", None, "finish")
        except (
            providers.ModelUnavailable,
            providers.ModelNotConfigured,
            gateway.DailyCapReached,
        ) as error:
            if not self._hold(session, turn, str(error)):
                self._finish(session, turn, translator, "failed", str(error), "error")
        except (providers.ModelFlagged, guard.DamagedToken, guard.GuardBlocked) as error:
            self._finish(session, turn, translator, "failed", str(error), "error")
        except gateway.RunLimitReached as error:
            self._finish(session, turn, translator, "stopped", str(error), "error")
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

    def _hold(self, session: str, turn: int, why: str) -> bool:
        """With no model, a triggered run takes itself back and waits in line, leaving no trace.

        There's nobody to tell, and it starts over from the same place when the model returns.
        A person gets the error in the chat instead, so they know.
        """
        rows = self.db.fetch_all("SELECT origin FROM agent_turns WHERE id = ?", (turn,))
        if not rows or rows[0]["origin"] == PERSON or self.on_hold is None:
            return False
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE trigger_runs SET status = 'pending', turn = NULL, session = NULL WHERE turn = ?",
                (turn,),
            )
            tx.execute("DELETE FROM agent_parts WHERE turn = ?", (turn,))
            tx.execute("DELETE FROM agent_turns WHERE id = ?", (turn,))
        self.notifier.wake(turn)
        self._set(session, status="done", step=None)
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "agent.held",
                {"session": session, "turn": turn},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
        self.on_hold(why)
        return True

    def _turn_thread(self, turn: int) -> int | None:
        rows = self.db.fetch_all("SELECT target FROM agent_turns WHERE id = ?", (turn,))
        return _thread_of(rows[0]["target"]) if rows else None

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
        if translator.citations is not None:
            parts += translator.citations.part()
        if ending == "error":
            parts.append({"type": "error", "errorText": error or "Something went wrong."})
        elif ending == "abort":
            parts.append({"type": "abort"})
        else:
            parts.append({"type": "finish"})
        self._append(turn, parts)
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE agent_turns SET end_checkpoint = ?,"
                " last_call = (SELECT MAX(id) FROM model_calls WHERE session = ?) WHERE id = ?",
                (self._latest_checkpoint(session), session, turn),
            )
        self._close_turn(turn)
        self._record_usage(session)
        self._set(session, status=status, error=error, step=None)
        if self.on_turn_end is not None:
            self.on_turn_end(turn, error)

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

    def answered(self, session: str) -> None:
        """A question in the channel got its answer."""
        turn = self.active_turn(session)
        if turn is not None:
            self._resume_if_ready(session, turn)

    def _settle(self, row: Any, approved: bool) -> None:
        """Records one decision. The run carries on once everything it's waiting on is decided."""
        status = "approved" if approved else "denied"
        session = row["session"]
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE tool_approvals SET status = ? WHERE id = ?", (status, row["id"])
            )
            work.emit(
                "approval.changed",
                {"id": row["id"], "status": status},
                source="agent",
                trace_id=self.ctx.trace_id,
            )
        turn = self.active_turn(session)
        if turn is None:
            return
        self._append(
            turn,
            [
                {
                    "type": "tool-approval-response",
                    "approvalId": str(row["id"]),
                    "approved": approved,
                    "toolCallId": row["tool_call_id"],
                }
            ],
        )
        if not approved:
            self._append(turn, [{"type": "tool-output-denied", "toolCallId": row["tool_call_id"]}])

    def _carry_on(self, session: str) -> None:
        turn = self.active_turn(session)
        if turn is not None:
            self._resume_if_ready(session, turn)

    def _remember(self, row: Any) -> list[Any]:
        """Allows this kind for the session, and everything of that kind already waiting."""
        if not policy.can_remember(row["tool"], self.row(row["session"]).untrusted):
            return []
        policy.allow_for_session(self.db, row["session"], row["kind"])
        return self.db.fetch_all(
            "SELECT * FROM tool_approvals WHERE session = ? AND kind = ? AND status = 'pending'"
            " AND id != ?",
            (row["session"], row["kind"], row["id"]),
        )

    def decide(self, approval: int, choice: str) -> None:
        rows = self.db.fetch_all("SELECT * FROM tool_approvals WHERE id = ?", (approval,))
        if not rows:
            raise CommandError("approval.not_found", "That approval no longer exists.", 404)
        row = rows[0]
        if row["status"] != "pending":
            raise CommandError("approval.decided", "That has already been decided.", 409)
        also = self._remember(row) if choice == "session" else []
        self._settle(row, choice != "deny")
        for other in also:
            self._settle(other, True)
        self._carry_on(row["session"])

    def decide_many(self, allow: list[int], deny: list[int], remember: bool) -> None:
        sessions = set()
        for identifiers, approved in ((deny, False), (allow, True)):
            for identifier in identifiers:
                rows = self.db.fetch_all(
                    "SELECT * FROM tool_approvals WHERE id = ? AND status = 'pending'",
                    (identifier,),
                )
                # Another window may have decided it first, and that answer stands.
                if not rows:
                    continue
                sessions.add(rows[0]["session"])
                if approved and remember:
                    for other in self._remember(rows[0]):
                        if other["id"] not in deny:
                            self._settle(other, True)
                self._settle(rows[0], approved)
        for session in sessions:
            self._carry_on(session)

    def _resume_if_ready(self, session: str, turn: int) -> None:
        # Others from the same step may still wait. The run continues once they're all decided.
        interrupts = self._pending_interrupts(session)
        answers = {item_id: self._answer_for(value) for item_id, value in interrupts}
        if not answers or any(answer is None for answer in answers.values()):
            return
        self._set(session, status="queued", step=None)
        self._submit(session, turn, Command(resume=answers))

    def _pending_interrupts(self, session: str) -> list[tuple[str, dict[str, Any]]]:
        agent = self._agent(session, self.row(session), tools.RunControl())
        snapshot = agent.get_state({"configurable": {"thread_id": session}})
        return [(item.id, item.value) for task in snapshot.tasks for item in task.interrupts]

    def _answer_for(self, value: dict[str, Any]) -> str | None:
        if "approval" in value:
            rows = self.db.fetch_all(
                "SELECT status FROM tool_approvals WHERE id = ?", (value["approval"],)
            )
            status = rows[0]["status"] if rows else "denied"
            return None if status == "pending" else str(status)
        if "channel" in value:
            row = channel.get(self.db, value["channel"])
            if row["status"] == "open":
                return None
            return (
                str(row["answer"])
                if row["status"] == "answered"
                else "They skipped this. Use your best judgement."
            )
        return "denied"

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
            said = self.db.fetch_all(
                "SELECT text, model_text FROM agent_turns WHERE id = ?", (turn,)
            )[0]
            turn_text = said["model_text"] or said["text"]
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


def _thread_of(target: str | None) -> int | None:
    return json.loads(target).get("thread") if target else None


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
        model=row["model"],
    )


def resolve_context(ctx: Context, ref: str) -> str:
    """The text behind an attached item, such as thread:12, document:u:3, task:4 or text:..."""
    kind, _, value = ref.partition(":")
    if kind == "text":
        return f"Selected text:\n{value}"
    if kind == "thread":
        view = store.thread_view(ctx.bus.db, int(value))
        if view is None:
            return ""
        body = "\n\n".join(
            f"From {m.from_name} <{m.from_addr}>\n{m.own_text}"
            for m in view.messages[-ctx.config.agent.max_recent_thread_messages :]
        )
        return f"Mail conversation {value}: {view.thread.subject}\n{body}"[
            : ctx.config.agent.max_thread_chars
        ]
    if kind == "document":
        try:
            return f"Document {value}:\n{tools.get_document(GetDocument(key=value), ctx).text}"[
                : ctx.config.agent.max_thread_chars
            ]
        except CommandError:
            return ""
    if kind == "task":
        rows = ctx.bus.db.fetch_all(
            "SELECT title, notes, due, thread FROM tasks WHERE id = ?", (int(value),)
        )
        if not rows:
            return ""
        return f"Task {value}: {rows[0]['title']}\nDue: {rows[0]['due']}\nNotes: {rows[0]['notes']}\nConversation: {rows[0]['thread']}"
    return ""


def context_label(ctx: Context, ref: str) -> str:
    kind, _, value = ref.partition(":")
    if kind == "thread":
        rows = ctx.bus.db.fetch_all("SELECT subject FROM threads WHERE id = ?", (int(value),))
        return rows[0]["subject"] if rows else value
    if kind == "document":
        try:
            return tools.get_document(GetDocument(key=value), ctx).document.name
        except CommandError:
            return value
    if kind == "task":
        rows = ctx.bus.db.fetch_all("SELECT title FROM tasks WHERE id = ?", (int(value),))
        return rows[0]["title"] if rows else value
    return value[:60]


def approvals_view(db: Any) -> ApprovalList:
    rows = db.fetch_all(
        "SELECT a.*, s.title AS session_title, s.untrusted AS untrusted FROM tool_approvals a JOIN agent_sessions s ON s.id = a.session"
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
                preview=approval_view.describe(row["tool"], row["summary"], row["detail"]),
                undoable=bool(row["undoable"]),
                status=row["status"],
                time=row["time"],
                tool_label=(
                    policy.TOOLS_BY_NAME[row["tool"]].label
                    if row["tool"] in policy.TOOLS_BY_NAME
                    else row["tool"].replace("_", " ")
                ),
                can_remember=policy.can_remember(row["tool"], bool(row["untrusted"])),
            )
            for row in rows
        ]
    )
