"""Stands in for the PST reader: same output format, with a chosen pace and failure."""

import json
import os
import sys
import time

from fake_mail import make_mail

total = int(os.environ.get("FAKE_PST_TOTAL", "5"))
delay = float(os.environ.get("FAKE_PST_DELAY", "0"))
start = int(sys.argv[2])
if os.environ.get("FAKE_PST_FAIL"):
    print("not a pst", file=sys.stderr)
    sys.exit(3)
print(json.dumps({"total": total}), flush=True)
for seq in range(start, total):
    raw = make_mail(
        subject=f"Archived {seq}",
        message_id=f"<archived-{seq}@x>",
        sender="old@x.com",
        date="Mon, 5 Jan 2015 10:00:00 +0000",
        headers=json.loads(os.environ.get("FAKE_PST_HEADERS", "{}")),
    )
    attachments = [{"index": 0, "name": "old.pdf", "size": 5}] if seq == 0 else []
    print(
        json.dumps(
            {
                "seq": seq,
                "folder": "Inbox/2015",
                "index": seq,
                "raw": raw.hex(),
                "attachments": attachments,
            }
        ),
        flush=True,
    )
    time.sleep(delay)
print(json.dumps({"finished": "now"}), flush=True)
