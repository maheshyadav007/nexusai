"""What an agent is told when a tool call can't run: what was wrong and what to do next.

A small model that sees its failed call repeated back tends to make the same call again, so these
messages never repeat the arguments. They name the problem, show the right shape with an example,
and point to the next move."""

import difflib
import json
from collections.abc import Callable
from typing import Any

import structlog
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from pydantic import BaseModel, ValidationError

log = structlog.get_logger()
FIND_TOOLS = "find_tools"
# Filled in by the app, never by the model, so never shown or asked for.
INJECTED = frozenset({"tool_call_id"})
CLOSEST = 3
DESCRIPTION_WORDS = 14


def _short(text: str) -> str:
    first = text.split(". ")[0].strip().rstrip(".")
    words = first.split()
    return " ".join(words[:DESCRIPTION_WORDS]) + ("…" if len(words) > DESCRIPTION_WORDS else "")


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return dict(schema.get("$defs", {}).get(ref.rsplit("/", 1)[-1], {}))
    for key in ("anyOf", "oneOf"):
        options = [o for o in node.get(key, []) if o.get("type") != "null"]
        if options:
            return _resolve(schema, options[0])
    return node


def _example(schema: dict[str, Any], node: dict[str, Any], depth: int = 0) -> Any:
    node = _resolve(schema, node)
    kind = node.get("type")
    if "enum" in node:
        return node["enum"][0]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return [_example(schema, node.get("items", {}), depth + 1)] if depth < 3 else []
    if kind == "object" or "properties" in node:
        required = node.get("required", [])
        return {
            name: _example(schema, prop, depth + 1)
            for name, prop in node.get("properties", {}).items()
            if name in required and name not in INJECTED
        }
    return "…"


def _fields(schema: dict[str, Any]) -> list[str]:
    required = set(schema.get("required", []))
    lines = []
    for name, prop in schema.get("properties", {}).items():
        if name in INJECTED:
            continue
        need = "required" if name in required else "optional"
        about = _short(
            str(_resolve(schema, prop).get("description") or prop.get("description") or "")
        )
        lines.append(f"- {name} ({need}){': ' + about if about else ''}")
    return lines


def _example_call(schema: dict[str, Any]) -> str:
    values = _example(schema, schema)
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in values.items())


def bad_arguments(tool: str, schema_type: type[BaseModel] | None, error: ValidationError) -> str:
    """The fields that were wrong, the shape the tool takes, and an example. Never the failed call."""
    missing, wrong = [], []
    for item in error.errors(include_url=False, include_input=False):
        place = ".".join(str(part) for part in item.get("loc", ()) if part not in INJECTED)
        if not place:
            continue
        if item.get("type") == "missing":
            missing.append(place)
        else:
            wrong.append(f"{place} ({str(item.get('msg', '')).lower()})")
    problems = []
    if missing:
        problems.append(f"{tool} is missing {', '.join(missing)}.")
    if wrong:
        problems.append(f"Wrong value for {'; '.join(wrong)}.")
    lines = [f"Not run: {' '.join(problems) or f'{tool} needs different arguments.'}"]
    if schema_type is not None:
        schema = schema_type.model_json_schema()
        fields = _fields(schema)
        if fields:
            lines += ["It takes:", *fields]
        example = _example_call(schema)
        if example:
            lines.append(f"Example: {tool}({example})")
    lines.append("Fix the call and try again.")
    return "\n".join(lines)


def unknown_tool(name: str, available: list[str]) -> str:
    """The nearest names, and how to find the right one."""
    words = set(name.lower().replace("-", "_").split("_"))
    by_words = sorted(
        (n for n in available if words & set(n.split("_")) and n != FIND_TOOLS),
        key=lambda n: -len(words & set(n.split("_"))),
    )
    near = difflib.get_close_matches(name, available, n=CLOSEST, cutoff=0.5)
    closest = list(dict.fromkeys([*near, *by_words]))[:CLOSEST]
    lines = [f"Not run: there's no tool called {name}."]
    if closest:
        lines.append(f"Closest: {', '.join(closest)}.")
    if FIND_TOOLS in available:
        lines.append(f"Use one of those, or {FIND_TOOLS} with a few words for the job.")
    else:
        lines.append("Use one of the tools you were given.")
    return " ".join(lines)


def failed(tool: str, error: Exception) -> str:
    """A tool that broke. The run carries on, so the agent can try another way."""
    reason = (
        str(error).strip().splitlines()[0][:300] if str(error).strip() else type(error).__name__
    )
    return (
        f"{tool} failed: {reason}. It may not have finished. Check with a list or read tool before "
        "trying again, try once more if the call looks right, and otherwise tell the person what "
        "failed and what they can do."
    )


class ToolFeedback(AgentMiddleware):
    """Checks each call before it runs, and turns any failure into a message the agent can act
    on, so one bad call never ends the run."""

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self.names = sorted(names)

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        call = request.tool_call
        name = str(call.get("name") or "")
        call_id = str(call.get("id") or "")

        def told(text: str) -> ToolMessage:
            return ToolMessage(content=text, tool_call_id=call_id, name=name, status="error")

        tool = request.tool
        if tool is None:
            return told(unknown_tool(name, self.names))
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema.model_validate({**(call.get("args") or {}), "tool_call_id": call_id})
            except ValidationError as error:
                return told(bad_arguments(name, schema, error))
        try:
            return handler(request)
        except GraphBubbleUp:
            # Questions to the person and approvals pause the run this way. They aren't failures.
            raise
        except Exception as error:  # noqa: BLE001 - any failure becomes a message to act on
            log.warning("tool_failed", tool=name, exc_info=True)
            return told(failed(name, error))
