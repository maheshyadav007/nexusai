"""Turns one raw email into one normal shape, whatever client wrote it."""

import base64
import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

SUBJECT_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|aw|sv|vs|antw|tr|rv|ref|رد|答复|回复|转发)\s*(\[\d+\])?\s*[:：]\s*)+", re.I
)
QUOTE_STARTS = (
    re.compile(r"^On .{5,200}wrote:\s*$", re.I),
    re.compile(r"^-{2,}\s*(Original|Forwarded) Message\s*-{2,}\s*$", re.I),
    re.compile(r"^_{10,}\s*$"),
    re.compile(r"^(From|보낸 사람|보낸사람|Von|De)\s*:\s.+", re.I),
    re.compile(r"^Am .{5,200}schrieb .{1,100}:\s*$", re.I),
    re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}.{0,60}(wrote|작성):\s*$", re.I),
)
SIGNATURE_STARTS = (
    re.compile(r"^--\s*$"),
    re.compile(r"^__\s*$"),
    re.compile(r"^Sent from my .{1,40}$", re.I),
    re.compile(r"^(Thanks|Regards|Best|Best regards|Kind regards|Cheers|Sincerely),?\s*$", re.I),
)
DISCLAIMER = re.compile(
    r"(this (e-?mail|message).{0,80}(confidential|privileged|intended)|"
    r"disclaimer:|if you (have )?received this .{0,40}(in )?error|이 메일은.{0,40}기밀)",
    re.I,
)
SNIPPET_LENGTH = 200
BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"}
SKIP_TAGS = {"style", "script", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Broken HTML shouldn't lose the message: fall back to dropping tags.
        return html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = "".join(parser.parts).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def own_text(text: str) -> str:
    """Only what this message itself added, with quoted earlier mail removed."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in QUOTE_STARTS):
            break
        if stripped.startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def clean_text(text: str) -> str:
    """What the agent reads: own text without the signature and legal footer."""
    kept: list[str] = []
    for line in own_text(text).splitlines():
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in SIGNATURE_STARTS):
            break
        if DISCLAIMER.search(stripped):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def normalize_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", SUBJECT_PREFIX.sub("", subject or "")).strip().lower()


@dataclass
class Part:
    index: int
    filename: str
    content_type: str
    size: int
    content_id: str | None
    disposition: str | None
    sha256: str


@dataclass
class ParsedMessage:
    message_id: str
    in_reply_to: str | None
    references: list[str]
    thread_index_root: str | None
    subject: str
    from_name: str
    from_addr: str
    to: list[str]
    cc: list[str]
    date: str
    text: str
    html: str | None
    own: str
    clean: str
    snippet: str
    encrypted: str | None
    signed: bool
    headers: dict[str, str]
    parts: list[Part] = field(default_factory=list)


def _ids(value: str | None) -> list[str]:
    return re.findall(r"<[^<>\s]+>", value or "")


def _addresses(message: EmailMessage, name: str) -> list[str]:
    values = message.get_all(name) or []
    return [address.lower() for _, address in getaddresses([str(v) for v in values]) if address]


def _decode(part: EmailMessage) -> str:
    try:
        return str(part.get_content())
    except (LookupError, UnicodeError, ValueError, KeyError):
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""


def _date(message: EmailMessage) -> str:
    try:
        value = parsedate_to_datetime(str(message["date"]))
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    except (TypeError, ValueError, IndexError):
        return datetime.now(UTC).isoformat()


def _thread_index_root(value: str | None) -> str | None:
    """Outlook's Thread-Index starts with 22 bytes shared by the whole conversation."""
    if not value:
        return None
    try:
        return base64.b64decode(value.strip() + "==")[:22].hex()
    except ValueError:
        return None


def walk_parts(message: EmailMessage) -> list[EmailMessage]:
    return [part for part in message.walk() if not part.is_multipart()]


def parse_message(raw: bytes) -> ParsedMessage:
    message = message_from_bytes(raw, policy=policy.default)
    assert isinstance(message, EmailMessage)
    text_parts: list[str] = []
    html_parts: list[str] = []
    parts: list[Part] = []
    encrypted: str | None = None
    signed = False

    content_type = message.get_content_type()
    if content_type == "multipart/encrypted":
        encrypted = "pgp"
    if content_type == "application/pkcs7-mime" or content_type == "application/x-pkcs7-mime":
        smime = str(message.get_param("smime-type") or "").lower()
        if smime == "signed-data":
            signed = True
        else:
            encrypted = "smime"
    if content_type == "multipart/signed":
        signed = True

    for index, part in enumerate(walk_parts(message)):
        kind = part.get_content_type()
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if kind in {"application/pkcs7-signature", "application/x-pkcs7-signature"}:
            signed = True
            continue
        if kind == "application/pgp-signature":
            signed = True
            continue
        if kind in {
            "application/pkcs7-mime",
            "application/x-pkcs7-mime",
            "application/pgp-encrypted",
        }:
            continue
        if kind == "text/plain" and disposition != "attachment" and not filename:
            text_parts.append(_decode(part))
            continue
        if kind == "text/html" and disposition != "attachment" and not filename:
            html_parts.append(_decode(part))
            continue
        payload = part.get_payload(decode=True)
        body = payload if isinstance(payload, bytes) else b""
        content_id = str(part["content-id"]).strip("<> ") if part["content-id"] else None
        parts.append(
            Part(
                index=index,
                filename=filename or (content_id or "attachment"),
                content_type=kind,
                size=len(body),
                content_id=content_id,
                disposition=disposition,
                sha256=hashlib.sha256(body).hexdigest(),
            )
        )

    html = "\n".join(html_parts) or None
    text = "\n".join(text_parts).strip()
    if not text and html:
        text = html_to_text(html)
    own = own_text(text)
    clean = clean_text(text)
    names = getaddresses([str(message["from"] or "")])
    from_name, from_addr = names[0] if names else ("", "")
    raw_id = _ids(str(message["message-id"] or ""))
    identifier = (
        raw_id[0] if raw_id else f"<generated-{hashlib.sha256(raw).hexdigest()[:32]}@nexusai>"
    )
    in_reply_to = _ids(str(message["in-reply-to"] or ""))
    snippet_source = own or text
    return ParsedMessage(
        message_id=identifier,
        in_reply_to=in_reply_to[0] if in_reply_to else None,
        references=_ids(str(message["references"] or "")),
        thread_index_root=_thread_index_root(str(message["thread-index"] or "") or None),
        subject=str(message["subject"] or "").strip(),
        from_name=from_name,
        from_addr=from_addr.lower(),
        to=_addresses(message, "to"),
        cc=_addresses(message, "cc"),
        date=_date(message),
        text=text,
        html=html,
        own=own,
        clean=clean,
        snippet=re.sub(r"\s+", " ", snippet_source)[:SNIPPET_LENGTH],
        encrypted=encrypted,
        signed=signed,
        headers={key.lower(): str(value) for key, value in message.items()},
        parts=parts,
    )


def part_bytes(raw: bytes, index: int) -> tuple[bytes, EmailMessage] | None:
    message = message_from_bytes(raw, policy=policy.default)
    assert isinstance(message, EmailMessage)
    parts = walk_parts(message)
    if not 0 <= index < len(parts):
        return None
    payload = parts[index].get_payload(decode=True)
    return (payload if isinstance(payload, bytes) else b""), parts[index]
