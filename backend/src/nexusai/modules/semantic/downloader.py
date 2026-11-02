"""Fetches a model once: resumes after a dropped connection, and checks every byte before use."""

import hashlib
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import structlog

from nexusai.kernel.files import replace_file
from nexusai.modules.semantic.catalog import CatalogModel, ModelFile, folder, url

log = structlog.get_logger()

CHUNK = 1024 * 256
ATTEMPTS = 4
CONNECT_SECONDS = 20.0
READ_SECONDS = 60.0
SPACE_MARGIN = 1.2


class DownloadFailed(Exception):
    """Holds what to tell the person."""


class Cancelled(Exception):
    pass


def _partial(target: Path) -> Path:
    return target.with_name(target.name + ".partial")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def is_complete(home: Path, model: CatalogModel) -> bool:
    """Sizes only, so this is quick enough to ask often. Hashes are checked when it arrives."""
    base = folder(home, model)
    return all(
        (base / item.name).is_file() and (base / item.name).stat().st_size == item.size
        for item in model.files
    )


def bytes_present(home: Path, model: CatalogModel) -> int:
    base = folder(home, model)
    total = 0
    for item in model.files:
        for path in (base / item.name, _partial(base / item.name)):
            if path.is_file():
                total += path.stat().st_size
                break
    return total


def _plain(error: Exception) -> str:
    if isinstance(error, httpx.ConnectError | httpx.ConnectTimeout | httpx.ProxyError):
        return (
            "Couldn't reach the download server. If your network blocks it, use a mirror"
            " or files you already have."
        )
    if isinstance(error, httpx.HTTPStatusError):
        return f"The download server answered with an error ({error.response.status_code})."
    if isinstance(error, httpx.TimeoutException):
        return "The download stalled. It will carry on from where it stopped if you try again."
    return "The download stopped. It will carry on from where it stopped if you try again."


def _fetch(
    client: httpx.Client,
    address: str,
    item: ModelFile,
    target: Path,
    stop: threading.Event,
    progress: Callable[[], None],
) -> None:
    partial = _partial(target)
    start = partial.stat().st_size if partial.exists() else 0
    if start < item.size:
        headers = {"Range": f"bytes={start}-"} if start else {}
        with client.stream("GET", address, headers=headers) as response:
            response.raise_for_status()
            # A server that ignores the range sends it all again from the start.
            resumed = response.status_code == httpx.codes.PARTIAL_CONTENT
            with partial.open("ab" if resumed else "wb") as file:
                for block in response.iter_bytes(CHUNK):
                    if stop.is_set():
                        raise Cancelled
                    file.write(block)
                    progress()
    if partial.stat().st_size != item.size or _hash(partial) != item.sha256:
        partial.unlink(missing_ok=True)
        raise DownloadFailed(
            "The downloaded file didn't match what was expected, so it wasn't used."
        )
    replace_file(partial, target)


def download(
    home: Path,
    model: CatalogModel,
    source: str,
    stop: threading.Event,
    progress: Callable[[], None],
) -> None:
    base = folder(home, model)
    base.mkdir(parents=True, exist_ok=True)
    needed = (model.size - bytes_present(home, model)) * SPACE_MARGIN
    if shutil.disk_usage(base).free < needed:
        raise DownloadFailed("There isn't enough free space on this drive for the model.")
    timeout = httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS)
    # Follows the system's proxy settings, which corporate networks rely on.
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=True) as client:
        for item in model.files:
            target = base / item.name
            if target.is_file() and target.stat().st_size == item.size:
                continue
            last: Exception | None = None
            for _ in range(ATTEMPTS):
                try:
                    _fetch(client, url(model, item, source), item, target, stop, progress)
                    last = None
                    break
                except httpx.HTTPStatusError as error:
                    # Waiting won't change a refusal.
                    raise DownloadFailed(_plain(error)) from error
                except httpx.HTTPError as error:
                    last = error
                    if stop.wait(1):
                        raise Cancelled from error
            if last is not None:
                raise DownloadFailed(_plain(last)) from last
    log.info("model_downloaded", model=model.id)


def import_files(home: Path, model: CatalogModel, source: Path) -> None:
    """Checks the same hashes as a download, so a copy can't be anything other than the model."""
    base = folder(home, model)
    base.mkdir(parents=True, exist_ok=True)
    for item in model.files:
        found = next(
            (
                candidate
                for candidate in (
                    source / item.name,
                    source / Path(item.path).name,
                    source / item.path,
                )
                if candidate.is_file()
            ),
            None,
        )
        if found is None:
            raise DownloadFailed(f"{item.name} isn't in that folder.")
        if found.stat().st_size != item.size or _hash(found) != item.sha256:
            raise DownloadFailed(f"{found.name} isn't the expected file.")
        partial = _partial(base / item.name)
        shutil.copyfile(found, partial)
        replace_file(partial, base / item.name)


def remove(home: Path, model: CatalogModel) -> None:
    shutil.rmtree(folder(home, model), ignore_errors=True)
