"""Starts the sort lab on this computer: uv run python -m nexusai.sortlab"""

import secrets
import socket
import sys
import webbrowser

import uvicorn

from nexusai.sortlab.lab import create_app, default_lab


def main() -> None:
    lab = default_lab()
    # Mail left by a run that never finished is deleted before anything else happens.
    left = lab.forget_mail()
    if left:
        print(f"Deleted {left} emails left from an earlier run.")
    token = secrets.token_urlsafe(24)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/#{token}"
    print(f"Sort lab: {url}\nResults are saved in {lab.results}\nPress Ctrl+C to stop.")
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
