import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from nexusai.api.security import LocalOnlyMiddleware
from nexusai.api.sse import sse_stream
from nexusai.contracts.errors import ApiError
from nexusai.contracts.events import AppEvent, EventLog, EventLogQuery
from nexusai.contracts.home import (
    BrowseFolders,
    CheckHome,
    ChooseHome,
    FolderListing,
    HomeCheck,
    HomeStatus,
)
from nexusai.kernel import home as homes
from nexusai.kernel.config import Config, load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.logging import configure_logging, sink
from nexusai.kernel.module import CommandError, Context, Endpoint, Listener, Module
from nexusai.modules.models.module import models_module, reset_login
from nexusai.modules.notifications.module import notifications_module
from nexusai.modules.onboarding.module import onboarding_module
from nexusai.modules.settings.module import settings_module
from nexusai.modules.system.module import system_module

MODULES: list[Module] = [
    settings_module,
    models_module,
    onboarding_module,
    notifications_module,
    system_module,
]
log = structlog.get_logger()


def _error(status: int, code: str, message: str, trace_id: str | None = None) -> JSONResponse:
    body = ApiError(code=code, message=message, trace_id=trace_id).model_dump()
    return JSONResponse(body, status_code=status)


@dataclass
class Runtime:
    """Everything that needs an open Home. It doesn't exist until one is chosen or found."""

    config: Config
    db: Database
    bus: EventBus


def _bound(handler: Listener, bus: EventBus, config: Config) -> Callable[[AppEvent], None]:
    return lambda event: handler(event, Context(bus=bus, config=config, trace_id=event.trace_id))


def _open_runtime(config: Config, home: Path) -> Runtime:
    homes.create_home(home)
    opened = replace(config, home_dir=home)
    db = Database(opened.database_path)
    bus = EventBus(db, opened)
    sink.attach(opened.home / "system" / "logs", opened.log_retention_days)
    for module in MODULES:
        db.migrate(module.migrations)
        for name, pattern, handler in module.listeners:
            bus.subscribe(name, pattern, _bound(handler, bus, opened))
    bus.start()
    return Runtime(opened, db, bus)


def create_app(config: Config | None = None) -> FastAPI:
    configure_logging()
    cfg = config or load_config()
    data_dir = homes.app_data_dir()
    commands = {name: ep for m in MODULES for name, ep in m.commands.items()}
    queries = {name: ep for m in MODULES for name, ep in m.queries.items()}
    runtime: Runtime | None = None
    runtime_lock = threading.Lock()

    def open_home(path: Path) -> None:
        nonlocal runtime
        with runtime_lock:
            if runtime is None:
                runtime = _open_runtime(cfg, path)
                app.state.bus = runtime.bus

    def startup_home() -> Path | None:
        """The Home to open at startup. A missing one is never silently recreated."""
        if cfg.home_dir is not None:
            return cfg.home_dir
        pointer = homes.read_pointer(data_dir)
        if pointer and homes.is_home(pointer) and not homes.too_new(pointer):
            return pointer
        return None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if home := startup_home():
            open_home(home)
        yield
        reset_login()
        if runtime is not None:
            runtime.bus.stop()
            runtime.db.close()
            sink.detach()

    app = FastAPI(title="NexusAI", lifespan=lifespan)
    app.add_middleware(
        LocalOnlyMiddleware,
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=cfg.allowed_origins,
    )

    async def run(endpoint: Endpoint | None, name: str, request: Request) -> JSONResponse:
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        if endpoint is None:
            return _error(404, "contract.unknown", f"Unknown: {name}", trace_id)
        current = runtime
        if current is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.", trace_id)
        with structlog.contextvars.bound_contextvars(trace_id=trace_id, contract=name):
            try:
                body = await request.json() if await request.body() else {}
                data = endpoint.input_model.model_validate(body)
            except (ValidationError, json.JSONDecodeError) as error:
                log.warning("invalid_request", error=str(error))
                return _error(422, "request.invalid", "That request wasn't valid.", trace_id)
            ctx = Context(bus=current.bus, config=current.config, trace_id=trace_id)
            try:
                result = await asyncio.to_thread(endpoint.handler, data, ctx)
            except CommandError as error:
                log.info("command_refused", code=error.code)
                return _error(error.status, error.code, error.message, trace_id)
            except Exception:
                log.exception("handler_failed")
                return _error(500, "internal.error", "Something went wrong.", trace_id)
            return JSONResponse(result.model_dump(mode="json"), headers={"x-trace-id": trace_id})

    def home_status() -> HomeStatus:
        default = str(homes.default_home())
        if runtime is not None:
            return HomeStatus(state="ready", path=str(runtime.config.home), default_path=default)
        pointer = homes.read_pointer(data_dir)
        if pointer is None:
            return HomeStatus(state="unset", default_path=default)
        message = (
            "This Home was made by a newer NexusAI. Update the app to open it."
            if homes.too_new(pointer)
            else "NexusAI can't find your Home at this location."
        )
        return HomeStatus(state="missing", path=str(pointer), default_path=default, message=message)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        latest = runtime.bus.latest_seq() if runtime is not None else 0
        return {"status": "ok", "latest_seq": latest, "home": home_status().state}

    @app.post("/api/home/status")
    async def get_home_status() -> HomeStatus:
        return home_status()

    @app.post("/api/home/check")
    async def check_home(command: CheckHome) -> HomeCheck:
        return await asyncio.to_thread(homes.check_folder, command.path, cfg.min_free_bytes)

    @app.post("/api/home/browse", response_model=None)
    async def browse_home(command: BrowseFolders) -> FolderListing | JSONResponse:
        try:
            return await asyncio.to_thread(homes.browse, command.path)
        except homes.HomeError as error:
            return _error(422, "home.unreadable", str(error))

    @app.post("/api/home/choose", response_model=None)
    async def choose_home(command: ChooseHome) -> HomeStatus | JSONResponse:
        if runtime is not None:
            return _error(409, "home.already_open", "Home is already open.")
        check = await asyncio.to_thread(homes.check_folder, command.path, cfg.min_free_bytes)
        if not check.ok:
            return _error(422, "home.not_allowed", " ".join(check.problems))
        path = Path(check.path)
        if command.must_exist and not check.is_existing_home:
            message = "That folder isn't a NexusAI Home. Choose the folder that contains home.json."
            return _error(422, "home.not_found", message)
        try:
            await asyncio.to_thread(open_home, path)
        except homes.HomeError as error:
            return _error(422, "home.not_allowed", str(error))
        homes.write_pointer(data_dir, path)
        log.info("home_opened", existing=check.is_existing_home)
        return home_status()

    @app.post("/api/commands/{name}")
    async def command(name: str, request: Request) -> JSONResponse:
        return await run(commands.get(name), name, request)

    @app.post("/api/queries/{name}")
    async def query(name: str, request: Request) -> JSONResponse:
        return await run(queries.get(name), name, request)

    @app.get("/api/logs/stream")
    async def log_stream(request: Request) -> StreamingResponse:
        async def body() -> AsyncIterator[str]:
            queue, stop = sink.follow()
            yield ": connected\n\n"
            try:
                while not await request.is_disconnected():
                    try:
                        line = await asyncio.wait_for(queue.get(), cfg.sse_keepalive_seconds)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(line, default=str)}\n\n"
            finally:
                stop()

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(body(), media_type="text/event-stream", headers=headers)

    @app.post("/api/events/log", response_model=None)
    async def event_log(query: EventLogQuery) -> EventLog | JSONResponse:
        if runtime is None:
            return EventLog(events=[], failed=[])
        return EventLog(
            events=runtime.bus.events_since(query.since, cfg.log_page_size),
            failed=runtime.bus.failed_events(),
        )

    @app.get("/api/events", response_model=None)
    async def events(
        request: Request, since: int = 0, last_event_id: str | None = Header(default=None)
    ) -> Response:
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else since
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        body = sse_stream(
            runtime.bus.stream(start), cfg.sse_keepalive_seconds, request.is_disconnected
        )
        return StreamingResponse(body, media_type="text/event-stream", headers=headers)

    return app
