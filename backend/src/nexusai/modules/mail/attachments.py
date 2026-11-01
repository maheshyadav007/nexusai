"""Sorts each part before anything expensive runs, so logos never reach search or the agent."""

from nexusai.kernel.config import MailConfig
from nexusai.modules.mail.parse import Part

RISKY_EXTENSIONS = {
    "exe", "msi", "bat", "cmd", "com", "scr", "ps1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "cpl", "jar", "reg", "lnk", "dll", "docm", "xlsm", "pptm", "dotm", "xlam", "iso", "img",
}  # fmt: skip
CALENDAR_TYPES = {"text/calendar", "application/ics"}


def classify(part: Part, times_seen: int, config: MailConfig) -> str:
    extension = part.filename.rsplit(".", 1)[-1].lower() if "." in part.filename else ""
    if extension in RISKY_EXTENSIONS:
        return "risky"
    if part.content_type in CALENDAR_TYPES or extension == "ics":
        return "calendar"
    if part.disposition == "attachment":
        return "attachment"
    if part.content_id or part.disposition == "inline":
        if not part.content_type.startswith("image/"):
            return "attachment"
        repeated = times_seen >= config.signature_repeat_count
        return "signature" if repeated or part.size < config.signature_max_bytes else "inline"
    return "attachment"
