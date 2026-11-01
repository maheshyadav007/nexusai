import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from nexusai.api.security import LocalOnlyMiddleware
from nexusai.api.sse import sse_stream
from nexusai.contracts.errors import ApiError
from nexusai.contracts.events import EventLog, EventLogQuery
from nexusai.kernel.config import Config, load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.module import Context, Endpoint, Module
from nexusai.modules.settings.module import settings_module

MODULES: list[Module] = [settings_module]
log = structlog.get_logger()


def _error(status: int, code: str, message: str, trace_id: str | None = None) -> JSONResponse:
    body = ApiError(code=code, message=message, trace_id=trace_id).model_dump()
    return JSONResponse(body, status_code=status)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()
    db = Database(cfg.database_path)
    bus = EventBus(db, cfg)
    for module in MODULES:
        db.migrate(module.migrations)

    commands = {name: ep for m in MODULES for name, ep in m.commands.items()}
    queries = {name: ep for m in MODULES for name, ep in m.queries.items()}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        bus.start()
        yield
        bus.stop()
        db.close()

    app = FastAPI(title="NexusAI", lifespan=lifespan)
    app.add_middleware(
        LocalOnlyMiddleware,
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=cfg.allowed_origins,
    )
    app.state.bus = bus

    async def run(endpoint: Endpoint | None, name: str, request: Request) -> JSONResponse:
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        if endpoint is None:
            return _error(404, "contract.unknown", f"Unknown: {name}", trace_id)
        with structlog.contextvars.bound_contextvars(trace_id=trace_id, contract=name):
            try:
                body = await request.json() if await request.body() else {}
                data = endpoint.input_model.model_validate(body)
            except (ValidationError, json.JSONDecodeError) as error:
                log.warning("invalid_request", error=str(error))
                return _error(422, "request.invalid", "That request wasn't valid.", trace_id)
            ctx = Context(bus=bus, config=cfg, trace_id=trace_id)
            try:
                result = await asyncio.to_thread(endpoint.handler, data, ctx)
            except Exception:
                log.exception("handler_failed")
                return _error(500, "internal.error", "Something went wrong.", trace_id)
            return JSONResponse(result.model_dump(mode="json"), headers={"x-trace-id": trace_id})

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "latest_seq": bus.latest_seq()}

    @app.post("/api/commands/{name}")
    async def command(name: str, request: Request) -> JSONResponse:
        return await run(commands.get(name), name, request)

    @app.post("/api/queries/{name}")
    async def query(name: str, request: Request) -> JSONResponse:
        return await run(queries.get(name), name, request)

    @app.post("/api/events/log")
    async def event_log(query: EventLogQuery) -> EventLog:
        return EventLog(
            events=bus.events_since(query.since, cfg.log_page_size),
            failed=bus.failed_events(),
        )

    @app.get("/api/events")
    async def events(
        request: Request, since: int = 0, last_event_id: str | None = Header(default=None)
    ) -> StreamingResponse:
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else since

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        body = sse_stream(bus.stream(start), cfg.sse_keepalive_seconds, request.is_disconnected)
        return StreamingResponse(body, media_type="text/event-stream", headers=headers)

    return app
