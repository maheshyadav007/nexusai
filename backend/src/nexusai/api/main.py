import io
import os
import sys
import threading

import uvicorn

from nexusai.api.app import create_app
from nexusai.kernel.config import load_config

KEEP_ALIVE_SECONDS = 75


def _speak_utf8() -> None:
    """A Windows console defaults to an older encoding, and one odd character shouldn't stop us."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run() -> None:
    _speak_utf8()
    config = load_config()
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_config=None,
        # Longer than the frontend keeps an idle connection, so it never reuses one just closed.
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )
    # The Home is closed by now. A worker thread still waiting on a model or mail server would
    # otherwise hold the process open at exit, unseen and still connected, so it's let go.
    lingering = [
        t for t in threading.enumerate() if t is not threading.main_thread() and not t.daemon
    ]
    if lingering:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    run()
