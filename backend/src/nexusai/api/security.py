from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog
from starlette.responses import JSONResponse

from nexusai.contracts.errors import ApiError

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

log = structlog.get_logger()


class LocalOnlyMiddleware:
    """Any website could try to call a local port, so only the app's own requests get through.

    The Host check stops DNS rebinding, and the Origin check stops other sites' pages.
    """

    def __init__(
        self, app: App, allowed_hosts: frozenset[str], allowed_origins: frozenset[str]
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins

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
        await self.app(scope, receive, send)
