"""Copies a PST into Home in pieces, so a dropped connection can pick up where it stopped."""

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from nexusai.contracts.mail import PstUploadStarted, PstUploadStatus, StartPstUpload
from nexusai.kernel.module import CommandError, Context

ALLOWED = {".pst", ".ost"}
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
# One piece. The browser sends many of these, so the file's size has no limit of its own.
MOST_BYTES = 16 * 1024 * 1024
NOTICE_SECONDS = 1.0
# With nothing arriving for this long, the page has gone. Picking the file again carries on.
GONE_SECONDS = 60.0


@dataclass
class Sending:
    name: str
    size: int
    received: int
    last: float
    last_notice: float = 0.0


# What's on its way up right now. Only for showing, so it's fine for a restart to forget it.
sending: dict[str, Sending] = {}


def _note(ctx: Context, identifier: str, name: str, size: int, received: int) -> None:
    now = time.monotonic()
    current = sending.get(identifier)
    if current is None:
        current = Sending(name, size, received, now)
        sending[identifier] = current
    current.received, current.last = received, now
    if received >= size:
        sending.pop(identifier, None)
    elif now - current.last_notice < NOTICE_SECONDS:
        return
    current.last_notice = now
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "pst.uploadProgress", {"received": received}, source="mail", trace_id=ctx.trace_id
        )


def in_progress() -> list[tuple[str, Sending]]:
    now = time.monotonic()
    for identifier in [k for k, v in sending.items() if now - v.last > GONE_SECONDS]:
        sending.pop(identifier, None)
    return list(sending.items())


def _folder(ctx: Context) -> Path:
    folder = ctx.config.home / "system" / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _part(ctx: Context, identifier: str) -> Path:
    if not UPLOAD_ID.match(identifier):
        raise CommandError("pst.upload_unknown", "That upload no longer exists.", 404)
    return _folder(ctx) / f"{identifier}.part"


def _meta(ctx: Context, identifier: str) -> dict[str, object]:
    path = _part(ctx, identifier).with_suffix(".json")
    if not path.exists():
        raise CommandError("pst.upload_unknown", "That upload no longer exists.", 404)
    return dict(json.loads(path.read_text(encoding="utf-8")))


def start(ctx: Context, command: StartPstUpload) -> PstUploadStarted:
    """The same file picked again continues, so nothing has to be sent twice."""
    name = Path(command.name).name
    if Path(name).suffix.lower() not in ALLOWED:
        raise CommandError("pst.not_a_pst", "Choose a .pst file.", 422)
    seed = f"{name}|{command.size}|{command.modified}"
    identifier = hashlib.sha256(seed.encode()).hexdigest()[:32]
    part = _part(ctx, identifier)
    have = part.stat().st_size if part.exists() else 0
    needed = command.size - have + ctx.config.min_free_bytes
    if shutil.disk_usage(_folder(ctx)).free < needed:
        raise CommandError(
            "pst.no_room",
            "There isn't enough free space for this file. Try its location instead.",
            422,
        )
    part.with_suffix(".json").write_text(
        json.dumps({"name": name, "size": command.size}), encoding="utf-8"
    )
    part.touch()
    return PstUploadStarted(id=identifier, received=have)


def write(ctx: Context, identifier: str, offset: int, data: bytes) -> PstUploadStatus:
    """Only the next piece is accepted. If this isn't it, the reply says where it's up to."""
    meta = _meta(ctx, identifier)
    part = _part(ctx, identifier)
    have = part.stat().st_size
    size = int(str(meta["size"]))
    name = str(meta["name"])
    if offset != have:
        return PstUploadStatus(received=have, size=size)
    if have + len(data) > size:
        raise CommandError("pst.upload_too_long", "That's more than the file's size.", 422)
    with part.open("ab") as file:
        file.write(data)
    have += len(data)
    _note(ctx, identifier, name, size, have)
    if have < size:
        return PstUploadStatus(received=have, size=size)
    return PstUploadStatus(
        received=have, size=size, path=str(_finish(ctx, identifier, str(meta["name"])))
    )


def _finish(ctx: Context, identifier: str, name: str) -> Path:
    folder = _folder(ctx)
    target = folder / name
    number = 2
    while target.exists():
        target = folder / f"{Path(name).stem} {number}{Path(name).suffix}"
        number += 1
    part = _part(ctx, identifier)
    part.replace(target)
    part.with_suffix(".json").unlink(missing_ok=True)
    return target
