import json
import os
import threading
from pathlib import Path
from typing import Protocol

import keyring

from nexusai.kernel.files import replace_file


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


# Windows Credential Manager holds 2,560 bytes per entry, and it stores text in two bytes a
# character. A sign-in token can be longer, so long values are kept in several entries.
PIECE_CHARS = 1000
PIECES_MARK = "nexusai-pieces:"


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
    """For tests only, so they never touch the real credential store."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Replaced in one step, because the sign-in thread writes while requests read.
        temporary = self.path.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(values), encoding="utf-8")
        os.chmod(temporary, 0o600)
        replace_file(temporary, self.path)

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        self._write({**self._read(), name: value})

    def delete(self, name: str) -> None:
        self._write({k: v for k, v in self._read().items() if k != name})


def secret_store(test_file: Path | None) -> SecretStore:
    return FileStore(test_file) if test_file else KeyringStore()
