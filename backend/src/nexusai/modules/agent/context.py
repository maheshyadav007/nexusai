"""What the model gets to see of a conversation. The chat itself always shows everything."""

import json
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
from langchain_core.messages import HumanMessage, RemoveMessage, trim_messages
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
KEEP_RESULTS_OF = ("record_triage",)


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
    return base.model_copy(update={k: v for k, v in (own or {}).items() if v is not None})


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
                messages[index] = HumanMessage(
                    content=f"{self.task}\n\n{message.text}", id=message.id
                )
                break
        return handler(request.override(messages=messages))


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
) -> list[Any]:
    chain: list[Any] = []
    if profile.mode == "auto_compact":
        trigger = ("tokens", settings.compact.trigger_tokens)
        chain.append(summarizer(model, settings, trigger=trigger, on_compacted=on_compacted))
    elif profile.trim_saved_history:
        chain.append(TrimSaved(profile.keep_messages))
    else:
        chain.append(TrimView(profile.keep_messages))
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
