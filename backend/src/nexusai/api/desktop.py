"""Packaged desktop entry point; the ordinary web server has no desktop control routes."""

import asyncio
import os
import secrets
import sys
import threading
from typing import Any

import uvicorn
from starlette.responses import JSONResponse

from nexusai.api.app import create_app
from nexusai.api.main import KEEP_ALIVE_SECONDS, _speak_utf8
from nexusai.kernel.config import load_config


class DesktopControl:
    """Refuse a restart while work is active, then stop accepting new UI requests.

    Uvicorn drains HTTP work and the existing app lifespan closes workers and databases.
    The supervisor waits for a clean process exit; it never force-kills an update into place.
    """

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token
        self.active = 0
        self.draining = False
        self.server: uvicorn.Server | None = None

    def busy(self) -> bool:
        if self.active:
            return True
        bus = getattr(self.app.state, "bus", None)
        if bus is None:
            return False
        for table in ("agent_sessions", "pst_imports"):
            if bus.db.fetch_all(
                f"SELECT 1 FROM {table} WHERE status IN ('running', 'queued') LIMIT 1"
            ):
                return True
        return False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/__desktop__/prepare-exit":
            headers = dict(scope["headers"])
            supplied = headers.get(b"x-nexusai-desktop", b"").decode("latin-1")
            if scope["method"] != "POST" or not secrets.compare_digest(supplied, self.token):
                await JSONResponse({"error": "Not found"}, status_code=404)(scope, receive, send)
                return
            # Close the admission gate before yielding to the database check.
            self.draining = True
            if await asyncio.to_thread(self.busy):
                self.draining = False
                await JSONResponse({"busy": True}, status_code=409)(scope, receive, send)
                return
            await JSONResponse({"stopping": True})(scope, receive, send)
            assert self.server is not None
            self.server.should_exit = True
            return
        if self.draining:
            await JSONResponse({"error": "App is closing"}, status_code=503)(scope, receive, send)
            return
        tracked = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        if tracked:
            self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if tracked:
                self.active -= 1


def run() -> None:
    _speak_utf8()
    token = os.environ.pop("NEXUSAI_DESKTOP_CONTROL_TOKEN")
    config = load_config()
    controlled = DesktopControl(create_app(config), token)
    server = uvicorn.Server(
        uvicorn.Config(
            controlled,
            host=config.host,
            port=config.port,
            log_config=None,
            timeout_keep_alive=KEEP_ALIVE_SECONDS,
        )
    )
    controlled.server = server

    def parent_watch() -> None:
        # Closing the supervisor closes this pipe. This also handles a crashed Electron main.
        # No forced timeout: active HTTP work and lifespan shutdown must finish safely.
        sys.stdin.read()
        server.should_exit = True

    threading.Thread(target=parent_watch, daemon=True, name="desktop-parent").start()
    server.run()


if __name__ == "__main__":
    run()
