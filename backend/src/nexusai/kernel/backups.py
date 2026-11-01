"""Copies of a Home's databases.

Before an upgrade they're plain file copies while nothing has them open. The daily one mustn't
hold up launch on a large mailbox, so it copies page by page while the app keeps working.
"""

import re
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from nexusai.kernel.database import connect_raw

log = structlog.get_logger()

DATABASES = ("nexusai.db", "checkpoints.db")
NAME = re.compile(r"^\d{8}-\d{6}-\d{6}-(daily|upgrade|before-restore)$")
# Room to spare, so a backup can't be what fills the drive.
SPACE_MARGIN = 1.5
ONLINE_PAGES = 2000
ONLINE_PAUSE_SECONDS = 0.01
CHECK_EVERY_SECONDS = 3600.0


@dataclass(frozen=True)
class Backup:
    name: str
    reason: str
    time: datetime
    size: int


def _root(home: Path) -> Path:
    return home / "system" / "backups"


def _files(folder: Path) -> list[Path]:
    # The write-ahead log can hold the latest changes after an unclean exit.
    names = [name + suffix for name in DATABASES for suffix in ("", "-wal")]
    return [folder / name for name in names if (folder / name).exists()]


def _copy(source: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".partial")
    temporary.mkdir(parents=True)
    for file in _files(source):
        shutil.copy2(file, temporary / file.name)
    temporary.rename(target)


def listing(home: Path) -> list[Backup]:
    found = []
    root = _root(home)
    if not root.exists():
        return []
    for folder in root.iterdir():
        # A copy that was interrupted ends in .partial, so it's never offered.
        if folder.is_dir() and NAME.match(folder.name):
            stamp = datetime.strptime(folder.name[:22], "%Y%m%d-%H%M%S-%f").replace(tzinfo=UTC)
            size = sum(file.stat().st_size for file in folder.iterdir())
            found.append(Backup(folder.name, folder.name[23:], stamp, size))
    return sorted(found, key=lambda backup: backup.time, reverse=True)


def is_due(home: Path, hours: int) -> bool:
    latest = listing(home)
    return not latest or datetime.now(UTC) - latest[0].time >= timedelta(hours=hours)


def _has_room(system: Path) -> bool:
    size = sum(file.stat().st_size for file in _files(system))
    if not size:
        return False
    if shutil.disk_usage(system).free < size * SPACE_MARGIN:
        log.warning("backup_skipped_no_space", needed=size)
        return False
    return True


def _new_name(reason: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{reason}"


def _finished(home: Path, name: str, keep: int) -> Backup:
    for old in listing(home)[keep:]:
        shutil.rmtree(_root(home) / old.name, ignore_errors=True)
    found = next(item for item in listing(home) if item.name == name)
    log.info("backup_created", reason=found.reason, size=found.size)
    return found


def create(home: Path, reason: str, keep: int) -> Backup | None:
    """Only while nothing has the databases open."""
    system = home / "system"
    if not _has_room(system):
        return None
    name = _new_name(reason)
    _root(home).mkdir(parents=True, exist_ok=True)
    _copy(system, _root(home) / name)
    return _finished(home, name, keep)


def create_online(home: Path, key: str, keep: int, stopping: threading.Event) -> Backup | None:
    """Safe while the app is running. Encrypted with the same key, like the original."""
    system = home / "system"
    if not _has_room(system):
        return None
    name = _new_name("daily")
    target = _root(home) / name
    temporary = target.with_name(target.name + ".partial")
    temporary.mkdir(parents=True)

    def pause_or_stop(_: int, __: int, ___: int) -> None:
        if stopping.is_set():
            raise InterruptedError

    try:
        for database in DATABASES:
            if not (system / database).exists():
                continue
            source = connect_raw(system / database, key)
            copy = connect_raw(temporary / database, key)
            try:
                source.backup(
                    copy, pages=ONLINE_PAGES, progress=pause_or_stop, sleep=ONLINE_PAUSE_SECONDS
                )
            finally:
                copy.close()
                source.close()
    except InterruptedError:
        shutil.rmtree(temporary, ignore_errors=True)
        return None
    for leftover in temporary.glob("*-*"):
        leftover.unlink(missing_ok=True)
    temporary.rename(target)
    return _finished(home, name, keep)


class DailyBackups:
    """Runs apart from the app's work, and only when one is due."""

    def __init__(self, home: Path, key: str, keep: int, hours: int) -> None:
        self.home, self.key, self.keep, self.hours = home, key, keep, hours
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="backups")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                if is_due(self.home, self.hours):
                    create_online(self.home, self.key, self.keep, self.stopping)
            except Exception:
                log.exception("backup_failed")
            self.stopping.wait(CHECK_EVERY_SECONDS)


def restore(home: Path, name: str) -> None:
    """The damaged files are set aside rather than deleted, in case support can use them."""
    if not NAME.match(name) or not (_root(home) / name).is_dir():
        raise FileNotFoundError(name)
    system = home / "system"
    aside = system / f"damaged-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
    aside.mkdir()
    for base in DATABASES:
        for suffix in ("", "-wal", "-shm"):
            file = system / (base + suffix)
            if file.exists():
                file.rename(aside / file.name)
    for file in _files(_root(home) / name):
        shutil.copy2(file, system / file.name)
