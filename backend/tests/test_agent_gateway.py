from collections.abc import Iterator
from typing import Any

import pytest

from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.home import create_home
from nexusai.kernel.module import Context
from nexusai.modules.agent import gateway, guard
from nexusai.modules.agent.gateway import DailyCapReached, Layer, call_model
from nexusai.modules.agent.guard import DamagedToken, DataGuard, GuardBlocked, default_rules
from nexusai.modules.agent.providers import (
    Message,
    ModelFlagged,
    ModelRequest,
    ModelUnavailable,
    OpenAiCompatibleProvider,
    TextChunk,
    ToolCall,
    ToolSpec,
    Usage,
    _chat_messages,
    _json_tool_call,
    _responses_input,
)
from nexusai.modules.notifications.module import notifications_module

SECRET = "kim.j@samsung.com"
LINK = "http://wiki.samsung.net/proj-x"
PHONE = "+91 98765 43210"


@pytest.fixture
def ctx(config: Config) -> Iterator[Context]:
    create_home(config.home)
    db = Database(config.database_path)
    db.migrate([guard.MIGRATION, gateway.MIGRATION, *notifications_module.migrations])
    bus = EventBus(db, config)
    yield Context(bus=bus, config=config, trace_id="t")
    db.close()


class FakeProvider:
    name = "fake"

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script = script if script is not None else [TextChunk("ok"), Usage(10, 2)]
        self.requests: list[ModelRequest] = []

    def stream(self, request: ModelRequest) -> Iterator[Any]:
        self.requests.append(request)
        for item in self.script:
            if isinstance(item, Exception):
                raise item
            yield item


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    fake = FakeProvider()
    monkeypatch.setattr(gateway, "resolve_provider", lambda _: (fake, "fake-model"))
    return fake


def everything_sent(request: ModelRequest) -> str:
    calls = [str(call.arguments) for m in request.messages for call in m.tool_calls]
    return " ".join(
        [
            request.instructions,
            *[m.text for m in request.messages],
            *calls,
            *[str(t.parameters) + t.description for t in request.tools],
        ]
    )


def test_rules_catch_the_starter_values(ctx: Context) -> None:
    guarded = DataGuard(ctx.bus.db, default_rules())
    masked = guarded.mask(
        f"Ask {SECRET}, see {LINK} or call {PHONE} and 9876543210. Priya Nair agrees."
    )
    for value in (SECRET, "samsung", "98765", "9876543210"):
        assert value not in masked
    assert "<EMAIL_" in masked and "<INT_URL_" in masked and "<PHONE_" in masked
    assert "Priya Nair" in masked


def test_plain_text_and_ordinary_numbers_are_left_alone(ctx: Context) -> None:
    guarded = DataGuard(ctx.bus.db, default_rules())
    text = "Invoice 1234567 for 2026 at https://example.org/page costs 50000."
    assert guarded.mask(text) == text


def test_tokens_are_stable_and_round_trip(ctx: Context) -> None:
    guarded = DataGuard(ctx.bus.db, default_rules())
    first = guarded.mask(f"{SECRET} and {SECRET}")
    token = first.split()[0]
    assert first == f"{token} and {token}"
    assert DataGuard(ctx.bus.db, default_rules()).mask(SECRET) == token
    assert guarded.restore(f"Contact {token}") == f"Contact {SECRET}"


@pytest.mark.parametrize("sizes", [1, 2, 3, 5, 100])
def test_tokens_split_across_chunks_are_restored(ctx: Context, sizes: int) -> None:
    guarded = DataGuard(ctx.bus.db, default_rules())
    token = guarded.mask(SECRET)
    text = f"Please contact {token} today, {token}."
    restorer = guarded.stream_restorer()
    pieces = [text[i : i + sizes] for i in range(0, len(text), sizes)]
    out = "".join(restorer.feed(piece) for piece in pieces) + restorer.finish()
    assert out == f"Please contact {SECRET} today, {SECRET}."


def test_ordinary_angle_brackets_in_a_stream_arent_lost(ctx: Context) -> None:
    restorer = DataGuard(ctx.bus.db, default_rules()).stream_restorer()
    text = "if a <b and c > d then <html> ok <"
    out = "".join(restorer.feed(c) for c in text) + restorer.finish()
    assert out == text


def test_damaged_tokens_stop_actions_and_arent_guessed(ctx: Context) -> None:
    guarded = DataGuard(ctx.bus.db, default_rules())
    token = guarded.mask(SECRET)
    assert guarded.restore_arguments({"to": [token]}) == {"to": [SECRET]}
    with pytest.raises(DamagedToken):
        guarded.restore_arguments({"to": "<EMAIL_999>"})
    assert guarded.restore("see <EMAIL_999>") == "see <EMAIL_999>"
    assert guarded.restore_arguments({"note": "<NOTATOKEN_1> stays"}) == {
        "note": "<NOTATOKEN_1> stays"
    }


def test_block_rules_refuse_to_send(ctx: Context) -> None:
    rules = default_rules().model_copy(deep=True)
    rules.rules[0].action = "block"
    with pytest.raises(GuardBlocked):
        DataGuard(ctx.bus.db, rules).mask(SECRET)


def test_rule_test_reports_without_saving_tokens(ctx: Context) -> None:
    result = guard.test_rules(default_rules(), f"Ask {SECRET} at {LINK}")
    assert SECRET not in result.masked and {f.rule for f in result.findings} >= {
        "Email addresses",
        "Samsung links and hosts",
    }
    assert ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM guard_tokens")[0]["n"] == 0
    bad = default_rules().model_copy(deep=True)
    bad.rules[0].pattern = "("
    assert guard.test_rules(bad, "x").errors


def test_no_raw_value_reaches_a_provider_from_any_layer(
    ctx: Context, provider: FakeProvider
) -> None:
    call_model(
        ctx,
        agent="mail",
        session="s1",
        layers=[Layer("System", f"You help {SECRET}"), Layer("About me", f"My wiki is {LINK}")],
        messages=[
            Message("user", f"Mail from {SECRET}, phone {PHONE}"),
            Message(
                "assistant",
                "",
                tool_calls=[ToolCall("c1", "read", {"path": LINK, "people": [SECRET]})],
            ),
            Message("tool", f"Result mentions {SECRET}", tool_call_id="c1"),
        ],
        tools=[ToolSpec("send", f"Send like {SECRET}", {"example": SECRET})],
    )
    sent = everything_sent(provider.requests[0])
    for value in (SECRET, "samsung", "98765"):
        assert value not in sent


def test_replies_stream_restored_and_tool_arguments_come_back_real(
    ctx: Context, provider: FakeProvider
) -> None:
    token = DataGuard(ctx.bus.db, default_rules()).mask(SECRET)
    provider.script = [
        TextChunk(f"Ask {token[:4]}"),
        TextChunk(f"{token[4:]} now"),
        ToolCall("c", "send", {"to": [token]}),
        Usage(5, 1),
    ]
    seen: list[str] = []
    result = call_model(
        ctx,
        agent="a",
        session=None,
        layers=[Layer("S", "x")],
        messages=[Message("user", "hi")],
        on_text=seen.append,
    )
    assert result.text == f"Ask {SECRET} now"
    assert "".join(seen) == result.text
    assert not any("<EMAIL" in piece for piece in seen)
    assert result.tool_calls[0].arguments == {"to": [SECRET]}


def test_a_damaged_tool_argument_stops_the_call(ctx: Context, provider: FakeProvider) -> None:
    provider.script = [ToolCall("c", "send", {"to": "<EMAIL_999>"})]
    with pytest.raises(DamagedToken):
        call_model(
            ctx, agent="a", session=None, layers=[Layer("S", "x")], messages=[Message("user", "hi")]
        )
    assert ctx.bus.db.fetch_all("SELECT status FROM model_calls")[0]["status"] == "failed"


def test_final_prompt_view_has_each_layer_masked_and_real(
    ctx: Context, provider: FakeProvider
) -> None:
    result = call_model(
        ctx,
        agent="a",
        session="s9",
        layers=[Layer("System", f"Hi {SECRET}")],
        messages=[Message("user", f"From {SECRET}")],
    )
    view = gateway.call_view(ctx.bus.db, result.call_id, None)
    assert view
    assert (
        view.layers[0].name == "System"
        and SECRET in view.layers[0].real
        and SECRET not in view.layers[0].masked
    )
    assert view.layers[-1].name == "Task content" and SECRET not in view.layers[-1].masked
    assert (view.input_tokens, view.output_tokens, view.status) == (10, 2, "done")
    assert gateway.call_view(ctx.bus.db, None, "s9").id == result.call_id  # type: ignore[union-attr]


def test_usage_adds_up_by_agent_and_the_cap_stops_calls(
    ctx: Context, provider: FakeProvider
) -> None:
    call_model(ctx, agent="mail", session=None, layers=[Layer("S", "x")], messages=[])
    call_model(ctx, agent="mail", session=None, layers=[Layer("S", "x")], messages=[])
    call_model(ctx, agent="chat", session=None, layers=[Layer("S", "x")], messages=[])
    usage = gateway.usage_view(ctx)
    assert usage.total_today == 36
    assert {r.agent: r.calls for r in usage.today} == {"mail": 2, "chat": 1}
    gateway.set_cap(ctx.bus.db, 36)
    with pytest.raises(DailyCapReached):
        call_model(ctx, agent="mail", session=None, layers=[Layer("S", "x")], messages=[])
    assert len(provider.requests) == 3


def test_near_the_cap_warns_once(ctx: Context, provider: FakeProvider) -> None:
    gateway.set_cap(ctx.bus.db, 13)
    call_model(ctx, agent="a", session=None, layers=[Layer("S", "x")], messages=[])
    events = [e for e in ctx.bus.events_since(0) if e.type == "notification.requested"]
    assert len(events) == 1 and events[0].payload["kind"] == "usage"


@pytest.mark.parametrize("failure", [ModelUnavailable("down"), ModelFlagged("flagged")])
def test_failures_are_recorded_and_raised(
    ctx: Context, provider: FakeProvider, failure: Exception
) -> None:
    provider.script = [failure]
    with pytest.raises(type(failure)):
        call_model(ctx, agent="a", session=None, layers=[Layer("S", "x")], messages=[])
    row = ctx.bus.db.fetch_all("SELECT status, error FROM model_calls")[0]
    assert row["status"] == ("flagged" if isinstance(failure, ModelFlagged) else "failed")


def test_responses_format_for_chatgpt() -> None:
    items = _responses_input(
        [
            Message("user", "hi"),
            Message("assistant", "ok", tool_calls=[ToolCall("c1", "read", {"p": 1})]),
            Message("tool", "done", tool_call_id="c1"),
        ]
    )
    assert items[0] == {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
    assert items[1]["content"][0]["type"] == "output_text"
    assert items[2]["type"] == "function_call" and items[2]["call_id"] == "c1"
    assert items[3] == {"type": "function_call_output", "call_id": "c1", "output": "done"}


def test_json_fallback_for_servers_without_tool_calling() -> None:
    request = ModelRequest(
        "m",
        "Be useful",
        [
            Message("assistant", "", tool_calls=[ToolCall("c", "read", {"a": 1})]),
            Message("tool", "res", tool_call_id="c"),
        ],
        [ToolSpec("read", "Reads", {})],
    )
    messages = _chat_messages(request, native_tools=False)
    assert "read" in messages[0]["content"] and "JSON" in messages[0]["content"]
    assert messages[1]["content"] == '{"tool": "read", "arguments": {"a": 1}}'
    assert messages[2] == {"role": "user", "content": "Tool result:\nres"}
    call = _json_tool_call('```json\n{"tool": "read", "arguments": {"a": 1}}\n```')
    assert call and call.name == "read" and call.arguments == {"a": 1}
    assert _json_tool_call("Just words") is None
    assert _json_tool_call('{"answer": 1}') is None


def sse(*events: str) -> Any:
    import httpx

    return httpx.Response(
        200,
        content="\n\n".join(f"data: {e}" for e in events).encode(),
        headers={"content-type": "text/event-stream"},
    )


def provider_with(handler: Any, supports_tools: bool = True) -> OpenAiCompatibleProvider:
    import httpx

    made = OpenAiCompatibleProvider("https://llm.example/v1", "k", supports_tools, 5)
    made.http = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer k"}
    )
    return made


def test_litellm_streams_text_tools_and_usage() -> None:
    def handler(request: Any) -> Any:
        assert request.headers["authorization"] == "Bearer k"
        return sse(
            '{"choices":[{"delta":{"content":"Hel"}}]}',
            '{"choices":[{"delta":{"content":"lo"}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read","arguments":"{\\"a\\""}}]}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":1}"}}]}}]}',
            '{"usage":{"prompt_tokens":7,"completion_tokens":3},"choices":[]}',
            "[DONE]",
        )

    chunks = list(
        provider_with(handler).stream(
            ModelRequest("m", "i", [Message("user", "hi")], [ToolSpec("read", "r", {})])
        )
    )
    assert "".join(c.text for c in chunks if isinstance(c, TextChunk)) == "Hello"
    assert [c.arguments for c in chunks if isinstance(c, ToolCall)] == [{"a": 1}]
    assert [c.input_tokens for c in chunks if isinstance(c, Usage)] == [7]


def test_litellm_json_fallback_turns_replies_into_tool_calls() -> None:
    def handler(_: Any) -> Any:
        return sse(
            '{"choices":[{"delta":{"content":"{\\"tool\\": \\"read\\","}}]}',
            '{"choices":[{"delta":{"content":" \\"arguments\\": {}}"}}]}',
            "[DONE]",
        )

    chunks = list(
        provider_with(handler, supports_tools=False).stream(
            ModelRequest("m", "i", [Message("user", "hi")], [ToolSpec("read", "r", {})])
        )
    )
    assert [c.name for c in chunks if isinstance(c, ToolCall)] == ["read"]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [(400, b"Request flagged by content policy", ModelFlagged), (500, b"boom", ModelUnavailable)],
)
def test_litellm_classifies_errors(status: int, body: bytes, error: type[Exception]) -> None:
    import httpx

    made = provider_with(lambda _: httpx.Response(status, content=body))
    with pytest.raises(error):
        list(made.stream(ModelRequest("m", "i", [Message("user", "hi")])))
