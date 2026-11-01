"""Reads one file's text in its own process, so a hostile or broken file can't hang the app."""

import json
import sys
from dataclasses import asdict

from nexusai.modules.mail.extract import extract_detail

MEMORY_LIMIT_BYTES = 2 * 1024**3


def _limit_memory() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ImportError, ValueError, OSError):
        # Not every system allows this, and the time limit still applies.
        pass


def main() -> None:
    _limit_memory()
    filename = sys.stdin.buffer.readline().decode("utf-8").strip()
    data = sys.stdin.buffer.read()
    sys.stdout.write(json.dumps(asdict(extract_detail(filename, data))))


if __name__ == "__main__":
    main()
