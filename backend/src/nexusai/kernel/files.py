"""File operations that hold up on Windows, where an open file can't be replaced or removed.

Antivirus and search indexing briefly open new files there, so a moment's wait usually clears it.
"""

import os
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path

ATTEMPTS = 8
FIRST_WAIT_SECONDS = 0.05


def _patiently(action: Callable[[], None]) -> None:
    wait = FIRST_WAIT_SECONDS
    for attempt in range(ATTEMPTS):
        try:
            action()
            return
        except PermissionError:
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(wait)
            wait *= 2


def replace_file(source: Path, target: Path) -> None:
    """Puts source where target is in one step."""
    _patiently(lambda: os.replace(source, target))


def remove_tree(folder: Path) -> None:
    """Removes a folder and everything in it, including files marked read-only."""

    def writable_then_again(function: Callable[[str], object], path: str, _: BaseException) -> None:
        os.chmod(path, stat.S_IWRITE)
        function(path)

    _patiently(lambda: shutil.rmtree(folder, onexc=writable_then_again))
