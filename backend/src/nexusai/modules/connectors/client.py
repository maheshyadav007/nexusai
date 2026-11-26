"""Talks to one MCP server. Each call opens a connection and closes it, so nothing is left open."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

HTTP_SCHEMES = {"http", "https"}
MESSAGE_LIMIT = 300


class ConnectorUnavailable(Exception):
    """The message is shown to the person."""


@dataclass(frozen=True)
class Listed:
    name: str
    description: str
    parameters: dict[str, Any]


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in HTTP_SCHEMES or not parsed.netloc:
        raise ConnectorUnavailable("Enter a full web address, starting with http:// or https://.")


def _flatten(error: BaseException) -> BaseException:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


def _run[T](
    url: str,
    token: str | None,
    seconds: float,
    work: Callable[[Client], Awaitable[T]],
    headers: dict[str, str] | None = None,
    transport: str = "http",
) -> T:
    """Agents run on plain threads, so each call gets its own short-lived event loop."""

    # What the server answered over HTTP, read only for its status: a 401 or 403 means it wants a
    # sign-in or a key, which its own words (never passed on) don't always say.
    statuses: list[int] = []

    async def record(response: Any) -> None:
        statuses.append(response.status_code)

    async def session() -> T:
        # The person's own headers, such as an API key, then the bearer token as a shortcut.
        sent = dict(headers or {})
        if token:
            sent["Authorization"] = f"Bearer {token}"
        if transport == "sse":
            # The older MCP transport: server-sent events, which some servers still use.
            async with Client(sse_client(url, headers=sent, timeout=seconds)) as client:
                return await asyncio.wait_for(work(client), seconds)
        async with (
            httpx2.AsyncClient(
                headers=sent, timeout=seconds, event_hooks={"response": [record]}
            ) as http,
            Client(streamable_http_client(url, http_client=http)) as client,
        ):
            return await asyncio.wait_for(work(client), seconds)

    try:
        return asyncio.run(session())
    except Exception as error:
        cause = _flatten(error)
        kind = type(cause).__name__
        # A server's own words could hold anything, so they're never passed on. Only whether it
        # asked for a sign-in is read from them, to say what the person can do.
        if _asks_to_sign_in(cause) or any(code in {401, 403} for code in statuses):
            raise ConnectorUnavailable(
                "The server was reached, but it wants you to sign in to it first (OAuth), which"
                " NexusAI can't do yet. If it also takes an API key or token, add that instead."
            ) from error
        raise ConnectorUnavailable(f"Couldn't reach that server ({kind}).") from error


def _asks_to_sign_in(cause: BaseException) -> bool:
    status = getattr(getattr(cause, "response", None), "status_code", None)
    words = str(cause).casefold()
    return status == 401 or "authenticat" in words or "unauthorized" in words


def list_tools(
    url: str,
    token: str | None,
    seconds: float,
    headers: dict[str, str] | None = None,
    transport: str = "http",
) -> list[Listed]:
    async def work(client: Client) -> list[Listed]:
        found = await client.list_tools()
        return [
            Listed(tool.name, tool.description or "", dict(tool.input_schema or {}))
            for tool in found.tools
        ]

    return _run(url, token, seconds, work, headers, transport)


def call_tool(
    url: str,
    token: str | None,
    name: str,
    arguments: dict[str, Any],
    seconds: float,
    headers: dict[str, str] | None = None,
    transport: str = "http",
) -> tuple[str, bool]:
    async def work(client: Client) -> tuple[str, bool]:
        result = await client.call_tool(name, arguments)
        words = [getattr(block, "text", "") for block in result.content]
        return "\n".join(word for word in words if word), bool(result.is_error)

    return _run(url, token, seconds, work, headers, transport)
