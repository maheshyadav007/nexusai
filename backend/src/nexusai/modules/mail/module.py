import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, cast

import structlog

from nexusai.contracts.events import AppEvent
from nexusai.contracts.mail import (
    AddPstImport,
    CategoryList,
    CategoryName,
    CategorySaved,
    CategorySortEstimate,
    ChangeThreadCategory,
    ChangeThreadFolder,
    CheckDraft,
    ConnectionResult,
    DecideCategory,
    DecidePriority,
    Draft,
    DraftList,
    FindPst,
    GetMailAccounts,
    GetMailPresets,
    GetMailStatus,
    GetMoreMail,
    GetPstImports,
    GetPstSearch,
    GetRules,
    GetSendChecks,
    GetThread,
    ListCategories,
    ListDrafts,
    ListMailFolders,
    ListThreads,
    MailAccounts,
    MailAccountView,
    MailCategory,
    MailChanged,
    MailDone,
    MailFolder,
    MailFolderCount,
    MailFolders,
    MailPreset,
    MailPresets,
    MailProfile,
    MailRule,
    MailStatus,
    MailSyncChanged,
    MailTestResult,
    MarkFolderRead,
    MergeCategories,
    MoveThread,
    ProbeServer,
    PstImport,
    PstImportAction,
    PstImports,
    PstSearchStatus,
    PstUploadStarted,
    Recipient,
    RemoveDraft,
    RemoveMailAccount,
    ReorderCategories,
    ReplyContext,
    ReplyDraft,
    RuleActions,
    RuleCondition,
    RuleSet,
    SaveCategory,
    SaveMailAccount,
    SearchMail,
    SearchResults,
    SendCheckResult,
    SendCheckSettings,
    SendDraft,
    SendProblem,
    ServerProbe,
    SetNeverDelete,
    SetSenderImages,
    SetThreadCategory,
    SetThreadFlag,
    SetThreadImportance,
    SetThreadRead,
    SetThreadStatus,
    SortCategory,
    StartPstUpload,
    StopHistory,
    TestMailAccount,
    ThreadList,
    ThreadUpdated,
    ThreadView,
    UpdateCategory,
)
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail import accounts, pst, pst_search, pst_upload, rules, send, store
from nexusai.modules.mail.imap import DELETING_ROLES, Folder, distinct_total, test_imap
from nexusai.modules.mail.parse import normalize_subject, parse_message
from nexusai.modules.mail.pop3 import test_pop3
from nexusai.modules.mail.rules import own_domain_of
from nexusai.modules.mail.sync import MailSync
from nexusai.modules.semantic import module as semantic

log = structlog.get_logger()
ATTACHED_WORDS = re.compile(r"\b(attached|attachment|enclosed|첨부)\b|첨부", re.I)
mail_module = Module(name="mail", migrations=[*store.MIGRATIONS, pst.MIGRATION])

# Filing that only exists on this computer, and old mail read from an archive file.
LOCAL_PREFIXES = ("local:", "pst:")
LOCAL_SENT = "local:sent"
# Removing the last folder is what Delete is for.
MINIMUM_TO_REMOVE = 2
# A count far larger than any folder, for "everything in this one".
FOLDER_EVERYTHING = 1_000_000_000

KINDS_SORTED = "mail_kinds_sorted_001"
KINDS_BATCH = 200

_sync: MailSync | None = None
_closing = threading.Event()
_sync_lock = threading.Lock()
_maintenance: threading.Thread | None = None


def _start_sync(ctx: Context) -> None:
    global _sync
    with _sync_lock:
        if _sync:
            _sync.stop()
            _sync = None
        active, profiles = accounts.read_accounts(ctx.config)
        if active is None:
            return
        profile = profiles[active]
        password = accounts.get_password(ctx.config, profile.auth.user)
        if password is None or accounts.require_encrypted(profile, ctx.config):
            return
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT INTO mail_sync_settings (account) VALUES (?) ON CONFLICT DO NOTHING",
                (active,),
            )
        settings = store.sync_settings(ctx.bus.db, active)
        if settings is None or settings["paused"]:
            return
        _sync = MailSync(ctx, active, profile, password)
        _sync.start()


def _sort_kinds_once(ctx: Context) -> None:
    """Sorts mail filed before Promotions, Updates and Forums existed, a little at a time."""
    db = ctx.bus.db
    if db.fetch_all("SELECT 1 FROM migrations WHERE id = ?", (KINDS_SORTED,)):
        return
    last = 0
    home_rules = rules.load_rules(ctx.config.home)
    changed = False
    while not _closing.is_set():
        rows = db.fetch_all(
            "SELECT m.id, m.thread_id, m.account FROM messages m"
            " WHERE m.rule IS NOT NULL AND m.id > ? ORDER BY m.id LIMIT ?",
            (last, KINDS_BATCH),
        )
        if not rows:
            with db.transaction() as tx:
                tx.execute("INSERT INTO migrations (id) VALUES (?)", (KINDS_SORTED,))
            break
        last = rows[-1]["id"]
        with db.transaction() as tx:
            for row in rows:
                raw = store.raw_of(db, row["id"])
                if raw is None:
                    continue
                parsed = parse_message(raw)
                _, profiles = accounts.read_accounts(ctx.config)
                profile = profiles.get(row["account"])
                domain = own_domain_of(profile.address or profile.auth.user) if profile else None
                match = rules.evaluate(parsed, home_rules, domain, folder_modes(ctx))
                if match is None:
                    continue
                tx.execute(
                    "UPDATE messages SET rule = ?, why = ? WHERE id = ?",
                    (match.name, match.why, row["id"]),
                )
                if match.actions.category:
                    tx.execute(
                        "UPDATE threads SET category = ?, why = ? WHERE id = ?"
                        " AND category_source = 'rule'",
                        (match.actions.category, match.why, row["thread_id"]),
                    )
                    changed = True
    if changed:
        with ctx.bus.unit_of_work() as work:
            work.emit(
                "mail.changed",
                MailChanged(threads=0, reason="kinds").model_dump(),
                source="mail",
                trace_id=ctx.trace_id,
            )


def _startup(ctx: Context) -> None:
    _closing.clear()
    _add_starter_categories(ctx)
    _organization_defaults(ctx)
    global _maintenance

    def maintain() -> None:
        try:
            _sort_kinds_once(ctx)
            if not _closing.is_set():
                _organization_provenance(ctx)
        except Exception:
            log.exception("mail_maintenance_failed")

    _maintenance = threading.Thread(target=maintain, daemon=True, name="mail-maintenance")
    _maintenance.start()
    _start_sync(ctx)
    # An import that was running when the app closed carries on from its saved position.
    pst.runner.kick(ctx)


def _shutdown() -> None:
    global _sync, _maintenance
    _closing.set()
    with _sync_lock:
        if _sync:
            _sync.stop()
            _sync = None
    if _maintenance:
        _maintenance.join(timeout=10)
        _maintenance = None


mail_module.on_start.append(_startup)
mail_module.on_stop.append(_shutdown)
mail_module.on_stop.append(pst.runner.stop)
mail_module.on_stop.append(pst_search.search.stop)


def _forget(ctx: Context) -> None:
    accounts.forget_everything(ctx.config)
    pst_search.search.status = PstSearchStatus(state="idle")


mail_module.on_reset.append(_forget)


def _account(ctx: Context) -> str:
    active, _ = accounts.read_accounts(ctx.config)
    if active is None:
        raise CommandError("mail.no_account", "Connect a mail account first.", 409)
    return active


def _active_profile(ctx: Context) -> tuple[str, MailProfile, str]:
    active, profiles = accounts.read_accounts(ctx.config)
    if active is None:
        raise CommandError("mail.no_account", "Connect a mail account first.", 409)
    profile = profiles[active]
    password = accounts.get_password(ctx.config, profile.auth.user)
    if password is None:
        raise CommandError(
            "mail.no_password", "Enter the password for this account in Settings.", 409
        )
    return active, profile, password


def _wake() -> None:
    if _sync:
        _sync.wake()


def check_now() -> None:
    if _sync:
        with _sync.ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_outbox SET failed_at=NULL,error=NULL,attempts=0 WHERE account=? AND failed_at IS NOT NULL",
                (_sync.account,),
            )
    _wake()


def pause_sync(ctx: Context, paused: bool) -> None:
    """Stops the connection altogether, or starts it again. A restart keeps this as it was."""
    account = _account(ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_sync_settings (account, paused) VALUES (?, ?)"
            " ON CONFLICT (account) DO UPDATE SET paused = excluded.paused",
            (account, int(paused)),
        )
    _start_sync(ctx)
    if paused:
        _announce(ctx, "paused")


def _announce(ctx: Context, state: Any) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "mail.syncChanged",
            MailSyncChanged(state=state).model_dump(),
            source="mail",
            trace_id=ctx.trace_id,
        )


# Accounts


def _accounts_view(ctx: Context) -> MailAccounts:
    active, profiles = accounts.read_accounts(ctx.config)
    return MailAccounts(
        active=active,
        accounts=[
            MailAccountView(
                name=name,
                profile=profile,
                has_password=accounts.get_password(ctx.config, profile.auth.user) is not None,
            )
            for name, profile in profiles.items()
        ],
    )


@mail_module.query("mail.accounts")
def get_accounts(query: GetMailAccounts, ctx: Context) -> MailAccounts:
    return _accounts_view(ctx)


@mail_module.command("mail.accounts.test")
def test_account(command: TestMailAccount, ctx: Context) -> MailTestResult:
    profile = accounts.with_system_servers(command.profile, ctx.config)
    if problem := accounts.require_encrypted(profile, ctx.config):
        raise CommandError("mail.not_encrypted", problem, 422)
    password = command.password or accounts.get_password(ctx.config, profile.auth.user)
    if not password:
        raise CommandError("mail.no_password", "Enter the password first.", 422)
    timeout = ctx.config.mail.connect_timeout_seconds
    counts: dict[Folder, int] = {}
    check = test_pop3 if profile.protocol == "pop3" else test_imap
    imap_problem = check(profile, password, timeout, counts)
    smtp_problem = send.test_smtp(profile, password, timeout)
    total = distinct_total(counts)
    return MailTestResult(
        counts=[
            MailFolderCount(name=folder.name, role=folder.role, messages=count)
            for folder, count in counts.items()
        ],
        total=total,
        suggested_pull=min(ctx.config.mail.suggested_pull, total),
        ok=not imap_problem and not smtp_problem,
        results=[
            ConnectionResult(
                service="imap", ok=not imap_problem, message=imap_problem or "Connected"
            ),
            ConnectionResult(
                service="smtp", ok=not smtp_problem, message=smtp_problem or "Connected"
            ),
        ],
    )


@mail_module.command("mail.accounts.save")
def save_account(command: SaveMailAccount, ctx: Context) -> MailAccounts:
    profile = accounts.with_system_servers(command.profile, ctx.config)
    if problem := accounts.require_encrypted(profile, ctx.config):
        raise CommandError("mail.not_encrypted", problem, 422)
    active, profiles = accounts.read_accounts(ctx.config)
    profiles[command.name] = profile
    if command.password:
        accounts.set_password(ctx.config, profile.auth.user, command.password)
    accounts.write_accounts(ctx.config, command.name if command.make_active else active, profiles)
    # Connecting is asking for mail, so an account paused earlier starts again. How much history
    # it brings is only decided once. Stop and Get more change that afterwards.
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_sync_settings (account, history_budget) VALUES (?, ?)"
            " ON CONFLICT (account) DO UPDATE SET paused = 0",
            (command.name, command.pull_limit),
        )
    _start_sync(ctx)
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "mail.accountsChanged", {"name": command.name}, source="mail", trace_id=ctx.trace_id
        )
    return _accounts_view(ctx)


def stop_history(ctx: Context) -> None:
    """Enough older mail. New mail keeps coming, so this also ends a pause."""
    account = _account(ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_sync_settings (account, history_budget) VALUES (?, 0)"
            " ON CONFLICT (account) DO UPDATE SET history_budget = 0, paused = 0",
            (account,),
        )
    if _sync is None:
        _start_sync(ctx)
    _wake()


def get_more(ctx: Context, count: int | None, folder: str | None = None) -> None:
    """More older mail, from one folder or from all of them in turn. Empty means all of it."""
    account = _account(ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_sync_settings (account) VALUES (?) ON CONFLICT DO NOTHING", (account,)
        )
        if folder:
            tx.execute(
                "UPDATE mail_folders SET history_more = history_more + ?"
                " WHERE account = ? AND name = ?",
                (count or FOLDER_EVERYTHING, account, folder),
            )
        elif count is None:
            tx.execute(
                "UPDATE mail_sync_settings SET history_budget = NULL WHERE account = ?", (account,)
            )
        else:
            tx.execute(
                "UPDATE mail_sync_settings SET history_budget = COALESCE(history_budget, 0) + ?"
                " WHERE account = ?",
                (count, account),
            )
        tx.execute(
            "UPDATE mail_sync_settings SET history_finished = NULL, paused = 0 WHERE account = ?",
            (account,),
        )
    if _sync is None:
        _start_sync(ctx)
    _wake()


@mail_module.command("mail.history.stop")
def history_stop(command: StopHistory, ctx: Context) -> MailStatus:
    stop_history(ctx)
    return cast(MailStatus, get_status(GetMailStatus(), ctx))


@mail_module.command("mail.history.more")
def history_more(command: GetMoreMail, ctx: Context) -> MailStatus:
    get_more(ctx, command.count, command.folder)
    return cast(MailStatus, get_status(GetMailStatus(), ctx))


@mail_module.command("mail.sync.neverDelete")
def set_never_delete(command: SetNeverDelete, ctx: Context) -> MailStatus:
    """Applies from the next connection, so the running one is restarted to pick it up."""
    account = _account(ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE mail_sync_settings SET never_delete = ? WHERE account = ?",
            (int(command.value), account),
        )
    _start_sync(ctx)
    return cast(MailStatus, get_status(GetMailStatus(), ctx))


@mail_module.query("mail.folders")
def mail_folders(query: ListMailFolders, ctx: Context) -> MailFolders:
    account = accounts.current_account(ctx.config)
    db = ctx.bus.db
    tally = {
        row["folder"]: (row["n"], row["unread"] or 0)
        for row in db.fetch_all(
            "SELECT l.folder, COUNT(*) AS n, COUNT(DISTINCT CASE WHEN m.read = 0 THEN m.thread_id END)"
            " AS unread FROM message_locations l JOIN messages m ON m.id = l.message"
            " WHERE l.account = ? GROUP BY l.folder",
            (account,),
        )
    }
    rows = db.fetch_all(
        "SELECT name, role, server_count FROM mail_folders WHERE account = ? ORDER BY name COLLATE NOCASE",
        (account,),
    )
    names = {row["name"] for row in rows}
    found: list[MailFolder] = []
    for row in rows:
        parent, _, leaf = str(row["name"]).rpartition("/")
        here, unread = tally.get(row["name"], (0, 0))
        found.append(
            MailFolder(
                name=row["name"],
                label=leaf or row["name"],
                parent=parent if parent in names else None,
                role=row["role"],
                on_server=row["server_count"],
                here=here,
                unread=unread,
            )
        )
    return MailFolders(folders=found, counts=store.unread_counts(db, account))


@mail_module.command("mail.accounts.remove")
def remove_account(command: RemoveMailAccount, ctx: Context) -> MailAccounts:
    active, profiles = accounts.read_accounts(ctx.config)
    removed = profiles.pop(command.name, None)
    accounts.write_accounts(ctx.config, None if active == command.name else active, profiles)
    still_used = removed and any(p.auth.user == removed.auth.user for p in profiles.values())
    if removed and not still_used:
        accounts.delete_password(ctx.config, removed.auth.user)
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM mail_sync_settings WHERE account = ?", (command.name,))
    _start_sync(ctx)
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "mail.accountsChanged", {"name": command.name}, source="mail", trace_id=ctx.trace_id
        )
    return _accounts_view(ctx)


@mail_module.query("mail.status")
def get_status(query: GetMailStatus, ctx: Context) -> MailStatus:
    active, _ = accounts.read_accounts(ctx.config)
    count = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM messages WHERE account = ?",
        (accounts.current_account(ctx.config),),
    )[0]["n"]
    every = int(ctx.config.mail.check_every_seconds)
    settings = store.sync_settings(ctx.bus.db, active) if active else None
    # Mail brought in from a PST isn't part of what's on the server.
    pulled = ctx.bus.db.fetch_all(
        "SELECT COUNT(DISTINCT message) AS n FROM message_locations"
        " WHERE account = ? AND folder NOT LIKE 'pst:%'",
        (active,),
    )[0]["n"]
    kept: dict[str, Any] = (
        {
            "history_budget": settings["history_budget"],
            "history_finished": bool(settings["history_finished"]),
            "never_delete": bool(settings["never_delete"]),
            "server_total": settings["server_total"],
            "last_check": settings["last_check"],
            "last_found": settings["last_found"],
            "last_pulled": settings["last_pulled"],
            "last_found_at": settings["last_found_at"],
        }
        if settings
        else {}
    )
    if _sync is None:
        state = "paused" if settings and settings["paused"] else "off"
        return MailStatus(
            account=active,
            state=state,
            messages=count,
            pulled=pulled,
            check_every_seconds=every,
            **kept,
        )
    live = _sync.status
    failed_ops = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM mail_outbox WHERE account=? AND failed_at IS NOT NULL", (active,)
    )[0]["n"]
    failure = (
        "A saved mail change could not sync. Run Mail sync from Pipelines to retry."
        if failed_ops
        else None
    )
    return MailStatus(
        **{
            **kept,
            "server_total": live.server_total or kept.get("server_total", 0),
            "last_check": live.last_check,
            "last_found": live.last_found,
            "last_pulled": live.last_pulled,
            "last_found_at": live.last_found_at,
        },
        account=active,
        state="failed" if failed_ops and live.state == "live" else live.state,
        message=live.message or failure,
        messages=count,
        pulled=pulled,
        backfill_remaining=live.backfill_remaining,
        total=live.total,
        done=live.done,
        check_every_seconds=every,
        next_check=live.next_check,
    )


@mail_module.command("mail.accounts.probe")
def probe_server(command: ProbeServer, ctx: Context) -> ServerProbe:
    return accounts.probe(command.server)


@mail_module.query("mail.presets")
def mail_presets(query: GetMailPresets, ctx: Context) -> MailPresets:
    known = [MailPreset(**preset) for preset in ctx.config.mail.presets]
    system = accounts.system_preset(ctx.config)
    return MailPresets(presets=[*known, system] if system else known)


# Reading


@mail_module.query("threads.list")
def list_threads(query: ListThreads, ctx: Context) -> ThreadList:
    account = accounts.current_account(ctx.config)
    return store.list_threads(
        ctx.bus.db,
        account,
        query.folder,
        query.category,
        query.before,
        query.limit,
        query.location,
        query.offset,
    )


@mail_module.command("mail.images.sender")
def set_sender_images(command: SetSenderImages, ctx: Context) -> MailDone:
    """Always load this sender's images, or never."""
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO mail_image_senders (address, allow) VALUES (?, ?)"
            " ON CONFLICT (address) DO UPDATE SET allow = excluded.allow",
            (command.address.lower(), int(command.allow)),
        )
        work.emit(
            "mail.changed",
            MailChanged(threads=0, reason="images").model_dump(),
            source="mail",
            trace_id=ctx.trace_id,
        )
    return MailDone()


def _remote_images(ctx: Context) -> str:
    """The person's setting, or the default for this install, which a company can set to block."""
    rows = ctx.bus.db.fetch_all("SELECT value FROM settings WHERE key = 'remote_images'")
    return str(
        json.loads(rows[0]["value"]) if rows else ctx.config.default_settings["remote_images"]
    )


@mail_module.query("thread.get")
def get_thread(query: GetThread, ctx: Context) -> ThreadView:
    view = store.thread_view(ctx.bus.db, query.id, _remote_images(ctx))
    if view is None:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    # Older mail's attachments get read the first time someone opens them.
    if any(a.kind == "attachment" for m in view.messages for a in m.attachments):
        with ctx.bus.unit_of_work() as work:
            work.emit(
                "thread.opened", {"thread_id": query.id}, source="mail", trace_id=ctx.trace_id
            )
    return view


@mail_module.query("search.run")
def run_search(query: SearchMail, ctx: Context) -> SearchResults:
    account = accounts.current_account(ctx.config)
    query = store.with_operators(query)
    found = store.search(ctx.bus.db, account, query)
    engine = semantic.engine()
    # Words work right away. If the model isn't here yet, asking is what fetches it.
    if not query.query.strip() or engine is None or not engine.is_ready():
        return found
    hits = engine.search(found.corrected or query.query, {"mail"}, MEANING_CANDIDATES)
    return store.merge_meaning(
        ctx.bus.db, account, query, found, [(int(hit.ref), hit.excerpt) for hit in hits]
    )


# Changing state: saved here at once, and sent to the server through the outbox


def _outbox(work_tx: object, account: str, op: str, payload: dict[str, object]) -> None:
    work_tx.execute(  # type: ignore[attr-defined]
        "INSERT INTO mail_outbox (account, op, payload) VALUES (?, ?, ?)",
        (account, op, json.dumps(payload)),
    )


def _on_server(tx: Any, message: object) -> list[Any]:
    """Where this email really is. Local filing and PST archives aren't folders on the server."""
    return [
        row
        for row in store.locations_of(tx, int(str(message)))
        if not str(row["folder"]).startswith(LOCAL_PREFIXES)
    ]


def _thread_messages(ctx: Context, thread: int) -> list[dict[str, object]]:
    rows = ctx.bus.db.fetch_all("SELECT * FROM messages WHERE thread_id = ?", (thread,))
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    return [dict(row) for row in rows]


def _changed(
    work: object, ctx: Context, thread: int, field: str, value: object, old_value: object = None
) -> None:
    work.emit(  # type: ignore[attr-defined]
        "thread.updated",
        ThreadUpdated(
            thread_id=thread, field=field, value=value, old_value=old_value, by=ctx.actor
        ).model_dump(),
        source="mail",
        trace_id=ctx.trace_id,
    )
    work.emit(  # type: ignore[attr-defined]
        "mail.changed",
        MailChanged(threads=1, reason=field).model_dump(),
        source="mail",
        trace_id=ctx.trace_id,
    )


@mail_module.command("thread.setRead")
def set_read(command: SetThreadRead, ctx: Context) -> MailDone:
    messages = _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        for message in messages:
            if bool(message["read"]) != command.read:
                work.tx.execute(
                    "UPDATE messages SET read = ? WHERE id = ?", (int(command.read), message["id"])
                )
                # Every folder on the server, since a company server keeps each copy's own flags.
                for place in _on_server(work.tx, message["id"]):
                    _outbox(
                        work.tx,
                        str(message["account"]),
                        "read",
                        {
                            "message": message["id"],
                            "folder": place["folder"],
                            "uid": place["uid"],
                            "value": command.read,
                        },
                    )
        store.refresh_thread(work.tx, command.id)
        _changed(work, ctx, command.id, "read", command.read)
    _wake()
    return MailDone()


@mail_module.command("mail.markFolderRead")
def mark_folder_read(command: MarkFolderRead, ctx: Context) -> MailDone:
    """Snapshot downloaded conversations in this scope; repeated calls are safe after partial failure."""
    account = accounts.current_account(ctx.config)
    where = [
        "account = ?",
        "unread_count > 0",
        store.IN_LOCATION if command.location else store.FOLDER_FILTERS[command.folder],
    ]
    params: list[object] = [account, account, command.location] if command.location else [account]
    if command.category:
        where.append(store.IN_CATEGORY)
        params.extend([command.category, command.category])
    rows = ctx.bus.db.fetch_all(
        f"SELECT id FROM threads WHERE {' AND '.join(where)} ORDER BY id",  # noqa: S608
        params,
    )
    for row in rows:
        # Use the regular read path: all copies get durable, retried IMAP outbox work.
        set_read(SetThreadRead(id=row["id"], read=True), ctx)
    return MailDone()


@mail_module.command("thread.setFlag")
def set_flag(command: SetThreadFlag, ctx: Context) -> MailDone:
    messages = _thread_messages(ctx, command.id)
    # Flags sit on the newest message, as mail clients show them.
    newest = max(messages, key=lambda m: str(m["date"]))
    targets = messages if not command.flagged else [newest]
    with ctx.bus.unit_of_work() as work:
        for message in targets:
            work.tx.execute(
                "UPDATE messages SET flagged = ? WHERE id = ?",
                (int(command.flagged), message["id"]),
            )
            for place in _on_server(work.tx, message["id"]):
                _outbox(
                    work.tx,
                    str(message["account"]),
                    "flag",
                    {
                        "message": message["id"],
                        "folder": place["folder"],
                        "uid": place["uid"],
                        "value": command.flagged,
                    },
                )
        store.refresh_thread(work.tx, command.id)
        _changed(work, ctx, command.id, "flagged", command.flagged)
    _wake()
    return MailDone()


@mail_module.command("thread.move")
def move_thread(command: MoveThread, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    if command.to not in {"inbox", "archive", "trash"}:
        raise CommandError("thread.invalid_move", "Choose Inbox, Archive or Trash.", 422)
    with ctx.bus.unit_of_work() as work:
        fields = "category,category_source,extra_categories,importance,status,next_action,follow_up_on,followup_notified,why"
        before = tuple(
            work.tx.execute(f"SELECT {fields} FROM threads WHERE id=?", (command.id,)).fetchone()
        )
        messages = work.tx.execute(
            "SELECT * FROM messages WHERE thread_id = ?", (command.id,)
        ).fetchall()
        for message in messages:
            places = store.locations_of(work.tx, message["id"])
            sources = [
                place for place in places if place["role"] in {"inbox", "archive", "trash", "all"}
            ]
            if not sources or (
                command.to != "inbox" and not any(p["role"] == "inbox" for p in sources)
            ):
                continue
            account = message["account"]
            settings = store.sync_settings(ctx.bus.db, account)
            refused = command.to in DELETING_ROLES and (not settings or settings["never_delete"])
            server = [p for p in sources if not p["folder"].startswith(LOCAL_PREFIXES)]
            if server and not refused:
                source = min(server, key=lambda place: store.ROLE_RANK.get(place["role"], 99))
                _outbox(
                    work.tx,
                    account,
                    "move",
                    {
                        "message": message["id"],
                        "folder": source["folder"],
                        "uid": source["uid"],
                        "role": command.to,
                    },
                )
            work.tx.execute(
                "UPDATE messages SET local_role=? WHERE id=?", (command.to, message["id"])
            )
            # Keep a local copy through server failures, restarts, or a refused delete.
            store.add_location(
                work.tx, message["id"], account, f"local:{command.to}", command.to, message["id"]
            )
            for place in sources:
                if (
                    place["folder"].startswith("local:")
                    and place["folder"] != f"local:{command.to}"
                ):
                    store.remove_location(work.tx, account, place["folder"], place["uid"])
        store.refresh_thread(work.tx, command.id)
        after = tuple(
            work.tx.execute(f"SELECT {fields} FROM threads WHERE id=?", (command.id,)).fetchone()
        )
        work.tx.execute(
            "INSERT INTO mail_move_checks(account,thread,target,preserved,time) VALUES(?,?,?,?,?)",
            (
                messages[0]["account"],
                command.id,
                command.to,
                int(before == after),
                datetime.now(UTC).isoformat(),
            ),
        )
        _changed(work, ctx, command.id, "folder", command.to)
    _wake()
    return MailDone()


@mail_module.command("thread.addToFolder")
def add_to_folder(command: ChangeThreadFolder, ctx: Context) -> MailDone:
    """Copies on the server. The next check sees the copy and files it, so this needs no guess."""
    messages = _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        for message in messages:
            places = _on_server(work.tx, message["id"])
            if not places or any(place["folder"] == command.folder for place in places):
                continue
            _outbox(
                work.tx,
                str(message["account"]),
                "copy",
                {
                    "message": message["id"],
                    "folder": places[0]["folder"],
                    "uid": places[0]["uid"],
                    "target": command.folder,
                },
            )
        _changed(work, ctx, command.id, "folder", command.folder)
    _wake()
    return MailDone()


@mail_module.command("thread.removeFromFolder")
def remove_from_folder(command: ChangeThreadFolder, ctx: Context) -> MailDone:
    """Out of this folder and no other. An email can't lose its last folder this way."""
    messages = _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        for message in messages:
            places = store.locations_of(work.tx, int(str(message["id"])))
            here = next((p for p in places if p["folder"] == command.folder), None)
            if here is None or len(places) < MINIMUM_TO_REMOVE:
                continue
            _outbox(
                work.tx,
                str(message["account"]),
                "remove_from",
                {
                    "message": message["id"],
                    "folder": here["folder"],
                    "uid": here["uid"],
                    "role": here["role"],
                },
            )
            store.remove_location(work.tx, str(message["account"]), here["folder"], here["uid"])
        _changed(work, ctx, command.id, "folder", command.folder)
    _wake()
    return MailDone()


@mail_module.command("thread.addCategory")
def add_category(command: ChangeThreadCategory, ctx: Context) -> MailDone:
    """Another category for this conversation. The first one set is still what Priority goes by."""
    rows = ctx.bus.db.fetch_all(
        "SELECT category, extra_categories FROM threads WHERE id = ?", (command.id,)
    )
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    with ctx.bus.unit_of_work() as work:
        if rows[0]["category"] is None:
            work.tx.execute(
                "UPDATE threads SET category = ?, category_source = 'user', why = ? WHERE id = ?",
                (command.name, "You chose this category", command.id),
            )
        elif command.name != rows[0]["category"]:
            extras = {*json.loads(rows[0]["extra_categories"]), command.name}
            work.tx.execute(
                "UPDATE threads SET extra_categories = ?, category_source = 'user' WHERE id = ?",
                (json.dumps(sorted(extras)), command.id),
            )
        _changed(work, ctx, command.id, "category", command.name)
    return MailDone()


@mail_module.command("thread.removeCategory")
def remove_thread_category(command: ChangeThreadCategory, ctx: Context) -> MailDone:
    rows = ctx.bus.db.fetch_all(
        "SELECT category, extra_categories FROM threads WHERE id = ?", (command.id,)
    )
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    extras = [name for name in json.loads(rows[0]["extra_categories"]) if name != command.name]
    main = rows[0]["category"]
    with ctx.bus.unit_of_work() as work:
        # The next one along takes over as the main category.
        if main == command.name:
            main = extras.pop(0) if extras else None
            work.tx.execute(
                "UPDATE threads SET category = ?, category_source = ?, why = ? WHERE id = ?",
                (
                    main,
                    "user",
                    "You chose this category" if main else None,
                    command.id,
                ),
            )
        work.tx.execute(
            "UPDATE threads SET extra_categories = ?, category_source = 'user' WHERE id = ?",
            (json.dumps(extras), command.id),
        )
        _changed(work, ctx, command.id, "category", command.name)
    return MailDone()


@mail_module.command("thread.setStatus")
def set_status(command: SetThreadStatus, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        old = work.tx.execute("SELECT status FROM threads WHERE id=?", (command.id,)).fetchone()[0]
        work.tx.execute(
            "UPDATE threads SET status = ?, next_action = CASE WHEN ?='waiting_on_you' THEN next_action ELSE NULL END, follow_up_on = CASE WHEN ?='waiting_on_others' THEN follow_up_on ELSE NULL END WHERE id = ?",
            (command.status, command.status, command.status, command.id),
        )
        if ctx.actor == "person":
            work.tx.execute(
                "UPDATE threads SET status_user_message=(SELECT MAX(id) FROM messages WHERE thread_id=?) WHERE id=?",
                (command.id, command.id),
            )
        _changed(work, ctx, command.id, "status", command.status, old)
    return MailDone()


@mail_module.command("thread.setImportance")
def set_importance(command: SetThreadImportance, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        old = work.tx.execute(
            "SELECT importance FROM threads WHERE id=?", (command.id,)
        ).fetchone()[0]
        work.tx.execute(
            "UPDATE threads SET importance = ? WHERE id = ?", (command.importance, command.id)
        )
        if ctx.actor == "person":
            work.tx.execute(
                "UPDATE threads SET importance_user_message=(SELECT MAX(id) FROM messages WHERE thread_id=?) WHERE id=?",
                (command.id, command.id),
            )
        _changed(work, ctx, command.id, "importance", command.importance, old)
    return MailDone()


@mail_module.command("thread.setCategory")
def set_category(command: SetThreadCategory, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        old = work.tx.execute("SELECT category FROM threads WHERE id=?", (command.id,)).fetchone()[
            0
        ]
        source = "user"
        why = "You chose this category" if command.category else None
        work.tx.execute(
            "UPDATE threads SET category = ?, category_source = ?, why = ? WHERE id = ?",
            (command.category, source, why, command.id),
        )
        _changed(work, ctx, command.id, "category", command.category, old)
    return MailDone()


# Rules


def upsert_rule(ctx: Context, rule: MailRule) -> None:
    def changed(existing: list[MailRule]) -> list[MailRule]:
        return [*(item for item in existing if item.name != rule.name), rule]

    rules.change_rules(ctx.config.home, changed)
    with ctx.bus.unit_of_work() as work:
        work.emit("rules.changed", {"count": 1}, source="mail", trace_id=ctx.trace_id)


def delete_rules(ctx: Context, names: list[str]) -> None:
    rules.change_rules(
        ctx.config.home, lambda existing: [rule for rule in existing if rule.name not in names]
    )
    with ctx.bus.unit_of_work() as work:
        work.emit("rules.changed", {"count": len(names)}, source="mail", trace_id=ctx.trace_id)


@mail_module.query("rules.get")
def get_rules(query: GetRules, ctx: Context) -> RuleSet:
    return RuleSet(rules=rules.load_rules(ctx.config.home))


@mail_module.command("rules.save")
def save_rules(command: RuleSet, ctx: Context) -> RuleSet:
    rules.save_rules(ctx.config.home, command)
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "rules.changed", {"count": len(command.rules)}, source="mail", trace_id=ctx.trace_id
        )
    return command


# Categories

MEANING_CANDIDATES = 200
CATEGORY_RULE_PREFIX = "Category: "
# What each Home last announced, so a count that didn't change doesn't send an event.
_last_categories: dict[str, list[dict[str, Any]]] = {}
SUGGESTED, DECLINED = 1, 2
PRIORITY_SUGGESTED, PRIORITY_DECLINED = 1, 2
UNORDERED = 1_000_000


def _rename_extras(tx: Any, names: set[str], into: str | None) -> None:
    """The same change for conversations that have this as one of several categories."""
    for row in tx.execute(
        "SELECT id, category, extra_categories FROM threads WHERE extra_categories != '[]'"
    ).fetchall():
        current = json.loads(row["extra_categories"])
        if not names & set(current):
            continue
        replaced = {into if name in names else name for name in current} - {None, row["category"]}
        tx.execute(
            "UPDATE threads SET extra_categories = ? WHERE id = ?",
            (json.dumps(sorted(replaced)), row["id"]),
        )


def category_rows(ctx: Context) -> list[MailCategory]:
    db = ctx.bus.db
    account = accounts.current_account(ctx.config)
    counts = {
        row["name"]: (row["n"], row["unread"])
        for row in db.fetch_all(
            "SELECT name, COUNT(*) AS n, SUM(unread_count > 0) AS unread FROM ("
            " SELECT category AS name, id AS thread, unread_count FROM threads WHERE account = ?"
            " AND category IS NOT NULL AND (in_inbox = 1 OR in_archive = 1)"
            " UNION SELECT e.value, t.id, t.unread_count FROM threads t, json_each(t.extra_categories) e"
            " WHERE t.account = ? AND t.extra_categories != '[]' AND (t.in_inbox = 1 OR t.in_archive = 1)"
            ") GROUP BY name",
            (account, account),
        )
    }
    found = []
    named = set()
    positions: dict[str, int] = {}
    # Only worked out for what's being suggested, since this list is read all the time.
    needed = {
        row["name"]: row["n"]
        for row in db.fetch_all(
            "SELECT category AS name, COUNT(*) AS n FROM threads WHERE account = ?"
            " AND (importance = 'high' OR status = 'waiting_on_you') AND category IN"
            " (SELECT name FROM mail_categories WHERE priority_suggested = 1) GROUP BY category",
            (account,),
        )
    }
    votes = {
        row["name"]: row["n"]
        for row in db.fetch_all("SELECT name, COUNT(*) AS n FROM mail_category_votes GROUP BY name")
    }
    for row in db.fetch_all("SELECT * FROM mail_categories ORDER BY name"):
        named.add(row["name"])
        # One the person turned down stays recorded, so it isn't suggested again.
        if row["proposed"] == DECLINED:
            continue
        # One email isn't a pattern, so a suggestion waits until enough mail would go in it.
        if (
            row["proposed"] == SUGGESTED
            and row["needs_votes"]
            and votes.get(row["name"], 0) < ctx.config.agent.category_suggestion_min_threads
        ):
            continue
        count, unread = counts.get(row["name"], (0, 0))
        found.append(
            MailCategory(
                name=row["name"],
                mode=row["mode"],
                description=row["description"],
                source=row["source"],
                in_priority=bool(row["in_priority"]),
                proposed=row["proposed"] == SUGGESTED,
                priority_suggested=row["priority_suggested"] == PRIORITY_SUGGESTED
                and not row["in_priority"],
                priority_why=row["priority_why"],
                needed_you=needed.get(row["name"], 0),
                why=row["why"],
                sender=row["sender"],
                subject=row["subject"],
                count=count,
                unread=unread or 0,
                created=row["created"],
                updated=row["updated"] or row["created"],
            )
        )
        positions[row["name"]] = row["position"]
    # Rules can name a category nobody created, like Newsletters.
    for name, (count, unread) in sorted(counts.items()):
        if name not in named:
            found.append(
                MailCategory(
                    name=name,
                    source="rule",
                    in_priority=False,
                    proposed=False,
                    count=count,
                    unread=unread or 0,
                )
            )
    # Those the person put in order come first, and new ones follow by name.
    return sorted(
        found,
        key=lambda category: (
            positions.get(category.name) or UNORDERED,
            category.name.casefold(),
        ),
    )


def _apply_category_rule(
    ctx: Context, name: str, sender: str | None, subject: str | None, *, refile: bool = True
) -> int:
    """Mail from now on follows the rule, and what's already here is filed too."""
    conditions = []
    if sender:
        conditions.append(RuleCondition(field="sender_exact", value=sender))
    if subject:
        conditions.append(RuleCondition(field="subject_prefix", value=subject))
    rule_name = CATEGORY_RULE_PREFIX + name

    def changed(existing: list[MailRule]) -> list[MailRule]:
        kept = [
            rule
            for rule in existing
            if rule.name != rule_name
            and not (rule.name.startswith(rule_name + ": ") and not conditions)
        ]
        if conditions:
            kept.append(
                MailRule(
                    name=rule_name,
                    conditions=conditions,
                    actions=RuleActions(category=name, skip_agent=True),
                )
            )
        return kept

    rules.change_rules(ctx.config.home, changed)
    if not conditions or not refile:
        return 0
    current_rules = ordered_rules(ctx)
    active = accounts.current_account(ctx.config)
    _, profiles = accounts.read_accounts(ctx.config)
    profile = profiles.get(active)
    domain = own_domain_of(profile.address or profile.auth.user) if profile else None
    changed_threads: set[int] = set()
    # Latest-message provenance and primary/extra filing are determined together.
    with ctx.bus.db.transaction() as tx:
        rows = tx.execute(
            "SELECT m.id,m.thread_id FROM messages m WHERE m.account=? AND m.id=(SELECT id FROM messages WHERE thread_id=m.thread_id ORDER BY date DESC,id DESC LIMIT 1)",
            (active,),
        ).fetchall()
        for row in rows:
            raw = store.raw_of(ctx.bus.db, row["id"])
            if raw is None:
                continue
            match = rules.evaluate(parse_message(raw), current_rules, domain, folder_modes(ctx))
            if not match or not match.actions.category:
                continue
            if name not in {match.actions.category, *match.extra_categories}:
                continue
            tx.execute(
                "UPDATE messages SET rule=?,why=? WHERE id=?", (match.name, match.why, row["id"])
            )
            tx.execute(
                "UPDATE threads SET latest_rule=? WHERE id=?", (match.name, row["thread_id"])
            )
            current = tx.execute(
                "SELECT category_source,extra_categories FROM threads WHERE id=?",
                (row["thread_id"],),
            ).fetchone()
            if current and current["category_source"] != "user":
                extras = list(
                    dict.fromkeys(
                        [*json.loads(current["extra_categories"]), *match.extra_categories]
                    )
                )
                tx.execute(
                    "UPDATE threads SET category=?,category_source='rule',why=?,extra_categories=? WHERE id=?",
                    (
                        match.actions.category,
                        match.why,
                        json.dumps([extra for extra in extras if extra != match.actions.category]),
                        row["thread_id"],
                    ),
                )
                changed_threads.add(row["thread_id"])
    return len(changed_threads)


SUBJECT_REPLY_PREFIXES = ("",)


def _add_starter_categories(ctx: Context) -> None:
    """Once for each Home, with what's already here filed too. An empty one stays out of the sidebar."""
    db = ctx.bus.db
    if not ctx.config.mail.starter_categories or db.fetch_all(
        "SELECT 1 FROM mail_starter_categories LIMIT 1"
    ):
        return
    for starter in ctx.config.mail.starter_categories:
        name, prefix = starter["name"], starter["subject_prefix"]
        rule_name = CATEGORY_RULE_PREFIX + name

        def changed(
            existing: list[MailRule],
            rule_name: str = rule_name,
            name: str = name,
            prefix: str = prefix,
        ) -> list[MailRule]:
            if any(rule.name == rule_name for rule in existing):
                return existing
            condition = RuleCondition(field="subject_prefix", value=prefix)
            return [
                *existing,
                MailRule(
                    name=rule_name,
                    conditions=[condition],
                    actions=RuleActions(category=name, skip_agent=True, read_replies=False),
                ),
            ]

        rules.change_rules(ctx.config.home, changed)
        patterns = [f"{reply}{prefix}%" for reply in SUBJECT_REPLY_PREFIXES]
        marks = " OR ".join("m.subject LIKE ?" for _ in patterns)
        with db.transaction() as tx:
            tx.execute(
                # Automated mail, kept to itself, so it's never suggested for the Priority inbox.
                "INSERT OR IGNORE INTO mail_categories (name, source, priority_suggested, created)"
                " VALUES (?, 'rule', ?, ?)",
                (name, PRIORITY_DECLINED, datetime.now(UTC).isoformat()),
            )
            tx.execute(
                "UPDATE threads AS t SET category = ?, category_source = 'rule', why = ? WHERE"  # noqa: S608
                " COALESCE(t.category_source, '') != 'user' AND EXISTS"
                f" (SELECT 1 FROM messages m WHERE m.thread_id = t.id AND ({marks}))",
                (name, f"Matched the category “{name}”", *patterns),
            )
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_starter_categories (added) VALUES (?)",
            (datetime.now(UTC).isoformat(),),
        )
    _categories_changed(ctx)


def _organization_defaults(ctx: Context) -> None:
    """Idempotent upgrades for existing Homes; never reinstate a folder the person removed."""
    marker = "mail_organization_defaults_001"
    if ctx.bus.db.fetch_all("SELECT 1 FROM migrations WHERE id = ?", (marker,)):
        return
    defaults = {
        "Updates": "exact",
        "Promotions": "exact",
        "Forums": "exact",
        "Social": "exact",
        "Broadcast": "smart",
    }
    with ctx.bus.db.transaction() as tx:
        for name, mode in defaults.items():
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, mode, description, created) VALUES (?, 'rule', ?, ?, ?)",
                (
                    name,
                    mode,
                    "Mail to many people that no Exact rule caught" if mode == "smart" else name,
                    datetime.now(UTC).isoformat(),
                ),
            )
        tx.execute(
            "UPDATE mail_categories SET mode = 'exact' WHERE name IN (SELECT name FROM mail_categories WHERE source = 'rule' AND name != 'Broadcast')"
        )

    existing_rules = rules.load_rules(ctx.config.home)
    with ctx.bus.db.transaction() as tx:
        for rule in existing_rules:
            if not rule.actions.category:
                continue
            sender = next(
                (
                    condition.value
                    for condition in rule.conditions
                    if condition.field in {"sender", "sender_exact"}
                ),
                None,
            )
            subject = next(
                (
                    condition.value
                    for condition in rule.conditions
                    if condition.field in {"subject", "subject_prefix"}
                ),
                None,
            )
            if not (sender or subject):
                continue
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories(name,source,mode,description,sender,subject,created) VALUES(?,'rule','exact','',?,?,?)",
                (rule.actions.category, sender, subject, datetime.now(UTC).isoformat()),
            )
            tx.execute(
                "UPDATE mail_categories SET mode='exact',sender=COALESCE(sender,?),subject=COALESCE(subject,?) WHERE name=?",
                (sender, subject, rule.actions.category),
            )

    def upgraded(existing: list[MailRule]) -> list[MailRule]:
        starters = {item["name"] for item in ctx.config.mail.starter_categories}
        result = []
        for rule in existing:
            if rule.actions.category in starters and rule.name == CATEGORY_RULE_PREFIX + str(
                rule.actions.category
            ):
                rule = rule.model_copy(
                    update={
                        "actions": rule.actions.model_copy(
                            update={"read_replies": False, "skip_agent": True}
                        )
                    }
                )
            result.append(rule)
        return result

    rules.change_rules(ctx.config.home, upgraded)
    with ctx.bus.db.transaction() as tx:
        tx.execute("INSERT INTO migrations (id) VALUES (?)", (marker,))


def _organization_provenance(ctx: Context) -> None:
    marker = "mail_organization_provenance_001"
    if ctx.bus.db.fetch_all("SELECT 1 FROM migrations WHERE id=?", (marker,)):
        return
    try:
        last = 0
        home_rules = ordered_rules(ctx)
        _, profiles = accounts.read_accounts(ctx.config)
        while not _closing.is_set():
            rows = ctx.bus.db.fetch_all(
                "SELECT id,thread_id,account FROM messages WHERE id>? ORDER BY id LIMIT ?",
                (last, KINDS_BATCH),
            )
            if not rows:
                with ctx.bus.db.transaction() as tx:
                    tx.execute("INSERT OR IGNORE INTO migrations(id) VALUES(?)", (marker,))
                if last:
                    _categories_changed(ctx)
                return
            with ctx.bus.db.transaction() as tx:
                for row in rows:
                    raw = store.raw_of(ctx.bus.db, row["id"])
                    if raw is None:
                        continue
                    profile = profiles.get(row["account"])
                    domain = (
                        own_domain_of(profile.address or profile.auth.user) if profile else None
                    )
                    match = rules.evaluate(
                        parse_message(raw), home_rules, domain, folder_modes(ctx)
                    )
                    tx.execute(
                        "UPDATE messages SET rule=? WHERE id=?",
                        (match.name if match else None, row["id"]),
                    )
                    store.refresh_thread(tx, row["thread_id"])
            last = rows[-1]["id"]
    except Exception:
        log.exception("mail_organization_provenance_failed")


def folder_modes(ctx: Context) -> dict[str, str]:
    return {
        row["name"]: row["mode"]
        for row in ctx.bus.db.fetch_all("SELECT name,mode FROM mail_categories WHERE proposed=0")
    }


def ordered_rules(ctx: Context) -> list[MailRule]:
    existing = rules.load_rules(ctx.config.home)
    folders = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE proposed=0")
    generated = {
        CATEGORY_RULE_PREFIX + row["name"] for row in folders if row["sender"] or row["subject"]
    }
    kept = [rule for rule in existing if rule.name not in generated]
    for folder in folders:
        conditions = []
        if folder["mode"] != "exact":
            continue
        rule_name = CATEGORY_RULE_PREFIX + folder["name"]
        canonical = next((rule for rule in existing if rule.name == rule_name), None)
        related = [rule for rule in existing if rule.actions.category == folder["name"]]
        # Arbitrary personal rules can include body/header conditions that folder settings
        # cannot represent. Never broaden those rules into a sender-only match.
        if canonical is None and related:
            continue
        if canonical and (
            any(
                condition.field not in {"sender", "sender_exact", "subject", "subject_prefix"}
                for condition in canonical.conditions
            )
            or sum(
                condition.field in {"sender", "sender_exact"} for condition in canonical.conditions
            )
            > 1
            or sum(
                condition.field in {"subject", "subject_prefix"}
                for condition in canonical.conditions
            )
            > 1
        ):
            kept.append(canonical)
            continue
        if folder["sender"]:
            conditions.append(RuleCondition(field="sender_exact", value=folder["sender"]))
        if folder["subject"]:
            conditions.append(RuleCondition(field="subject_prefix", value=folder["subject"]))
        if conditions:
            kept.append(
                MailRule(
                    name=rule_name,
                    enabled=canonical.enabled if canonical else True,
                    conditions=conditions,
                    actions=canonical.actions.model_copy(
                        update={
                            "category": folder["name"],
                            "skip_agent": True,
                            "read_replies": False,
                        }
                    )
                    if canonical
                    else RuleActions(category=folder["name"], skip_agent=True),
                )
            )
    return rules.for_folders(
        kept,
        folders,
        {item["name"] for item in ctx.config.mail.starter_categories},
    )


def sender_rule_name(category: str, sender: str) -> str:
    suffix = hashlib.sha256(sender.casefold().encode()).hexdigest()[:12]
    return f"Category: {category}: {suffix}"


def file_by_sender(ctx: Context, name: str, sender: str) -> int:
    """What's already here from this sender, without touching what the person filed themselves."""
    with ctx.bus.db.transaction() as tx:
        cursor = tx.execute(
            "UPDATE threads AS t SET category = ?, category_source = 'rule', why = ? WHERE"
            " COALESCE(t.category_source, '') != 'user' AND EXISTS"
            " (SELECT 1 FROM messages m WHERE t.id = m.thread_id AND LOWER(m.from_addr) = ?)",
            (name, f"Matched the category “{name}”", sender),
        )
        return int(cursor.rowcount)


def _categories_changed(ctx: Context) -> None:
    with ctx.bus.unit_of_work() as work:
        _announce_categories(work, ctx)
        work.emit(
            "mail.changed",
            {"threads": 0, "reason": "categories"},
            source="mail",
            trace_id=ctx.trace_id,
        )


def _announce_categories(work: Any, ctx: Context) -> None:
    """The event carries the new list and counts, so every screen is right without asking."""
    current = [row.model_dump(mode="json") for row in category_rows(ctx)]
    _last_categories[str(ctx.config.home)] = current
    work.emit("categories.changed", {"categories": current}, source="mail", trace_id=ctx.trace_id)


@mail_module.on("thread.updated", "mail.category_counts_thread")
@mail_module.on("mail.changed", "mail.category_counts_mail")
@mail_module.on("mail.accountsChanged", "mail.category_counts_account")
def recount_categories(event: AppEvent, ctx: Context) -> None:
    """Anything that moves mail can change a count. Nothing goes out if none did."""
    if _last_categories.get(str(ctx.config.home)) == [
        row.model_dump(mode="json") for row in category_rows(ctx)
    ]:
        return
    with ctx.bus.unit_of_work() as work:
        _announce_categories(work, ctx)


@mail_module.query("categories.list")
def list_categories(query: ListCategories, ctx: Context) -> CategoryList:
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.save")
def save_category(command: SaveCategory, ctx: Context) -> CategorySaved:
    if command.mode == "exact" and not (command.sender or command.subject):
        raise CommandError(
            "category.rule_required", "An Exact folder needs a sender or subject prefix.", 422
        )
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_categories (name, source, in_priority, proposed, sender, subject, created)"
            " VALUES (?, ?, ?, 0, ?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
            " in_priority = excluded.in_priority, proposed = 0, sender = excluded.sender,"
            " subject = excluded.subject",
            (
                command.name,
                command.source,
                int(command.in_priority),
                command.sender,
                command.subject,
                datetime.now(UTC).isoformat(),
            ),
        )
    mode = command.mode or ("exact" if command.sender or command.subject else "smart")
    if mode == "exact" and not (command.sender or command.subject):
        raise CommandError(
            "category.rule_required", "An Exact folder needs a sender or subject prefix.", 422
        )
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE mail_categories SET mode = ?, description = ? WHERE name = ?",
            (mode, command.description.strip() or command.name, command.name),
        )
    filed = _apply_category_rule(
        ctx,
        command.name,
        command.sender if mode == "exact" else None,
        command.subject if mode == "exact" else None,
    )
    _categories_changed(ctx)
    return CategorySaved(categories=category_rows(ctx), filed=filed)


@mail_module.command("categories.update")
def update_category(command: UpdateCategory, ctx: Context) -> CategoryList:
    db = ctx.bus.db
    rows = db.fetch_all("SELECT * FROM mail_categories WHERE name = ?", (command.name,))
    row = rows[0] if rows else None
    in_use = db.fetch_all("SELECT 1 FROM threads WHERE category = ? LIMIT 1", (command.name,))
    if row is None and not in_use:
        raise CommandError("category.not_found", "That category no longer exists.", 404)
    new_name = command.new_name or command.name
    if new_name != command.name:
        taken = db.fetch_all("SELECT 1 FROM mail_categories WHERE name = ?", (new_name,))
        if taken:
            raise CommandError(
                "category.exists", f"There's already a category called {new_name}.", 409
            )
    sender = (
        None
        if command.clear_rule
        else (command.sender or None)
        if "sender" in command.model_fields_set
        else (row["sender"] if row else None)
    )
    subject = (
        None
        if command.clear_rule
        else (command.subject or None)
        if "subject" in command.model_fields_set
        else (row["subject"] if row else None)
    )
    in_priority = (
        command.in_priority if command.in_priority is not None else bool(row and row["in_priority"])
    )
    mode = command.mode or (
        "smart"
        if command.clear_rule
        else "exact"
        if command.sender or command.subject
        else row["mode"]
        if row
        else "smart"
    )
    description = (
        command.description
        if command.description is not None
        else (row["description"] if row else new_name)
    )
    if (
        mode == "exact"
        and not (sender or subject)
        and command.name not in {"Updates", "Promotions", "Forums", "Social"}
    ):
        top = db.fetch_all(
            "SELECT m.from_addr FROM messages m JOIN threads t ON t.id=m.thread_id WHERE t.account=? AND (t.category=? OR EXISTS(SELECT 1 FROM json_each(t.extra_categories) WHERE value=?)) GROUP BY LOWER(m.from_addr) ORDER BY COUNT(*) DESC LIMIT 1",
            (accounts.current_account(ctx.config), command.name, command.name),
        )
        sender = top[0]["from_addr"] if top else None
        if not sender:
            raise CommandError(
                "category.rule_required", "An Exact folder needs a sender or subject prefix.", 422
            )
    if mode == "smart" and row and row["mode"] == "exact" and command.description is None:
        top = db.fetch_all(
            "SELECT m.from_addr FROM messages m JOIN threads t ON t.id=m.thread_id WHERE t.account=? AND (t.category=? OR EXISTS(SELECT 1 FROM json_each(t.extra_categories) WHERE value=?)) GROUP BY LOWER(m.from_addr) ORDER BY COUNT(*) DESC LIMIT 3",
            (accounts.current_account(ctx.config), command.name, command.name),
        )
        description = f"{new_name}: {sender or subject or new_name}" + (
            ". Common senders: " + ", ".join(item["from_addr"] for item in top) if top else ""
        )
        description = description[:500]
    now = datetime.now(UTC).isoformat()
    with db.transaction() as tx:
        if row is None:
            tx.execute(
                "INSERT INTO mail_categories (name, source, created) VALUES (?, 'user', ?)",
                (command.name, now),
            )
        tx.execute(
            "UPDATE mail_categories SET name = ?, in_priority = ?, sender = ?, subject = ?,"
            " proposed = 0, updated = ?, mode = ?, description = ? WHERE name = ?",
            (new_name, int(in_priority), sender, subject, now, mode, description, command.name),
        )
        tx.execute("UPDATE threads SET category = ? WHERE category = ?", (new_name, command.name))
        _rename_extras(tx, {command.name}, new_name)
    if new_name != command.name:
        # Rules the person wrote themselves may file into it too.
        def renamed(existing: list[MailRule]) -> list[MailRule]:
            return [
                rule.model_copy(
                    update={
                        "actions": rule.actions.model_copy(update={"category": new_name}),
                    }
                )
                if rule.actions.category == command.name
                else rule
                for rule in existing
                if rule.name != CATEGORY_RULE_PREFIX + command.name
            ]

        rules.change_rules(ctx.config.home, renamed)
    _apply_category_rule(
        ctx,
        new_name,
        sender if mode == "exact" else None,
        subject if mode == "exact" else None,
        refile=False,
    )
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.merge")
def merge_categories(command: MergeCategories, ctx: Context) -> CategoryList:
    db = ctx.bus.db
    now = datetime.now(UTC).isoformat()
    others = [name for name in command.names if name != command.into]
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO mail_categories (name, source, description, in_priority, created) VALUES (?, 'user', ?, 1, ?)",
            (command.into, command.into, now),
        )
        for name in others:
            tx.execute("UPDATE threads SET category = ? WHERE category = ?", (command.into, name))
            _rename_extras(tx, {name}, command.into)
            tx.execute("DELETE FROM mail_categories WHERE name = ?", (name,))

    def renamed(existing: list[MailRule]) -> list[MailRule]:
        return [
            rule.model_copy(
                update={"actions": rule.actions.model_copy(update={"category": command.into})}
            )
            if rule.actions.category in others
            else rule
            for rule in existing
        ]

    rules.change_rules(ctx.config.home, renamed)
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.reorder")
def reorder_categories(command: ReorderCategories, ctx: Context) -> CategoryList:
    with ctx.bus.db.transaction() as tx:
        for position, name in enumerate(command.names, start=1):
            tx.execute("UPDATE mail_categories SET position = ? WHERE name = ?", (position, name))
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.remove")
def remove_category(command: CategoryName, ctx: Context) -> CategoryList:
    """Its mail stays where it is, only without this label."""
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM mail_categories WHERE name = ?", (command.name,))
        tx.execute(
            "UPDATE threads SET category = NULL, category_source = NULL WHERE category = ?",
            (command.name,),
        )
        _rename_extras(tx, {command.name}, None)
    _apply_category_rule(ctx, command.name, None, None)
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.decide")
def decide_category(command: DecideCategory, ctx: Context) -> CategoryList:
    """An agent's suggestion. Saying no keeps the row, so it won't be suggested again."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name = ?", (command.name,))
    if not rows:
        raise CommandError("category.not_found", "That category no longer exists.", 404)
    row = rows[0]
    if command.accept:
        if row["mode"] == "exact" and not (row["sender"] or row["subject"]):
            senders = ctx.bus.db.fetch_all(
                "SELECT DISTINCT sender FROM mail_learning_groups WHERE folder=?", (command.name,)
            )
            if not senders:
                raise CommandError(
                    "category.rule_required",
                    "Add a sender or prefix before accepting this Exact folder.",
                    422,
                )
            with ctx.bus.db.transaction() as tx:
                tx.execute(
                    "UPDATE mail_categories SET sender=? WHERE name=?",
                    (senders[0]["sender"], command.name),
                )
            row = ctx.bus.db.fetch_all(
                "SELECT * FROM mail_categories WHERE name=?", (command.name,)
            )[0]
        save_category(
            SaveCategory(
                name=row["name"],
                in_priority=bool(row["in_priority"]),
                sender=row["sender"],
                subject=row["subject"],
                source="agent",
                mode=row["mode"],
                description=row["description"],
            ),
            ctx,
        )
        if row["mode"] == "exact":
            senders = ctx.bus.db.fetch_all(
                "SELECT DISTINCT sender FROM mail_learning_groups WHERE folder=?", (command.name,)
            )

            def add_group_rules(existing: list[MailRule]) -> list[MailRule]:
                names = {rule.name for rule in existing}
                for sender in senders:
                    rule_name = sender_rule_name(command.name, sender["sender"])
                    if rule_name not in names:
                        existing.append(
                            MailRule(
                                name=rule_name,
                                conditions=[
                                    RuleCondition(field="sender_exact", value=sender["sender"])
                                ],
                                actions=RuleActions(category=command.name, skip_agent=True),
                            )
                        )
                return existing

            rules.change_rules(ctx.config.home, add_group_rules)
        # The agent already read this mail when it suggested the name, so nothing is read again.
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE threads SET category = ?, category_source = 'agent' WHERE id IN"
                " (SELECT thread FROM mail_category_votes WHERE name = ?)"
                " AND COALESCE(category_source, '') NOT IN ('user', 'rule')",
                (row["name"], row["name"]),
            )
        group_reviews = ctx.bus.db.fetch_all(
            "SELECT 1 FROM mail_learning_reviews WHERE state IN ('learning','asking') LIMIT 1"
        )
        if not group_reviews:
            from nexusai.modules.agent import bulk_learning

            bulk_learning.finalize(ctx)
        _categories_changed(ctx)
    else:
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_categories SET proposed = ? WHERE name = ?", (DECLINED, command.name)
            )
        _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.decidePriority")
def decide_priority(command: DecidePriority, ctx: Context) -> CategoryList:
    """Saying no is remembered, so it isn't suggested again. Right-click can still add it."""
    with ctx.bus.db.transaction() as tx:
        cursor = tx.execute(
            "UPDATE mail_categories SET priority_suggested = ?, in_priority = in_priority OR ?"
            " WHERE name = ? AND priority_suggested = ?",
            (PRIORITY_DECLINED, int(command.accept), command.name, PRIORITY_SUGGESTED),
        )
    if not cursor.rowcount:
        raise CommandError("category.not_found", "That suggestion has already been handled.", 409)
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


def suggest_priority(ctx: Context, name: str, reason: str) -> str:
    """Only for a category with mail in it, that's not there yet and hasn't been turned down."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name = ?", (name,))
    if not rows or rows[0]["proposed"]:
        return f"There's no category called {name}."
    if rows[0]["in_priority"]:
        return f"{name} is in the Priority inbox already."
    if rows[0]["priority_suggested"]:
        return f"{name} has been suggested already, or they said no."
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE mail_categories SET priority_suggested = ?, priority_why = ? WHERE name = ?",
            (PRIORITY_SUGGESTED, reason[:500], name),
        )
    _categories_changed(ctx)
    return f"Suggested {name} for the Priority inbox. The person decides."


# Writing


def _load_drafts(ctx: Context) -> list[Draft]:
    rows = ctx.bus.db.fetch_all("SELECT id, body FROM mail_drafts ORDER BY updated DESC")
    return [Draft.model_validate({**json.loads(row["body"]), "id": row["id"]}) for row in rows]


def _sender_name(ctx: Context) -> str:
    rows = ctx.bus.db.fetch_all("SELECT value FROM profile")
    return str(json.loads(rows[0]["value"]).get("name", "")) if rows else ""


def _threading_headers(ctx: Context, draft: Draft) -> tuple[str | None, list[str]]:
    if draft.reply_to_message_id is None:
        return None, []
    rows = ctx.bus.db.fetch_all(
        "SELECT message_id FROM messages WHERE id = ?", (draft.reply_to_message_id,)
    )
    if not rows:
        return None, []
    refs = ctx.bus.db.fetch_all(
        "SELECT ref FROM message_refs WHERE message = ?", (draft.reply_to_message_id,)
    )
    return rows[0]["message_id"], [row["ref"] for row in refs]


@mail_module.query("drafts.list")
def list_drafts(query: ListDrafts, ctx: Context) -> DraftList:
    return DraftList(drafts=_load_drafts(ctx))


@mail_module.command("drafts.save")
def save_draft(command: Draft, ctx: Context) -> Draft:
    active, profile, _ = _active_profile(ctx)
    now = datetime.now(UTC).isoformat()
    body = command.model_dump_json(exclude={"id"})
    with ctx.bus.unit_of_work() as work:
        if command.id is None:
            cursor = work.tx.execute(
                "INSERT INTO mail_drafts (body, updated) VALUES (?, ?)", (body, now)
            )
            saved = command.model_copy(update={"id": cursor.lastrowid})
        else:
            work.tx.execute(
                "UPDATE mail_drafts SET body = ?, updated = ? WHERE id = ?", (body, now, command.id)
            )
            saved = command
        marker = str(saved.id)
        in_reply_to, references = _threading_headers(ctx, saved)
        raw = send.build_message(
            saved, profile, _sender_name(ctx), in_reply_to, references, draft_marker=marker
        ).as_bytes()
        # The server keeps one copy of each draft: the old one goes before the new one lands. With
        # deleting refused, old copies would pile up there, so drafts stay on this computer.
        settings = store.sync_settings(ctx.bus.db, active)
        if settings and not settings["never_delete"]:
            _outbox(work.tx, active, "delete_drafts", {"draft": marker})
            _outbox(work.tx, active, "append", {"role": "drafts", "raw": raw.hex()})
        work.emit("drafts.changed", {"id": saved.id}, source="mail", trace_id=ctx.trace_id)
    _wake()
    return saved


@mail_module.command("drafts.remove")
def remove_draft(command: RemoveDraft, ctx: Context) -> MailDone:
    active = _account(ctx)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM mail_drafts WHERE id = ?", (command.id,))
        _outbox(work.tx, active, "delete_drafts", {"draft": str(command.id)})
        work.emit("drafts.changed", {"id": command.id}, source="mail", trace_id=ctx.trace_id)
    _wake()
    return MailDone()


@mail_module.query("mail.replyDraft")
def reply_draft(query: ReplyContext, ctx: Context) -> ReplyDraft:
    _, profile, _ = _active_profile(ctx)
    rows = ctx.bus.db.fetch_all("SELECT * FROM messages WHERE id = ?", (query.message_id,))
    if not rows:
        raise CommandError("thread.not_found", "That message no longer exists.", 404)
    message = rows[0]
    me = (profile.address or profile.auth.user).lower()
    sender = message["from_addr"]
    to_people = json.loads(message["to_json"])
    cc_people = json.loads(message["cc_json"])
    if sender == me:
        # Replying to your own message goes to the people you wrote to.
        primary, rest = to_people[:1], to_people[1:] + cc_people
    else:
        primary, rest = [sender], to_people + cc_people
    others = [
        address for address in dict.fromkeys(rest) if address != me and address not in primary
    ]
    cc = others if query.reply_all else []
    subject = message["subject"]
    already_prefixed = normalize_subject(subject) != subject.strip().lower()
    prefixed = subject if already_prefixed or not subject else f"Re: {subject}"
    thread = ctx.bus.db.fetch_all(
        "SELECT participants FROM threads WHERE id = ?", (message["thread_id"],)
    )
    included = {*primary, *cc, me}
    dropped = (
        [p for p in json.loads(thread[0]["participants"]) if p not in included] if thread else []
    )
    return ReplyDraft(
        draft=Draft(
            thread_id=message["thread_id"],
            reply_to_message_id=message["id"],
            to=[Recipient(address=parseaddr(a)[1] or a) for a in primary],
            cc=[Recipient(address=a) for a in cc],
            subject=prefixed,
        ),
        dropped=dropped,
    )


def _send_checks(ctx: Context) -> SendCheckSettings:
    rows = ctx.bus.db.fetch_all("SELECT value FROM settings WHERE key = 'send_checks'")
    return SendCheckSettings.model_validate_json(rows[0]["value"]) if rows else SendCheckSettings()


@mail_module.query("sendChecks.get")
def get_send_checks(query: GetSendChecks, ctx: Context) -> SendCheckSettings:
    return _send_checks(ctx)


@mail_module.command("sendChecks.save")
def save_send_checks(command: SendCheckSettings, ctx: Context) -> SendCheckSettings:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO settings (key, value) VALUES ('send_checks', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (command.model_dump_json(),),
        )
    return command


def _problems(
    ctx: Context, draft: Draft, written_after: str | None, settings: SendCheckSettings
) -> list[SendProblem]:
    found: list[SendProblem] = []

    def add(check: str, level: str, message: str) -> None:
        if level != "off":
            found.append(SendProblem(check=check, level=level, message=message))

    active, profiles = accounts.read_accounts(ctx.config)
    own = (profiles[active].address or profiles[active].auth.user) if active else ""
    domain = own.rsplit("@", 1)[-1].lower() if "@" in own else ""
    recipients = [r.address.lower() for r in [*draft.to, *draft.cc, *draft.bcc]]
    if draft.thread_id is not None and domain:
        rows = ctx.bus.db.fetch_all(
            "SELECT participants FROM threads WHERE id = ?", (draft.thread_id,)
        )
        people = json.loads(rows[0]["participants"]) if rows else []
        internal = bool(people) and all(p.rsplit("@", 1)[-1] == domain for p in people)
        outside = [a for a in recipients if a.rsplit("@", 1)[-1] != domain]
        if internal and outside:
            add(
                "external_recipient",
                settings.external_recipient,
                f"This internal conversation would go outside: {', '.join(outside)}.",
            )
    if ATTACHED_WORDS.search(draft.body):
        add(
            "missing_attachment",
            settings.missing_attachment,
            "It mentions an attachment, but nothing is attached.",
        )
    if draft.thread_id is not None and written_after:
        newer = ctx.bus.db.fetch_all(
            "SELECT 1 FROM messages WHERE thread_id = ? AND date > ? AND folder_role = 'inbox' LIMIT 1",
            (draft.thread_id, written_after),
        )
        if newer:
            add(
                "newer_reply",
                settings.newer_reply,
                "A new reply arrived after you started this draft.",
            )
    return found


@mail_module.query("mail.checkSend")
def check_send(query: CheckDraft, ctx: Context) -> SendCheckResult:
    settings = _send_checks(ctx)
    return SendCheckResult(
        problems=_problems(ctx, query.draft, query.written_after, settings),
        undo_seconds=settings.undo_seconds,
    )


def _keep_sent_copy(work: Any, ctx: Context, account: str, raw: bytes) -> None:
    """POP3 has nowhere on the server for sent mail, so this computer's copy is the only one."""
    next_uid = work.tx.execute(
        "SELECT COALESCE(MAX(uid), 0) + 1 FROM message_locations WHERE account = ? AND folder = ?",
        (account, LOCAL_SENT),
    ).fetchone()[0]
    stored = store.store_message(
        work.tx,
        account=account,
        folder=LOCAL_SENT,
        role="sent",
        uid=next_uid,
        raw=raw,
        read=True,
        flagged=False,
        parsed=parse_message(raw),
        match=None,
        config=ctx.config.mail,
    )
    if stored:
        work.emit(
            "mail.changed",
            MailChanged(threads=1, reason="sent").model_dump(),
            source="mail",
            trace_id=ctx.trace_id,
        )


@mail_module.command("mail.send")
def send_mail(command: SendDraft, ctx: Context) -> MailDone:
    active, profile, password = _active_profile(ctx)
    draft = command.draft
    # A Block setting can't be skipped by calling this directly.
    blocked = [p for p in _problems(ctx, draft, None, _send_checks(ctx)) if p.level == "block"]
    if blocked:
        raise CommandError("mail.send_blocked", blocked[0].message, 422)
    in_reply_to, references = _threading_headers(ctx, draft)
    message = send.build_message(draft, profile, _sender_name(ctx), in_reply_to, references)
    try:
        send.send(message, draft, profile, password, ctx.config.mail.connect_timeout_seconds)
    except send.SendFailed as error:
        raise CommandError("mail.send_failed", str(error), 502) from error
    log.info("mail_sent", recipients=len(draft.to) + len(draft.cc) + len(draft.bcc))
    with ctx.bus.unit_of_work() as work:
        if draft.id is not None:
            work.tx.execute("DELETE FROM mail_drafts WHERE id = ?", (draft.id,))
            _outbox(work.tx, active, "delete_drafts", {"draft": str(draft.id)})
        if profile.protocol == "pop3":
            _keep_sent_copy(work, ctx, active, message.as_bytes())
        # Gmail files sent mail by itself, and a second copy would show up twice.
        elif "gmail.com" not in profile.smtp.host:
            _outbox(work.tx, active, "append", {"role": "sent", "raw": message.as_bytes().hex()})
        work.emit("mail.sent", {"thread_id": draft.thread_id}, source="mail", trace_id=ctx.trace_id)
        work.emit("drafts.changed", {"id": draft.id}, source="mail", trace_id=ctx.trace_id)
    _wake()
    return MailDone()


# PST archives


def _pst_rows(ctx: Context) -> PstImports:
    rows = ctx.bus.db.fetch_all("SELECT * FROM pst_imports ORDER BY id DESC")
    return PstImports(imports=[PstImport(**dict(row)) for row in rows])


@mail_module.query("pst.imports")
def pst_imports(query: GetPstImports, ctx: Context) -> PstImports:
    return _pst_rows(ctx)


@mail_module.command("pst.add")
def pst_add(command: AddPstImport, ctx: Context) -> PstImports:
    path = Path(command.path).expanduser().resolve()
    if not path.is_file():
        raise CommandError("pst.not_found", "That file doesn't exist. Check the path.", 422)
    if path.suffix.lower() not in {".pst", ".ost"}:
        raise CommandError("pst.not_a_pst", "Choose a .pst file.", 422)
    with ctx.bus.unit_of_work() as work:
        existing = work.tx.execute(
            "SELECT 1 FROM pst_imports WHERE path = ? AND status != 'failed'", (str(path),)
        ).fetchone()
        if existing:
            raise CommandError("pst.already_added", "That archive has already been added.", 409)
        work.tx.execute(
            "INSERT INTO pst_imports (path, name, status) VALUES (?, ?, 'queued')",
            (str(path), path.name),
        )
        work.emit("pst.progress", {"status": "queued"}, source="mail", trace_id=ctx.trace_id)
    pst.runner.kick(ctx)
    return _pst_rows(ctx)


@mail_module.query("pst.search")
def pst_search_status(query: GetPstSearch, ctx: Context) -> PstSearchStatus:
    return pst_search.search.status


@mail_module.command("pst.find")
def pst_find(command: FindPst, ctx: Context) -> PstSearchStatus:
    pst_search.search.start(ctx, command.everywhere)
    return pst_search.search.status


@mail_module.command("pst.findStop")
def pst_find_stop(command: GetPstSearch, ctx: Context) -> PstSearchStatus:
    pst_search.search.stop()
    return pst_search.search.status


@mail_module.command("pst.uploadStart")
def pst_upload_start(command: StartPstUpload, ctx: Context) -> PstUploadStarted:
    return pst_upload.start(ctx, command)


@mail_module.command("pst.pause")
def pst_pause(command: PstImportAction, ctx: Context) -> PstImports:
    if not pst.runner.pause(command.id):
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE pst_imports SET status = 'paused' WHERE id = ? AND status = 'queued'",
                (command.id,),
            )
            work.emit(
                "pst.progress",
                {"id": command.id, "status": "paused"},
                source="mail",
                trace_id=ctx.trace_id,
            )
    return _pst_rows(ctx)


@mail_module.command("pst.resume")
def pst_resume(command: PstImportAction, ctx: Context) -> PstImports:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE pst_imports SET status = 'queued', error = NULL WHERE id = ? AND status IN ('paused', 'failed')",
            (command.id,),
        )
        work.emit(
            "pst.progress",
            {"id": command.id, "status": "queued"},
            source="mail",
            trace_id=ctx.trace_id,
        )
    pst.runner.kick(ctx)
    return _pst_rows(ctx)


@mail_module.command("categories.sort")
def sort_category(command: SortCategory, ctx: Context) -> CategorySortEstimate:
    """Explicit historical sorting, with a cost estimate before any model work is queued."""
    from nexusai.modules.agent import mail_agent
    from nexusai.modules.agent import module as agent

    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM mail_categories WHERE name=? AND proposed=0", (command.name,)
    )
    if not rows:
        raise CommandError("category.not_found", "That folder no longer exists.", 404)
    folder = rows[0]
    candidates = ctx.bus.db.fetch_all(
        "SELECT t.id,m.id AS message,t.decision_version FROM threads t JOIN messages m ON m.id=(SELECT id FROM messages WHERE thread_id=t.id ORDER BY date DESC,id DESC LIMIT 1) WHERE t.account=? AND t.in_trash=0 AND t.in_junk=0 AND COALESCE(t.category_source,'')!='user' ORDER BY t.last_date DESC,t.id DESC",
        (accounts.current_account(ctx.config),),
    )
    tokens = (
        len(candidates) * mail_agent.APPROX_TOKENS_PER_MESSAGE if folder["mode"] == "smart" else 0
    )
    if not command.confirm:
        return CategorySortEstimate(conversations=len(candidates), estimated_tokens=tokens)
    if folder["mode"] == "exact":
        count = _apply_category_rule(ctx, folder["name"], folder["sender"], folder["subject"])
        _categories_changed(ctx)
        return CategorySortEstimate(conversations=len(candidates), estimated_tokens=0, queued=count)
    for row in candidates:
        mail_agent.enqueue(
            ctx,
            row["message"],
            row["id"],
            event=f"refile-{command.name}-{row['message']}-{row['decision_version']}",
        )
    dispatcher = agent._triggers
    if dispatcher:
        dispatcher.wake.set()
    return CategorySortEstimate(
        conversations=len(candidates), estimated_tokens=tokens, queued=len(candidates)
    )
