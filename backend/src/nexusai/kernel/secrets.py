import json
import os
import threading
from pathlib import Path
from typing import Protocol

import keyring


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringStore:
    """The OS credential store: macOS Keychain, Windows Credential Manager."""

    SERVICE = "NexusAI"

    def get(self, name: str) -> str | None:
        return keyring.get_password(self.SERVICE, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.SERVICE, name, value)

    def delete(self, name: str) -> None:
        if keyring.get_password(self.SERVICE, name) is not None:
            keyring.delete_password(self.SERVICE, name)


class FileStore:
    """For tests only, so they never touch the real credential store."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, str]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Replaced in one step, because the sign-in thread writes while requests read.
        temporary = self.path.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(values))
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        self._write({**self._read(), name: value})

    def delete(self, name: str) -> None:
        self._write({k: v for k, v in self._read().items() if k != name})


def secret_store(test_file: Path | None) -> SecretStore:
    return FileStore(test_file) if test_file else KeyringStore()
