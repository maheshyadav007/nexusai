"""A thin wrapper over imapclient, so the sync engine speaks in folders and UIDs."""

import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError

from nexusai.contracts.mail import MailProfile

ROLE_FLAGS = {
    b"\\Sent": "sent",
    b"\\Drafts": "drafts",
    b"\\Trash": "trash",
    b"\\Archive": "archive",
    b"\\All": "all",
    b"\\Junk": "junk",
}
ROLE_NAMES = {
    "sent": "sent",
    "sent items": "sent",
    "sent mail": "sent",
    "drafts": "drafts",
    "trash": "trash",
    "deleted items": "trash",
    "archive": "archive",
}
READ, FLAGGED = b"\\Seen", b"\\Flagged"
ConnectionFailed = (OSError, IMAPClientError, ssl.SSLError, EOFError, TimeoutError)


class SignInFailed(Exception):
    pass


@dataclass(frozen=True)
class Folder:
    name: str
    role: str


@dataclass(frozen=True)
class Fetched:
    uid: int
    raw: bytes
    read: bool
    flagged: bool


class ImapSession:
    def __init__(self, profile: MailProfile, password: str, timeout: float) -> None:
        self.client = IMAPClient(
            profile.imap.host,
            port=profile.imap.port,
            ssl=profile.imap.secure,
            timeout=timeout,
            use_uid=True,
        )
        try:
            self.client.login(profile.auth.user, password)
        except LoginError as error:
            raise SignInFailed from error

    def folders(self) -> list[Folder]:
        found = []
        for flags, _, name in self.client.list_folders():
            if any(flag.lower() == b"\\noselect" for flag in flags):
                continue
            role = next((ROLE_FLAGS[f] for f in flags if f in ROLE_FLAGS), None)
            if role is None:
                leaf = str(name).rsplit("/", 1)[-1].lower()
                role = "inbox" if str(name).upper() == "INBOX" else ROLE_NAMES.get(leaf, "other")
            found.append(Folder(str(name), role))
        return found

    def select(self, name: str) -> tuple[int, int]:
        """The folder's UIDVALIDITY and message count."""
        info: dict[bytes, Any] = self.client.select_folder(name)
        return int(info[b"UIDVALIDITY"]), int(info.get(b"EXISTS", 0))

    def all_uids(self) -> list[int]:
        return sorted(int(uid) for uid in self.client.search(["ALL"]))

    def uids_after(self, uid: int) -> list[int]:
        # A range ending in * always includes the newest message, even if it's older than uid.
        return sorted(u for u in map(int, self.client.search(["UID", f"{uid + 1}:*"])) if u > uid)

    def fetch(self, uids: list[int]) -> list[Fetched]:
        if not uids:
            return []
        rows = self.client.fetch(uids, ["BODY.PEEK[]", "FLAGS"])
        result = []
        for uid, row in rows.items():
            flags = row.get(b"FLAGS", ())
            raw = row.get(b"BODY[]")
            if raw is not None:
                result.append(Fetched(int(uid), raw, READ in flags, FLAGGED in flags))
        return sorted(result, key=lambda item: item.uid)

    def flags(self, uids: list[int]) -> dict[int, tuple[bool, bool]]:
        if not uids:
            return {}
        rows = self.client.fetch(uids, ["FLAGS"])
        return {
            int(uid): (READ in row.get(b"FLAGS", ()), FLAGGED in row.get(b"FLAGS", ()))
            for uid, row in rows.items()
        }

    def set_read(self, uid: int, read: bool) -> None:
        (self.client.add_flags if read else self.client.remove_flags)([uid], [READ])

    def set_flagged(self, uid: int, flagged: bool) -> None:
        (self.client.add_flags if flagged else self.client.remove_flags)([uid], [FLAGGED])

    def move(self, uid: int, folder: str) -> None:
        self.client.move([uid], folder)

    def delete(self, uid: int) -> None:
        self.client.delete_messages([uid])
        self.client.expunge()

    def append(self, folder: str, raw: bytes, flags: tuple[bytes, ...]) -> None:
        self.client.append(folder, raw, flags=flags)

    def wait_for_change(self, seconds: float, interrupted: Callable[[], bool]) -> None:
        """IDLE until the server reports a change, the time passes, or we're interrupted."""
        self.client.idle()
        try:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not interrupted():
                if self.client.idle_check(timeout=1):
                    return
        finally:
            self.client.idle_done()

    def close(self) -> None:
        try:
            self.client.logout()
        except (*ConnectionFailed, AttributeError):
            pass


def test_imap(profile: MailProfile, password: str, timeout: float) -> str | None:
    """None if it worked, or what went wrong in plain words."""
    try:
        ImapSession(profile, password, timeout).close()
    except SignInFailed:
        return "The server refused that username or password."
    except ConnectionFailed as error:
        return (
            f"Couldn't connect to {profile.imap.host}:{profile.imap.port}. {type(error).__name__}"
        )
    return None
