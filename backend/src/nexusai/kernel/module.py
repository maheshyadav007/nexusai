from collections.abc import Callable
from dataclasses import dataclass, field
from inspect import signature
from typing import Any, get_type_hints

from pydantic import BaseModel

from nexusai.contracts.events import AppEvent
from nexusai.kernel.config import Config
from nexusai.kernel.database import Migration
from nexusai.kernel.event_bus import EventBus


class CommandError(Exception):
    """A failure the user should see. The message says what to do next."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Context:
    bus: EventBus
    config: Config
    trace_id: str
    # Who a change comes from, so what an agent does isn't taken as the person's own choice.
    actor: str = "person"


Route = Callable[[Any, Context], BaseModel]
Listener = Callable[[AppEvent, Context], None]


@dataclass(frozen=True)
class Endpoint:
    name: str
    handler: Route
    input_model: type[BaseModel]
    output_model: type[BaseModel]


@dataclass
class Module:
    """One area of the app. Its commands, queries and events are the only way in or out."""

    name: str
    migrations: list[Migration] = field(default_factory=list)
    commands: dict[str, Endpoint] = field(default_factory=dict)
    queries: dict[str, Endpoint] = field(default_factory=dict)
    listeners: list[tuple[str, str, Listener]] = field(default_factory=list)
    on_start: list[Callable[[Context], None]] = field(default_factory=list)
    on_stop: list[Callable[[], None]] = field(default_factory=list)
    # Before a reset wipes everything: whatever it keeps outside Home, like saved passwords.
    on_reset: list[Callable[[Context], None]] = field(default_factory=list)

    def on(self, pattern: str, name: str) -> Callable[[Listener], Listener]:
        """Runs after matching events. The name keeps its place in the event log across restarts."""

        def decorator(handler: Listener) -> Listener:
            self.listeners.append((name, pattern, handler))
            return handler

        return decorator

    def command(self, name: str) -> Callable[[Route], Route]:
        return self._register(self.commands, name)

    def query(self, name: str) -> Callable[[Route], Route]:
        return self._register(self.queries, name)

    @staticmethod
    def _register(target: dict[str, Endpoint], name: str) -> Callable[[Route], Route]:
        def decorator(handler: Route) -> Route:
            hints = get_type_hints(handler)
            input_param = next(iter(signature(handler).parameters))
            target[name] = Endpoint(name, handler, hints[input_param], hints["return"])
            return handler

        return decorator
