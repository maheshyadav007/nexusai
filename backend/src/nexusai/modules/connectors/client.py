"""Talks to one MCP server. Each call opens a connection and closes it, so nothing is left open."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx2
from mcp import Client
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
    url: str, token: str | None, seconds: float, work: Callable[[Client], Awaitable[T]]
) -> T:
    """Agents run on plain threads, so each call gets its own short-lived event loop."""

    async def session() -> T:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=seconds) as http,
            Client(streamable_http_client(url, http_client=http)) as client,
        ):
            return await asyncio.wait_for(work(client), seconds)

    try:
        return asyncio.run(session())
    except Exception as error:
        kind = type(_flatten(error)).__name__
        # A server's own words could hold anything, so only what kind of failure it was is kept.
        raise ConnectorUnavailable(f"Couldn't reach that server ({kind}).") from error


def list_tools(url: str, token: str | None, seconds: float) -> list[Listed]:
    async def work(client: Client) -> list[Listed]:
        found = await client.list_tools()
        return [
            Listed(tool.name, tool.description or "", dict(tool.input_schema or {}))
            for tool in found.tools
        ]

    return _run(url, token, seconds, work)


def call_tool(
    url: str, token: str | None, name: str, arguments: dict[str, Any], seconds: float
) -> tuple[str, bool]:
    async def work(client: Client) -> tuple[str, bool]:
        result = await client.call_tool(name, arguments)
        words = [getattr(block, "text", "") for block in result.content]
        return "\n".join(word for word in words if word), bool(result.is_error)

    return _run(url, token, seconds, work)
