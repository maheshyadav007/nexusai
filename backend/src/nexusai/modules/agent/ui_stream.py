"""Turns LangChain v3 stream events into the AI SDK's UI message parts.

This is the only file that knows either format, so a change in v3 stops here.
"""

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexusai.modules.agent.citations import Citations

MODEL_NODE = "model"
PARTIAL = re.compile(r"\[(?:m|ma|mai|mail|d|do|doc|(?:mail|doc):[^\]\s]{0,240})?$")
FOLLOWUPS_OPEN = "<followups>"
FOLLOWUPS_CLOSE = "</followups>"
MAX_FOLLOWUPS = 4


def _held_back(text: str) -> int:
    """How much of the end could be the start of the tag, so it isn't shown yet."""
    for size in range(min(len(text), len(FOLLOWUPS_OPEN) - 1), 0, -1):
        if FOLLOWUPS_OPEN.startswith(text[-size:]):
            return size
    return 0


def followups_part(raw: str) -> list[dict[str, Any]]:
    """Next steps the model offered, as their own part. Anything malformed is dropped."""
    try:
        parsed = json.loads(raw.split(FOLLOWUPS_CLOSE)[0])
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    questions = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    if not questions:
        return []
    return [{"type": "data-followups", "data": {"questions": questions[:MAX_FOLLOWUPS]}}]


class UiTranslator:
    """One per run. It carries what a stream needs to keep straight across events."""

    def __init__(
        self,
        *,
        started: bool,
        declined_text: str = "",
        metadata: dict[str, Any] | None = None,
        citations: "Citations | None" = None,
    ) -> None:
        self.citations = citations
        self.started = started
        self.declined_text = declined_text
        self.metadata = metadata or {}
        self.step_open = False
        self.blocks: dict[int, dict[str, Any]] = {}
        self.announced: set[str] = set()
        self.finished_tools: set[str] = set()
        self.usage: dict[str, int] = {}
        self._message = 0
        self._counter = 0

    def _id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._message}-{self._counter}"

    def start(self) -> list[dict[str, Any]]:
        if self.started:
            return []
        self.started = True
        time = datetime.now(UTC).isoformat()
        return [{"type": "start", "messageMetadata": {"time": time, **self.metadata}}]

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        method = event.get("method")
        params = event.get("params", {})
        data = params.get("data")
        if method == "messages" and isinstance(data, (list, tuple)) and data:
            metadata = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
            # Other nodes also call models, such as to summarize. People don't need those words.
            if metadata.get("langgraph_node", MODEL_NODE) == MODEL_NODE:
                return self._message_event(data[0])
            return []
        if method == "tools" and isinstance(data, dict):
            return self._tool_event(data)
        return []

    def _message_event(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        kind = data.get("event")
        if kind == "message-start":
            self._message += 1
            self.blocks = {}
            self.step_open = True
            return [*self.start(), {"type": "start-step"}]
        if kind == "content-block-start":
            return self._block_start(data["index"], data.get("content", {}))
        if kind == "content-block-delta":
            return self._block_delta(data["index"], data.get("delta", {}))
        if kind == "content-block-finish":
            return self._block_finish(data["index"], data.get("content", {}))
        if kind == "message-finish":
            usage = data.get("usage") or {}
            if usage:
                self.usage = {
                    "input_tokens": int(usage.get("input_tokens", 0)),
                    "output_tokens": int(usage.get("output_tokens", 0)),
                }
            self.step_open = False
            return [{"type": "finish-step"}]
        return []

    def _thinking_over(self) -> list[dict[str, Any]]:
        """Thinking ends when anything else starts, though its block only finishes with the reply."""
        parts = []
        for index, block in list(self.blocks.items()):
            if block["kind"] == "reasoning":
                parts.append({"type": "reasoning-end", "id": block["id"]})
                del self.blocks[index]
        return parts

    def _block_start(self, index: int, content: dict[str, Any]) -> list[dict[str, Any]]:
        block_type = content.get("type")
        if block_type == "text":
            block_id = self._id("text")
            over = self._thinking_over()
            self.blocks[index] = {"kind": "text", "id": block_id}
            return [*over, {"type": "text-start", "id": block_id}]
        if block_type == "reasoning":
            block_id = self._id("reasoning")
            self.blocks[index] = {"kind": "reasoning", "id": block_id}
            return [{"type": "reasoning-start", "id": block_id}]
        if block_type in {"tool_call_chunk", "tool_call"}:
            call_id = str(content.get("id"))
            over = self._thinking_over()
            self.blocks[index] = {"kind": "tool", "id": call_id, "name": content.get("name")}
            self.announced.add(call_id)
            return [
                *over,
                {
                    "type": "tool-input-start",
                    "toolCallId": call_id,
                    "toolName": content.get("name"),
                },
            ]
        return []

    def _block_delta(self, index: int, delta: dict[str, Any]) -> list[dict[str, Any]]:
        block = self.blocks.get(index)
        if block is None:
            return []
        if block["kind"] == "text" and delta.get("type") == "text-delta":
            return self._visible_text(block, delta.get("text", ""))
        if block["kind"] == "reasoning" and delta.get("type") == "reasoning-delta":
            return [
                {"type": "reasoning-delta", "id": block["id"], "delta": delta.get("reasoning", "")}
            ]
        if block["kind"] == "tool" and delta.get("type") == "tool-call-delta":
            return [
                {
                    "type": "tool-input-delta",
                    "toolCallId": block["id"],
                    "inputTextDelta": delta.get("args", ""),
                }
            ]
        return []

    def _block_finish(self, index: int, content: dict[str, Any]) -> list[dict[str, Any]]:
        block = self.blocks.pop(index, None)
        if block is None:
            return []
        if block["kind"] == "text":
            return self._end_text(block)
        if block["kind"] == "reasoning":
            return [{"type": "reasoning-end", "id": block["id"]}]
        return [
            {
                "type": "tool-input-available",
                "toolCallId": block["id"],
                "toolName": content.get("name") or block.get("name"),
                "input": content.get("args", {}),
            }
        ]

    def _tool_event(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        kind = data.get("event")
        call_id = str(data.get("tool_call_id"))
        # v3 announces a tool again when it resumes after an approval.
        if kind == "tool-finished" and call_id not in self.finished_tools:
            self.finished_tools.add(call_id)
            output = data.get("output")
            content = getattr(output, "content", output)
            # A decline was already announced, and the screen should keep saying so.
            if self.declined_text and content == self.declined_text:
                return []
            return [{"type": "tool-output-available", "toolCallId": call_id, "output": content}]
        if kind == "tool-error" and call_id not in self.finished_tools:
            self.finished_tools.add(call_id)
            return [
                {
                    "type": "tool-output-error",
                    "toolCallId": call_id,
                    "errorText": str(data.get("message", "The tool failed.")),
                }
            ]
        return []

    def _visible_text(self, block: dict[str, Any], delta: str) -> list[dict[str, Any]]:
        """Keeps the follow-up tag out of the words, even when it arrives split across chunks."""
        if "hidden" in block:
            block["hidden"] += delta
            return []
        text = block.get("held", "") + delta
        at = text.find(FOLLOWUPS_OPEN)
        if at >= 0:
            block["hidden"] = text[at + len(FOLLOWUPS_OPEN) :]
            block["held"] = ""
            text = text[:at]
        else:
            size = _held_back(text)
            block["held"] = text[-size:] if size else ""
            text = text[:-size] if size else text
        text = self._cited(block, text)
        return [{"type": "text-delta", "id": block["id"], "delta": text}] if text else []

    def _cited(self, block: dict[str, Any], text: str) -> str:
        """Turns markers into numbers, keeping back one that may finish in the next chunk."""
        if self.citations is None:
            return text
        text = block.pop("cite_held", "") + text
        partial = PARTIAL.search(text)
        if partial:
            block["cite_held"] = text[partial.start() :]
            text = text[: partial.start()]
        return self.citations.rewrite(text)

    def _end_text(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        held = self._cited(block, block["held"]) if block.get("held") else ""
        # Anything still kept back never became a marker, so it's only words, unless it was cut off.
        leftover = block.pop("cite_held", "")
        if ":" not in leftover:
            held += leftover
        if held:
            parts.append({"type": "text-delta", "id": block["id"], "delta": held})
        parts.append({"type": "text-end", "id": block["id"]})
        if "hidden" in block:
            parts += followups_part(block["hidden"])
        return parts

    def close_open_blocks(self) -> list[dict[str, Any]]:
        """After a stop or an error, so the screen doesn't show text still arriving."""
        parts: list[dict[str, Any]] = []
        for block in self.blocks.values():
            if block["kind"] == "text":
                parts += self._end_text(block)
            elif block["kind"] == "reasoning":
                parts.append({"type": "reasoning-end", "id": block["id"]})
        self.blocks = {}
        if self.step_open:
            parts.append({"type": "finish-step"})
            self.step_open = False
        return parts


def assemble_messages(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Finished turns as UI messages, so a reopened session shows without replaying a stream."""
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if turn["text"]:
            messages.append(
                {
                    "id": f"user-{turn['id']}",
                    "role": "user",
                    "parts": [{"type": "text", "text": turn["text"]}],
                    "metadata": {"time": turn.get("created"), "origin": turn.get("origin")},
                }
            )
        parts = _assemble_parts(turn["parts"])
        if parts:
            started: dict[str, Any] = next((p for p in turn["parts"] if p["type"] == "start"), {})
            messages.append(
                {
                    "id": f"assistant-{turn['id']}",
                    "role": "assistant",
                    "parts": parts,
                    "metadata": {
                        **started.get("messageMetadata", {}),
                        "turn": turn["id"],
                        "feedback": turn.get("feedback"),
                        "versions": turn.get("versions"),
                        "thread": turn.get("thread"),
                    },
                }
            )
    return messages


def _assemble_parts(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    texts: dict[str, dict[str, Any]] = {}
    tools: dict[str, dict[str, Any]] = {}
    for part in stream:
        kind = part["type"]
        if kind == "start-step":
            parts.append({"type": "step-start"})
        elif kind in {"text-start", "reasoning-start"}:
            block = {"type": kind.split("-")[0], "text": "", "state": "streaming"}
            texts[part["id"]] = block
            parts.append(block)
        elif kind in {"text-delta", "reasoning-delta"} and part["id"] in texts:
            texts[part["id"]]["text"] += part["delta"]
        elif kind in {"text-end", "reasoning-end"} and part["id"] in texts:
            texts[part["id"]]["state"] = "done"
        elif kind == "tool-input-available":
            tool = {
                "type": f"tool-{part['toolName']}",
                "toolCallId": part["toolCallId"],
                "state": "input-available",
                "input": part["input"],
            }
            tools[part["toolCallId"]] = tool
            parts.append(tool)
        elif kind == "tool-approval-request" and part["toolCallId"] in tools:
            tools[part["toolCallId"]].update(
                {"state": "approval-requested", "approval": {"id": part["approvalId"]}}
            )
        elif kind == "tool-approval-response" and part.get("toolCallId") in tools:
            tool = tools[part["toolCallId"]]
            tool["state"] = "approval-responded"
            tool["approval"] = {"id": part["approvalId"], "approved": part["approved"]}
        elif kind == "tool-output-available" and part["toolCallId"] in tools:
            tools[part["toolCallId"]].update(
                {"state": "output-available", "output": part["output"]}
            )
        elif kind == "tool-output-denied" and part["toolCallId"] in tools:
            tools[part["toolCallId"]]["state"] = "output-denied"
        elif kind == "tool-output-error" and part["toolCallId"] in tools:
            tools[part["toolCallId"]].update(
                {"state": "output-error", "errorText": part["errorText"]}
            )
        elif kind == "error":
            parts.append({"type": "data-error", "data": {"text": part["errorText"]}})
        elif kind.startswith("data-"):
            parts.append({"type": kind, "data": part["data"]})
    return parts
