"""The one door for model calls. Nothing else in the app talks to a model."""

import json
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from nexusai.contracts.agent import (
    GenerationPhase,
    GenerationState,
    GetGeneration,
    ModelCallView,
    PromptLayerView,
    UsageRow,
    UsageView,
)
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import guard as guards
from nexusai.modules.agent.guard import DataGuard
from nexusai.modules.agent.providers import (
    Chunk,
    Message,
    ModelFlagged,
    ModelProvider,
    ModelRateLimited,
    ModelRequest,
    ReasoningChunk,
    TextChunk,
    ToolCall,
    ToolSpec,
    Usage,
    active_provider,
)

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_gateway_001",
    """
CREATE TABLE model_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, day TEXT NOT NULL, session TEXT, agent TEXT NOT NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, layers TEXT NOT NULL, status TEXT NOT NULL, error TEXT);
CREATE INDEX model_calls_day ON model_calls (day, agent);
CREATE INDEX model_calls_session ON model_calls (session, id);
CREATE TABLE model_limits (id INTEGER PRIMARY KEY CHECK (id = 1), daily_cap INTEGER NOT NULL);
""",
)
NEAR_CAP_SHARE = 0.8

GENERATION_MIGRATION = Migration(
    "model_generation_001",
    """
CREATE TABLE model_generation (
  call_id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, session TEXT, phase TEXT NOT NULL);
CREATE INDEX model_generation_trace ON model_generation (trace_id, call_id);
CREATE INDEX model_generation_session ON model_generation (session, call_id);
""",
)


def generation_state(ctx: Context, query: GetGeneration) -> GenerationState:
    if not query.trace_id and not query.session:
        return GenerationState()
    field, value = ("trace_id", query.trace_id) if query.trace_id else ("session", query.session)
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM model_generation WHERE {field} = ? ORDER BY call_id DESC LIMIT 1",
        (value,),
    )
    return GenerationState.model_validate(dict(rows[0])) if rows else GenerationState()


def _generation(ctx: Context, call_id: int, session: str | None, phase: GenerationPhase) -> None:
    state = GenerationState(call_id=call_id, trace_id=ctx.trace_id, session=session, phase=phase)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO model_generation VALUES (?, ?, ?, ?)"
            " ON CONFLICT(call_id) DO UPDATE SET phase = excluded.phase",
            (call_id, ctx.trace_id, session, phase),
        )
        work.emit("generation.changed", state.model_dump(), source="agent", trace_id=ctx.trace_id)


RUN_LIMIT_MIGRATION = Migration(
    "agent_gateway_run_limits_001",
    "CREATE TABLE model_run_limits (session TEXT PRIMARY KEY, token_limit INTEGER NOT NULL);",
)
RUN_LIMIT_SINCE_MIGRATION = Migration(
    "gateway_run_limit_since_001",
    "ALTER TABLE model_run_limits ADD COLUMN since INTEGER NOT NULL DEFAULT 0;",
)


class RunLimitReached(Exception):
    """This run has used what the person allowed it. What it already did is kept."""


class DailyCapReached(Exception):
    pass


@dataclass(frozen=True)
class Layer:
    name: str
    text: str


@dataclass
class GatewayResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    call_id: int = 0


TextListener = Callable[[str], None]
ProviderResolver = Callable[[Context], tuple[ModelProvider, str]]
# Tests swap this for a fake, so no test can reach a real model.
resolve_provider: ProviderResolver = active_provider


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def daily_cap(db: Database, default: int) -> int:
    rows = db.fetch_all("SELECT daily_cap FROM model_limits")
    return int(rows[0]["daily_cap"]) if rows else default


def used_today(db: Database) -> int:
    rows = db.fetch_all(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS used FROM model_calls WHERE day = ?",
        (_today(),),
    )
    return int(rows[0]["used"])


def _mask_message(guard: DataGuard, message: Message) -> Message:
    return Message(
        role=message.role,
        text=guard.mask(message.text),
        tool_call_id=message.tool_call_id,
        tool_calls=[
            ToolCall(call.id, call.name, guard.mask_value(call.arguments))
            for call in message.tool_calls
        ],
    )


def _mask_tool(guard: DataGuard, tool: ToolSpec) -> ToolSpec:
    return ToolSpec(tool.name, guard.mask(tool.description), guard.mask_value(tool.parameters))


def _message_text(message: Message) -> str:
    parts = [message.text] if message.text else []
    parts += [f"[calls {call.name}] {json.dumps(call.arguments)}" for call in message.tool_calls]
    return "\n".join(parts)


def set_run_limit(db: Database, session: str, token_limit: int) -> None:
    """For the run about to start. A chat can run many times, so earlier runs don't count."""
    with db.transaction() as tx:
        if not token_limit:
            tx.execute("DELETE FROM model_run_limits WHERE session = ?", (session,))
            return
        tx.execute(
            "INSERT INTO model_run_limits (session, token_limit, since)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(id), 0) FROM model_calls))"
            " ON CONFLICT (session) DO UPDATE SET token_limit = excluded.token_limit, since = excluded.since",
            (session, token_limit),
        )


def _check_run_limit(db: Database, session: str | None) -> None:
    """Checked before each call, so a run can pass its limit by at most the call in progress."""
    if not session:
        return
    limits = db.fetch_all(
        "SELECT token_limit, since FROM model_run_limits WHERE session = ?", (session,)
    )
    if not limits:
        return
    limit = int(limits[0]["token_limit"])
    used = db.fetch_all(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS used FROM model_calls"
        " WHERE session = ? AND id > ?",
        (session, limits[0]["since"]),
    )
    if int(used[0]["used"]) >= limit:
        raise RunLimitReached(f"Stopped at its limit of {limit} tokens. What it finished is kept.")


class CallPacer:
    """Keeps model calls within what the server allows, across every agent in the app."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.recent: deque[float] = deque()
        self.not_before = 0.0

    def seconds_to_wait(self) -> float:
        """How long the server asked everyone to wait, which can be long."""
        return max(0.0, self.not_before - time.monotonic())

    def told_to_wait(self, seconds: float) -> None:
        with self.lock:
            self.not_before = max(self.not_before, time.monotonic() + seconds)

    def take_turn(self, per_minute: int, longest_wait: float) -> None:
        """Waits for a free slot. A wait too long to sit through goes back to whoever asked."""
        while True:
            with self.lock:
                now = time.monotonic()
                while self.recent and now - self.recent[0] >= CALL_WINDOW_SECONDS:
                    self.recent.popleft()
                wait = self.not_before - now
                if per_minute and len(self.recent) >= per_minute:
                    wait = max(wait, self.recent[0] + CALL_WINDOW_SECONDS - now)
                if wait <= 0:
                    self.recent.append(now)
                    return
            if wait > longest_wait:
                raise ModelRateLimited("The model server is limiting calls right now.", wait)
            time.sleep(min(wait, PACER_CHECK_SECONDS))


CALL_WINDOW_SECONDS = 60.0
PACER_CHECK_SECONDS = 1.0
pacer = CallPacer()


def _within_limits(
    ctx: Context,
    provider: ModelProvider,
    request: ModelRequest,
    phase: Callable[[GenerationPhase], None],
) -> Iterator[Chunk]:
    """Waits its turn, and tries again if told to slow down before anything came back."""
    config = ctx.config.agent
    for attempt in range(config.rate_limit_retries + 1):
        phase("queued")
        pacer.take_turn(config.model_calls_per_minute, config.rate_limit_longest_wait)
        try:
            phase("generating")
            yield from provider.stream(request)
            return
        except ModelRateLimited as error:
            wait = error.retry_after or config.rate_limit_wait_seconds * 2**attempt
            pacer.told_to_wait(wait)
            log.info("model_rate_limited", attempt=attempt, wait=wait)
            if attempt == config.rate_limit_retries or wait > config.rate_limit_longest_wait:
                raise


def stream_model(
    ctx: Context,
    *,
    agent: str,
    session: str | None,
    layers: list[Layer],
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    model_override: str | None = None,
) -> Iterator[Chunk]:
    """Every prompt layer, message and tool description is masked before it leaves.

    Whatever returns is restored: text as it streams, and tool arguments before any tool sees them.
    A damaged token in tool arguments raises DamagedToken, so that tool never runs.
    """
    db = ctx.bus.db
    guard = DataGuard(db, guards.load_rules(ctx.config.home))
    cap = daily_cap(db, ctx.config.agent.daily_token_cap)
    if cap and used_today(db) >= cap:
        raise DailyCapReached(
            "Today's model limit is used up. Raise it in Settings, or wait until tomorrow."
        )
    _check_run_limit(db, session)

    provider, default_model = resolve_provider(ctx)
    model = model_override or default_model
    masked_layers = [Layer(layer.name, guard.mask(layer.text)) for layer in layers]
    masked_messages = [_mask_message(guard, message) for message in messages]
    masked_tools = [_mask_tool(guard, tool) for tool in tools or []]
    request = ModelRequest(
        model=model,
        instructions="\n\n".join(layer.text for layer in masked_layers),
        messages=masked_messages,
        tools=masked_tools,
    )
    views = [
        {"name": layer.name, "real": layer.text, "masked": masked.text}
        for layer, masked in zip(layers, masked_layers, strict=True)
    ]
    if messages:
        views.append(
            {
                "name": "Task content",
                "real": "\n\n".join(_message_text(m) for m in messages),
                "masked": "\n\n".join(_message_text(m) for m in masked_messages),
            }
        )
    with db.transaction() as tx:
        cursor = tx.execute(
            "INSERT INTO model_calls (time, day, session, agent, provider, model, layers, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'running')",
            (
                datetime.now(UTC).isoformat(),
                _today(),
                session,
                agent,
                provider.name,
                model,
                json.dumps(views),
            ),
        )
        call_id = int(cursor.lastrowid or 0)

    usage = Usage()
    restorer = guard.stream_restorer()
    thought = guard.stream_restorer()
    raw_calls: list[ToolCall] = []

    def finish(status: str, error: str | None) -> None:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE model_calls SET status = ?, error = ?, input_tokens = ?, output_tokens = ? WHERE id = ?",
                (status, error, usage.input_tokens, usage.output_tokens, call_id),
            )

    last_phase: GenerationPhase | None = None

    def phase(value: GenerationPhase) -> None:
        nonlocal last_phase
        if last_phase != value:
            _generation(ctx, call_id, session, value)
            last_phase = value

    try:
        for chunk in _within_limits(ctx, provider, request, phase):
            if isinstance(chunk, TextChunk):
                text = restorer.feed(chunk.text)
                if text:
                    yield TextChunk(text)
            elif isinstance(chunk, ReasoningChunk):
                text = thought.feed(chunk.text)
                if text:
                    yield ReasoningChunk(text)
            elif isinstance(chunk, ToolCall):
                raw_calls.append(chunk)
            elif isinstance(chunk, Usage):
                usage = chunk
        text = thought.finish()
        if text:
            yield ReasoningChunk(text)
        text = restorer.finish()
        if text:
            yield TextChunk(text)
        for call in raw_calls:
            yield ToolCall(call.id, call.name, guard.restore_arguments(call.arguments))
    except Exception as error:
        status = "flagged" if isinstance(error, ModelFlagged) else "failed"
        finish(status, str(error))
        phase("failed")
        log.info("model_call_failed", agent=agent, kind=type(error).__name__)
        raise
    except GeneratorExit:
        finish("stopped", None)
        phase("stopped")
        raise
    finish("done", None)
    phase("done")
    _warn_near_cap(ctx, cap)
    log.info("model_call", agent=agent, provider=provider.name, tokens=usage.output_tokens)
    yield usage


def call_model(
    ctx: Context,
    *,
    agent: str,
    session: str | None,
    layers: list[Layer],
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    on_text: TextListener | None = None,
    model_override: str | None = None,
) -> GatewayResult:
    """The whole reply at once, for work with no one watching it arrive."""
    result = GatewayResult()
    parts: list[str] = []
    for chunk in stream_model(
        ctx,
        agent=agent,
        session=session,
        layers=layers,
        messages=messages,
        tools=tools,
        model_override=model_override,
    ):
        if isinstance(chunk, TextChunk):
            parts.append(chunk.text)
            if on_text:
                on_text(chunk.text)
        elif isinstance(chunk, ToolCall):
            result.tool_calls.append(chunk)
        elif isinstance(chunk, Usage):
            result.usage = chunk
    result.text = "".join(parts)
    rows = ctx.bus.db.fetch_all("SELECT MAX(id) AS id FROM model_calls WHERE agent = ?", (agent,))
    result.call_id = int(rows[0]["id"] or 0)
    return result


def _warn_near_cap(ctx: Context, cap: int) -> None:
    if not cap or used_today(ctx.bus.db) < cap * NEAR_CAP_SHARE:
        return
    day = _today()
    with ctx.bus.unit_of_work() as work:
        seen = work.tx.execute(
            "SELECT 1 FROM notifications WHERE kind = 'usage' AND time LIKE ?", (f"{day}%",)
        ).fetchone()
        if seen:
            return
        work.emit(
            "notification.requested",
            NotificationRequested(
                kind="usage",
                title="Close to today's model limit",
                detail="The agent stops when the limit is reached. You can raise it in Settings.",
                link="/settings?section=models",
            ).model_dump(),
            source="agent",
            trace_id=ctx.trace_id,
        )


def call_view(db: Database, query_id: int | None, session: str | None) -> ModelCallView | None:
    if query_id is not None:
        rows = db.fetch_all("SELECT * FROM model_calls WHERE id = ?", (query_id,))
    else:
        rows = db.fetch_all(
            "SELECT * FROM model_calls WHERE session = ? ORDER BY id DESC LIMIT 1", (session,)
        )
    if not rows:
        return None
    row = rows[0]
    layers = [PromptLayerView(**layer) for layer in json.loads(row["layers"])]
    return ModelCallView(
        id=row["id"],
        time=row["time"],
        session=row["session"],
        agent=row["agent"],
        provider=row["provider"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        layers=layers,
        status=row["status"],
        error=row["error"],
    )


def usage_view(ctx: Context) -> UsageView:
    db = ctx.bus.db
    rows = db.fetch_all(
        "SELECT agent, SUM(input_tokens) AS i, SUM(output_tokens) AS o, COUNT(*) AS c FROM model_calls"
        " WHERE day = ? GROUP BY agent ORDER BY agent",
        (_today(),),
    )
    used = used_today(db)
    cap = daily_cap(db, ctx.config.agent.daily_token_cap)
    return UsageView(
        today=[
            UsageRow(agent=r["agent"], input_tokens=r["i"], output_tokens=r["o"], calls=r["c"])
            for r in rows
        ],
        total_today=used,
        daily_cap=cap,
        near_cap=bool(cap and used >= cap * NEAR_CAP_SHARE),
    )


def set_cap(db: Database, cap: int) -> None:
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO model_limits (id, daily_cap) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET daily_cap = excluded.daily_cap",
            (cap,),
        )
