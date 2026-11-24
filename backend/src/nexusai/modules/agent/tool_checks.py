"""Plain checks on what a tool was given, added as a note to its result.

A small model doesn't always follow every rule in its prompt. A check here doesn't stop the tool:
the work is done, and the note says what looks missing so the model can fix it in one more call.
Each check takes the tool's arguments and its result, and returns a note or nothing."""

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from nexusai.modules.agent.citations import MARKER

Check = Callable[[dict[str, Any], str], str | None]


def _brief_cites(args: dict[str, Any], result: str) -> str | None:
    said = " ".join(
        [
            str(args.get("lead") or ""),
            *map(str, args.get("new") or []),
            *map(str, args.get("still_open") or []),
        ]
    )
    if not result.startswith("Saved") or MARKER.search(said):
        return None
    return (
        "Note: this brief cites nothing. Every point that comes from an email needs its marker "
        "straight after it, such as [mail:123], copied as the tool showed it. If you missed any, "
        "call update_brief again with the whole brief."
    )


CHECKS: dict[str, list[Check]] = {
    "update_brief": [_brief_cites],
}


def notes(tool: str, args: dict[str, Any], result: str) -> list[str]:
    return [note for check in CHECKS.get(tool, []) if (note := check(args, result))]


class ToolChecks(AgentMiddleware):
    """Adds each check's note to the tool's result."""

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        result = handler(request)
        call = request.tool_call
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        found = notes(str(call.get("name") or ""), dict(call.get("args") or {}), result.content)
        if not found:
            return result
        return result.model_copy(update={"content": "\n\n".join([result.content, *found])})
