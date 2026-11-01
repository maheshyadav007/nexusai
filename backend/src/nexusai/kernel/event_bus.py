import asyncio
import fnmatch
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.events import AppEvent, FailedEvent
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.logging import log

Handler = Callable[[AppEvent], None]

MIGRATIONS = [
    Migration(
        "event_bus_001",
        """
        CREATE TABLE events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            version INTEGER NOT NULL,
            time TEXT NOT NULL,
            source TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            cause_id TEXT,
            depth INTEGER NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX events_trace ON events (trace_id);
        CREATE TABLE event_cursors (listener TEXT PRIMARY KEY, seq INTEGER NOT NULL);
        CREATE TABLE failed_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listener TEXT NOT NULL,
            event_seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            error TEXT NOT NULL,
            time TEXT NOT NULL
        );
        """,
    )
]


class EventChainTooDeep(Exception):
    pass


@dataclass(frozen=True)
class _Listener:
    name: str
    pattern: str
    handler: Handler


def _row_to_event(row: sqlite3.Row) -> AppEvent:
    return AppEvent(
        id=row["id"],
        seq=row["seq"],
        type=row["type"],
        version=row["version"],
        time=row["time"],
        source=row["source"],
        trace_id=row["trace_id"],
        cause_id=row["cause_id"],
        depth=row["depth"],
        payload=json.loads(row["payload"]),
    )


class UnitOfWork:
    """A data change and its events, committed together or not at all."""

    def __init__(self, tx: sqlite3.Connection, bus: "EventBus") -> None:
        self.tx = tx
        self._bus = bus
        self.events: list[AppEvent] = []

    def emit(
        self,
        type: str,
        payload: dict[str, Any],
        *,
        source: str,
        trace_id: str | None = None,
        cause: AppEvent | None = None,
        version: int = 1,
    ) -> AppEvent:
        depth = cause.depth + 1 if cause else 0
        if depth > self._bus.config.max_chain_depth:
            raise EventChainTooDeep(f"{type} exceeds depth {self._bus.config.max_chain_depth}")
        event_id = uuid.uuid4().hex
        trace = trace_id or (cause.trace_id if cause else uuid.uuid4().hex)
        now = datetime.now(UTC).isoformat()
        cursor = self.tx.execute(
            "INSERT INTO events"
            " (id, type, version, time, source, trace_id, cause_id, depth, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                type,
                version,
                now,
                source,
                trace,
                cause.id if cause else None,
                depth,
                json.dumps(payload),
            ),
        )
        event = AppEvent(
            id=event_id,
            seq=cursor.lastrowid or 0,
            type=type,
            version=version,
            time=now,
            source=source,
            trace_id=trace,
            cause_id=cause.id if cause else None,
            depth=depth,
            payload=payload,
        )
        self.events.append(event)
        return event


class EventBus:
    def __init__(self, db: Database, config: Config) -> None:
        self.db = db
        self.config = config
        self._listeners: list[_Listener] = []
        self._streams: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[AppEvent]]] = []
        self._streams_lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = False
        self._worker: threading.Thread | None = None
        db.migrate(MIGRATIONS)

    @contextmanager
    def unit_of_work(self) -> Iterator[UnitOfWork]:
        with self.db.transaction() as tx:
            work = UnitOfWork(tx, self)
            yield work
        for event in work.events:
            self._publish_to_streams(event)
            log.info("event", type=event.type, seq=event.seq, trace_id=event.trace_id)
        if work.events:
            self._wake.set()

    def subscribe(self, listener: str, pattern: str, handler: Handler) -> None:
        """New listeners start from now; existing ones resume from their saved position."""
        self._listeners.append(_Listener(listener, pattern, handler))
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO event_cursors (listener, seq)"
                " SELECT ?, COALESCE(MAX(seq), 0) FROM events",
                (listener,),
            )

    def deliver_pending(self) -> None:
        for listener in self._listeners:
            cursor = self.db.fetch_all(
                "SELECT seq FROM event_cursors WHERE listener = ?", (listener.name,)
            )[0]["seq"]
            rows = self.db.fetch_all("SELECT * FROM events WHERE seq > ? ORDER BY seq", (cursor,))
            for row in rows:
                event = _row_to_event(row)
                if fnmatch.fnmatch(event.type, listener.pattern):
                    self._deliver(listener, event)
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE event_cursors SET seq = ? WHERE listener = ?",
                        (event.seq, listener.name),
                    )

    def _deliver(self, listener: _Listener, event: AppEvent) -> None:
        for attempt in range(1, self.config.handler_max_attempts + 1):
            try:
                listener.handler(event)
                return
            except Exception as error:
                log.warning(
                    "listener_failed",
                    listener=listener.name,
                    type=event.type,
                    trace_id=event.trace_id,
                    attempt=attempt,
                    error=str(error),
                )
                if attempt == self.config.handler_max_attempts:
                    with self.db.transaction() as tx:
                        tx.execute(
                            "INSERT INTO failed_events"
                            " (listener, event_seq, event_type, error, time)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (
                                listener.name,
                                event.seq,
                                event.type,
                                str(error),
                                datetime.now(UTC).isoformat(),
                            ),
                        )
                else:
                    time.sleep(self.config.handler_retry_delay_seconds)

    def start(self) -> None:
        """Delivers anything missed while stopped, then sleeps until new events arrive."""

        def run() -> None:
            while not self._stopping:
                self.deliver_pending()
                self._wake.wait()
                self._wake.clear()

        self._worker = threading.Thread(target=run, name="event-bus", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._worker:
            self._worker.join()

    def events_since(self, since: int, limit: int | None = None) -> list[AppEvent]:
        sql = "SELECT * FROM events WHERE seq > ? ORDER BY seq"
        params: tuple[int, ...] = (since,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (since, limit)
        return [_row_to_event(row) for row in self.db.fetch_all(sql, params)]

    def failed_events(self) -> list[FailedEvent]:
        rows = self.db.fetch_all(
            "SELECT listener, event_seq, event_type, error, time FROM failed_events ORDER BY id"
        )
        return [FailedEvent(**dict(row)) for row in rows]

    def latest_seq(self) -> int:
        return int(self.db.fetch_all("SELECT COALESCE(MAX(seq), 0) AS seq FROM events")[0]["seq"])

    def _publish_to_streams(self, event: AppEvent) -> None:
        with self._streams_lock:
            for loop, queue in self._streams:
                loop.call_soon_threadsafe(queue.put_nowait, event)

    async def stream(self, since: int) -> AsyncGenerator[AppEvent, None]:
        """Saved events after `since`, then live ones, with no gap and no repeats."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AppEvent] = asyncio.Queue()
        entry = (loop, queue)
        with self._streams_lock:
            self._streams.append(entry)
        try:
            last = since
            for event in await asyncio.to_thread(self.events_since, since):
                last = event.seq
                yield event
            while True:
                event = await queue.get()
                if event.seq > last:
                    last = event.seq
                    yield event
        finally:
            with self._streams_lock:
                self._streams.remove(entry)
