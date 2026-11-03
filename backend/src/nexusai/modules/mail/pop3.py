"""POP3 behind the same calls as ImapSession, so the sync engine needs no second path.

POP3 is one mailbox and nothing else. There are no folders, read marks, flags or moves on the
server, so those stay on this computer, and a mail the server later drops is kept here.
"""

import poplib
import ssl
import time
from collections.abc import Callable

import structlog

from nexusai.contracts.mail import MailProfile
from nexusai.modules.mail.imap import DeleteRefused, Fetched, Folder, FolderStatus, SignInFailed

log = structlog.get_logger()
INBOX = Folder("INBOX", "inbox")
# Never changes: a POP3 server's IDs stay valid for as long as it keeps the mail.
VALIDITY = 1
# Servers lock the mailbox and hide new mail until the connection ends, so none stays open longer.
REFRESH_SECONDS = 60.0
WAIT_STEP_SECONDS = 1.0
# poplib refuses lines over 2 KB by default, and real mail has much longer ones.
poplib._MAXLINE = 16 * 1024 * 1024  # type: ignore[attr-defined]  # noqa: SLF001
BUSY_REPLIES = (b"IN-USE", b"SYS/TEMP", b"LOCK")
LOST_REPLIES = (b"EOF", b"line too long")

# Each server message ID's lasting number, newest highest, kept in the database.
UidBook = Callable[[list[str]], dict[str, int]]


class Pop3Failed(OSError):
    """The server gave an answer we can't carry on from. Counts as a lost connection."""


def _reply(error: poplib.error_proto) -> bytes:
    detail = error.args[0] if error.args else b""
    return detail if isinstance(detail, bytes) else str(detail).encode()


class Pop3Session:
    keeps_flags = False
    is_gmail = False

    def __init__(
        self,
        profile: MailProfile,
        password: str,
        timeout: float,
        *,
        never_delete: bool = True,
        uids: UidBook,
    ) -> None:
        self.profile = profile
        self.password = password
        self.timeout = timeout
        self.never_delete = never_delete
        self.uids = uids
        self.client: poplib.POP3 | None = None
        self.opened = 0.0
        self.numbers: dict[int, int] | None = None
        self._connect()

    def _connect(self) -> None:
        server = self.profile.imap
        try:
            if server.secure:
                context = ssl.create_default_context()
                if not server.verify_cert:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                client: poplib.POP3 = poplib.POP3_SSL(
                    server.host, server.port, timeout=self.timeout, context=context
                )
            else:
                client = poplib.POP3(server.host, server.port, timeout=self.timeout)
        except poplib.error_proto as error:
            raise Pop3Failed(_reply(error).decode(errors="replace")) from error
        try:
            client.user(self.profile.auth.user)
            client.pass_(self.password)
        except poplib.error_proto as error:
            client.close()
            # Another mail program has the mailbox open, which passes by itself.
            if any(word in _reply(error).upper() for word in BUSY_REPLIES):
                raise Pop3Failed(_reply(error).decode(errors="replace")) from error
            raise SignInFailed from error
        self.client = client
        self.opened = time.monotonic()
        self.numbers = None

    def _listing(self) -> tuple[poplib.POP3, dict[int, int]]:
        """The connection, and where each mail is in it. Numbers only hold for one connection."""
        if self.client is None or time.monotonic() - self.opened >= REFRESH_SECONDS:
            self.close()
            self._connect()
        client = self.client
        assert client is not None
        if self.numbers is None:
            try:
                lines = client.uidl()[1]
            except poplib.error_proto as error:
                raise Pop3Failed(_reply(error).decode(errors="replace")) from error
            rows = [
                line.decode("ascii", "replace").split() for line in lines if isinstance(line, bytes)
            ]
            pairs = [(int(row[0]), row[1]) for row in rows if len(row) == 2]
            known = self.uids([name for _, name in pairs])
            self.numbers = {known[name]: number for number, name in pairs}
        return client, self.numbers

    def folders(self) -> list[Folder]:
        return [INBOX]

    def status(self, name: str) -> FolderStatus:
        _, numbers = self._listing()
        return FolderStatus(
            messages=len(numbers),
            unseen=0,
            uid_next=max(numbers, default=0) + 1 if numbers else 0,
            validity=VALIDITY,
        )

    def message_ids(self, uids: list[int]) -> dict[int, str]:
        return {}

    def select(self, name: str) -> tuple[int, int]:
        _, numbers = self._listing()
        return VALIDITY, len(numbers)

    def all_uids(self) -> list[int]:
        return sorted(self._listing()[1])

    def uids_after(self, uid: int) -> list[int]:
        return [found for found in self.all_uids() if found > uid]

    def fetch(self, uids: list[int]) -> list[Fetched]:
        client, numbers = self._listing()
        result = []
        for uid in sorted(uids):
            number = numbers.get(uid)
            if number is None:
                continue
            try:
                lines = client.retr(number)[1]
            except poplib.error_proto as error:
                if any(word in _reply(error) for word in LOST_REPLIES):
                    raise Pop3Failed(_reply(error).decode(errors="replace")) from error
                # One mail the server won't give shouldn't stop all the others.
                log.warning("pop3_mail_refused", uid=uid)
                continue
            raw = b"\r\n".join(line for line in lines if isinstance(line, bytes)) + b"\r\n"
            result.append(Fetched(uid, raw, False, False))
        return result

    def flags(self, uids: list[int]) -> dict[int, tuple[bool, bool]]:
        return {}

    def set_read(self, uid: int, read: bool) -> None:
        pass

    def set_flagged(self, uid: int, flagged: bool) -> None:
        pass

    def move(self, uid: int, folder: str) -> None:
        pass

    def copy(self, uid: int, folder: str) -> None:
        pass

    def remove_label(self, uid: int, label: str, all_mail: str) -> None:
        pass

    def delete(self, uid: int) -> None:
        if self.never_delete:
            raise DeleteRefused(str(uid))
        client, numbers = self._listing()
        number = numbers.get(uid)
        if number is not None:
            try:
                client.dele(number)
            except poplib.error_proto as error:
                raise Pop3Failed(_reply(error).decode(errors="replace")) from error
            # A server only really deletes when the connection ends properly.
            self.close()

    def append(self, folder: str, raw: bytes, flags: tuple[bytes, ...]) -> None:
        pass

    def draft_uids(self, marker: str) -> list[int]:
        return []

    def wait_for_change(self, seconds: float, interrupted: Callable[[], bool]) -> bool:
        """POP3 can't announce anything, and the mailbox shouldn't stay locked while waiting."""
        self.close()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not interrupted():
            time.sleep(WAIT_STEP_SECONDS)
        return False

    def close(self) -> None:
        client, self.client = self.client, None
        self.numbers = None
        if client is None:
            return
        try:
            client.quit()
        except (OSError, EOFError, poplib.error_proto):
            client.close()


def test_pop3(
    profile: MailProfile, password: str, timeout: float, counts: dict[Folder, int] | None = None
) -> str | None:
    """None if it worked, or what went wrong in plain words. Fills counts for the mailbox."""
    server = profile.imap
    try:
        session = Pop3Session(
            profile,
            password,
            timeout,
            uids=lambda names: {name: index for index, name in enumerate(names, 1)},
        )
        try:
            if counts is not None:
                counts[INBOX] = session.status(INBOX.name).messages
        finally:
            session.close()
    except SignInFailed:
        return "The server refused that username or password."
    except ssl.SSLCertVerificationError:
        return (
            f"The certificate from {server.host} can't be verified. If it's a company server, set"
            " NEXUSAI_MAIL_VERIFY_CERT=false."
        )
    except OSError as error:
        return f"Couldn't connect to {server.host}:{server.port}. {type(error).__name__}"
    return None
