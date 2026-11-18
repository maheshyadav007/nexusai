"""What goes out with a mail: its files, a forward's starting draft, and who to send it to."""

import json
import mimetypes
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from nexusai.contracts.mail import Draft, DraftAttachment, Recipient, RecipientSuggestions
from nexusai.kernel.module import CommandError, Context

# A file added in the composer and never sent is let go after this long.
UPLOADS_KEPT_DAYS = 3
SUGGESTIONS_SHOWN = 6
SENT_READ = 2000
# Being written to by them counts, but much less than writing to them.
WRITTEN_WEIGHT = 10


@dataclass(frozen=True)
class Outgoing:
    name: str
    content_type: str
    data: bytes


def _type_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def save_upload(ctx: Context, name: str, data: bytes) -> DraftAttachment:
    """Kept in the database, encrypted with everything else, until the draft goes or is dropped."""
    name = name.strip().replace("/", "_").replace("\\", "_")[:500] or "attachment"
    if len(data) > ctx.config.mail.most_attached_bytes:
        raise CommandError("draft.attachment_too_large", too_large(ctx), 413)
    identifier = uuid.uuid4().hex
    now = datetime.now(UTC)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_draft_uploads (id, name, content_type, size, data, created)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, name, _type_of(name), len(data), data, now.isoformat()),
        )
        _let_go_of_old(tx, now)
    return DraftAttachment(name=name, size=len(data), upload=identifier)


def _let_go_of_old(tx: Any, now: datetime) -> None:
    before = (now - timedelta(days=UPLOADS_KEPT_DAYS)).isoformat()
    kept = {
        item.get("upload")
        for row in tx.execute("SELECT body FROM mail_drafts").fetchall()
        for item in json.loads(row["body"]).get("attachments", [])
    }
    for row in tx.execute(
        "SELECT id FROM mail_draft_uploads WHERE created < ?", (before,)
    ).fetchall():
        if row["id"] not in kept:
            tx.execute("DELETE FROM mail_draft_uploads WHERE id = ?", (row["id"],))


def forget_uploads(tx: Any, draft: Draft) -> None:
    for item in draft.attachments:
        if item.upload:
            tx.execute("DELETE FROM mail_draft_uploads WHERE id = ?", (item.upload,))


def too_large(ctx: Context) -> str:
    most = ctx.config.mail.most_attached_bytes / 1024 / 1024
    return f"Attachments can add up to {most:.0f} MB on one email. Remove some, or share a link."


def files_of(ctx: Context, draft: Draft) -> list[Outgoing]:
    """Every file the draft carries, read now, or a plain reason it can't go."""
    from nexusai.modules.documents import module as documents

    found: list[Outgoing] = []
    for item in draft.attachments:
        if item.upload:
            rows = ctx.bus.db.fetch_all(
                "SELECT name, content_type, data FROM mail_draft_uploads WHERE id = ?",
                (item.upload,),
            )
            if not rows:
                raise CommandError(
                    "draft.attachment_gone", f"{item.name} is no longer here. Add it again.", 422
                )
            found.append(Outgoing(rows[0]["name"], rows[0]["content_type"], rows[0]["data"]))
        elif item.key:
            try:
                file = documents.document_file(ctx, item.key)
            except ValueError:
                file = None
            if file is None:
                raise CommandError(
                    "draft.attachment_gone",
                    f"{item.name} can't be attached: it's gone, or it's a kind of file NexusAI "
                    "won't pass on.",
                    422,
                )
            found.append(Outgoing(file[0], _type_of(file[0]), file[1]))
    if sum(len(file.data) for file in found) > ctx.config.mail.most_attached_bytes:
        raise CommandError("draft.attachment_too_large", too_large(ctx), 413)
    return found


def forward(ctx: Context, message_id: int) -> Draft:
    """The message quoted under a forward line, with its attachments going along."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM messages WHERE id = ?", (message_id,))
    if not rows:
        raise CommandError("thread.not_found", "That message no longer exists.", 404)
    message = rows[0]
    subject = message["subject"] or ""
    prefixed = subject if subject.lower().startswith(("fwd:", "fw:")) else f"Fwd: {subject}"
    sender = (
        f"{message['from_name']} <{message['from_addr']}>"
        if message["from_name"]
        else message["from_addr"]
    )
    to = ", ".join(_addresses(message["to_json"]))
    head = [
        "---------- Forwarded message ---------",
        f"From: {sender}",
        f"Date: {message['date']}",
        f"Subject: {subject}",
        *([f"To: {to}"] if to else []),
    ]
    parts = ctx.bus.db.fetch_all(
        "SELECT part_index, filename, size FROM message_parts"
        " WHERE message = ? AND kind IN ('attachment', 'calendar') ORDER BY part_index",
        (message_id,),
    )
    return Draft(
        subject=prefixed,
        body="\n\n" + "\n".join(head) + "\n\n" + (message["text"] or "").strip(),
        attachments=[
            DraftAttachment(
                name=part["filename"], size=part["size"], key=f"m:{message_id}:{part['part_index']}"
            )
            for part in parts
        ],
    )


def _addresses(column: str) -> list[str]:
    parsed = json.loads(column or "[]")
    found = (item.get("address", "") if isinstance(item, dict) else str(item) for item in parsed)
    return [address.lower() for address in found if address]


def suggest(ctx: Context, account: str, own: set[str], text: str) -> RecipientSuggestions:
    """People they write to first, then people who write to them, matched on name or address."""
    needle = text.strip().lower()
    if len(needle) < 2 or not own:
        return RecipientSuggestions(people=[])
    marks = ",".join("?" * len(own))
    written: Counter[str] = Counter()
    for row in ctx.bus.db.fetch_all(
        f"SELECT to_json, cc_json FROM messages WHERE account = ? AND LOWER(from_addr) IN ({marks})"  # noqa: S608
        " ORDER BY date DESC LIMIT ?",
        (account, *own, SENT_READ),
    ):
        written.update(_addresses(row["to_json"]) + _addresses(row["cc_json"]))
    like = f"%{needle}%"
    received = {
        row["address"]: (row["name"], row["n"])
        for row in ctx.bus.db.fetch_all(
            "SELECT LOWER(from_addr) AS address, MAX(from_name) AS name, COUNT(*) AS n"
            " FROM messages WHERE account = ? GROUP BY LOWER(from_addr)"
            " HAVING LOWER(from_addr) LIKE ? OR LOWER(MAX(from_name)) LIKE ?",
            (account, like, like),
        )
    }
    names = {
        row["address"]: row["name"]
        for row in ctx.bus.db.fetch_all(
            "SELECT LOWER(from_addr) AS address, MAX(from_name) AS name FROM messages"
            " WHERE account = ? AND from_name != '' GROUP BY LOWER(from_addr)",
            (account,),
        )
        if needle in row["address"] or needle in row["name"].lower()
    }
    score: dict[str, int] = {}
    for address, count in written.items():
        if needle in address or needle in names.get(address, "").lower():
            score[address] = count * WRITTEN_WEIGHT
    for address, (_, count) in received.items():
        score[address] = score.get(address, 0) + count
    ranked = sorted(
        (address for address in score if address not in own and "@" in address),
        key=lambda address: (-score[address], address),
    )[:SUGGESTIONS_SHOWN]
    people = []
    for address in ranked:
        try:
            people.append(
                Recipient(
                    name=(names.get(address) or received.get(address, ("", 0))[0] or "")[:200],
                    address=address,
                )
            )
        except ValueError:
            continue
    return RecipientSuggestions(people=people)


SIGNATURE_LINE = "-- "


def with_signature(ctx: Context, body: str) -> str:
    """Their signature under the text, once. The composer adds it the same way."""
    from nexusai.modules.settings.module import load_profile

    signature = load_profile(ctx).signature.strip()
    if not signature or signature in body:
        return body
    return f"{body.rstrip()}\n\n{SIGNATURE_LINE}\n{signature}"


def attachments_from_keys(ctx: Context, keys: list[str]) -> tuple[list[DraftAttachment], list[str]]:
    """What an agent asked to attach, by the keys it was shown, and the keys that didn't work."""
    from nexusai.modules.documents import module as documents

    found: list[DraftAttachment] = []
    missing: list[str] = []
    for key in dict.fromkeys(item.strip() for item in keys if item.strip()):
        try:
            file = documents.document_file(ctx, key)
        except ValueError:
            file = None
        if file is None:
            missing.append(key)
        else:
            found.append(DraftAttachment(name=file[0], size=len(file[1]), key=key))
    return found, missing
