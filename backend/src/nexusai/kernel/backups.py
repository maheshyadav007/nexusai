"""Copies of a Home's databases, taken only while nothing has them open."""

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

log = structlog.get_logger()

DATABASES = ("nexusai.db", "checkpoints.db")
NAME = re.compile(r"^\d{8}-\d{6}-\d{6}-(daily|upgrade|before-restore)$")
# Room to spare, so a backup can't be what fills the drive.
SPACE_MARGIN = 1.5


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
        if folder.is_dir() and NAME.match(folder.name):
            stamp = datetime.strptime(folder.name[:22], "%Y%m%d-%H%M%S-%f").replace(tzinfo=UTC)
            size = sum(file.stat().st_size for file in folder.iterdir())
            found.append(Backup(folder.name, folder.name[23:], stamp, size))
    return sorted(found, key=lambda backup: backup.time, reverse=True)


def is_due(home: Path, hours: int) -> bool:
    latest = listing(home)
    return not latest or datetime.now(UTC) - latest[0].time >= timedelta(hours=hours)


def create(home: Path, reason: str, keep: int) -> Backup | None:
    system = home / "system"
    size = sum(file.stat().st_size for file in _files(system))
    if not size:
        return None
    if shutil.disk_usage(system).free < size * SPACE_MARGIN:
        log.warning("backup_skipped_no_space", needed=size)
        return None
    name = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{reason}"
    root = _root(home)
    root.mkdir(parents=True, exist_ok=True)
    _copy(system, root / name)
    for old in listing(home)[keep:]:
        shutil.rmtree(root / old.name, ignore_errors=True)
    log.info("backup_created", reason=reason, size=size)
    return next(item for item in listing(home) if item.name == name)


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
