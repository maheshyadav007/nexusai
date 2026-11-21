"""A made-up company's mail server, for trying NexusAI as a company employee would.

It speaks real POP3 and SMTP, so the app connects to it through the same code and the same
onboarding as a real company server: sign in as admin / admin. Its mailbox is the Korvia mockup
from corp_mail.py (1,000 emails over six months) plus the corp eval cases (MR-Nov, change 88213,
Carrier X, Orion) dated over the last few days, so there's history to learn from and fresh mail
that needs you.

Run by `make test-start COMPANY=1`, which also points the test instance's system mail settings
here. New mail can arrive while it runs:

    curl -X POST localhost:8768 -d '{"subject": "CL 88213 is merged", "sender": "Karthik Nair <karthik.nair@korvia.example>", "body": "Done."}'

Ports come from COMPANY_POP3_PORT, COMPANY_SMTP_PORT and COMPANY_CONTROL_PORT. COMPANY_DELAY_MS
slows each email down, to watch a download take time as it does from Gmail.
"""

import json
import os
import random
import re
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.utils import format_datetime, make_msgid, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import corp_mail  # noqa: E402
from fake_mail import _SmtpHandler, _Threaded, make_mail  # noqa: E402
from fake_pop3 import start_fake_pop3  # noqa: E402

LOGIN = ("admin", "admin")
DOMAIN = corp_mail.COMPANY
OWNER = f"admin@{DOMAIN}"
CASES = Path(__file__).parents[1] / "evals" / "corp_mailbox.json"
# How far back the eval cases are spread, so they read as this week's mail.
RECENT_HOURS = 72


def _as_owner(raw: bytes) -> bytes:
    """The mockup's owner signs in as admin, so their address becomes admin's. The IT team's own
    admin@ address moves aside first, or its notices would look like the person's own mail."""
    text = raw.decode("utf8", "replace")
    text = text.replace(f"admin@{DOMAIN}", f"it-admin@{DOMAIN}")
    text = text.replace(corp_mail.OWNER[1], OWNER)
    return text.encode("utf8")


def _case_mail(case: dict[str, Any], when: datetime) -> bytes:
    """An eval case, moved into Korvia and addressed to admin, so it fits the same mailbox."""

    def local(text: str) -> str:
        text = text.replace("arjun.rao@corp.example", OWNER).replace("corp.example", DOMAIN)
        return re.sub(r"\bArjun\b", corp_mail.OWNER[0].split()[0], text)

    return make_mail(
        subject=local(case["subject"]),
        sender=local(case["from"]),
        to=local(case.get("to") or OWNER),
        body=local(case.get("body") or ""),
        message_id=make_msgid(domain=DOMAIN),
        date=format_datetime(when),
    )


def mailbox() -> list[bytes]:
    """History first, oldest to newest, then this week's mail."""
    with tempfile.TemporaryDirectory() as folder:
        corp_mail.build(Path(folder))
        history = [_as_owner(path.read_bytes()) for path in Path(folder).glob("*.eml")]
    history.sort(key=lambda raw: parsedate_to_datetime(message_from_bytes(raw)["Date"]))
    cases = json.loads(CASES.read_text(encoding="utf8"))["cases"]
    now = datetime.now(UTC)
    picker = random.Random(11)
    times = sorted(now - timedelta(hours=picker.uniform(1, RECENT_HOURS)) for _ in cases)
    return history + [_case_mail(case, when) for case, when in zip(cases, times, strict=True)]


def main() -> None:
    pop3 = start_fake_pop3(int(os.environ.get("COMPANY_POP3_PORT", 8110)), LOGIN)
    # COMPANY_DELAY_MS slows each email down, to see a download take time as Gmail's does.
    pop3.server.delay = int(os.environ.get("COMPANY_DELAY_MS", 0)) / 1000  # type: ignore[attr-defined]
    for raw in mailbox():
        pop3.state.deliver(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    smtp = _Threaded(("127.0.0.1", int(os.environ.get("COMPANY_SMTP_PORT", 8026))), _SmtpHandler)
    smtp.sent = []  # type: ignore[attr-defined]
    smtp.login = LOGIN  # type: ignore[attr-defined]
    threading.Thread(target=smtp.serve_forever, daemon=True).start()

    class Control(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["content-length"] or 0)) or b"{}")
            raw = make_mail(**{"to": OWNER, **body})
            pop3.state.deliver(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_: Any) -> None:
            pass

    control = int(os.environ.get("COMPANY_CONTROL_PORT", 8768))
    print(
        f"Company mail for {OWNER}: POP3 on 127.0.0.1:{pop3.port}, SMTP on {smtp.server_address[1]},"
        f" {len(pop3.state.mails)} emails. Sign in as {LOGIN[0]} / {LOGIN[1]}."
        f" New mail: POST JSON to 127.0.0.1:{control}.",
        flush=True,
    )
    HTTPServer(("127.0.0.1", control), Control).serve_forever()


if __name__ == "__main__":
    main()
