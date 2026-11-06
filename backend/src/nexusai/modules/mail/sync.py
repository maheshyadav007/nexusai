"""Keeps the local store and the server in step: new mail by IDLE, history in the background."""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from nexusai.contracts.mail import (
    MailChanged,
    MailHistoryFinished,
    MailProfile,
    MailPulled,
    MailReceived,
    MailSyncChanged,
    SyncState,
)
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel.module import Context
from nexusai.modules.mail import store
from nexusai.modules.mail.imap import (
    READ,
    ConnectionFailed,
    DeleteRefused,
    Fetched,
    Folder,
    FolderStatus,
    ImapSession,
    SignInFailed,
    distinct_total,
    synced_folders,
)
from nexusai.modules.mail.parse import parse_message
from nexusai.modules.mail.pop3 import Pop3Session
from nexusai.modules.mail.rules import evaluate, own_domain_of

log = structlog.get_logger()
DRAFT_HEADER = "x-nexusai-draft"
PROGRESS_NOTICE_SECONDS = 1.0
MailSession = ImapSession | Pop3Session


GMAIL_SYSTEM_LABELS = {"inbox": "\\Inbox", "sent": "\\Sent", "drafts": "\\Draft"}
# Folders where mail already here is often filed too, like Gmail's labels. All Mail holds nearly
# everything, so walking it would say nothing useful.
FILED_ROLES = {"other", "sent", "drafts", "archive"}
COPY_BATCHES_PER_PASS = 10
# Looked at on every check. The rest are only opened when their status says something changed.
ALWAYS_CHECKED = {"inbox", "sent"}
# Who takes turns bringing down older mail, then who waits until they've all finished.
HISTORY_TIERS = (("inbox", "sent", "drafts", "other", "archive"), ("all",), ("trash", "junk"))


@dataclass
class SyncStatus:
    state: SyncState = "off"
    message: str | None = None
    backfill_remaining: bool = False
    folders: dict[str, str] = field(default_factory=dict)
    total: int = 0
    done: int = 0
    server_total: int = 0
    last_check: str | None = None
    next_check: str | None = None
    last_found: int = 0
    last_pulled: int = 0
    last_found_at: str | None = None


class MailSync:
    def __init__(self, ctx: Context, account: str, profile: MailProfile, password: str) -> None:
        self.ctx = ctx
        self.account = account
        self.profile = profile
        self.password = password
        self.config = ctx.config.mail
        self._own_domain = own_domain_of(profile.address or profile.auth.user)
        self._own = {(profile.address or profile.auth.user).lower(), profile.auth.user.lower()}
        self.status = SyncStatus()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"mail-{account}")
        self._last_notice = 0.0
        self._statuses: dict[str, FolderStatus] = {}
        # Older UIDs still to come for each folder, so a large one isn't listed for every batch.
        self._older: dict[str, list[int]] = {}
        self._copies: dict[str, list[int]] = {}
        self._turn = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=self.config.connect_timeout_seconds + 5)

    def wake(self) -> None:
        """New local work for the server, such as a read flag."""
        self._wake.set()

    def _set_state(self, state: SyncState, message: str | None = None) -> None:
        changed = state != self.status.state or message != self.status.message
        self.status.state, self.status.message = state, message
        if changed:
            with self.ctx.bus.unit_of_work() as work:
                work.emit(
                    "mail.syncChanged",
                    MailSyncChanged(state=state).model_dump(),
                    source="mail",
                    trace_id=self.ctx.trace_id,
                )

    def _settings(self) -> Any:
        return store.sync_settings(self.ctx.bus.db, self.account)

    def _pulled(self) -> int:
        return int(
            self.ctx.bus.db.fetch_all(
                "SELECT COUNT(DISTINCT message) AS n FROM message_locations"
                " WHERE account = ? AND folder NOT LIKE 'pst:%'",
                (self.account,),
            )[0]["n"]
        )

    def _note_progress(self, downloading: int = 0) -> None:
        """How much of what's wanted is here, counting each email once, and what's on its way."""
        settings = self._settings()
        budget = settings["history_budget"] if settings else None
        pulled = self._pulled() + downloading
        wanted = self.status.server_total if budget is None else pulled + budget
        self.status.total = max(min(wanted, self.status.server_total), pulled)
        self.status.done = pulled
        now = time.monotonic()
        if now - self._last_notice < PROGRESS_NOTICE_SECONDS:
            return
        self._last_notice = now
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "mail.syncProgress",
                {"total": self.status.total, "done": self.status.done},
                source="mail",
                trace_id=self.ctx.trace_id,
            )

    def _run(self) -> None:
        delay = self.config.reconnect_min_seconds
        while not self._stop.is_set():
            session: MailSession | None = None
            try:
                self._set_state("connecting")
                settings = self._settings()
                # Refusing is the default, so only a person's clear choice turns it off.
                never_delete = bool(settings["never_delete"]) if settings else True
                timeout = self.config.connect_timeout_seconds
                if self.profile.protocol == "pop3":
                    session = Pop3Session(
                        self.profile,
                        self.password,
                        timeout,
                        never_delete=never_delete,
                        uids=self._pop3_uids,
                    )
                else:
                    session = ImapSession(
                        self.profile, self.password, timeout, never_delete=never_delete
                    )
                delay = self.config.reconnect_min_seconds
                self._session(session)
            except SignInFailed:
                self._set_state("failed", "The mail server refused the username or password.")
                return
            except ConnectionFailed as error:
                log.info(
                    "mail_connection_lost",
                    account=self.account,
                    error=type(error).__name__,
                    detail=str(error)[:200],
                )
                self._set_state("offline", "Can't reach the mail server. Retrying.")
                self._stop.wait(delay)
                delay = min(delay * 2, self.config.reconnect_max_seconds)
            except Exception:
                log.exception("mail_sync_failed", account=self.account)
                self._set_state("offline", "Mail sync hit a problem. Retrying.")
                self._stop.wait(delay)
                delay = min(delay * 2, self.config.reconnect_max_seconds)
            finally:
                if session:
                    session.close()
        self.status.state = "off"

    def _pop3_uids(self, names: list[str]) -> dict[str, int]:
        """A lasting number for each server ID. New ones count up, so newer mail is higher."""
        with self.ctx.bus.db.transaction() as tx:
            known = {
                row["name"]: row["uid"]
                for row in tx.execute(
                    "SELECT name, uid FROM pop3_uids WHERE account = ?", (self.account,)
                ).fetchall()
            }
            biggest = max(known.values(), default=0)
            for name in names:
                if name not in known:
                    biggest += 1
                    known[name] = biggest
                    tx.execute(
                        "INSERT INTO pop3_uids (account, name, uid) VALUES (?, ?, ?)",
                        (self.account, name, biggest),
                    )
        return known

    def _discover(self, session: MailSession) -> list[Folder]:
        """Every folder on the server, as it is right now. A label can appear or go at any time."""
        found = session.folders()
        wanted = synced_folders(found)
        self.status.folders = {}
        for folder in reversed(wanted):
            self.status.folders[folder.role] = folder.name
        with self.ctx.bus.db.transaction() as tx:
            for folder in wanted:
                tx.execute(
                    "INSERT INTO mail_folders (account, name, role) VALUES (?, ?, ?)"
                    " ON CONFLICT (account, name) DO UPDATE SET role = excluded.role",
                    (self.account, folder.name, folder.role),
                )
            names = {folder.name for folder in wanted}
            for row in tx.execute(
                "SELECT name FROM mail_folders WHERE account = ?", (self.account,)
            ).fetchall():
                if row["name"] not in names:
                    self._forget_folder(tx, row["name"])
        return wanted

    def _forget_folder(self, tx: Any, name: str) -> None:
        for row in tx.execute(
            "SELECT uid FROM message_locations WHERE account = ? AND folder = ?",
            (self.account, name),
        ).fetchall():
            store.remove_location(tx, self.account, name, row["uid"])
        tx.execute("DELETE FROM mail_folders WHERE account = ? AND name = ?", (self.account, name))

    def _session(self, session: MailSession) -> None:
        self._older = {}
        self._copies = {}
        self._statuses = {}
        folders: list[Folder] = []
        measured = 0.0
        while not self._stop.is_set():
            woken = self._wake.is_set()
            self._wake.clear()
            # Asking every folder takes seconds, so a large download only does it now and then.
            due = time.monotonic() - measured >= self.config.check_every_seconds
            if not folders or woken or due:
                folders = self._discover(session)
            inbox = next((f for f in folders if f.role == "inbox"), None)
            self._drain_outbox(session)
            changed: set[str] = set()
            if not measured or woken or due:
                changed = self._measure(session, folders)
                measured = time.monotonic()
            looking = [f for f in folders if f.role in ALWAYS_CHECKED or f.name in changed]
            found = pulled = 0
            for folder in looking:
                if self._stop.is_set():
                    return
                came = self._fetch_new(session, folder)
                found += came[0]
                pulled += came[1]
            self._sync_flags(session, looking)
            remaining = self._backfill(session, folders)
            self.status.backfill_remaining = remaining
            self._checked(found, pulled, waiting=not remaining)
            if remaining:
                self._set_state("backfilling")
                continue
            self.status.total = self.status.done = 0
            self._history_done()
            self._set_state("live")
            if self._file_copies(session, folders):
                continue
            if inbox:
                session.select(inbox.name)
                announced = session.wait_for_change(
                    self.config.check_every_seconds,
                    lambda: self._stop.is_set() or self._wake.is_set(),
                )
                if announced:
                    self._wake.set()
            else:
                self._wake.wait(self.config.check_every_seconds)

    def _file_copies(self, session: MailSession, folders: list[Folder]) -> bool:
        """Files mail that's already here under the other folders it's in, downloading nothing.

        True while there's more to look through, so the check doesn't wait before carrying on.
        """
        rows = self.ctx.bus.db.fetch_all(
            "SELECT name, copies_below FROM mail_folders"
            " WHERE account = ? AND copies_below IS NOT NULL ORDER BY name",
            (self.account,),
        )
        if not rows:
            return False
        by_name = {folder.name: folder for folder in folders}
        name, below = rows[0]["name"], rows[0]["copies_below"]
        folder = by_name.get(name)
        batch = self.config.backfill_batch
        left: list[int] = []
        if folder is not None:
            session.select(name)
            left = self._copies.get(name) or [uid for uid in session.all_uids() if uid < below]
            for _ in range(COPY_BATCHES_PER_PASS):
                if not left or self._stop.is_set():
                    break
                self._note_copies(session, folder, left[-batch:])
                left = left[:-batch]
            self._copies[name] = left
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_folders SET copies_below = ? WHERE account = ? AND name = ?",
                ((left[-1] + 1) if left else None, self.account, name),
            )
        return True

    def _measure(self, session: MailSession, folders: list[Folder]) -> set[str]:
        """What each folder holds, and which ones changed since the last look."""
        changed: set[str] = set()
        counts: dict[Folder, int] = {}
        statuses = {folder: session.status(folder.name) for folder in folders}
        with self.ctx.bus.db.transaction() as tx:
            for folder, status in statuses.items():
                counts[folder] = status.messages
                if self._statuses.get(folder.name) != status:
                    changed.add(folder.name)
                    self._statuses[folder.name] = status
                    tx.execute(
                        "UPDATE mail_folders SET server_count = ?, server_unseen = ?, uid_next = ?"
                        " WHERE account = ? AND name = ?",
                        (
                            status.messages,
                            status.unseen,
                            status.uid_next,
                            self.account,
                            folder.name,
                        ),
                    )
        self.status.server_total = distinct_total(counts)
        return changed

    def _history_done(self) -> None:
        """Says once that older mail has stopped coming, by choice or because it's all here."""
        settings = self._settings()
        if settings is None or settings["history_finished"]:
            return
        budget = settings["history_budget"]
        pulled = self._pulled()
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE mail_sync_settings SET history_finished = ? WHERE account = ?",
                (datetime.now(UTC).isoformat(), self.account),
            )
            work.emit(
                "mail.historyFinished",
                MailHistoryFinished(
                    pulled=pulled,
                    total=max(self.status.server_total, pulled),
                    reason="enough" if budget == 0 else "everything",
                ).model_dump(),
                source="mail",
                trace_id=self.ctx.trace_id,
            )

    def _checked(self, found: int, pulled: int, *, waiting: bool) -> None:
        """One check is done: note what it found, so the Cockpit can say whether we're in step."""
        now = datetime.now(UTC)
        status = self.status
        status.last_check = now.isoformat()
        wait = timedelta(seconds=self.config.check_every_seconds)
        status.next_check = (now + wait).isoformat() if waiting else None
        if found:
            status.last_found, status.last_pulled = found, pulled
            status.last_found_at = status.last_check
        with self.ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE mail_sync_settings SET server_total = ?, last_check = ?, last_found = ?,"
                " last_pulled = ?, last_found_at = ? WHERE account = ?",
                (
                    status.server_total,
                    status.last_check,
                    status.last_found,
                    status.last_pulled,
                    status.last_found_at,
                    self.account,
                ),
            )
            if found:
                work.emit(
                    "mail.pulled",
                    MailPulled(found=found, pulled=pulled).model_dump(),
                    source="mail",
                    trace_id=self.ctx.trace_id,
                )

    def _folder_row(self, name: str) -> tuple[int | None, int, int | None]:
        row = self.ctx.bus.db.fetch_all(
            "SELECT uidvalidity, last_uid, backfill_below FROM mail_folders"
            " WHERE account = ? AND name = ?",
            (self.account, name),
        )[0]
        return row["uidvalidity"], row["last_uid"], row["backfill_below"]

    def _reset_folder(self, name: str, validity: int) -> None:
        """The server renumbered this folder, so what we hold no longer lines up."""
        with self.ctx.bus.db.transaction() as tx:
            rows = tx.execute(
                "SELECT uid FROM message_locations WHERE account = ? AND folder = ?",
                (self.account, name),
            ).fetchall()
            for row in rows:
                store.remove_location(tx, self.account, name, row["uid"])
            tx.execute(
                "UPDATE mail_folders SET uidvalidity = ?, last_uid = 0, backfill_below = NULL"
                " WHERE account = ? AND name = ?",
                (validity, self.account, name),
            )
        self._older.pop(name, None)

    def _spend(self, tx: Any, stored: int) -> None:
        tx.execute(
            "UPDATE mail_sync_settings SET history_budget = MAX(0, history_budget - ?)"
            " WHERE account = ? AND history_budget IS NOT NULL",
            (stored, self.account),
        )

    def _first_look(self, session: MailSession, folder: Folder, validity: int) -> None:
        """Older mail comes as the budget allows. Whatever arrives after this moment is new."""
        settings = self._settings()
        budget = settings["history_budget"] if settings else None
        allowance = (
            self.config.initial_batch if budget is None else min(self.config.initial_batch, budget)
        )
        if folder.role not in HISTORY_TIERS[0]:
            allowance = 0
        if allowance <= 0:
            status = self._statuses.get(folder.name)
            if status and status.uid_next:
                top, below = status.uid_next - 1, status.uid_next if status.messages else None
            else:
                uids = session.all_uids()
                top, below = (uids[-1], uids[-1] + 1) if uids else (0, None)
            with self.ctx.bus.db.transaction() as tx:
                tx.execute(
                    "UPDATE mail_folders SET uidvalidity = ?, backfill_below = ?, last_uid = ?,"
                    " copies_below = ? WHERE account = ? AND name = ?",
                    (
                        validity,
                        below,
                        top,
                        below if folder.role in FILED_ROLES else None,
                        self.account,
                        folder.name,
                    ),
                )
            return
        uids = session.all_uids()
        newest = uids[-allowance:]
        below = newest[0] if len(uids) > len(newest) else None
        self._set_state("syncing")
        stored = self._ingest(session, folder, newest, live=False, advance=False)
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_folders SET uidvalidity = ?, backfill_below = ?, last_uid = ?,"
                " copies_below = ? WHERE account = ? AND name = ?",
                (
                    validity,
                    below,
                    uids[-1] if uids else 0,
                    below if folder.role in FILED_ROLES else None,
                    self.account,
                    folder.name,
                ),
            )
            self._spend(tx, stored)
        self._note_progress()

    def _fetch_new(self, session: MailSession, folder: Folder) -> tuple[int, int]:
        """How many new emails this check found in the folder, and how many came down."""
        validity, _ = session.select(folder.name)
        known, last_uid, _ = self._folder_row(folder.name)
        if known is not None and known != validity:
            self._reset_folder(folder.name, validity)
            known, last_uid = None, 0
        # Not last_uid == 0: a mailbox that started empty has been synced, so its first mail is new.
        if known is None:
            self._first_look(session, folder, validity)
            return 0, 0
        uids = session.uids_after(last_uid)
        pulled = 0
        bulk = len(uids) > self.ctx.config.agent.bulk_mail_threshold
        for start in range(0, len(uids), self.config.backfill_batch):
            if self._stop.is_set():
                break
            batch = uids[start : start + self.config.backfill_batch]
            # A week with the laptop closed can take a while, so that shows as downloading.
            if len(uids) > len(batch):
                self._set_state("syncing")
            pulled += self._ingest(session, folder, batch, live=True, advance=True, bulk=bulk)
            if len(uids) > len(batch):
                self._note_progress()
        if bulk and pulled:
            with self.ctx.bus.unit_of_work() as work:
                work.emit(
                    "mail.bulkArrived", {"count": pulled}, source="mail", trace_id=self.ctx.trace_id
                )
        return len(uids), pulled

    def _next_history(self, folders: list[Folder]) -> tuple[Folder, int, bool] | None:
        """Whose turn it is, how many it may bring, and whether it was asked for itself."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT name, history_more FROM mail_folders"
            " WHERE account = ? AND backfill_below IS NOT NULL",
            (self.account,),
        )
        waiting = {row["name"]: row["history_more"] for row in rows}
        batch = self.config.backfill_batch
        for folder in folders:
            if waiting.get(folder.name, 0) > 0:
                return folder, min(batch, waiting[folder.name]), True
        settings = self._settings()
        budget = settings["history_budget"] if settings else None
        if budget == 0:
            return None
        allowance = batch if budget is None else min(batch, budget)
        for tier in HISTORY_TIERS:
            turns = [f for f in folders if f.role in tier and f.name in waiting]
            if turns:
                self._turn += 1
                return turns[self._turn % len(turns)], allowance, False
        return None

    def _backfill(self, session: MailSession, folders: list[Folder]) -> bool:
        """One batch of history per pass, so new mail is never kept waiting by a large mailbox."""
        chosen = self._next_history(folders)
        if chosen is None:
            return False
        folder, allowance, for_itself = chosen
        _, _, below = self._folder_row(folder.name)
        session.select(folder.name)
        older = self._older.get(folder.name)
        if older is None:
            older = [uid for uid in session.all_uids() if uid < (below or 0)]
        batch, rest = older[-allowance:], older[:-allowance]
        self._older[folder.name] = rest
        stored = self._ingest(session, folder, batch, live=False, advance=False)
        with self.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_folders SET backfill_below = ?, history_more = CASE WHEN ? THEN"
                " MAX(0, history_more - ?) ELSE history_more END WHERE account = ? AND name = ?",
                (
                    batch[0] if rest and batch else None,
                    int(for_itself),
                    stored,
                    self.account,
                    folder.name,
                ),
            )
            if not rest:
                tx.execute(
                    "UPDATE mail_folders SET history_more = 0 WHERE account = ? AND name = ?",
                    (self.account, folder.name),
                )
            if not for_itself:
                self._spend(tx, stored)
        self._note_progress()
        return True

    def _deserves_a_look(self, tx: Any, result: store.Stored) -> bool:
        """Only generated Updates with a consequential subject bypass an Exact match."""
        return result.worth_a_look

    def _note_copies(self, session: MailSession, folder: Folder, uids: list[int]) -> list[int]:
        """Files what's already held under this folder too, and returns what needs downloading."""
        ids = session.message_ids(uids)
        if not ids:
            return uids
        marks = ",".join("?" * len(ids))
        rows = self.ctx.bus.db.fetch_all(
            f"SELECT message_id, MIN(id) AS id FROM messages WHERE account = ?"  # noqa: S608
            f" AND message_id IN ({marks}) GROUP BY message_id",
            (self.account, *ids.values()),
        )
        held = {row["message_id"]: row["id"] for row in rows}
        copies = {uid: held[identity] for uid, identity in ids.items() if identity in held}
        if copies:
            with self.ctx.bus.unit_of_work() as work:
                for uid, message in copies.items():
                    store.add_location(
                        work.tx, message, self.account, folder.name, folder.role, uid
                    )
                work.emit(
                    "mail.changed",
                    MailChanged(threads=len(copies), reason=folder.role).model_dump(),
                    source="mail",
                    trace_id=self.ctx.trace_id,
                )
        return [uid for uid in uids if uid not in copies]

    def _download(self, session: MailSession, uids: list[int]) -> list[Fetched]:
        """A few at a time, so a large batch shows its progress as it comes."""
        every = self.config.progress_every
        if len(uids) <= every:
            return session.fetch(uids)
        fetched: list[Fetched] = []
        self._note_progress()
        for start in range(0, len(uids), every):
            fetched += session.fetch(uids[start : start + every])
            self._note_progress(downloading=len(fetched))
        return fetched

    def _ingest(
        self,
        session: MailSession,
        folder: Folder,
        uids: list[int],
        *,
        live: bool,
        advance: bool,
        bulk: bool = False,
    ) -> int:
        """How many emails were new to this computer. One already here just gains this folder."""
        if not uids:
            return 0
        wanted = self._note_copies(session, folder, uids)
        fetched = self._download(session, wanted)
        from nexusai.modules.mail.module import folder_modes, ordered_rules

        rules = ordered_rules(self.ctx)
        modes = folder_modes(self.ctx)
        prepared = []
        for item in fetched:
            try:
                parsed = parse_message(item.raw)
            except Exception as error:
                log.warning(
                    "mail_parse_skipped",
                    account=self.account,
                    folder=folder.name,
                    uid=item.uid,
                    error=type(error).__name__,
                )
                continue
            # NexusAI's own saved drafts are shown from the drafts list, not as mail.
            if DRAFT_HEADER in parsed.headers:
                continue
            prepared.append((item, parsed, evaluate(parsed, rules, self._own_domain, modes)))
        with self.ctx.bus.unit_of_work() as work:
            stored = []
            for item, parsed, match in prepared:
                result = store.store_message(
                    work.tx,
                    account=self.account,
                    folder=folder.name,
                    role=folder.role,
                    uid=item.uid,
                    raw=item.raw,
                    read=item.read,
                    flagged=item.flagged,
                    parsed=parsed,
                    match=match,
                    config=self.config,
                )
                if result:
                    stored.append(result)
                    if match and match.actions.mark_read and not item.read:
                        work.tx.execute(
                            "INSERT INTO mail_outbox (account, op, payload) VALUES (?, 'read', ?)",
                            (
                                self.account,
                                json.dumps(
                                    {
                                        "message": result.message,
                                        "folder": folder.name,
                                        "uid": item.uid,
                                        "value": True,
                                    }
                                ),
                            ),
                        )
                        self._wake.set()
            if advance:
                work.tx.execute(
                    "UPDATE mail_folders SET last_uid = MAX(last_uid, ?)"
                    " WHERE account = ? AND name = ?",
                    (max(uids), self.account, folder.name),
                )
            if stored:
                work.emit(
                    "mail.changed",
                    MailChanged(
                        threads=len({s.thread for s in stored}), reason=folder.role
                    ).model_dump(),
                    source="mail",
                    trace_id=self.ctx.trace_id,
                )
            if live and not bulk and len(stored) > self.ctx.config.agent.bulk_mail_threshold:
                work.emit(
                    "mail.bulkArrived",
                    {"count": len(stored)},
                    source="mail",
                    trace_id=self.ctx.trace_id,
                )
            if live and not bulk and folder.role == "sent":
                for result in stored:
                    work.emit(
                        "mail.sent",
                        {"message_id": result.message, "thread_id": result.thread},
                        source="mail",
                        trace_id=self.ctx.trace_id,
                    )
            if live and folder.role == "inbox":
                for result in stored:
                    work.emit(
                        "mail.received",
                        MailReceived(
                            message_id=result.message, thread_id=result.thread, rule=result.rule
                        ).model_dump(),
                        source="mail",
                        trace_id=self.ctx.trace_id,
                    )
                    if (
                        not bulk
                        and len(stored) <= self.ctx.config.agent.bulk_mail_threshold
                        and not result.skip_agent
                    ) or self._deserves_a_look(work.tx, result):
                        work.emit(
                            "mail.needsTriage",
                            {"message_id": result.message, "thread_id": result.thread},
                            source="mail",
                            trace_id=self.ctx.trace_id,
                        )
                    if result.notify:
                        work.emit(
                            "notification.requested",
                            NotificationRequested(
                                kind="mail",
                                title="New mail matched a rule",
                                detail=result.rule or "",
                                link=f"/mail/thread/{result.thread}",
                            ).model_dump(),
                            source="mail",
                            trace_id=self.ctx.trace_id,
                        )
        return len(stored)

    def _sync_flags(self, session: MailSession, folders: list[Folder]) -> None:
        """Changes made elsewhere: read, flagged, and mail moved or deleted on the server."""
        # Nothing to learn from POP3, and mail its server has dropped stays here.
        if not session.keeps_flags:
            return
        for folder in folders:
            rows = self.ctx.bus.db.fetch_all(
                "SELECT l.uid, l.message, m.read, m.flagged, m.thread_id, m.folder AS speaks_from"
                " FROM message_locations l JOIN messages m ON m.id = l.message"
                " WHERE l.account = ? AND l.folder = ? ORDER BY l.uid DESC LIMIT ?",
                (self.account, folder.name, self.config.flag_window),
            )
            if not rows:
                continue
            session.select(folder.name)
            current = session.flags([row["uid"] for row in rows])
            changed: set[int] = set()
            with self.ctx.bus.unit_of_work() as work:
                # Local changes still on their way out win until the server has them.
                pending = {
                    json.loads(op["payload"]).get("message")
                    for op in work.tx.execute(
                        "SELECT payload FROM mail_outbox WHERE account = ?", (self.account,)
                    )
                }
                for row in rows:
                    if row["message"] in pending:
                        continue
                    if row["uid"] not in current:
                        store.remove_location(work.tx, self.account, folder.name, row["uid"])
                        changed.add(row["thread_id"])
                        continue
                    # An email in many folders takes its flags from one, so they can't flip-flop.
                    if row["speaks_from"] != folder.name:
                        continue
                    read, flagged = current[row["uid"]]
                    if read != bool(row["read"]) or flagged != bool(row["flagged"]):
                        work.tx.execute(
                            "UPDATE messages SET read = ?, flagged = ? WHERE id = ?",
                            (int(read), int(flagged), row["message"]),
                        )
                        store.refresh_thread(work.tx, row["thread_id"])
                        changed.add(row["thread_id"])
                if changed:
                    work.emit(
                        "mail.changed",
                        MailChanged(threads=len(changed), reason="server").model_dump(),
                        source="mail",
                        trace_id=self.ctx.trace_id,
                    )

    def _drain_outbox(self, session: MailSession) -> None:
        """Local changes, kept in the database so they survive a restart or a dropped connection."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id, op, payload, attempts FROM mail_outbox WHERE account = ?"
            " AND failed_at IS NULL ORDER BY id",
            (self.account,),
        )
        for row in rows:
            payload = json.loads(row["payload"])
            try:
                self._apply(session, row["op"], payload)
            except DeleteRefused:
                # It stays on the server, and isn't retried if the switch changes later.
                log.info("mail_delete_refused", op=row["op"])
                self._finish_op(row["id"])
                continue
            except ConnectionFailed as error:
                if not isinstance(error, OSError) and row["attempts"] + 1 >= 3:
                    log.warning("mail_op_needs_attention", op=row["op"], error=type(error).__name__)
                    with self.ctx.bus.unit_of_work() as work:
                        work.tx.execute(
                            "UPDATE mail_outbox SET failed_at=?,error=?,attempts=attempts+1"
                            " WHERE id=?",
                            (datetime.now(UTC).isoformat(), str(error)[:500], row["id"]),
                        )
                        work.emit(
                            "notification.requested",
                            NotificationRequested(
                                kind="mail-sync",
                                title="A mail change could not sync",
                                detail=(
                                    "Your local change is saved. Open Cockpit, then Pipelines. "
                                    "Run Mail sync to retry after fixing the server problem."
                                ),
                                link="/cockpit",
                            ).model_dump(),
                            source="mail",
                            trace_id=self.ctx.trace_id,
                        )
                        work.emit(
                            "mail.syncChanged",
                            {"state": "failed", "message": "A saved mail change needs retrying."},
                            source="mail",
                            trace_id=self.ctx.trace_id,
                        )
                    continue
                with self.ctx.bus.db.transaction() as tx:
                    tx.execute(
                        "UPDATE mail_outbox SET attempts = attempts + 1 WHERE id = ?", (row["id"],)
                    )
                raise
            self._finish_op(row["id"])

    def _finish_op(self, op_id: int) -> None:
        with self.ctx.bus.db.transaction() as tx:
            tx.execute("DELETE FROM mail_outbox WHERE id = ?", (op_id,))

    def _take_label_off(self, session: MailSession, uid: int, role: str, folder: str) -> None:
        all_mail = self.status.folders.get("all")
        if all_mail is None:
            log.warning("mail_no_all_mail_folder", folder=folder)
            return
        session.remove_label(uid, GMAIL_SYSTEM_LABELS.get(role, folder), all_mail)

    def _apply(self, session: MailSession, op: str, payload: dict[str, object]) -> None:
        if op == "append":
            role = str(payload["role"])
            folder = self.status.folders.get(role)
            if folder:
                raw = bytes.fromhex(str(payload["raw"]))
                flags = (READ,) if role == "sent" else (b"\\Draft",)
                session.append(folder, raw, flags)
            return
        if op == "delete_drafts":
            folder = self.status.folders.get("drafts")
            if folder:
                session.select(folder)
                for uid in session.draft_uids(str(payload["draft"])):
                    session.delete(uid)
            return
        folder_name, uid = str(payload["folder"]), int(str(payload["uid"]))
        if op == "move" and isinstance(session, ImapSession):
            rows = self.ctx.bus.db.fetch_all(
                "SELECT message_id,local_role FROM messages WHERE id=?", (payload.get("message"),)
            )
            if not rows or (rows[0]["local_role"] and rows[0]["local_role"] != payload["role"]):
                return  # A later Restore/Undo superseded this queued move.
            identity = rows[0]["message_id"]
            source = None
            folders = list(dict.fromkeys([folder_name, *self.status.folders.values()]))
            for candidate in folders:
                session.select(candidate)
                # Check the cheap known UID first; retries then resolve the new UID after a move.
                if candidate == folder_name and session.message_ids([uid]).get(uid) == identity:
                    source = (candidate, uid)
                    break
                found = session.message_uids(identity)
                if found:
                    source = (candidate, found[0])
                    break
            if source is None:
                raise OSError("The moved message is not available on the server yet.")
            folder_name, uid = source
            if self.status.folders.get(str(payload["role"])) == folder_name:
                return  # Replayed move already reached its destination.
        session.select(folder_name)
        if op == "read":
            session.set_read(uid, bool(payload["value"]))
        elif op == "flag":
            session.set_flagged(uid, bool(payload["value"]))
        elif op == "delete":
            session.delete(uid)
        elif op == "copy":
            session.copy(uid, str(payload["target"]))
        elif op == "remove_from":
            if session.is_gmail:
                self._take_label_off(session, uid, str(payload["role"]), folder_name)
            else:
                session.delete(uid)
        elif op == "move":
            role = str(payload["role"])
            target = self.status.folders.get(role)
            if target:
                session.move(uid, target)
            elif role == "archive" and session.is_gmail:
                # Gmail has no Archive folder: archiving is taking the Inbox label off.
                self._take_label_off(session, uid, "inbox", folder_name)
