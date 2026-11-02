"""Keeps the local store and the server in step: new mail by IDLE, history in the background."""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog

from nexusai.contracts.mail import (
    MailChanged,
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
    Folder,
    ImapSession,
    SignInFailed,
    synced_folders,
)
from nexusai.modules.mail.parse import parse_message
from nexusai.modules.mail.rules import evaluate, load_rules

log = structlog.get_logger()
DRAFT_HEADER = "x-nexusai-draft"
PROGRESS_NOTICE_SECONDS = 1.0


def shares_of(limit: int | None, totals: dict[str, int]) -> dict[str, int]:
    """How many of the newest emails each folder gets, in proportion to its size."""
    everything = sum(totals.values())
    if limit is None or limit >= everything:
        return dict(totals)
    shares = {name: limit * total // everything for name, total in totals.items()}
    spare = limit - sum(shares.values())
    # In the order the folders were given, so the inbox gets what rounding left over.
    for name, total in totals.items():
        extra = min(spare, total - shares[name])
        shares[name] += extra
        spare -= extra
    return shares


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
    def __init__(
        self,
        ctx: Context,
        account: str,
        profile: MailProfile,
        password: str,
        limit: int | None = None,
    ) -> None:
        self.ctx = ctx
        self.account = account
        self.profile = profile
        self.password = password
        self.limit = limit
        self.config = ctx.config.mail
        self.status = SyncStatus()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"mail-{account}")
        # For each folder still coming down: how many are on the server, and how many are left.
        self._coming: dict[str, tuple[int, int]] = {}
        self._shares: dict[str, int] = {}
        # Folders that have all the limit allows, so a quiet check needn't list every UID again.
        self._filled: set[str] = set()
        rows = store.sync_settings(ctx.bus.db, account)
        if rows:
            self.status.server_total = rows["server_total"]
            self.status.last_check = rows["last_check"]
            self.status.last_found = rows["last_found"]
            self.status.last_pulled = rows["last_pulled"]
            self.status.last_found_at = rows["last_found_at"]
        self._last_notice = 0.0

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

    def _note_progress(self, folder: str, total: int, left: int) -> None:
        if left:
            self._coming[folder] = (total, left)
        else:
            self._coming.pop(folder, None)
        self.status.total = sum(pair[0] for pair in self._coming.values())
        self.status.done = self.status.total - sum(pair[1] for pair in self._coming.values())
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
            session: ImapSession | None = None
            try:
                self._set_state("connecting")
                session = ImapSession(
                    self.profile, self.password, self.config.connect_timeout_seconds
                )
                delay = self.config.reconnect_min_seconds
                self._session(session)
            except SignInFailed:
                self._set_state("failed", "The mail server refused the username or password.")
                return
            except ConnectionFailed as error:
                log.info("mail_connection_lost", account=self.account, error=type(error).__name__)
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

    def _discover(self, session: ImapSession) -> list[Folder]:
        folders = session.folders()
        wanted = synced_folders(folders)
        self.status.folders = {f.role: f.name for f in folders}
        with self.ctx.bus.db.transaction() as tx:
            for folder in wanted:
                tx.execute(
                    "INSERT INTO mail_folders (account, name, role) VALUES (?, ?, ?)"
                    " ON CONFLICT (account, name) DO UPDATE SET role = excluded.role",
                    (self.account, folder.name, folder.role),
                )
        return wanted

    def _session(self, session: ImapSession) -> None:
        folders = self._discover(session)
        inbox = next((f for f in folders if f.role == "inbox"), None)
        while not self._stop.is_set():
            self._wake.clear()
            self._drain_outbox(session)
            self._measure(session, folders)
            found = pulled = 0
            for folder in folders:
                if self._stop.is_set():
                    return
                came = self._fetch_new(session, folder)
                found += came[0]
                pulled += came[1]
            self._sync_flags(session, folders)
            remaining = self._backfill(session, folders)
            self.status.backfill_remaining = remaining
            self._checked(found, pulled, waiting=not remaining)
            if remaining:
                self._set_state("backfilling")
                continue
            self._set_state("live")
            if inbox:
                session.select(inbox.name)
                session.wait_for_change(
                    self.config.check_every_seconds,
                    lambda: self._stop.is_set() or self._wake.is_set(),
                )
            else:
                self._wake.wait(self.config.check_every_seconds)

    def _measure(self, session: ImapSession, folders: list[Folder]) -> None:
        totals = {folder.name: session.select(folder.name)[1] for folder in folders}
        self.status.server_total = sum(totals.values())
        self._shares = shares_of(self.limit, totals)

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
                "SELECT id FROM messages WHERE account = ? AND folder = ?", (self.account, name)
            ).fetchall()
            for row in rows:
                store.remove_message(tx, row["id"])
            tx.execute(
                "UPDATE mail_folders SET uidvalidity = ?, last_uid = 0, backfill_below = NULL"
                " WHERE account = ? AND name = ?",
                (validity, self.account, name),
            )

    def _fetch_new(self, session: ImapSession, folder: Folder) -> tuple[int, int]:
        """How many new emails this check found in the folder, and how many came down."""
        validity, _ = session.select(folder.name)
        known, last_uid, _ = self._folder_row(folder.name)
        if known is not None and known != validity:
            self._reset_folder(folder.name, validity)
            known, last_uid = None, 0
        # Not last_uid == 0: a mailbox that started empty has been synced, so its first mail is new.
        first_sync = known is None
        if first_sync:
            uids = session.all_uids()
            share = min(self._shares.get(folder.name, len(uids)), len(uids))
            take = min(self.config.initial_batch, share)
            newest = uids[-take:] if take else []
            # Past the newest kept here, whatever the limit left behind can still come later.
            below = (newest[0] if newest else uids[-1] + 1) if len(uids) > len(newest) else None
            self._set_state("syncing")
            with self.ctx.bus.db.transaction() as tx:
                tx.execute(
                    "UPDATE mail_folders SET uidvalidity = ?, backfill_below = ?, last_uid = ?"
                    " WHERE account = ? AND name = ?",
                    (validity, below, uids[-1] if uids else 0, self.account, folder.name),
                )
            self._ingest(session, folder, newest, live=False, advance=True)
            self._note_progress(folder.name, share, share - len(newest))
            return 0, 0
        uids = session.uids_after(last_uid)
        pulled = 0
        for start in range(0, len(uids), self.config.backfill_batch):
            if self._stop.is_set():
                break
            batch = uids[start : start + self.config.backfill_batch]
            # A week with the laptop closed can take a while, so that shows as downloading.
            if len(uids) > len(batch):
                self._set_state("syncing")
            self._ingest(session, folder, batch, live=True, advance=True)
            pulled += len(batch)
            if len(uids) > len(batch):
                self._note_progress(folder.name, len(uids), len(uids) - pulled)
        return len(uids), pulled

    def _backfill(self, session: ImapSession, folders: list[Folder]) -> bool:
        """One batch of history per pass, so new mail is never kept waiting by a large mailbox."""
        for folder in folders:
            _, _, below = self._folder_row(folder.name)
            if not below or folder.name in self._filled:
                continue
            session.select(folder.name)
            uids = session.all_uids()
            share = min(self._shares.get(folder.name, len(uids)), len(uids))
            older = [uid for uid in (uids[-share:] if share else []) if uid < below]
            if not older:
                # Kept below stays set, so raising the limit later carries on from here.
                self._filled.add(folder.name)
                self._note_progress(folder.name, share, 0)
                continue
            batch = older[-self.config.backfill_batch :]
            next_below = batch[0] if uids[0] < batch[0] else None
            self._ingest(session, folder, batch, live=False, advance=False)
            with self.ctx.bus.db.transaction() as tx:
                tx.execute(
                    "UPDATE mail_folders SET backfill_below = ? WHERE account = ? AND name = ?",
                    (next_below, self.account, folder.name),
                )
            self._note_progress(folder.name, share, len(older) - len(batch))
            return True
        return False

    def _ingest(
        self, session: ImapSession, folder: Folder, uids: list[int], *, live: bool, advance: bool
    ) -> None:
        if not uids:
            return
        fetched = session.fetch(uids)
        rules = load_rules(self.ctx.config.home)
        prepared = []
        for item in fetched:
            parsed = parse_message(item.raw)
            # NexusAI's own saved drafts are shown from the drafts list, not as mail.
            if DRAFT_HEADER in parsed.headers:
                continue
            prepared.append((item, parsed, evaluate(parsed, rules)))
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
                    if not result.skip_agent:
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

    def _sync_flags(self, session: ImapSession, folders: list[Folder]) -> None:
        """Changes made elsewhere: read, flagged, and mail moved or deleted on the server."""
        for folder in folders:
            rows = self.ctx.bus.db.fetch_all(
                "SELECT id, uid, read, flagged, thread_id FROM messages"
                " WHERE account = ? AND folder = ?"
                " ORDER BY uid DESC LIMIT ?",
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
                    if row["id"] in pending:
                        continue
                    if row["uid"] not in current:
                        store.remove_message(work.tx, row["id"])
                        changed.add(row["thread_id"])
                        continue
                    read, flagged = current[row["uid"]]
                    if read != bool(row["read"]) or flagged != bool(row["flagged"]):
                        work.tx.execute(
                            "UPDATE messages SET read = ?, flagged = ? WHERE id = ?",
                            (int(read), int(flagged), row["id"]),
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

    def _drain_outbox(self, session: ImapSession) -> None:
        """Local changes, kept in the database so they survive a restart or a dropped connection."""
        rows = self.ctx.bus.db.fetch_all(
            "SELECT id, op, payload, attempts FROM mail_outbox WHERE account = ? ORDER BY id",
            (self.account,),
        )
        for row in rows:
            payload = json.loads(row["payload"])
            try:
                self._apply(session, row["op"], payload)
            except ConnectionFailed as error:
                if not isinstance(error, OSError) and row["attempts"] + 1 >= 3:
                    log.warning("mail_op_dropped", op=row["op"], error=type(error).__name__)
                    self._finish_op(row["id"])
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

    def _apply(self, session: ImapSession, op: str, payload: dict[str, object]) -> None:
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
                for uid in session.client.search(
                    ["HEADER", "X-NexusAI-Draft", str(payload["draft"])]
                ):
                    session.delete(int(uid))
            return
        folder_name, uid = str(payload["folder"]), int(str(payload["uid"]))
        session.select(folder_name)
        if op == "read":
            session.set_read(uid, bool(payload["value"]))
        elif op == "flag":
            session.set_flagged(uid, bool(payload["value"]))
        elif op == "delete":
            session.delete(uid)
        elif op == "move":
            target = self.status.folders.get(str(payload["role"]))
            if target:
                session.move(uid, target)
