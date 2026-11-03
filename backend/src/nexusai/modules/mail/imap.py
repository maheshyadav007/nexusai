"""A thin wrapper over imapclient, so the sync engine speaks in folders and UIDs."""

import re
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
# The order folders are looked at. Everything is synced, and All Mail comes late because on Gmail
# it holds what the others already brought down.
ROLE_ORDER = ("inbox", "sent", "drafts", "other", "archive", "all", "trash", "junk")
# Never deleted from, and neither is anything moved into them while deleting is refused.
DELETING_ROLES = {"trash", "junk"}
READ, FLAGGED = b"\\Seen", b"\\Flagged"
ConnectionFailed = (OSError, IMAPClientError, ssl.SSLError, EOFError, TimeoutError)
MESSAGE_ID = re.compile(rb"message-id:\s*(<[^>]+>)", re.I)


class SignInFailed(Exception):
    pass


class DeleteRefused(Exception):
    """This account is set to never delete anything on the server."""


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


@dataclass(frozen=True)
class FolderStatus:
    messages: int
    unseen: int
    uid_next: int
    validity: int


class ImapSession:
    keeps_flags = True

    def __init__(
        self, profile: MailProfile, password: str, timeout: float, *, never_delete: bool = True
    ) -> None:
        self.never_delete = never_delete
        self.deleting_folders: set[str] = set()
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
        self.deleting_folders = {f.name for f in found if f.role in DELETING_ROLES}
        return found

    def status(self, name: str) -> FolderStatus:
        """What a folder holds, without opening it."""
        info: dict[bytes, Any] = self.client.folder_status(
            name, [b"MESSAGES", b"UNSEEN", b"UIDNEXT", b"UIDVALIDITY"]
        )
        return FolderStatus(
            messages=int(info.get(b"MESSAGES", 0)),
            unseen=int(info.get(b"UNSEEN", 0)),
            uid_next=int(info.get(b"UIDNEXT", 0)),
            validity=int(info.get(b"UIDVALIDITY", 0)),
        )

    @property
    def is_gmail(self) -> bool:
        return b"X-GM-EXT-1" in self.client.capabilities()

    def message_ids(self, uids: list[int]) -> dict[int, str]:
        """Each mail's Message-ID, so one already held in another folder needn't come down again."""
        if not uids:
            return {}
        rows = self.client.fetch(uids, ["BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])
        found: dict[int, str] = {}
        for uid, row in rows.items():
            header = next(
                (value for key, value in row.items() if key.startswith(b"BODY[HEADER")), b""
            )
            match = MESSAGE_ID.search(bytes(header or b""))
            if match:
                found[int(uid)] = match.group(1).decode(errors="replace").strip()
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
        if self.never_delete and folder in self.deleting_folders:
            raise DeleteRefused(folder)
        self.client.move([uid], folder)

    def copy(self, uid: int, folder: str) -> None:
        """Also in that folder now. On Gmail this adds the label."""
        self.client.copy([uid], folder)

    def remove_label(self, uid: int, label: str, all_mail: str) -> None:
        """Gmail only. Takes one label off, and the mail itself stays.

        Gmail ignores this from inside the label's own folder, so it's done from All Mail. The
        folder holding uid must be the one selected.
        """
        row = self.client.fetch([uid], [b"X-GM-MSGID"]).get(uid)
        if not row:
            return
        self.client.select_folder(all_mail)
        found = self.client.search(["X-GM-MSGID", row[b"X-GM-MSGID"]])
        if found:
            self.client.remove_gmail_labels(found, [label])

    def delete(self, uid: int) -> None:
        if self.never_delete:
            raise DeleteRefused(str(uid))
        self.client.delete_messages([uid])
        self.client.expunge()

    def append(self, folder: str, raw: bytes, flags: tuple[bytes, ...]) -> None:
        self.client.append(folder, raw, flags=flags)

    def draft_uids(self, marker: str) -> list[int]:
        return [int(uid) for uid in self.client.search(["HEADER", "X-NexusAI-Draft", marker])]

    def wait_for_change(self, seconds: float, interrupted: Callable[[], bool]) -> bool:
        """IDLE until the server reports a change (True), time passes, or we're interrupted."""
        self.client.idle()
        try:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not interrupted():
                if self.client.idle_check(timeout=1):
                    return True
            return False
        finally:
            self.client.idle_done()

    def close(self) -> None:
        try:
            self.client.logout()
        except (*ConnectionFailed, AttributeError):
            pass


def synced_folders(folders: list[Folder]) -> list[Folder]:
    """Every folder, in the order they're looked at."""
    known = {role: index for index, role in enumerate(ROLE_ORDER)}
    return sorted(folders, key=lambda f: known.get(f.role, known["other"]))


def distinct_total(counts: dict[Folder, int]) -> int:
    """How many different emails these hold. On Gmail, All Mail already has the labelled ones."""
    everywhere = sum(count for folder, count in counts.items() if folder.role == "all")
    if not everywhere:
        return sum(counts.values())
    apart = sum(count for folder, count in counts.items() if folder.role in DELETING_ROLES)
    return everywhere + apart


def test_imap(
    profile: MailProfile, password: str, timeout: float, counts: dict[Folder, int] | None = None
) -> str | None:
    """None if it worked, or what went wrong in plain words. Fills counts for each folder."""
    try:
        session = ImapSession(profile, password, timeout)
        try:
            if counts is not None:
                for folder in synced_folders(session.folders()):
                    counts[folder] = session.status(folder.name).messages
        finally:
            session.close()
    except SignInFailed:
        return "The server refused that username or password."
    except ConnectionFailed as error:
        return (
            f"Couldn't connect to {profile.imap.host}:{profile.imap.port}. {type(error).__name__}"
        )
    return None
