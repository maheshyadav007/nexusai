"""Reads a PST in its own process, so a huge archive can't slow the app.

Run as a command: writes one JSON line per message to stdout, starting after the given position.
"""

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from email.message import EmailMessage
from email.parser import HeaderParser
from typing import Any

KEPT_HEADERS = (
    "From", "To", "Cc", "Subject", "Date", "Message-ID", "In-Reply-To", "References",
    "Thread-Index",
    "List-Id", "List-Unsubscribe", "Precedence", "Auto-Submitted", "X-Auto-Response-Suppress",
)  # fmt: skip
ROOT_NAMES = {"top of personal folders", "root", ""}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def build_raw(message: Any) -> bytes:
    """A normal email from a PST message, so PST mail takes the same path as any other mail.

    Attachments stay in the PST: only their names and sizes are recorded.
    """
    built = EmailMessage(policy=EmailMessage().policy.clone(max_line_length=None))
    headers = HeaderParser().parsestr(_text(message.get_transport_headers()))
    for name in KEPT_HEADERS:
        value = headers.get(name)
        if value:
            try:
                built[name] = str(value).replace("\r", " ").replace("\n", " ")
            except ValueError:
                continue
    if not built["Subject"] and message.get_subject():
        built["Subject"] = _text(message.get_subject())
    if not built["From"] and message.get_sender_name():
        built["From"] = _text(message.get_sender_name())
    if not built["Date"] and message.get_delivery_time():
        moment = message.get_delivery_time().replace(tzinfo=UTC)
        built["Date"] = moment.strftime("%a, %d %b %Y %H:%M:%S +0000")
    plain = _text(message.get_plain_text_body())
    html = _text(message.get_html_body())
    if plain:
        built.set_content(plain, cte="8bit")
        if html:
            built.add_alternative(html, subtype="html", cte="8bit")
    elif html:
        built.set_content(html, subtype="html", cte="8bit")
    else:
        built.set_content("")
    return bytes(built)


def _attachment_name(item: Any) -> str | None:
    """pypff has no name getter for attachments, so it's read from the record entries."""
    for record_set in range(item.get_number_of_record_sets()):
        records = item.get_record_set(record_set)
        for entry in range(records.get_number_of_entries()):
            record = records.get_entry(entry)
            # PR_ATTACH_LONG_FILENAME, PR_ATTACH_FILENAME
            if record.get_entry_type() in (0x3707, 0x3704):
                try:
                    return str(record.get_data_as_string())
                except (OSError, ValueError):
                    continue
    return None


def _attachments(message: Any) -> list[dict[str, Any]]:
    found = []
    for index in range(message.get_number_of_attachments()):
        item = message.get_attachment(index)
        name = _attachment_name(item) or f"attachment-{index + 1}"
        found.append({"index": index, "name": name, "size": item.get_size()})
    return found


def walk(folder: Any, path: str) -> Iterator[tuple[str, int, Any]]:
    for index in range(folder.get_number_of_sub_messages()):
        yield path, index, folder
    for index in range(folder.get_number_of_sub_folders()):
        sub = folder.get_sub_folder(index)
        name = _text(sub.get_name())
        child = name if name.lower() in ROOT_NAMES and not path else f"{path}/{name}".strip("/")
        yield from walk(sub, child)


def count_messages(folder: Any) -> int:
    total = int(folder.get_number_of_sub_messages())
    for index in range(folder.get_number_of_sub_folders()):
        total += count_messages(folder.get_sub_folder(index))
    return total


def run(path: str, start: int) -> None:
    import pypff

    archive = pypff.file()
    archive.open(path)
    root = archive.get_root_folder()
    print(json.dumps({"total": count_messages(root)}), flush=True)
    for seq, (folder_path, index, folder) in enumerate(walk(root, "")):
        # Positions are stable, so resuming only needs to count, not read.
        if seq < start:
            continue
        try:
            message = folder.get_sub_message(index)
            line = {
                "seq": seq,
                "folder": folder_path,
                "index": index,
                "raw": build_raw(message).hex(),
                "attachments": _attachments(message),
            }
        except Exception as error:
            line = {
                "seq": seq,
                "folder": folder_path,
                "index": index,
                "error": type(error).__name__,
            }
        print(json.dumps(line), flush=True)
    print(json.dumps({"finished": datetime.now(UTC).isoformat()}), flush=True)


def read_attachment(path: str, folder_path: str, index: int, attachment: int) -> bytes:
    import pypff

    archive = pypff.file()
    archive.open(path)
    try:
        for current_path, position, folder in walk(archive.get_root_folder(), ""):
            if current_path == folder_path and position == index:
                item = folder.get_sub_message(index).get_attachment(attachment)
                return bytes(item.read_buffer(item.get_size()))
    finally:
        archive.close()
    raise FileNotFoundError(folder_path)


if __name__ == "__main__":
    run(sys.argv[1], int(sys.argv[2]))
