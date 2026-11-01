import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import structlog
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from nexusai.api.security import LocalOnlyMiddleware, install_token
from nexusai.api.sse import sse_stream
from nexusai.contracts.agent import SessionChat
from nexusai.contracts.documents import DocumentRow
from nexusai.contracts.errors import ApiError
from nexusai.contracts.events import AppEvent, EventLog, EventLogQuery
from nexusai.contracts.home import (
    BackupList,
    BackupRow,
    BrowseFolders,
    CheckHome,
    ChooseHome,
    FolderListing,
    HomeCheck,
    HomeStatus,
    RecoveryKeyView,
    RestoreBackup,
    UnlockHome,
)
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel import backups, vault
from nexusai.kernel import home as homes
from nexusai.kernel.config import Config, load_config
from nexusai.kernel.database import Database, DatabaseDamaged
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.logging import configure_logging, sink
from nexusai.kernel.module import CommandError, Context, Endpoint, Listener, Module
from nexusai.kernel.secrets import secret_store
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.module import agent_module
from nexusai.modules.documents import module as documents
from nexusai.modules.documents.module import documents_module
from nexusai.modules.mail import store as mail_store
from nexusai.modules.mail.module import mail_module
from nexusai.modules.models.module import models_module, reset_login
from nexusai.modules.notifications.module import notifications_module
from nexusai.modules.onboarding.module import onboarding_module
from nexusai.modules.panels.module import panels_module
from nexusai.modules.planner.module import planner_module
from nexusai.modules.semantic.module import semantic_module
from nexusai.modules.settings.module import settings_module
from nexusai.modules.system.module import system_module

MODULES: list[Module] = [
    settings_module,
    models_module,
    onboarding_module,
    notifications_module,
    system_module,
    mail_module,
    documents_module,
    panels_module,
    planner_module,
    semantic_module,
    agent_module,
]
log = structlog.get_logger()
# Present while the app runs, so one left behind means the last exit wasn't clean.
RUNNING_FILE = "running"


def _error(status: int, code: str, message: str, trace_id: str | None = None) -> JSONResponse:
    body = ApiError(code=code, message=message, trace_id=trace_id).model_dump()
    return JSONResponse(body, status_code=status)


@dataclass
class Runtime:
    """Everything that needs an open Home. It doesn't exist until one is chosen or found."""

    config: Config
    db: Database
    bus: EventBus
    daily_backups: backups.DailyBackups


def _bound(handler: Listener, bus: EventBus, config: Config) -> Callable[[AppEvent], None]:
    return lambda event: handler(event, Context(bus=bus, config=config, trace_id=event.trace_id))


def _open_database(config: Config, home: Path, key: str) -> tuple[Database, bool]:
    """Encrypts, checks and backs up. Backups are taken here because nothing else is using it."""
    path = config.database_path
    encrypted = vault.encrypt_existing(path, key)
    vault.encrypt_existing(home / "system" / "checkpoints.db", key)
    sentinel = home / "system" / RUNNING_FILE
    db = Database(path, key)
    try:
        if sentinel.exists():
            log.warning("unclean_exit_found")
            db.check()
        migrations = [migration for module in MODULES for migration in module.migrations]
        upgrading = db.pending(migrations)
    except DatabaseDamaged:
        db.close()
        raise
    if upgrading:
        db.close()
        backups.create(home, "upgrade", config.backups_kept)
        db = Database(path, key)
    sentinel.touch()
    return db, encrypted


def _open_runtime(config: Config, home: Path) -> Runtime:
    homes.create_home(home)
    key = vault.open_key(home, secret_store(config.secrets_test_file))
    opened = replace(config, home_dir=home, database_key=key)
    db, newly_encrypted = _open_database(opened, home, key)
    bus = EventBus(db, opened)
    sink.attach(opened.home / "system" / "logs", opened.log_retention_days)
    for module in MODULES:
        db.migrate(module.migrations)
        for name, pattern, handler in module.listeners:
            bus.subscribe(name, pattern, _bound(handler, bus, opened))
    bus.start()
    context = Context(bus=bus, config=opened, trace_id=uuid.uuid4().hex)
    if newly_encrypted:
        _ask_to_save_recovery_key(bus)
    for module in MODULES:
        for start in module.on_start:
            start(context)
    daily = backups.DailyBackups(home, key, opened.backups_kept, opened.backup_interval_hours)
    daily.start()
    return Runtime(opened, db, bus, daily)


def _ask_to_save_recovery_key(bus: EventBus) -> None:
    """A Home from before encryption skipped the setup step that shows this."""
    with bus.unit_of_work() as work:
        work.emit(
            "notification.requested",
            NotificationRequested(
                title="Save your recovery key",
                detail="Your data is now encrypted. A new computer will need this key to open it.",
                link="/settings?section=home",
                kind="recovery-key",
            ).model_dump(),
            source="app",
            trace_id=uuid.uuid4().hex,
        )


def create_app(config: Config | None = None) -> FastAPI:
    configure_logging()
    cfg = config or load_config()
    data_dir = homes.app_data_dir()
    commands = {name: ep for m in MODULES for name, ep in m.commands.items()}
    queries = {name: ep for m in MODULES for name, ep in m.queries.items()}
    runtime: Runtime | None = None
    runtime_lock = threading.Lock()
    # A Home that was found but can't open yet: its path, and what's in the way.
    blocked: tuple[Path, Literal["locked", "damaged"]] | None = None
    store = secret_store(cfg.secrets_test_file)

    def open_home(path: Path) -> None:
        nonlocal runtime, blocked
        with runtime_lock:
            if runtime is None:
                try:
                    runtime = _open_runtime(cfg, path)
                except vault.VaultLocked:
                    blocked = (path, "locked")
                except DatabaseDamaged as error:
                    log.error("database_damaged", error=str(error))
                    blocked = (path, "damaged")
                else:
                    blocked = None
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
        for module in MODULES:
            for stop in module.on_stop:
                stop()
        if runtime is not None:
            runtime.daily_backups.stop()
            runtime.bus.stop()
            runtime.db.close()
            (runtime.config.home / "system" / RUNNING_FILE).unlink(missing_ok=True)
            sink.detach()

    app = FastAPI(title="NexusAI", lifespan=lifespan)
    app.add_middleware(
        LocalOnlyMiddleware,
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=cfg.allowed_origins,
        token=install_token(data_dir) if cfg.require_install_token else None,
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
        if blocked is not None:
            message = (
                "This Home is encrypted. Enter its recovery key to open it on this computer."
                if blocked[1] == "locked"
                else "NexusAI can't read its database, which may be damaged."
            )
            return HomeStatus(
                state=blocked[1], path=str(blocked[0]), default_path=default, message=message
            )
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
            return await asyncio.to_thread(homes.browse, command.path, command.extension)
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

    @app.post("/api/home/unlock", response_model=None)
    async def unlock_home(command: UnlockHome) -> HomeStatus | JSONResponse:
        if blocked is None or blocked[1] != "locked":
            return _error(409, "home.not_locked", "This Home isn't locked.")
        path = blocked[0]
        try:
            await asyncio.to_thread(vault.unlock, path, store, command.recovery_key)
        except vault.WrongRecoveryKey:
            log.info("recovery_key_refused")
            return _error(422, "home.wrong_key", "That recovery key doesn't match this Home.")
        await asyncio.to_thread(open_home, path)
        return home_status()

    @app.post("/api/home/backups")
    async def list_backups() -> BackupList:
        current = blocked[0] if blocked else runtime.config.home if runtime else None
        if current is None:
            return BackupList(backups=[])
        found = await asyncio.to_thread(backups.listing, current)
        return BackupList(
            backups=[
                BackupRow(name=b.name, reason=b.reason, time=b.time.isoformat(), size=b.size)
                for b in found
            ]
        )

    @app.post("/api/home/restore", response_model=None)
    async def restore_home(command: RestoreBackup) -> HomeStatus | JSONResponse:
        # Only a Home that won't open: an open one is using these files.
        if blocked is None or blocked[1] != "damaged":
            return _error(409, "home.not_damaged", "This Home doesn't need restoring.")
        path = blocked[0]
        try:
            await asyncio.to_thread(backups.restore, path, command.name)
        except FileNotFoundError:
            return _error(404, "backup.not_found", "That backup no longer exists.")
        (path / "system" / RUNNING_FILE).unlink(missing_ok=True)
        await asyncio.to_thread(open_home, path)
        log.info("home_restored", backup=command.name)
        return home_status()

    @app.post("/api/home/recovery-key", response_model=None)
    async def recovery_key() -> RecoveryKeyView | JSONResponse:
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        pending = await asyncio.to_thread(vault.pending_recovery_key, runtime.config.home, store)
        return RecoveryKeyView(pending=pending)

    @app.post("/api/home/recovery-key/confirm", response_model=None)
    async def confirm_recovery_key() -> RecoveryKeyView | JSONResponse:
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        await asyncio.to_thread(vault.confirm_saved, runtime.config.home, store)
        return RecoveryKeyView()

    @app.post("/api/home/recovery-key/new", response_model=None)
    async def replace_recovery_key() -> RecoveryKeyView | JSONResponse:
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        fresh = await asyncio.to_thread(vault.new_recovery_key, runtime.config.home, store)
        return RecoveryKeyView(pending=fresh)

    @app.get("/api/mail/attachment/{message}/{index}", response_model=None)
    async def mail_attachment(message: int, index: int) -> Response:
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        found = await asyncio.to_thread(mail_store.attachment, runtime.db, message, index)
        if found is None:
            return _error(404, "attachment.not_found", "That attachment no longer exists.")
        filename, body, risky = found
        if risky:
            return _error(403, "attachment.risky", "NexusAI won't open this kind of file.")
        # Always a download with a fixed type, so a file can't run as a page on this address.
        safe_name = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
            "X-Content-Type-Options": "nosniff",
        }
        return Response(body, media_type="application/octet-stream", headers=headers)

    def bare_context() -> Context | None:
        if runtime is None:
            return None
        return Context(bus=runtime.bus, config=runtime.config, trace_id=uuid.uuid4().hex)

    @app.post("/api/documents/upload", response_model=None)
    async def upload_document(request: Request, name: str) -> DocumentRow | JSONResponse:
        ctx = bare_context()
        if ctx is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        declared = int(request.headers.get("content-length") or 0)
        if declared > cfg.max_upload_bytes:
            return _error(413, "document.too_large", "That file is too large to add.")
        data = await request.body()
        if len(data) > cfg.max_upload_bytes:
            return _error(413, "document.too_large", "That file is too large to add.")
        try:
            return await asyncio.to_thread(documents.save_upload, ctx, name, data)
        except CommandError as error:
            return _error(error.status, error.code, error.message)

    @app.get("/api/documents/file", response_model=None)
    async def document_file(key: str) -> Response:
        ctx = bare_context()
        if ctx is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        try:
            found = await asyncio.to_thread(documents.document_file, ctx, key)
        except ValueError:
            found = None
        if found is None:
            return _error(404, "document.not_found", "That document no longer exists.")
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(found[0])}",
            "X-Content-Type-Options": "nosniff",
        }
        return Response(found[1], media_type="application/octet-stream", headers=headers)

    ui_stream_headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        # The AI SDK reads this to know which stream format it's getting.
        "x-vercel-ai-ui-message-stream": "v1",
    }

    @app.post("/api/sessions/chat", response_model=None)
    async def session_chat(body: SessionChat, request: Request) -> Response:
        """Starts a turn and streams it. The turn keeps running if this connection drops."""
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        try:
            sessions = agent.current()
            turn = await asyncio.to_thread(sessions.send, body.id, body.text, body.edit_index)
        except CommandError as error:
            return _error(error.status, error.code, error.message)
        stream = sessions.stream_turn(turn, request.is_disconnected)
        return StreamingResponse(stream, media_type="text/event-stream", headers=ui_stream_headers)

    @app.get("/api/sessions/chat/{session}/stream", response_model=None)
    async def session_stream(session: str, request: Request) -> Response:
        """Reattaches to a running turn from its start. 204 means nothing is running."""
        if runtime is None:
            return _error(409, "home.not_ready", "Choose a NexusAI Home first.")
        sessions = agent.current()
        turn = await asyncio.to_thread(sessions.active_turn, session)
        if turn is None:
            return Response(status_code=204)
        stream = sessions.stream_turn(turn, request.is_disconnected)
        return StreamingResponse(stream, media_type="text/event-stream", headers=ui_stream_headers)

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
