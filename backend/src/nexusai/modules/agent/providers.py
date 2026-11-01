"""One interface for every model, whichever company or server runs it."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from nexusai.kernel.config import Config
from nexusai.kernel.module import Context
from nexusai.modules.models import module as models
from nexusai.modules.models.chatgpt import ChatGptError, SignInRequired

FLAGGED = re.compile(r"flagged|content.?filter|policy violation|content.?policy|moderation", re.I)
JSON_TOOL_NOTE = (
    "To use a tool, reply with only a JSON object: "
    '{"tool": "<name>", "arguments": {...}}. Available tools:\n'
)


class ModelUnavailable(Exception):
    """Temporary: work waits and tries again."""


class ModelFlagged(Exception):
    """The provider refused this content. Trying again wouldn't help."""


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
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


Chunk = TextChunk | ToolCall | Usage


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
        except ChatGptError as error:
            if FLAGGED.search(str(error)):
                raise ModelFlagged(str(error)) from error
            raise ModelUnavailable(str(error)) from error


def _arguments(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
    except ValueError as error:
        raise ModelUnavailable("The model sent an unreadable tool call.") from error
    return parsed if isinstance(parsed, dict) else {}


def _json_tool_call(text: str) -> ToolCall | None:
    """For servers without tool calling: the tool call comes back as plain JSON."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("tool"), str):
        return None
    arguments = parsed.get("arguments")
    return ToolCall("json-call", parsed["tool"], arguments if isinstance(arguments, dict) else {})


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
                call = message.tool_calls[0]
                entry["content"] = json.dumps({"tool": call.name, "arguments": call.arguments})
        output.append(entry)
    return output


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
        text_seen: list[str] = []
        try:
            with self.http.stream(
                "POST", f"{self.base_url}/chat/completions", json=body
            ) as response:
                if response.status_code != 200:
                    detail = response.read().decode("utf-8", "replace")
                    if FLAGGED.search(detail):
                        raise ModelFlagged("The model refused this content under its policy.")
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
                        if delta.get("content"):
                            # Without tool calling, a tool call only shows once the reply is whole.
                            if request.tools and not self.supports_tools:
                                text_seen.append(delta["content"])
                            else:
                                yield TextChunk(delta["content"])
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
        for slot in calls.values():
            yield ToolCall(slot["id"], slot["name"], _arguments(slot["arguments"]))
        if text_seen:
            whole = "".join(text_seen)
            call_found = _json_tool_call(whole)
            yield call_found if call_found else TextChunk(whole)


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
