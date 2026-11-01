"""The one door for model calls. Nothing else in the app talks to a model."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from nexusai.contracts.agent import ModelCallView, PromptLayerView, UsageRow, UsageView
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import guard as guards
from nexusai.modules.agent.guard import DataGuard
from nexusai.modules.agent.providers import (
    Message,
    ModelFlagged,
    ModelNotConfigured,
    ModelProvider,
    ModelRequest,
    ModelUnavailable,
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

    result = GatewayResult(call_id=call_id)
    restorer = guard.stream_restorer()
    parts: list[str] = []
    raw_calls: list[ToolCall] = []

    def emit(text: str) -> None:
        if text:
            parts.append(text)
            if on_text:
                on_text(text)

    def finish(status: str, error: str | None) -> None:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE model_calls SET status = ?, error = ?, input_tokens = ?, output_tokens = ? WHERE id = ?",
                (status, error, result.usage.input_tokens, result.usage.output_tokens, call_id),
            )

    try:
        for chunk in provider.stream(request):
            if isinstance(chunk, TextChunk):
                emit(restorer.feed(chunk.text))
            elif isinstance(chunk, ToolCall):
                raw_calls.append(chunk)
            elif isinstance(chunk, Usage):
                result.usage = chunk
        emit(restorer.finish())
        result.text = "".join(parts)
        result.tool_calls = [
            ToolCall(call.id, call.name, guard.restore_arguments(call.arguments))
            for call in raw_calls
        ]
    except (ModelUnavailable, ModelFlagged, ModelNotConfigured, guards.DamagedToken) as error:
        status = "flagged" if isinstance(error, ModelFlagged) else "failed"
        finish(status, str(error))
        log.info("model_call_failed", agent=agent, kind=type(error).__name__)
        raise
    finish("done", None)
    _warn_near_cap(ctx, cap)
    log.info("model_call", agent=agent, provider=provider.name, tokens=result.usage.output_tokens)
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
