"""Sorts each part before anything expensive runs, so logos never reach search or the agent."""

import re

from nexusai.kernel.config import MailConfig
from nexusai.modules.mail.parse import Part

RISKY_EXTENSIONS = {
    "exe", "msi", "bat", "cmd", "com", "scr", "ps1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "cpl", "jar", "reg", "lnk", "dll", "docm", "xlsm", "pptm", "dotm", "xlam", "iso", "img",
}  # fmt: skip
CALENDAR_TYPES = {"text/calendar", "application/ics"}
NOT_FILES = {"text/x-amp-html", "text/html", "text/plain"}
# What the parser calls a part that came with no name.
NAMELESS = {"", "attachment"}
# What mail programs and company footers call their pictures. A real photo is rarely so named,
# and one this large is more likely to be something the person meant to send.
FOOTER_NAME = re.compile(
    r"^(image\d*|img\d*|outlook-[\w-]*|logo[\w-]*|banner[\w-]*|signature[\w-]*|footer[\w-]*)\.\w+$",
    re.I,
)
FOOTER_NAME_MAX_BYTES = 200_000


def classify(part: Part, times_seen: int, config: MailConfig, html: str | None = None) -> str:
    extension = part.filename.rsplit(".", 1)[-1].lower() if "." in part.filename else ""
    if extension in RISKY_EXTENSIONS:
        return "risky"
    if part.content_type in CALENDAR_TYPES or extension == "ics":
        return "calendar"
    # Other versions of the mail's own body, and empty containers. Nobody sent these as files.
    if part.filename in NAMELESS and part.content_type in NOT_FILES:
        return "signature"
    if part.content_type.startswith("multipart/"):
        return "signature"
    if not part.content_type.startswith("image/"):
        return "attachment"
    # However it's labelled: logos often arrive marked as attachments.
    if (
        times_seen >= config.signature_repeat_count
        or part.size < config.signature_max_bytes
        or (FOOTER_NAME.match(part.filename) and part.size < FOOTER_NAME_MAX_BYTES)
    ):
        return "signature"
    used_in_body = bool(part.content_id and html and f"cid:{part.content_id}" in html)
    if used_in_body or (part.disposition != "attachment" and part.content_id):
        return "inline"
    return "inline" if part.disposition == "inline" else "attachment"
