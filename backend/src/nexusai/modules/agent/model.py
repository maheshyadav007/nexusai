"""The chat model LangChain sees. Every call it makes goes through the gateway."""

import json
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

from nexusai.kernel.module import Context
from nexusai.modules.agent.gateway import Layer, stream_model
from nexusai.modules.agent.providers import Message, TextChunk, ToolCall, ToolSpec, Usage

SUMMARY_SOURCE = "summarization"


def is_summary(message: BaseMessage) -> bool:
    """LangChain marks its summaries this way, and sends them as if the person had said them."""
    return message.additional_kwargs.get("lc_source") == SUMMARY_SOURCE


def _text_of(content: Any) -> str:
    """Content is a string, or a list of blocks once v3 has been through it."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def to_messages(messages: Sequence[BaseMessage]) -> tuple[list[Message], list[Layer]]:
    """LangChain messages as ours. System messages, such as a summary, become prompt layers."""
    converted: list[Message] = []
    extra: list[Layer] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            extra.append(Layer("Earlier in this session", _text_of(message.content)))
        elif is_summary(message):
            # It may retell mail, so it can't carry the person's authority.
            extra.append(
                Layer(
                    "Earlier in this session",
                    f"<untrusted>\n{_text_of(message.content)}\n</untrusted>",
                )
            )
        elif isinstance(message, ToolMessage):
            converted.append(
                Message("tool", _text_of(message.content), tool_call_id=message.tool_call_id)
            )
        elif isinstance(message, AIMessage):
            calls = [ToolCall(str(c["id"]), c["name"], c["args"]) for c in message.tool_calls]
            converted.append(Message("assistant", _text_of(message.content), tool_calls=calls))
        elif isinstance(message, HumanMessage):
            converted.append(Message("user", _text_of(message.content)))
    return converted, extra


class GatewayChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ctx: Context
    agent: str
    session: str | None
    layers: list[Layer]
    specs: list[ToolSpec] = []
    model_override: str | None = None

    @property
    def _llm_type(self) -> str:
        return "nexusai-gateway"

    def bind_tools(self, tools: Sequence[Any], **_: Any) -> "GatewayChatModel":
        specs = []
        for tool in tools:
            function = convert_to_openai_tool(tool)["function"]
            specs.append(
                ToolSpec(
                    function["name"],
                    function.get("description", ""),
                    # A connector's tool describes itself, so its own schema goes as it came.
                    (getattr(tool, "metadata", None) or {}).get("parameters")
                    or function.get("parameters", {}),
                )
            )
        return self.model_copy(update={"specs": specs})

    def _chunks(self, messages: list[BaseMessage]) -> Iterator[AIMessageChunk]:
        converted, extra = to_messages(messages)
        index = 0
        for chunk in stream_model(
            self.ctx,
            agent=self.agent,
            session=self.session,
            layers=[*self.layers, *extra],
            messages=converted,
            tools=self.specs,
            model_override=self.model_override,
        ):
            if isinstance(chunk, TextChunk):
                yield AIMessageChunk(content=chunk.text)
            elif isinstance(chunk, ToolCall):
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": chunk.name,
                            "args": json.dumps(chunk.arguments),
                            "id": chunk.id,
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
                index += 1
            elif isinstance(chunk, Usage):
                yield AIMessageChunk(
                    content="",
                    usage_metadata={
                        "input_tokens": chunk.input_tokens,
                        "output_tokens": chunk.output_tokens,
                        "total_tokens": chunk.input_tokens + chunk.output_tokens,
                    },
                )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **_: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for piece in self._chunks(messages):
            generation = ChatGenerationChunk(message=piece)
            if run_manager:
                run_manager.on_llm_new_token(_text_of(piece.content), chunk=generation)
            yield generation

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **_: Any,
    ) -> ChatResult:
        merged: AIMessageChunk | None = None
        for generation in self._stream(messages, stop, run_manager):
            piece = generation.message
            assert isinstance(piece, AIMessageChunk)
            merged = piece if merged is None else merged + piece
        final = merged or AIMessageChunk(content="")
        message = AIMessage(
            content=final.content,
            tool_calls=final.tool_calls,
            usage_metadata=final.usage_metadata,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
