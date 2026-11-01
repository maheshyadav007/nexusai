"""Fake IMAP and SMTP servers that speak the real protocols, so tests use the real clients."""

import json
import os
import re
import socketserver
import threading
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

USER, PASSWORD = "tester@example.com", "test-password"


def make_mail(
    subject: str = "Hello",
    sender: str = "Priya Nair <priya@example.com>",
    to: str = USER,
    body: str = "Please review the contract.",
    *,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    date: str | None = None,
    headers: dict[str, str] | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    html: str | None = None,
    cc: str | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message["Date"] = date or formatdate(localtime=True)
    message["Message-ID"] = message_id or make_msgid(domain="example.com")
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    for key, value in (headers or {}).items():
        message[key] = value
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for filename, content_type, data in attachments or []:
        main, _, sub = content_type.partition("/")
        message.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    return message.as_bytes()


@dataclass
class Mail:
    uid: int
    raw: bytes
    flags: set[str] = field(default_factory=set)


@dataclass
class Box:
    attrs: str = ""
    validity: int = 100
    next_uid: int = 1
    mails: list[Mail] = field(default_factory=list)


class ImapState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.boxes = {
            "INBOX": Box(),
            "Sent": Box("\\Sent"),
            "Drafts": Box("\\Drafts"),
            "Trash": Box("\\Trash"),
            "Archive": Box("\\Archive"),
        }
        self.idlers: list[Any] = []
        self.logins = 0

    def deliver(self, raw: bytes, box: str = "INBOX", flags: set[str] | None = None) -> int:
        with self.lock:
            target = self.boxes[box]
            uid = target.next_uid
            target.next_uid += 1
            target.mails.append(Mail(uid, raw, flags or set()))
            count = len(target.mails)
            for idler, selected in self.idlers:
                if selected == box:
                    idler.push(f"* {count} EXISTS\r\n")
        return uid

    def remove(self, uid: int, box: str = "INBOX") -> None:
        with self.lock:
            self.boxes[box].mails = [m for m in self.boxes[box].mails if m.uid != uid]
            for idler, selected in self.idlers:
                if selected == box:
                    idler.push("* 1 EXPUNGE\r\n")

    def set_flags(self, uid: int, flags: set[str], box: str = "INBOX") -> None:
        with self.lock:
            for mail in self.boxes[box].mails:
                if mail.uid == uid:
                    mail.flags = flags
            for idler, selected in self.idlers:
                if selected == box:
                    idler.push(f"* {uid} FETCH (FLAGS ())\r\n")


def _uid_set(text: str, biggest: int) -> set[int]:
    result: set[int] = set()
    for piece in text.split(","):
        if ":" in piece:
            low, high = piece.split(":")
            start = biggest if low == "*" else int(low)
            end = biggest if high == "*" else int(high)
            result |= set(range(min(start, end), max(start, end) + 1))
        else:
            result.add(biggest if piece == "*" else int(piece))
    return result


class _ImapHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.selected: str | None = None
        self.write_lock = threading.Lock()

    @property
    def state(self) -> ImapState:
        return self.server.imap_state  # type: ignore[attr-defined]

    def push(self, text: str) -> None:
        with self.write_lock:
            try:
                self.wfile.write(text.encode())
                self.wfile.flush()
            except OSError:
                pass

    def handle(self) -> None:
        self.push("* OK fake IMAP ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf8", "replace").rstrip("\r\n")
            tag, _, rest = text.partition(" ")
            command, _, args = rest.partition(" ")
            done = self.dispatch(tag, command.upper(), args)
            if done:
                return

    def dispatch(self, tag: str, command: str, args: str) -> bool:
        ok = lambda message="done": self.push(f"{tag} OK {message}\r\n")  # noqa: E731
        with self.state.lock:
            if command == "CAPABILITY":
                self.push("* CAPABILITY IMAP4rev1 IDLE MOVE UIDPLUS SPECIAL-USE AUTH=PLAIN\r\n")
                ok()
            elif command == "NOOP":
                ok()
            elif command == "ID":
                self.push("* ID NIL\r\n")
                ok()
            elif command == "ENABLE":
                ok()
            elif command == "LOGIN":
                parts = re.findall(r'"([^"]*)"|(\S+)', args)
                user, password = [a or b for a, b in parts][:2]
                if user == USER and password == PASSWORD:
                    self.state.logins += 1
                    ok("LOGIN completed")
                else:
                    self.push(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n")
            elif command == "LOGOUT":
                self.push("* BYE\r\n")
                ok()
                return True
            elif command == "LIST":
                for name, box in self.state.boxes.items():
                    self.push(f'* LIST ({box.attrs}) "/" "{name}"\r\n')
                ok()
            elif command in {"SELECT", "EXAMINE"}:
                name = args.strip().strip('"')
                box = self.state.boxes.get(name)
                if box is None:
                    self.push(f"{tag} NO no such mailbox\r\n")
                    return False
                self.selected = name
                self.push(f"* {len(box.mails)} EXISTS\r\n* 0 RECENT\r\n")
                self.push("* FLAGS (\\Seen \\Flagged \\Deleted \\Draft)\r\n")
                self.push(
                    f"* OK [UIDVALIDITY {box.validity}] ok\r\n* OK [UIDNEXT {box.next_uid}] ok\r\n"
                )
                ok("[READ-WRITE] SELECT completed")
            elif command == "CLOSE":
                self.selected = None
                ok()
            elif command == "UID":
                self.uid_command(tag, args)
            elif command == "SEARCH":
                self.search(tag, args, uid=False)
            elif command == "EXPUNGE":
                box = self.state.boxes[self.selected or "INBOX"]
                box.mails = [m for m in box.mails if "\\Deleted" not in m.flags]
                ok()
            elif command == "APPEND":
                self.append(tag, args)
            elif command == "IDLE":
                entry = (self, self.selected)
                self.state.idlers.append(entry)
                self.push("+ idling\r\n")
                self.state.lock.release()
                try:
                    self.rfile.readline()
                finally:
                    self.state.lock.acquire()
                    self.state.idlers.remove(entry)
                ok("IDLE terminated")
            else:
                self.push(f"{tag} BAD unknown {command}\r\n")
        return False

    def append(self, tag: str, args: str) -> None:
        match = re.match(r'"?([^"\s]+)"?\s*(?:\(([^)]*)\))?.*\{(\d+)\+?\}$', args)
        assert match
        name, flags, size = match.group(1), match.group(2) or "", int(match.group(3))
        if not args.rstrip().endswith("+}"):
            self.push("+ ready\r\n")
        raw = self.rfile.read(size)
        self.rfile.readline()
        self.state.deliver(raw, name, set(flags.split()))
        self.push(f"{tag} OK APPEND completed\r\n")

    def search(self, tag: str, args: str, *, uid: bool) -> None:
        box = self.state.boxes[self.selected or "INBOX"]
        biggest = max((m.uid for m in box.mails), default=0)
        upper = args.upper()
        if upper.startswith("UID "):
            wanted = _uid_set(args.split()[1], biggest)
            found = [m.uid for m in box.mails if m.uid in wanted]
        elif upper.startswith("HEADER "):
            parts = re.findall(r'"([^"]*)"|(\S+)', args)
            header, value = [a or b for a, b in parts][1:3]
            needle = f"{header}: {value}".lower().encode()
            found = [m.uid for m in box.mails if needle in m.raw.lower()]
        else:
            found = [m.uid for m in box.mails]
        self.push(f"* SEARCH {' '.join(map(str, found))}\r\n")
        self.push(f"{tag} OK SEARCH completed\r\n")

    def uid_command(self, tag: str, args: str) -> None:
        verb, _, rest = args.partition(" ")
        verb = verb.upper()
        box = self.state.boxes[self.selected or "INBOX"]
        if verb == "SEARCH":
            self.search(
                tag,
                rest.removeprefix("CHARSET UTF-8 ").removeprefix("(").removesuffix(")"),
                uid=True,
            )
            return
        biggest = max((m.uid for m in box.mails), default=0)
        uid_text, _, spec = rest.partition(" ")
        uids = _uid_set(uid_text, biggest)
        if verb == "FETCH":
            for position, mail in enumerate(box.mails, 1):
                if mail.uid not in uids:
                    continue
                flags = " ".join(sorted(mail.flags))
                if "BODY" in spec.upper():
                    head = f"* {position} FETCH (UID {mail.uid} FLAGS ({flags}) BODY[] {{{len(mail.raw)}}}\r\n"
                    with self.write_lock:
                        self.wfile.write(head.encode() + mail.raw + b")\r\n")
                else:
                    self.push(f"* {position} FETCH (UID {mail.uid} FLAGS ({flags}))\r\n")
            self.wfile.flush()
            self.push(f"{tag} OK FETCH completed\r\n")
        elif verb == "STORE":
            action, _, flag_text = spec.partition(" ")
            flags = set(re.findall(r"\\\w+", flag_text))
            for mail in box.mails:
                if mail.uid in uids:
                    if action.upper().startswith("+"):
                        mail.flags |= flags
                    elif action.upper().startswith("-"):
                        mail.flags -= flags
            self.push(f"{tag} OK STORE completed\r\n")
        elif verb == "MOVE":
            target = spec.strip().strip('"')
            moving = [m for m in box.mails if m.uid in uids]
            box.mails = [m for m in box.mails if m.uid not in uids]
            for mail in moving:
                self.state.deliver(mail.raw, target, mail.flags)
            self.push(f"{tag} OK MOVE completed\r\n")
        else:
            self.push(f"{tag} BAD unknown UID {verb}\r\n")


class _SmtpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        sent: list[dict[str, Any]] = self.server.sent  # type: ignore[attr-defined]
        reply = lambda text: (self.wfile.write(f"{text}\r\n".encode()), self.wfile.flush())  # noqa: E731
        reply("220 fake SMTP ready")
        envelope: dict[str, Any] = {"to": []}
        while line := self.rfile.readline():
            text = line.decode("utf8", "replace").strip()
            upper = text.upper()
            if upper.startswith(("EHLO", "HELO")):
                reply("250-fake\r\n250 AUTH PLAIN LOGIN")
            elif upper.startswith("AUTH PLAIN"):
                import base64

                decoded = base64.b64decode(text.split()[2]).split(b"\0")
                good = decoded[1].decode() == USER and decoded[2].decode() == PASSWORD
                reply("235 ok" if good else "535 bad credentials")
            elif upper.startswith("MAIL FROM"):
                envelope = {"from": text, "to": []}
                reply("250 ok")
            elif upper.startswith("RCPT TO"):
                address = re.search(r"<([^>]*)>", text)
                envelope["to"].append(address.group(1) if address else "")
                reply("250 ok")
            elif upper == "DATA":
                reply("354 go")
                data = bytearray()
                while (chunk := self.rfile.readline()) != b".\r\n":
                    data += chunk
                envelope["raw"] = bytes(data)
                sent.append(envelope)
                reply("250 queued")
            elif upper == "QUIT":
                reply("221 bye")
                return
            elif upper == "RSET":
                reply("250 ok")
            else:
                reply("502 not implemented")


class _Threaded(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@dataclass
class FakeMail:
    imap_port: int
    smtp_port: int
    state: ImapState
    sent: list[dict[str, Any]]
    servers: list[_Threaded]

    def profile(self, name: str = "Test account") -> dict[str, Any]:
        return {
            "label": name,
            "imap": {"host": "127.0.0.1", "port": self.imap_port, "secure": False},
            "smtp": {"host": "127.0.0.1", "port": self.smtp_port, "secure": False},
            "auth": {"type": "password", "user": USER},
            "mailboxes": ["INBOX"],
        }

    def stop(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()


def start_fake_mail(imap_port: int = 0, smtp_port: int = 0) -> FakeMail:
    state = ImapState()
    imap = _Threaded(("127.0.0.1", imap_port), _ImapHandler)
    imap.imap_state = state  # type: ignore[attr-defined]
    smtp = _Threaded(("127.0.0.1", smtp_port), _SmtpHandler)
    sent: list[dict[str, Any]] = []
    smtp.sent = sent  # type: ignore[attr-defined]
    for server in (imap, smtp):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return FakeMail(imap.server_address[1], smtp.server_address[1], state, sent, [imap, smtp])


def serve_with_control(control_port: int, imap_port: int, smtp_port: int) -> None:
    """For browser tests: the mail servers plus a small page to deliver mail and read what was sent."""
    fake = start_fake_mail(imap_port, smtp_port)

    class Control(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["content-length"])) or b"{}")
            fake.state.deliver(make_mail(**body))
            self.send_response(200)
            self.end_headers()

        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            sent = [{"to": s["to"], "raw": s["raw"].decode("utf8", "replace")} for s in fake.sent]
            self.wfile.write(json.dumps(sent).encode())

        def log_message(self, *_: Any) -> None:
            pass

    HTTPServer(("127.0.0.1", control_port), Control).serve_forever()


if __name__ == "__main__":
    serve_with_control(
        int(os.environ.get("FAKE_MAIL_CONTROL_PORT", 8767)),
        int(os.environ.get("FAKE_IMAP_PORT", 8143)),
        int(os.environ.get("FAKE_SMTP_PORT", 8025)),
    )
    time.sleep(0)
