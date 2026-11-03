"""A small POP3 server that behaves like a real one: each connection sees a locked snapshot."""

import socketserver
import threading
from dataclasses import dataclass, field

from fake_mail import PASSWORD, USER


@dataclass
class Pop3State:
    mails: list[tuple[str, bytes]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    connections: int = 0
    busy: bool = False
    refuse: set[str] = field(default_factory=set)
    next_id: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)

    def deliver(self, raw: bytes) -> str:
        with self.lock:
            name = f"id-{self.next_id:04}"
            self.next_id += 1
            self.mails.append((name, raw))
            return name

    def drop(self, name: str) -> None:
        with self.lock:
            self.mails = [mail for mail in self.mails if mail[0] != name]


class _Handler(socketserver.StreamRequestHandler):
    def reply(self, text: str) -> None:
        self.wfile.write(f"{text}\r\n".encode())
        self.wfile.flush()

    def handle(self) -> None:
        state: Pop3State = self.server.state  # type: ignore[attr-defined]
        state.connections += 1
        self.reply("+OK fake POP3 ready")
        user = ""
        snapshot: list[tuple[str, bytes]] = []
        marked: set[str] = set()
        while line := self.rfile.readline():
            parts = line.decode("utf8", "replace").strip().split()
            command = parts[0].upper() if parts else ""
            if command == "USER":
                user = parts[1]
                self.reply("+OK")
            elif command == "PASS":
                if state.busy:
                    self.reply("-ERR [IN-USE] mailbox locked")
                elif user == USER and parts[1] == PASSWORD:
                    with state.lock:
                        snapshot = list(state.mails)
                    self.reply("+OK signed in")
                else:
                    self.reply("-ERR [AUTH] bad login")
            elif command == "UIDL":
                self.reply("+OK")
                for number, (name, _) in enumerate(snapshot, 1):
                    self.reply(f"{number} {name}")
                self.reply(".")
            elif command == "RETR":
                name, raw = snapshot[int(parts[1]) - 1]
                if name in state.refuse:
                    self.reply("-ERR can't read that one")
                    continue
                state.retrieved.append(name)
                self.reply("+OK")
                for text in raw.split(b"\r\n"):
                    self.wfile.write((b"." + text if text.startswith(b".") else text) + b"\r\n")
                self.reply(".")
            elif command == "DELE":
                marked.add(snapshot[int(parts[1]) - 1][0])
                self.reply("+OK")
            elif command == "QUIT":
                for name in marked:
                    state.deleted.append(name)
                    state.drop(name)
                self.reply("+OK bye")
                return
            else:
                self.reply("-ERR not implemented")


class _Threaded(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@dataclass
class FakePop3:
    port: int
    state: Pop3State
    server: _Threaded

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def start_fake_pop3() -> FakePop3:
    server = _Threaded(("127.0.0.1", 0), _Handler)
    state = Pop3State()
    server.state = state  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return FakePop3(server.server_address[1], state, server)
