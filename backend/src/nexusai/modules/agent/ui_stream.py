"""Turns LangChain v3 stream events into the AI SDK's UI message parts.

This is the only file that knows either format, so a change in v3 stops here.
"""

from typing import Any

MODEL_NODE = "model"


class UiTranslator:
    """One per run. It carries what a stream needs to keep straight across events."""

    def __init__(self, *, started: bool) -> None:
        self.started = started
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
        return [{"type": "start"}]

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

    def _block_start(self, index: int, content: dict[str, Any]) -> list[dict[str, Any]]:
        block_type = content.get("type")
        if block_type == "text":
            block_id = self._id("text")
            self.blocks[index] = {"kind": "text", "id": block_id}
            return [{"type": "text-start", "id": block_id}]
        if block_type == "reasoning":
            block_id = self._id("reasoning")
            self.blocks[index] = {"kind": "reasoning", "id": block_id}
            return [{"type": "reasoning-start", "id": block_id}]
        if block_type in {"tool_call_chunk", "tool_call"}:
            call_id = str(content.get("id"))
            self.blocks[index] = {"kind": "tool", "id": call_id, "name": content.get("name")}
            self.announced.add(call_id)
            return [
                {"type": "tool-input-start", "toolCallId": call_id, "toolName": content.get("name")}
            ]
        return []

    def _block_delta(self, index: int, delta: dict[str, Any]) -> list[dict[str, Any]]:
        block = self.blocks.get(index)
        if block is None:
            return []
        if block["kind"] == "text" and delta.get("type") == "text-delta":
            return [{"type": "text-delta", "id": block["id"], "delta": delta.get("text", "")}]
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
            return [{"type": "text-end", "id": block["id"]}]
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

    def close_open_blocks(self) -> list[dict[str, Any]]:
        """After a stop or an error, so the screen doesn't show text still arriving."""
        parts: list[dict[str, Any]] = []
        for block in self.blocks.values():
            if block["kind"] == "text":
                parts.append({"type": "text-end", "id": block["id"]})
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
                }
            )
        parts = _assemble_parts(turn["parts"])
        if parts:
            messages.append({"id": f"assistant-{turn['id']}", "role": "assistant", "parts": parts})
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
    return parts
