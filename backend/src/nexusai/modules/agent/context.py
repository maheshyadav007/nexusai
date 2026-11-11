"""What the model gets to see of a conversation. The chat itself always shows everything."""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately  # noqa: E402
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from nexusai.contracts.agent import ContextProfile, ContextSettings
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.modules.agent.model import is_summary
from nexusai.modules.agent.prompts_builder import packaged

log = structlog.get_logger()
SETTINGS_KEY = "context_settings"
COMPACT_AS_NODE = "model"
PERSON = "person"
# Their result is the outcome of the run, so clearing it would lose what was decided.
KEEP_RESULTS_OF = ("record_triage", "find_tools")


@dataclass(frozen=True)
class TurnRequest:
    """One start of an agent, whichever way it came: a person, an event or the clock."""

    session: str
    # What the chat shows.
    text: str
    origin: str = PERSON
    # What the model is told, when the shown words hold things from outside, like a mail subject.
    model_text: str | None = None
    # Data for this run only, so it never stays in the saved history.
    task: str = ""
    target: dict[str, Any] | None = None
    # A schedule's own way of keeping context, over the default.
    context: dict[str, Any] | None = None
    # Who answers, when it isn't the chat's own agent: "@mail …" typed in the lead's chat.
    agent: str | None = None
    # What started it, and the run that led to it, so every run has a place in the tree.
    cause: str | None = None
    parent_turn: int | None = None


def load_settings(db: Database, config: Config) -> ContextSettings:
    defaults = ContextSettings.model_validate(config.context)
    rows = db.fetch_all("SELECT value FROM agent_defaults WHERE key = ?", (SETTINGS_KEY,))
    return (
        ContextSettings.model_validate({**defaults.model_dump(), **json.loads(rows[0]["value"])})
        if rows
        else defaults
    )


def save_settings(db: Database, settings: ContextSettings) -> None:
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_defaults (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, settings.model_dump_json()),
        )


def profile_for(
    settings: ContextSettings, origin: str, own: dict[str, Any] | None
) -> ContextProfile:
    base = settings.chat if origin == PERSON else settings.triggered
    overrides = {
        k: v for k, v in (own or {}).items() if k in ContextProfile.model_fields and v is not None
    }
    return ContextProfile.model_validate({**base.model_dump(), **overrides})


def recent(messages: list[Any], keep: int) -> list[Any]:
    """All of the current run, then up to `keep` before it, so tool calls stay with their results.

    Starting on something the person said means a cut can't separate a call from its result.
    """
    start = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not is_summary(m)),
        default=0,
    )
    earlier = messages[:start]
    # A summary stands in for everything before it, so it outlasts the trimming.
    summary = earlier[:1] if earlier and is_summary(earlier[0]) else []
    body = earlier[len(summary) :]
    kept = (
        trim_messages(body, max_tokens=keep, token_counter=len, strategy="last", start_on="human")
        if keep > 0
        else []
    )
    return [*summary, *kept, *messages[start:]]


class TrimSaved(AgentMiddleware):
    """Shortens the saved history. For chats that grow forever, like the Mail agent's."""

    def __init__(self, keep: int) -> None:
        super().__init__()
        self.keep = keep

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        kept = recent(messages, self.keep)
        if len(kept) == len(messages):
            return None
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept]}


class TrimView(AgentMiddleware):
    """Sends fewer messages and saves them all, so compacting later has something to read."""

    def __init__(self, keep: int) -> None:
        super().__init__()
        self.keep = keep

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(request.override(messages=recent(list(request.messages), self.keep)))


def approximate_tokens(messages: list[Any]) -> int:
    return int(count_tokens_approximately(messages))


class AutoCompact(SummarizationMiddleware):
    """Summarizes when long. If that fails the run still goes on, with the older part trimmed."""

    def __init__(
        self,
        keep_messages: int,
        on_compacted: Callable[[int, int], None] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(keep=("messages", keep_messages), **options)
        self.keep_messages = keep_messages
        self.on_compacted = on_compacted

    def _determine_cutoff_index(self, messages: list[Any]) -> int:
        cutoff = super()._determine_cutoff_index(messages)
        current = max(
            (
                i
                for i, message in enumerate(messages)
                if isinstance(message, HumanMessage) and not is_summary(message)
            ),
            default=0,
        )
        # The task and its tool results are one unit; compact only earlier turns.
        return min(cutoff, current)

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        try:
            update = super().before_model(state, runtime)
            if update is not None and self.on_compacted is not None:
                kept = [m for m in update["messages"] if not isinstance(m, RemoveMessage)]
                self.on_compacted(approximate_tokens(state["messages"]), approximate_tokens(kept))
            return update
        except Exception as error:
            log.warning("compact_failed", kind=type(error).__name__)
            messages = state["messages"]
            kept = recent(messages, self.keep_messages)
            if len(kept) == len(messages):
                return None
            return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept]}


FIND_TOOLS = "find_tools"
FOUND_LINE = re.compile(r"^- ([^\s:]+):", re.MULTILINE)


def _tool_name(tool: Any) -> str:
    return str(tool.get("name", "") if isinstance(tool, dict) else getattr(tool, "name", ""))


class ToolSearch(AgentMiddleware):
    """Shows the model the tools it uses most, and any it found with find_tools or already used.

    Every allowed tool stays registered, so what's hidden only costs a search, never permission.
    Read from the whole conversation, before it's trimmed, so a found tool stays found.
    """

    def __init__(self, shown: frozenset[str] | None, always_prefix: str = "") -> None:
        super().__init__()
        self.shown = shown
        # The person's own connectors are few, and theirs, so they're always shown.
        self.always_prefix = always_prefix

    def _starts_shown(self, name: str) -> bool:
        return (
            name in (self.shown or ())
            or name == FIND_TOOLS
            or (bool(self.always_prefix) and name.startswith(self.always_prefix))
        )

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        tools = list(request.tools)
        if self.shown is None:
            return handler(
                request.override(tools=[t for t in tools if _tool_name(t) != FIND_TOOLS])
            )
        names = {_tool_name(tool) for tool in tools}
        found: list[str] = []
        for message in request.messages:
            if isinstance(message, ToolMessage) and message.name == FIND_TOOLS:
                found += FOUND_LINE.findall(str(message.content))
            elif isinstance(message, AIMessage):
                found += [str(call["name"]) for call in message.tool_calls]
        later = [n for n in dict.fromkeys(found) if n in names and not self._starts_shown(n)]
        by_name = {_tool_name(tool): tool for tool in tools}
        # Found tools go last, in the order found, so the start of the request stays the same.
        kept = [t for t in tools if self._starts_shown(_tool_name(t))]
        return handler(request.override(tools=kept + [by_name[name] for name in later]))


class TaskContent(AgentMiddleware):
    """Puts this run's data beside its message, for the model only.

    It stays a user message rather than a prompt layer, because mail must never sit with the
    instructions, and it isn't saved, so old mail isn't sent again with every later run.
    """

    def __init__(self, task: str) -> None:
        super().__init__()
        self.task = task

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, HumanMessage) and not is_summary(message):
                messages[index] = message.model_copy(
                    update={"content": f"{self.task}\n\n{message.text}"}
                )
                break
        else:
            # A recovered checkpoint may contain only a summary; never omit run data.
            messages.append(HumanMessage(content=self.task))
        return handler(request.override(messages=messages))


class TaskNotes(AgentMiddleware):
    """Before each model call, adds notes on this run's task that it hasn't seen yet, so a note the
    person or the giver writes reaches it at its next step, not its next run. They join the
    conversation, so later steps and runs still have them."""

    def __init__(self, take: Callable[[], str]) -> None:
        super().__init__()
        self.take = take

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        notes = self.take()
        return {"messages": [HumanMessage(content=notes)]} if notes else None


class ToolLog(AgentMiddleware):
    """Records every tool call the approval path didn't already, so the run's record is whole."""

    def __init__(self, record: Callable[[str, str, dict[str, Any], str, int], None]) -> None:
        super().__init__()
        self.record = record

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        started = time.monotonic()
        result = handler(request)
        call = request.tool_call
        text = getattr(result, "content", "")
        self.record(
            str(call.get("id") or ""),
            str(call.get("name") or ""),
            dict(call.get("args") or {}),
            text if isinstance(text, str) else json.dumps(text, default=str),
            int((time.monotonic() - started) * 1000),
        )
        return result


def summarizer(
    model: Any,
    settings: ContextSettings,
    *,
    trigger: Any,
    on_compacted: Callable[[int, int], None] | None = None,
) -> AutoCompact:
    # Only the rules go with it. The agent's job and tools would just invite it to carry on working.
    writer = model.model_copy(update={"agent": "compress", "layers": model.layers[:1], "specs": []})
    return AutoCompact(
        settings.compact.keep_messages,
        on_compacted,
        model=writer,
        trigger=trigger,
        summary_prompt=packaged("compress.md"),
        trim_tokens_to_summarize=settings.compact.summarize_up_to_tokens,
    )


def middleware(
    model: Any,
    settings: ContextSettings,
    profile: ContextProfile,
    task: str,
    on_compacted: Callable[[int, int], None] | None = None,
    notes: Callable[[], str] | None = None,
    log_tool: Callable[[str, str, dict[str, Any], str, int], None] | None = None,
    shown_tools: frozenset[str] | None = None,
    always_shown_prefix: str = "",
) -> list[Any]:
    chain: list[Any] = [ToolSearch(shown_tools, always_shown_prefix)]
    if log_tool is not None:
        chain.append(ToolLog(log_tool))
    if profile.mode == "auto_compact":
        trigger = ("tokens", settings.compact.trigger_tokens)
        chain.append(summarizer(model, settings, trigger=trigger, on_compacted=on_compacted))
    elif profile.trim_saved_history:
        chain.append(TrimSaved(profile.keep_messages))
    else:
        chain.append(TrimView(profile.keep_messages))
    if notes is not None:
        chain.append(TaskNotes(notes))
    if task:
        chain.append(TaskContent(task))
    chain.append(
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=settings.tool_results.clear_after_tokens,
                    keep=settings.tool_results.keep_recent,
                    exclude_tools=KEEP_RESULTS_OF,
                )
            ]
        )
    )
    return chain


def compact_now(
    model: Any, settings: ContextSettings, messages: list[Any]
) -> dict[str, Any] | None:
    """Summarizes whatever is older than the messages to keep. None when there's nothing to do."""
    return SummarizationMiddleware.before_model(
        summarizer(model, settings, trigger=("messages", 1)),
        {"messages": messages},
        None,  # type: ignore[arg-type]
    )
