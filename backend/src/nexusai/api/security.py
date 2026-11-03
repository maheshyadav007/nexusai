import os
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

import structlog
from starlette.responses import JSONResponse, Response

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
PREFLIGHT = "access-control-request-method"
PREFLIGHT_SECONDS = "600"
ALLOWED_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
REFUSED = (
    "This address isn't allowed to reach NexusAI. Open the app at http://127.0.0.1:4000, or add"
    " this address to NEXUSAI_ALLOWED_ORIGINS."
)


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


def _cross_origin(origin: str) -> dict[str, str]:
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": ALLOWED_METHODS,
        "access-control-allow-headers": f"content-type, {TOKEN_HEADER}, x-trace-id",
        "vary": "Origin",
    }


def _answering(send: Send, origin: str) -> Send:
    """Lets the page read the answer, errors included, so it can say what went wrong."""

    async def sending(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            added = [
                (k.encode("latin-1"), v.encode("latin-1")) for k, v in _cross_origin(origin).items()
            ]
            message = {**message, "headers": [*message.get("headers", []), *added]}
        await send(message)

    return sending


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
            error = ApiError(code="request.refused", message=REFUSED)
            await JSONResponse(error.model_dump(), status_code=403)(scope, receive, send)
            return
        # A browser asks first, and that question can't carry the token.
        if origin and scope["method"] == "OPTIONS" and PREFLIGHT in headers:
            allowed = {**_cross_origin(origin), "access-control-max-age": PREFLIGHT_SECONDS}
            await Response(status_code=204, headers=allowed)(scope, receive, send)
            return
        if origin:
            send = _answering(send, origin)
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
