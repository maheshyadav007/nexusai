"""The invented corporate inbox as a mail server you connect the test instance to by hand.

    cd backend && uv run python evals/corp_inbox.py

Thirty of the emails in corp_mailbox.json are already there, dated over the past week, for setup
and onboarding to read. The other twenty wait, and arrive one at a time once you ask:

    curl -X POST http://127.0.0.1:8767/drip          one every 30 seconds
    curl -X POST "http://127.0.0.1:8767/drip?every=10"

In the app, add a mail account with these settings, encryption off for both:
    IMAP 127.0.0.1 port 8143, SMTP 127.0.0.1 port 8025
    user arjun.rao@corp.example, password test-password

Nothing leaves the machine: mail "sent" from the app is only kept in memory here.
"""

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

import fake_mail  # noqa: E402

DATA = Path(__file__).with_name("corp_mailbox.json")
ME = "arjun.rao@corp.example"
CONTROL_PORT, IMAP_PORT, SMTP_PORT = 8767, 8143, 8025
# What arrives while you watch: the mail that should make something happen.
LIVE = (
    "customer-escalation-rca",
    "diwali-celebration",
    "release-blocker-today",
    "phishing-lookalike",
    "manager-steering-eod",
    "plm-build-failed",
    "named-in-team-mail",
    "cafeteria-menu",
    "hr-digest-hidden-deadline",
    "new-skip-level",
    "ceo-gift-card-scam",
    "security-mfa-mandatory",
    "manager-leave-cover",
    "swarm-review-requested",
    "ran2-tdoc-deadline",
    "cc-but-named",
    "customer-rename",
    "interview-panel-tomorrow",
    "new-teammate-buddy",
    "it-password-expiry",
)


def message(case: dict[str, Any], when: datetime | None = None) -> bytes:
    return fake_mail.make_mail(
        subject=case["subject"],
        sender=case["from"],
        to=case["to"],
        cc=case.get("cc"),
        body=case["body"],
        date=format_datetime(when) if when else None,
    )


def main() -> None:
    # The fake server signs in whoever it was told is the user.
    fake_mail.USER = ME
    cases = json.loads(DATA.read_text(encoding="utf-8"))["cases"]
    past = [case for case in cases if case["id"] not in LIVE]
    live = [case for case in cases if case["id"] in LIVE]
    live.sort(key=lambda case: LIVE.index(case["id"]))
    fake = fake_mail.start_fake_mail(IMAP_PORT, SMTP_PORT)
    now = datetime.now().astimezone()
    for index, case in enumerate(past):
        fake.state.deliver(message(case, now - timedelta(days=7, hours=-5 * index)))
    print(f"{len(past)} emails in the inbox, {len(live)} waiting.", flush=True)
    print(__doc__, flush=True)
    started = threading.Event()

    def drip(every: float) -> None:
        for number, case in enumerate(live, 1):
            fake.state.deliver(message(case))
            stamp = f"{datetime.now():%H:%M:%S}"
            print(f"{stamp} arrived {number}/{len(live)}: {case['subject']}", flush=True)
            time.sleep(every)
        print("All delivered.", flush=True)

    class Control(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            url = urlparse(self.path)
            if url.path != "/drip" or started.is_set():
                self.send_response(409 if started.is_set() else 404)
                self.end_headers()
                return
            started.set()
            every = float(parse_qs(url.query).get("every", ["30"])[0])
            threading.Thread(target=drip, args=(every,), daemon=True).start()
            self.send_response(200)
            self.end_headers()

        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            sent = [{"to": s["to"], "raw": s["raw"].decode("utf8", "replace")} for s in fake.sent]
            self.wfile.write(json.dumps(sent).encode())

        def log_message(self, *_: Any) -> None:
            pass

    HTTPServer(("127.0.0.1", CONTROL_PORT), Control).serve_forever()


if __name__ == "__main__":
    main()
