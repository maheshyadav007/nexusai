import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

from nexusai.contracts.events import AppEvent


async def sse_stream(
    stream: AsyncGenerator[AppEvent, None],
    keepalive_seconds: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    next_event: asyncio.Future[AppEvent] | None = None
    yield ": connected\n\n"
    try:
        while not await is_disconnected():
            next_event = next_event or asyncio.ensure_future(anext(stream))
            done, _ = await asyncio.wait({next_event}, timeout=keepalive_seconds)
            if not done:
                yield ": keepalive\n\n"
                continue
            event = next_event.result()
            next_event = None
            yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"
    finally:
        # The pending read must finish cancelling before the generator can close.
        if next_event:
            next_event.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await next_event
        await stream.aclose()
