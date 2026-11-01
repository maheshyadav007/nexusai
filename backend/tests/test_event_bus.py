import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from nexusai.api.sse import sse_stream
from nexusai.contracts.events import AppEvent
from nexusai.kernel.config import Config, load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus, EventChainTooDeep


@pytest.fixture
def bus(config: Config) -> EventBus:
    return EventBus(Database(config.database_path), config)


def emit(bus: EventBus, type: str = "test.happened") -> AppEvent:
    with bus.unit_of_work() as work:
        return work.emit(type, {"n": 1}, source="test")


def test_failed_transaction_leaves_no_event(bus: EventBus) -> None:
    with pytest.raises(RuntimeError), bus.unit_of_work() as work:
        work.emit("test.happened", {}, source="test")
        raise RuntimeError
    assert bus.events_since(0) == []


def test_listener_receives_only_matching_events(bus: EventBus) -> None:
    seen: list[str] = []
    bus.subscribe("listener", "mail.*", lambda e: seen.append(e.type))
    emit(bus, "mail.received")
    emit(bus, "task.created")
    bus.deliver_pending()
    assert seen == ["mail.received"]


def test_delivered_event_is_not_repeated(bus: EventBus) -> None:
    seen: list[int] = []
    bus.subscribe("listener", "*", lambda e: seen.append(e.seq))
    emit(bus)
    bus.deliver_pending()
    bus.deliver_pending()
    assert len(seen) == 1


def test_failing_listener_does_not_affect_others_and_is_recorded(bus: EventBus) -> None:
    seen: list[int] = []

    def broken(_: AppEvent) -> None:
        raise ValueError("broken")

    bus.subscribe("broken", "*", broken)
    bus.subscribe("working", "*", lambda e: seen.append(e.seq))
    event = emit(bus)
    bus.deliver_pending()
    assert seen == [event.seq]
    failed = bus.failed_events()
    assert [(f.listener, f.event_seq, f.error) for f in failed] == [("broken", event.seq, "broken")]


def test_retry_succeeds_without_recording_failure(bus: EventBus) -> None:
    calls: list[int] = []

    def flaky(event: AppEvent) -> None:
        calls.append(event.seq)
        if len(calls) == 1:
            raise ValueError("first try fails")

    bus.subscribe("flaky", "*", flaky)
    emit(bus)
    bus.deliver_pending()
    assert len(calls) == 2
    assert bus.failed_events() == []


def test_event_chain_is_limited(bus: EventBus) -> None:
    event = emit(bus)
    with pytest.raises(EventChainTooDeep):
        for _ in range(bus.config.max_chain_depth + 1):
            with bus.unit_of_work() as work:
                event = work.emit("loop", {}, source="test", cause=event)


def test_chained_events_share_trace(bus: EventBus) -> None:
    first = emit(bus)
    with bus.unit_of_work() as work:
        second = work.emit("next", {}, source="test", cause=first)
    assert second.trace_id == first.trace_id
    assert second.cause_id == first.id


def test_event_survives_process_crash_and_is_delivered_after_restart(tmp_path: Path) -> None:
    # A listener registers, then a real process commits an event and dies before delivering it.
    script = textwrap.dedent(
        f"""
        import os
        from pathlib import Path
        from nexusai.kernel.config import load_config
        from nexusai.kernel.database import Database
        from nexusai.kernel.event_bus import EventBus
        config = load_config(Path({str(tmp_path)!r}))
        bus = EventBus(Database(config.database_path), config)
        bus.subscribe("listener", "*", lambda e: None)
        with bus.unit_of_work() as work:
            work.emit("mail.received", {{"id": "m1"}}, source="test")
        os._exit(9)
        """
    )
    result = subprocess.run([sys.executable, "-c", script], check=False)
    assert result.returncode == 9

    config = load_config(tmp_path)
    bus = EventBus(Database(config.database_path), config)
    seen: list[AppEvent] = []
    bus.subscribe("listener", "*", seen.append)
    bus.deliver_pending()
    assert [(e.type, e.payload) for e in seen] == [("mail.received", {"id": "m1"})]


async def test_stream_replays_then_goes_live_without_gap_or_repeat(bus: EventBus) -> None:
    first = emit(bus)
    second = emit(bus)
    stream = bus.stream(since=first.seq)
    assert (await anext(stream)).seq == second.seq
    third_read = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    third = await asyncio.to_thread(emit, bus)
    assert (await asyncio.wait_for(third_read, 2)).seq == third.seq
    await stream.aclose()


async def test_closing_a_browser_connection_cleans_up_while_waiting_for_events(
    bus: EventBus,
) -> None:
    # Regression: closing the stream while a read was pending raised RuntimeError.
    checks = iter([False, True])

    async def is_disconnected() -> bool:
        return next(checks)

    chunks = [c async for c in sse_stream(bus.stream(since=0), 0.01, is_disconnected)]
    assert chunks == [": connected\n\n", ": keepalive\n\n"]
    assert bus._streams == []


async def test_stream_format_carries_the_position_for_reconnecting(bus: EventBus) -> None:
    event = emit(bus)
    body = sse_stream(bus.stream(since=0), 1, lambda: asyncio.sleep(0, False))
    assert await anext(body) == ": connected\n\n"
    assert (await anext(body)).startswith(f"id: {event.seq}\ndata: ")
    await body.aclose()
