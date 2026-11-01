"""Structured logs: secrets removed, written to Home, and followed live by the Logs screen."""

import asyncio
import json
import logging
import re
import threading
from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

SECRET_KEYS = re.compile(
    r"pass(word|wd)?|secret|token|authorization|api[_-]?key|cookie|credential|verifier", re.I
)
# Mail content stays out unless debug logging is on.
CONTENT_KEYS = re.compile(r"^(body|html|text_body|message_body|content|prompt|snippet)$", re.I)
SECRET_VALUES = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)?"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
)
REMOVED = "[removed]"


def _clean(value: Any, debug: bool) -> Any:
    if isinstance(value, str):
        for pattern in SECRET_VALUES:
            value = pattern.sub(REMOVED, value)
        return value
    if isinstance(value, dict):
        return clean_fields(value, debug)
    if isinstance(value, (list, tuple)):
        return [_clean(item, debug) for item in value]
    return value


def clean_fields(fields: MutableMapping[str, Any], debug: bool = False) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if SECRET_KEYS.search(str(key)) or (not debug and CONTENT_KEYS.match(str(key))):
            cleaned[key] = REMOVED
        else:
            cleaned[key] = _clean(value, debug)
    return cleaned


class LogSink:
    """Daily files under Home, plus any screens following along. Empty until Home opens."""

    def __init__(self) -> None:
        self._folder: Path | None = None
        self._lock = threading.Lock()
        self._followers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []
        self.debug = False

    def attach(self, folder: Path, retention_days: int) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._folder = folder
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        for file in folder.glob("nexusai-*.jsonl"):
            if file.stem.removeprefix("nexusai-") < cutoff:
                file.unlink(missing_ok=True)

    def detach(self) -> None:
        with self._lock:
            self._folder = None

    def write(self, line: dict[str, Any]) -> None:
        with self._lock:
            if self._folder is not None:
                day = str(line.get("timestamp", ""))[:10] or datetime.now(UTC).strftime("%Y-%m-%d")
                with (self._folder / f"nexusai-{day}.jsonl").open("a", encoding="utf8") as file:
                    file.write(json.dumps(line, default=str) + "\n")
            for loop, queue in self._followers:
                loop.call_soon_threadsafe(queue.put_nowait, line)

    def follow(self) -> tuple[asyncio.Queue[dict[str, Any]], Any]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        entry = (loop, queue)
        with self._lock:
            self._followers.append(entry)

        def stop() -> None:
            with self._lock:
                self._followers.remove(entry)

        return queue, stop

    def search(
        self,
        *,
        level: str | None = None,
        text: str | None = None,
        trace_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Newest first."""
        with self._lock:
            folder = self._folder
        if folder is None:
            return []
        needle = text.lower() if text else None
        found: list[dict[str, Any]] = []
        for file in sorted(folder.glob("nexusai-*.jsonl"), reverse=True):
            for raw in reversed(file.read_text(encoding="utf8").splitlines()):
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue
                if level and line.get("level") != level:
                    continue
                if trace_id and line.get("trace_id") != trace_id:
                    continue
                if needle and needle not in raw.lower():
                    continue
                found.append(line)
                if len(found) >= limit:
                    return found
        return found


sink = LogSink()


def _clean_processor(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> dict[str, Any]:
    return clean_fields(event_dict, sink.debug)


def _sink_processor(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    sink.write(dict(event_dict))
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            _clean_processor,
            _sink_processor,
            structlog.processors.JSONRenderer(default=str),
        ],
    )


log = structlog.get_logger()
