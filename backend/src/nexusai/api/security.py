import os
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

import structlog
from starlette.responses import JSONResponse

from nexusai.contracts.errors import ApiError

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

log = structlog.get_logger()

TOKEN_FILE = "install-token"
TOKEN_HEADER = "x-nexusai-token"
# Only says the server is up, and whatever starts the app needs it before anything else.
OPEN_PATHS = frozenset({"/api/health"})


def install_token(data_dir: Path) -> str:
    """One secret per install, readable only by this user. Local programs can reach the port too."""
    path = data_dir / TOKEN_FILE
    try:
        if existing := path.read_text(encoding="utf-8").strip():
            return existing
    except FileNotFoundError:
        pass
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(token)
    return token


class LocalOnlyMiddleware:
    """Any website could try to call a local port, so only the app's own requests get through.

    The Host check stops DNS rebinding, the Origin check stops other sites' pages, and the
    token stops other programs on this computer.
    """

    def __init__(
        self,
        app: App,
        allowed_hosts: frozenset[str],
        allowed_origins: frozenset[str],
        token: str | None = None,
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host, origin = headers.get("host"), headers.get("origin")
        if host not in self.allowed_hosts or (origin and origin not in self.allowed_origins):
            log.warning("request_refused", host=host, origin=origin, path=scope["path"])
            error = ApiError(code="request.refused", message="Request refused")
            await JSONResponse(error.model_dump(), status_code=403)(scope, receive, send)
            return
        if (
            self.token
            and scope["path"] not in OPEN_PATHS
            and not secrets.compare_digest(
                headers.get(TOKEN_HEADER, "").encode("latin-1"), self.token.encode("latin-1")
            )
        ):
            log.warning("request_unauthorized", path=scope["path"])
            error = ApiError(code="request.unauthorized", message="Request refused")
            await JSONResponse(error.model_dump(), status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)
