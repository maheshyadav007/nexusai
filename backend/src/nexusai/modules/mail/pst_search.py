"""Looks for PST files, only when asked. It reads names and sizes, and never opens a file."""

import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
import structlog

from nexusai.contracts.mail import FoundPst, PstSearchStatus
from nexusai.kernel.home import NETWORK_FILESYSTEMS
from nexusai.kernel.module import Context

log = structlog.get_logger()
NOTICE_SECONDS = 1.0
EXTENSION = ".pst"
# Nobody keeps mail archives here, and they hold most of a drive's files.
SKIPPED_FOLDERS = {
    "$recycle.bin",
    "appdata\\local\\temp",
    "node_modules",
    "program files",
    "program files (x86)",
    "programdata",
    "system volume information",
    "windows",
    ".git",
    ".venv",
    "__pycache__",
    "library",
}
# Windows keeps AppData hidden, but Outlook puts its files there, so it's searched by name below.
OUTLOOK_FOLDERS = ("Documents/Outlook Files", "AppData/Local/Microsoft/Outlook")
USUAL_FOLDERS = ("Documents", "Desktop", "Downloads")


def usual_places() -> list[Path]:
    home = Path.home()
    return [home / folder for folder in (*OUTLOOK_FOLDERS, *USUAL_FOLDERS)]


def whole_computer() -> list[Path]:
    """Every local drive on Windows. Elsewhere the person's own folder, where their mail lives."""
    if sys.platform != "win32":
        return [Path.home()]
    return [
        Path(part.mountpoint)
        for part in psutil.disk_partitions(all=False)
        if part.fstype.lower() not in NETWORK_FILESYSTEMS and "cdrom" not in part.opts
    ]


class PstSearch:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = PstSearchStatus(state="idle")
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_notice = 0.0

    def start(self, ctx: Context, everywhere: bool) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stopping.clear()
            self.status = PstSearchStatus(state="running", everywhere=everywhere)
            roots = whole_computer() if everywhere else usual_places()
            self.thread = threading.Thread(
                target=self._run, args=(ctx, roots), daemon=True, name="pst-search"
            )
            self.thread.start()
        self._announce(ctx, force=True)

    def stop(self) -> None:
        self.stopping.set()
        thread = self.thread
        if thread:
            thread.join(timeout=10)

    def _announce(self, ctx: Context, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_notice < NOTICE_SECONDS:
            return
        self.last_notice = now
        with ctx.bus.unit_of_work() as work:
            work.emit("pst.searchChanged", {}, source="mail", trace_id=ctx.trace_id)

    def _run(self, ctx: Context, roots: list[Path]) -> None:
        seen: set[str] = set()
        try:
            for root in roots:
                self._walk(ctx, root, seen)
                if self.stopping.is_set():
                    break
        except Exception:
            log.exception("pst_search_failed")
        self.status.state = "stopped" if self.stopping.is_set() else "done"
        self.status.place = None
        self._announce(ctx, force=True)

    def _walk(self, ctx: Context, root: Path, seen: set[str]) -> None:
        # Doesn't follow links, so it can't loop or wander onto a network drive through one.
        for folder, names, files in os.walk(root, followlinks=False):
            if self.stopping.is_set():
                return
            names[:] = [name for name in names if name.lower() not in SKIPPED_FOLDERS]
            self.status.place = folder
            self.status.scanned += 1
            for name in files:
                if name.lower().endswith(EXTENSION):
                    self._found(Path(folder) / name, seen)
            self._announce(ctx)

    def _found(self, path: Path, seen: set[str]) -> None:
        text = str(path)
        if text in seen:
            return
        seen.add(text)
        try:
            info = path.stat()
        except OSError:
            return
        when = datetime.fromtimestamp(info.st_mtime, UTC).isoformat()
        self.status.found.append(
            FoundPst(path=text, name=path.name, size=info.st_size, modified=when)
        )


search = PstSearch()
