"""Finds, checks and creates the NexusAI Home, and keeps file access inside its rules."""

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import psutil

from nexusai.contracts.home import FolderListing, HomeCheck

FORMAT_VERSION = 1
SUBFOLDERS = ("system", "prompts", "memory", "documents", "artifacts", "scratch")
NETWORK_FILESYSTEMS = {"nfs", "nfs4", "smbfs", "smb", "cifs", "afpfs", "webdav", "fuse.sshfs"}
CLOUD_MARKERS = (
    "Mobile Documents",
    "CloudStorage",
    "OneDrive",
    "Dropbox",
    "Google Drive",
    "iCloud",
)
# Folders iCloud and OneDrive often sync without the path saying so.
OFTEN_SYNCED = ("Desktop", "Documents")
# The agent's file tools reach only these. system/ goes through app tools alone.
AGENT_WRITABLE = ("scratch", "memory", "documents", "artifacts")
AGENT_READABLE = (*AGENT_WRITABLE, "prompts")


class HomeError(Exception):
    """The message is shown to the user."""


class PathNotAllowed(Exception):
    pass


def app_data_dir() -> Path:
    if override := os.environ.get("NEXUSAI_APP_DATA"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "NexusAI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NexusAI"
    return Path.home() / ".config" / "nexusai"


def default_home() -> Path:
    return Path.home() / "NexusAI"


def read_pointer(data_dir: Path) -> Path | None:
    try:
        return Path(json.loads((data_dir / "home-pointer.json").read_text())["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_pointer(data_dir: Path, home: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    temporary = data_dir / "home-pointer.json.tmp"
    temporary.write_text(json.dumps({"path": str(home)}))
    temporary.replace(data_dir / "home-pointer.json")


def remove_pointer(data_dir: Path) -> None:
    (data_dir / "home-pointer.json").unlink(missing_ok=True)


def wipe(home: Path, *, keep_models: bool) -> None:
    """Only what NexusAI made. Anything else someone keeps in this folder stays where it is.

    Links are removed rather than followed, so nothing outside Home can be touched.
    """
    for name in SUBFOLDERS:
        folder = home / name
        if folder.is_symlink():
            folder.unlink()
        elif folder.is_dir():
            if name == "system" and keep_models:
                _wipe_except(folder, "models")
            else:
                shutil.rmtree(folder)
    (home / "home.json").unlink(missing_ok=True)


def _wipe_except(folder: Path, kept: str) -> None:
    for path in folder.iterdir():
        if path.name == kept and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def is_home(path: Path) -> bool:
    try:
        return int(json.loads((path / "home.json").read_text())["format_version"]) >= 1
    except (OSError, ValueError, KeyError, TypeError):
        return False


def too_new(path: Path) -> bool:
    try:
        return int(json.loads((path / "home.json").read_text())["format_version"]) > FORMAT_VERSION
    except (OSError, ValueError, KeyError, TypeError):
        return False


def normalize(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _is_network_path(path: Path) -> bool:
    if str(path).startswith("\\\\"):
        return True
    best, kind = "", ""
    for partition in psutil.disk_partitions(all=True):
        mount = partition.mountpoint
        if str(path).startswith(mount) and len(mount) > len(best):
            best, kind = mount, partition.fstype.lower()
    return kind in NETWORK_FILESYSTEMS


def _can_write(folder: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def check_folder(raw: str, min_free_bytes: int) -> HomeCheck:
    path = normalize(raw)
    problems: list[str] = []
    warnings: list[str] = []
    existing = _nearest_existing(path)
    free: int | None = None
    if not existing.is_dir():
        problems.append("That path is a file, not a folder. Choose a folder.")
    elif _is_network_path(path):
        problems.append("That's a network drive. Choose a folder on this computer.")
    elif not _can_write(existing):
        problems.append("NexusAI can't write to that folder. Choose one you have access to.")
    if existing.is_dir():
        free = shutil.disk_usage(existing).free
        if free < min_free_bytes:
            gigabytes = min_free_bytes / 1024**3
            warnings.append(
                f"This drive has less than {gigabytes:.0f} GB free, and mail takes space."
            )
    if any(marker in path.parts or marker in str(path) for marker in CLOUD_MARKERS) or (
        path.is_relative_to(Path.home())
        and path != Path.home()
        and path.relative_to(Path.home()).parts[0] in OFTEN_SYNCED
    ):
        warnings.append(
            "This folder may sync to the cloud, which copies your mail off this computer"
            " and can damage the database."
        )
    home = is_home(path)
    if home and too_new(path):
        problems.append("That Home was made by a newer NexusAI. Update the app to open it.")
    if not home and path.is_dir() and any(path.iterdir()):
        warnings.append(
            "This folder already has files in it. NexusAI adds its folders beside them."
        )
    return HomeCheck(
        path=str(path),
        ok=not problems,
        problems=problems,
        warnings=warnings,
        free_bytes=free,
        is_existing_home=home,
    )


def create_home(path: Path) -> None:
    """Creates the layout, and leaves anything already there alone."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        for folder in SUBFOLDERS:
            (path / folder).mkdir(exist_ok=True)
        marker = path / "home.json"
        if not marker.exists():
            marker.write_text(
                json.dumps({"format_version": FORMAT_VERSION, "id": uuid.uuid4().hex}, indent=2)
            )
    except OSError as error:
        raise HomeError("Couldn't create the folder there. Choose another one.") from error


def browse(raw: str | None, extension: str | None = None) -> FolderListing:
    path = normalize(raw) if raw else Path.home()
    if not path.is_dir():
        path = _nearest_existing(path)
    try:
        entries = [e for e in os.scandir(path) if not e.name.startswith(".")]
        folders = sorted((e.name for e in entries if e.is_dir()), key=str.lower)
        wanted = f".{extension}" if extension else None
        files = sorted(
            (e.name for e in entries if wanted and e.is_file() and e.name.lower().endswith(wanted)),
            key=str.lower,
        )
    except OSError as error:
        raise HomeError("Couldn't open that folder.") from error
    parent = None if path.parent == path else str(path.parent)
    return FolderListing(path=str(path), parent=parent, folders=folders, files=files)


def agent_path(home: Path, requested: str, *, write: bool) -> Path:
    """The real path an agent file tool may use, or PathNotAllowed.

    The path is fully resolved first, so `..` and symlinks can't lead out of the allowed folders.
    """
    root = home.resolve()
    candidate = Path(requested)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    allowed = AGENT_WRITABLE if write else AGENT_READABLE
    if any(target.is_relative_to(root / folder) for folder in allowed):
        return target
    action = "write to" if write else "read"
    raise PathNotAllowed(f"The agent isn't allowed to {action} {requested}.")


def scratch_folder(home: Path, task_id: str) -> Path:
    if not task_id.replace("-", "").isalnum():
        raise PathNotAllowed("That isn't a valid task ID.")
    folder = home / "scratch" / task_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder
