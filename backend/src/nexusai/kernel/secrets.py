import json
import os
import threading
from pathlib import Path
from typing import Protocol

import keyring
import structlog

from nexusai.kernel.files import replace_file
from nexusai.kernel.home import app_data_dir


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


# Windows Credential Manager holds 2,560 bytes per entry, and it stores text in two bytes a
# character. A sign-in token can be longer, so long values are kept in several entries.
PIECE_CHARS = 1000
PIECES_MARK = "nexusai-pieces:"
SECRETS_FILE = "secrets.json"
_FILE_LOCK = threading.Lock()
log = structlog.get_logger()


class KeyringStore:
    """The OS credential store: macOS Keychain, Windows Credential Manager."""

    SERVICE = "NexusAI"

    def _piece(self, name: str, index: int) -> str:
        return f"{name}#{index}"

    def _pieces_of(self, stored: str | None) -> int:
        if stored and stored.startswith(PIECES_MARK):
            return int(stored[len(PIECES_MARK) :])
        return 0

    def _remove_pieces(self, name: str, count: int, keeping: int = 0) -> None:
        for index in range(keeping, count):
            if keyring.get_password(self.SERVICE, self._piece(name, index)) is not None:
                keyring.delete_password(self.SERVICE, self._piece(name, index))

    def get(self, name: str) -> str | None:
        stored = keyring.get_password(self.SERVICE, name)
        count = self._pieces_of(stored)
        if not count:
            return stored
        pieces = [keyring.get_password(self.SERVICE, self._piece(name, i)) for i in range(count)]
        # Part of it missing means it's gone, and a piece of a token would only fail later.
        return None if None in pieces else "".join(str(piece) for piece in pieces)

    def set(self, name: str, value: str) -> None:
        before = self._pieces_of(keyring.get_password(self.SERVICE, name))
        pieces = [value[i : i + PIECE_CHARS] for i in range(0, len(value), PIECE_CHARS)]
        if len(pieces) <= 1:
            keyring.set_password(self.SERVICE, name, value)
            self._remove_pieces(name, before)
            return
        # The pieces go first, so the mark never points at something not yet there.
        for index, piece in enumerate(pieces):
            keyring.set_password(self.SERVICE, self._piece(name, index), piece)
        keyring.set_password(self.SERVICE, name, f"{PIECES_MARK}{len(pieces)}")
        self._remove_pieces(name, before, keeping=len(pieces))

    def delete(self, name: str) -> None:
        stored = keyring.get_password(self.SERVICE, name)
        if stored is not None:
            keyring.delete_password(self.SERVICE, name)
            self._remove_pieces(name, self._pieces_of(stored))


class FileStore:
    """One JSON file only this user can read. The secrets in it aren't encrypted."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Replaced in one step, because the sign-in thread writes while requests read.
        temporary = self.path.with_suffix(f".{threading.get_ident()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(values, file)
        replace_file(temporary, self.path)

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        with _FILE_LOCK:
            self._write({**self._read(), name: value})

    def delete(self, name: str) -> None:
        with _FILE_LOCK:
            self._write({k: v for k, v in self._read().items() if k != name})


class LocalStore:
    """Secrets go in a local file for now, because a missing or locked keyring stopped people from
    opening a Home at all, as it does on many Linux setups. To go back to the OS credential store
    when things are stable, return KeyringStore from secret_store.

    What's already in the keyring is still read, or Homes made earlier couldn't open.
    """

    def __init__(self, path: Path) -> None:
        self.file = FileStore(path)
        self.keyring = KeyringStore()

    def get(self, name: str) -> str | None:
        found = self.file.get(name)
        if found is not None:
            return found
        try:
            return self.keyring.get(name)
        # Each backend raises its own errors, and none of them should stop the app.
        except Exception:
            return None

    def set(self, name: str, value: str) -> None:
        self.file.set(name, value)

    def delete(self, name: str) -> None:
        self.file.delete(name)
        try:
            self.keyring.delete(name)
        except Exception:
            log.info("keyring_secret_kept")


def secret_store(test_file: Path | None) -> SecretStore:
    return FileStore(test_file) if test_file else LocalStore(app_data_dir() / SECRETS_FILE)
