"""Starts the sort lab on this computer. Double-click the built NexusAI-SortLab.exe, or run
uv run python -m nexusai.sortlab. --selftest only checks that it starts and serves its page."""

import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from nexusai.sortlab.lab import create_app, default_lab


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def selftest() -> int:
    """For the build: the packed app starts, serves its page and answers with its key."""
    lab = default_lab()
    token, port = secrets.token_urlsafe(24), _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(lab, token), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        base = f"http://127.0.0.1:{port}"
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
        status = urllib.request.urlopen(
            urllib.request.Request(base + "/api/status", headers={"X-Lab-Token": token}),
            timeout=10,
        ).read()
        ok = "Sort lab" in page and b'"state"' in status
        print("Sort lab self-test passed." if ok else "Sort lab self-test failed.")
        return 0 if ok else 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    lab = default_lab()
    lab.reveal = True
    # Mail left by a run that never finished is deleted before anything else happens.
    left = lab.forget_mail()
    if left:
        print(f"Deleted {left} emails left from an earlier run.")
    token, port = secrets.token_urlsafe(24), _free_port()
    url = f"http://127.0.0.1:{port}/#{token}"
    print(
        "NexusAI Sort lab is running on this computer.\n\n"
        "Your browser should open by itself. If it doesn't, open this link:\n"
        f"  {url}\n\n"
        "Keep this window open while you use the page.\n"
        f"Your results will be saved in: {lab.results}\n"
        "When you're done, close this window. Downloaded mail is deleted when you finish,\n"
        "or the next time you start the lab.\n"
    )
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        uvicorn.run(create_app(lab, token), host="127.0.0.1", port=port, log_level="warning")
    finally:
        left = lab.forget_mail()
        if left:
            print(f"Deleted {left} downloaded emails.")


if __name__ == "__main__":
    main()
