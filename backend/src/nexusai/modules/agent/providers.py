"""One interface for every model, whichever company or server runs it."""

import json
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import structlog

from nexusai.kernel.config import Config
from nexusai.kernel.module import Context
from nexusai.modules.models import module as models
from nexusai.modules.models.chatgpt import ChatGptError, ChatGptLimited, SignInRequired

log = structlog.get_logger()

FLAGGED = re.compile(r"flagged|content.?filter|policy violation|content.?policy|moderation", re.I)
JSON_TOOL_NOTE = (
    "To use a tool, reply with only a JSON object: "
    '{"tool": "<name>", "arguments": {...}}. Put every field inside arguments, and write line'
    " breaks inside text as \\n. Available tools:\n"
)
# Models name the parts of a tool call in different ways. A bare "name" could be any JSON,
# so only "tool", the word we asked for, counts for a tool we didn't offer.
OFFERED_NAME_KEYS = ("tool", "name", "tool_name", "function")
ARGUMENT_KEYS = ("arguments", "args", "parameters", "input")
# How thinking models mark what isn't the answer, when the server doesn't separate it for us.
THINKING_TAGS = (
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
    ("<reasoning>", "</reasoning>"),
    ("<seed:think>", "</seed:think>"),
    ("[THINK]", "[/THINK]"),
    ("◁think▷", "◁/think▷"),
)
THINKING = re.compile(
    "|".join(f"{re.escape(start)}.*?{re.escape(end)}" for start, end in THINKING_TAGS), re.S
)
# Servers that do separate it use one of these fields.
REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")
JSON_START = re.compile(r"[{\[]")
OPENING_FENCE = re.compile(r"```(?:json)?\s*$")
# Where a written tool call could begin, and how a reply may end part of the way into one.
CALL_START = re.compile(r"\{\s*\"|\[\s*\{|```(?:json)?\s*[{\[]")
CALL_START_CUT_OFF = re.compile(r"(?:\{\s*|\[\s*|`{1,3}(?:j|js|jso|json)?\s*)$")


class ModelUnavailable(Exception):
    """Temporary: work waits and tries again."""


class ModelRateLimited(ModelUnavailable):
    """The server said to slow down, sometimes with how long to wait."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ModelFlagged(Exception):
    """The provider refused this content. Trying again wouldn't help."""


class ModelContextExceeded(Exception):
    """The input must change; retrying it unchanged will not recover."""


class ModelResponseInvalid(Exception):
    """A malformed tool result is a failed attempt, not a network outage."""


CONTEXT_EXCEEDED = re.compile(
    r"context[_ ]length[_ ]exceeded|maximum context length|context window.{0,80}(?:exceed|limit)|(?:input|prompt).{0,40}too (?:long|large)|input token.{0,40}exceed",
    re.I,
)
CONTEXT_HELP = "This run exceeds the model's context limit. Reduce attached context, shorten personalized prompts, compact earlier history, or choose a larger-context model."


class ModelNotConfigured(Exception):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """Roles: user, assistant, tool. An assistant message can carry tool calls."""

    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class ModelRequest:
    model: str
    instructions: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)


@dataclass
class TextChunk:
    text: str


@dataclass
class ReasoningChunk:
    """What a thinking model thought on the way. It's shown apart, and never sent back to it."""

    text: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


Chunk = TextChunk | ReasoningChunk | ToolCall | Usage


class ModelProvider(Protocol):
    name: str

    def stream(self, request: ModelRequest) -> Iterator[Chunk]: ...


def _responses_input(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.text,
                }
            )
            continue
        if message.text:
            kind = "output_text" if message.role == "assistant" else "input_text"
            items.append({"role": message.role, "content": [{"type": kind, "text": message.text}]})
        for call in message.tool_calls:
            items.append(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                }
            )
    return items


class ChatGptProvider:
    """A ChatGPT subscription, through the Codex backend."""

    name = "chatgpt"

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def stream(self, request: ModelRequest) -> Iterator[Chunk]:
        body: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": _responses_input(request.messages),
            "store": False,
            "stream": True,
        }
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in request.tools
            ]

        try:
            for event in models.chatgpt_events(self.ctx, body):
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    yield TextChunk(event.get("delta", ""))
                elif kind == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        yield ToolCall(
                            item["call_id"], item["name"], _arguments(item.get("arguments", "{}"))
                        )
                elif kind == "response.completed":
                    usage = (event.get("response") or {}).get("usage") or {}
                    yield Usage(
                        int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
                    )
        except SignInRequired as error:
            raise ModelNotConfigured(str(error)) from error
        except ChatGptLimited as error:
            raise ModelRateLimited(str(error)) from error
        except ChatGptError as error:
            if CONTEXT_EXCEEDED.search(str(error)):
                raise ModelContextExceeded(CONTEXT_HELP) from error
            if FLAGGED.search(str(error)):
                raise ModelFlagged(str(error)) from error
            raise ModelUnavailable(str(error)) from error


def _arguments(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
    except ValueError as error:
        raise ModelResponseInvalid(
            "The model sent an unreadable tool call. Retry with a model that supports these tools."
        ) from error
    if not isinstance(parsed, dict):
        raise ModelResponseInvalid("The model returned tool arguments that are not an object.")
    return parsed


def _json_values(text: str) -> Iterator[tuple[int, Any]]:
    """Each JSON object or list in the text, and where it starts. Line breaks in strings are fine."""
    decoder = json.JSONDecoder(strict=False)
    position = 0
    while found := JSON_START.search(text, position):
        try:
            value, position = decoder.raw_decode(text, found.start())
        except ValueError:
            position = found.start() + 1
            continue
        yield found.start(), value


def _json_call(value: Any, tools: list[ToolSpec]) -> ToolCall | None:
    if not isinstance(value, dict):
        return None
    offered = {tool.name: tool for tool in tools}
    name = next((value[key] for key in OFFERED_NAME_KEYS if isinstance(value.get(key), str)), None)
    if name is None or (name not in offered and not isinstance(value.get("tool"), str)):
        return None
    given: Any = next((value[key] for key in ARGUMENT_KEYS if key in value), {})
    if isinstance(given, str):
        given = next((v for _, v in _json_values(given)), {})
    arguments = dict(given) if isinstance(given, dict) else {}
    # Some models put fields beside "arguments". The tool's own fields are kept wherever they are.
    spec = offered.get(name)
    fields = spec.parameters.get("properties", {}) if spec else {}
    for key, field_value in value.items():
        if key in fields and key not in arguments:
            arguments[key] = field_value
    return ToolCall(f"json-call-{uuid.uuid4().hex[:12]}", name, arguments)


def _json_tool_calls(text: str, tools: list[ToolSpec]) -> tuple[str, list[ToolCall]]:
    """For servers without tool calling: what the model said first, and the tool calls it wrote.

    Anything after a call is dropped, since the model hasn't seen the result yet.
    """
    stripped = THINKING.sub("", text).strip()
    first: int | None = None
    calls: list[ToolCall] = []
    for start, value in _json_values(stripped):
        found = [
            call
            for item in (value if isinstance(value, list) else [value])
            if (call := _json_call(item, tools))
        ]
        if found and first is None:
            first = start
        calls += found
    if first is not None:
        return OPENING_FENCE.sub("", stripped[:first]).strip(), calls
    if '"tool"' in stripped:
        log.warning("model_reply_not_a_tool_call", start=stripped[:300])
    return stripped, []


def _longest_cut_off(text: str, markers: Iterable[str]) -> int:
    """How much of the end could be the start of a marker, so it waits for the next piece."""
    longest = 0
    for marker in markers:
        for size in range(min(len(text), len(marker) - 1), longest, -1):
            if marker.startswith(text[-size:]):
                longest = size
                break
    return longest


class ReplyReader:
    """Sorts a reply into thinking, words and tool calls as it arrives, so it streams.

    A written tool call can't be used until it's whole. Only that part is kept back: if it turns
    out not to be a call, it's shown then.
    """

    def __init__(self, tools: list[ToolSpec], calls_in_text: bool, starts_thinking: bool) -> None:
        self.tools = tools
        self.calls_in_text = calls_in_text
        self.buffer = ""
        self.closing: str | None = THINKING_TAGS[0][1] if starts_thinking else None
        self.saw_unopened_close = False
        self.holding = False

    def feed(self, text: str) -> list[Chunk]:
        self.buffer += text
        if self.holding:
            return []
        chunks: list[Chunk] = []
        while True:
            if self.closing is not None:
                at = self.buffer.find(self.closing)
                if at < 0:
                    keep = _longest_cut_off(self.buffer, [self.closing])
                    self._take(chunks, ReasoningChunk, len(self.buffer) - keep)
                    return chunks
                self._take(chunks, ReasoningChunk, at)
                self.buffer = self.buffer[len(self.closing) :]
                self.closing = None
                continue
            found = self._next_tag()
            call = CALL_START.search(self.buffer) if self.calls_in_text else None
            if call and (found is None or call.start() < found[0]):
                self._take(chunks, TextChunk, call.start())
                self.holding = True
                return chunks
            if found is None:
                markers = [tag for pair in THINKING_TAGS for tag in pair]
                keep = _longest_cut_off(self.buffer, markers)
                if self.calls_in_text and (cut := CALL_START_CUT_OFF.search(self.buffer)):
                    keep = max(keep, len(self.buffer) - cut.start())
                self._take(chunks, TextChunk, len(self.buffer) - keep)
                return chunks
            at, tag, closing = found
            self._take(chunks, TextChunk, at)
            self.buffer = self.buffer[len(tag) :]
            if closing is None:
                # Its opening tag came from the server's template, so what came first was thinking.
                self.saw_unopened_close = True
            self.closing = closing

    def _next_tag(self) -> tuple[int, str, str | None] | None:
        found: tuple[int, str, str | None] | None = None
        for start, end in THINKING_TAGS:
            for tag, closing in ((start, end), (end, None)):
                at = self.buffer.find(tag)
                if at >= 0 and (found is None or at < found[0]):
                    found = (at, tag, closing)
        return found

    def _take(self, chunks: list[Chunk], kind: type[TextChunk | ReasoningChunk], size: int) -> None:
        if size > 0:
            chunks.append(kind(self.buffer[:size]))
            self.buffer = self.buffer[size:]

    def finish(self) -> list[Chunk]:
        left, self.buffer = self.buffer, ""
        if self.closing is not None:
            return [ReasoningChunk(left)] if left else []
        if not self.calls_in_text:
            return [TextChunk(left)] if left else []
        said, calls = _json_tool_calls(left, self.tools)
        return [*([TextChunk(said)] if said else []), *calls]


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers.get("retry-after", "")))
    except ValueError:
        return None


def _chat_messages(request: ModelRequest, native_tools: bool) -> list[dict[str, Any]]:
    instructions = request.instructions
    if request.tools and not native_tools:
        described = [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in request.tools
        ]
        instructions += "\n\n" + JSON_TOOL_NOTE + json.dumps(described)
    output: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
    for message in request.messages:
        if message.role == "tool":
            if native_tools:
                output.append(
                    {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.text}
                )
            else:
                output.append({"role": "user", "content": f"Tool result:\n{message.text}"})
            continue
        entry: dict[str, Any] = {"role": message.role, "content": message.text}
        if message.tool_calls:
            if native_tools:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in message.tool_calls
                ]
            else:
                entry["content"] = "\n".join(
                    json.dumps({"tool": call.name, "arguments": call.arguments})
                    for call in message.tool_calls
                )
        output.append(entry)
    return output


# Models whose replies begin already thinking, because the server's template opens the tag. Seen
# once, from a closing tag with no opening one.
_THINKING_OPENED_BY_SERVER: set[tuple[str, str]] = set()


class OpenAiCompatibleProvider:
    """A LiteLLM server, or anything else with the same API, such as the internal one."""

    name = "litellm"

    def __init__(self, base_url: str, api_key: str, supports_tools: bool, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.supports_tools = supports_tools
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})

    def list_models(self) -> list[str]:
        response = self.http.get(f"{self.base_url}/models")
        response.raise_for_status()
        return sorted(str(item["id"]) for item in response.json().get("data", []))

    def stream(self, request: ModelRequest) -> Iterator[Chunk]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": _chat_messages(request, self.supports_tools),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools and self.supports_tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        calls: dict[int, dict[str, str]] = {}
        started_in_thought = (self.base_url, request.model) in _THINKING_OPENED_BY_SERVER
        reader = ReplyReader(
            request.tools, bool(request.tools) and not self.supports_tools, started_in_thought
        )
        try:
            with self.http.stream(
                "POST", f"{self.base_url}/chat/completions", json=body
            ) as response:
                if response.status_code != 200:
                    detail = response.read().decode("utf-8", "replace")
                    if response.status_code == 413 or CONTEXT_EXCEEDED.search(detail):
                        raise ModelContextExceeded(CONTEXT_HELP)
                    if FLAGGED.search(detail):
                        raise ModelFlagged("The model refused this content under its policy.")
                    if response.status_code == 429:
                        raise ModelRateLimited(
                            "The model server is limiting calls right now.",
                            _retry_after(response),
                        )
                    if response.status_code in {401, 403}:
                        raise ModelNotConfigured(
                            "The model server refused this key. Check it in Settings."
                        )
                    raise ModelUnavailable(
                        f"The model server returned an error (HTTP {response.status_code})."
                    )
                for line in response.iter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    event = json.loads(line[5:].strip())
                    if event.get("usage"):
                        usage = event["usage"]
                        yield Usage(
                            int(usage.get("prompt_tokens", 0)),
                            int(usage.get("completion_tokens", 0)),
                        )
                    for choice in event.get("choices", []):
                        if choice.get("finish_reason") == "content_filter":
                            raise ModelFlagged("The model refused this content under its policy.")
                        delta = choice.get("delta", {})
                        for name in REASONING_FIELDS:
                            if isinstance(delta.get(name), str) and delta[name]:
                                yield ReasoningChunk(delta[name])
                        if delta.get("content"):
                            yield from reader.feed(delta["content"])
                        for call in delta.get("tool_calls") or []:
                            slot = calls.setdefault(
                                call.get("index", 0), {"id": "", "name": "", "arguments": ""}
                            )
                            function = call.get("function", {})
                            slot["id"] = call.get("id") or slot["id"]
                            slot["name"] = function.get("name") or slot["name"]
                            slot["arguments"] += function.get("arguments") or ""
        except httpx.HTTPError as error:
            raise ModelUnavailable("Couldn't reach the model server.") from error
        yield from reader.finish()
        if reader.saw_unopened_close:
            _THINKING_OPENED_BY_SERVER.add((self.base_url, request.model))
        for slot in calls.values():
            yield ToolCall(slot["id"], slot["name"], _arguments(slot["arguments"]))


def active_provider(ctx: Context) -> tuple[ModelProvider, str]:
    """The provider and model chosen in Settings."""
    settings = models.active_settings(ctx)
    if settings.provider == "litellm":
        key = models.litellm_key(ctx)
        if not settings.base_url or not key or not settings.model:
            raise ModelNotConfigured("Finish setting up the internal API in Settings.")
        provider = OpenAiCompatibleProvider(
            settings.base_url, key, settings.supports_tools, _timeout(ctx.config)
        )
        return provider, settings.model
    if not settings.model:
        raise ModelNotConfigured("Connect a model and choose one in Settings.")
    return ChatGptProvider(ctx), settings.model


def _timeout(config: Config) -> float:
    return config.chatgpt.timeout_seconds
