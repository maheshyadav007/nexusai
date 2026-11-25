import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, cast

import structlog

from nexusai.contracts.events import AppEvent
from nexusai.contracts.mail import (
    AddPstImport,
    ApplyMailSort,
    CategoryList,
    CategoryName,
    CategoryRulePreview,
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
    ForwardContext,
    GetMailAccounts,
    GetMailMe,
    GetMailPresets,
    GetMailSort,
    GetMailStatus,
    GetMoreMail,
    GetNamedYou,
    GetPstImports,
    GetPstSearch,
    GetRules,
    GetSendChecks,
    GetThread,
    HiddenFromAi,
    HideFromAi,
    HideFromAiPreview,
    HidePreview,
    ListCategories,
    ListDrafts,
    ListMailFolders,
    ListMixedFolders,
    ListThreads,
    MailAccounts,
    MailAccountView,
    MailCategory,
    MailChanged,
    MailDone,
    MailFolder,
    MailFolderCount,
    MailFolders,
    MailMe,
    MailPreset,
    MailPresets,
    MailProfile,
    MailRule,
    MailSent,
    MailSort,
    MailSortApplied,
    MailStatus,
    MailSyncChanged,
    MailTestResult,
    MarkFolderRead,
    MeExample,
    MePreview,
    MergeCategories,
    MixedFolder,
    MixedFolders,
    MoveThread,
    NamedYou,
    NamedYouList,
    NotAboutMe,
    PrepareMailSort,
    PreviewCategoryRule,
    PreviewMe,
    PreviewRule,
    ProbeServer,
    PstImport,
    PstImportAction,
    PstImports,
    PstSearchStatus,
    PstUploadStarted,
    Recipient,
    RecipientSuggestions,
    RemoveDraft,
    RemoveMailAccount,
    ReorderCategories,
    ReplyContext,
    ReplyDraft,
    RuleActions,
    RuleCondition,
    RuleExample,
    RulePreview,
    RuleSet,
    SaveCategory,
    SaveMailAccount,
    SearchMail,
    SearchResults,
    SendCheckResult,
    SendCheckSettings,
    SendDraft,
    SenderCount,
    SendProblem,
    ServerProbe,
    SetNeverDelete,
    SetSenderImages,
    SetThreadCategory,
    SetThreadFlag,
    SetThreadImportance,
    SetThreadRead,
    SetThreadStatus,
    SkipMailSort,
    SortCategory,
    SplitFolders,
    StartPstUpload,
    StopHistory,
    SuggestRecipients,
    TestMailAccount,
    ThreadInInbox,
    ThreadList,
    ThreadToInbox,
    ThreadUpdated,
    ThreadView,
    UndoHide,
    UpdateCategory,
)
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail import (
    accounts,
    folders,
    hiding,
    mentions,
    outgoing,
    pst,
    pst_search,
    pst_upload,
    rules,
    send,
    sort_rules,
    sorting,
    store,
)
from nexusai.modules.mail.imap import DELETING_ROLES, Folder, distinct_total, test_imap
from nexusai.modules.mail.parse import SUBJECT_PREFIX, normalize_subject, parse_message
from nexusai.modules.mail.pop3 import test_pop3
from nexusai.modules.mail.rules import own_domain_of
from nexusai.modules.mail.sync import MailSync
from nexusai.modules.semantic import module as semantic

log = structlog.get_logger()
ATTACHED_WORDS = re.compile(r"\b(attached|attachment|enclosed|첨부)\b|첨부", re.I)
mail_module = Module(
    name="mail",
    migrations=[
        *store.MIGRATIONS,
        pst.MIGRATION,
        sorting.MIGRATION,
        folders.MIGRATION,
        hiding.MIGRATION,
    ],
)

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


def _start_sync(ctx: Context, *, new_password: bool = False) -> None:
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
        _sync = MailSync(ctx, active, profile, password, proven=not new_password)
        _sync.start()


def _sort_kinds_once(ctx: Context) -> None:
    """Sorts mail filed before Promotions, Updates and Forums existed, a little at a time."""
    db = ctx.bus.db
    if db.fetch_all("SELECT 1 FROM migrations WHERE id = ?", (KINDS_SORTED,)):
        return
    last = 0
    home_rules = rules.load_rules(ctx.config.home)
    mail_rules_on = ctx.config.mail.rules_on
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
                engine = rules.Engine(home_rules, domain, folder_modes(ctx), on=mail_rules_on)
                match = engine.match(parsed)
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
    _automated_folder(ctx)
    _folder_tree_upgrade(ctx)
    sorting.record_past_sorting(ctx)
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
    _start_sync(ctx, new_password=bool(command.password))
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


# Where Gmail keeps its own folders, whatever the language.
GMAIL_SYSTEM = frozenset({"[Gmail]", "[Google Mail]"})


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
                # Gmail flags its other system folders, so a plain one under its own is one of these.
                shown_elsewhere=row["role"] == "other" and parent in GMAIL_SYSTEM,
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


READS_PREFIX = sort_rules.READS_PREFIX


@mail_module.query("mail.hide.preview")
def hide_preview(command: HidePreview, ctx: Context) -> HideFromAiPreview:
    return hiding.preview(ctx, command.thread)


@mail_module.command("mail.hide")
def hide_from_ai(command: HideFromAi, ctx: Context) -> HiddenFromAi:
    """Everything from the sender, or one conversation, to Kept from the AI, with one Undo."""
    return hiding.hide(ctx, command)


@mail_module.command("mail.hide.undo")
def undo_hide(command: UndoHide, ctx: Context) -> MailDone:
    hiding.undo(ctx, command.undo)
    return MailDone()


@mail_module.command("thread.toInbox")
def to_inbox(command: ThreadToInbox, ctx: Context) -> ThreadInInbox:
    """Undoes what kept a conversation from the AI: its folder, its rule, and Archive. The newest
    email is read again. Always also turns the sender's sorting rules into one that lets it in."""
    messages = _thread_messages(ctx, command.id)
    latest = max(messages, key=lambda row: (row["date"] or "", row["id"]))
    sender = str(latest["from_addr"] or "").casefold()
    if not ctx.bus.db.fetch_all("SELECT 1 FROM threads WHERE id=? AND in_inbox=1", (command.id,)):
        move_thread(MoveThread(id=command.id, to="inbox"), ctx)
    with ctx.bus.unit_of_work() as work:
        old = work.tx.execute("SELECT category FROM threads WHERE id=?", (command.id,)).fetchone()[
            0
        ]
        work.tx.execute(
            "UPDATE messages SET rule = NULL, why = NULL WHERE thread_id = ?", (command.id,)
        )
        # Marked the person's choice, so sorting and rules leave it where it is.
        work.tx.execute(
            "UPDATE threads SET category = NULL, extra_categories = '[]', category_source = 'user',"
            " latest_rule = NULL, why = 'You moved it to the Inbox' WHERE id = ?",
            (command.id,),
        )
        _changed(work, ctx, command.id, "category", None, old)
        work.emit(
            "mail.needsTriage",
            {"message_id": latest["id"], "thread_id": command.id},
            source="mail",
            trace_id=ctx.trace_id,
        )
    if command.always and sender:
        # The sender's one rule becomes one that lets it into the Inbox, as the Sort page does.
        sorting.move_sender(ctx, sender, reads=True, keep_folder=False)
    return ThreadInInbox(sender=sender)


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
    """This conversation into a folder. An email lives in one folder, so it leaves the one it
    was in; what the person chose stays, whatever a rule or the AI would say."""
    rows = ctx.bus.db.fetch_all(
        "SELECT category, extra_categories FROM threads WHERE id = ?", (command.id,)
    )
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE threads SET category = ?, extra_categories = '[]', category_source = 'user',"
            " why = ? WHERE id = ?",
            (command.name, "You chose this folder", command.id),
        )
        _changed(work, ctx, command.id, "category", command.name, rows[0]["category"])
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


def sender_sides(ctx: Context) -> dict[str, dict[str, bool]]:
    """For each folder, the senders a rule files there, and whether that keeps each from the AI.
    In a folder kept from the AI every sender is kept; elsewhere each sender's rule says."""
    reads = {
        row["name"]: bool(row["ai_reads"])
        for row in ctx.bus.db.fetch_all("SELECT name, ai_reads FROM mail_categories")
    }
    found: dict[str, dict[str, bool]] = {}
    for rule in rules.load_rules(ctx.config.home):
        name = rule.actions.category
        if not rule.enabled or not name:
            continue
        # A folder's own rule follows its side.
        kept = not reads.get(name, True) or (
            rule.actions.skip_agent and rule.name != CATEGORY_RULE_PREFIX + name
        )
        for condition in rule.conditions:
            if condition.field in {"sender", "sender_exact"} and "@" in condition.value:
                found.setdefault(name, {})[condition.value.strip().lower()] = kept
    return found


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
    sides = sender_sides(ctx)
    # What sorting keeps from the AI is decided by each sender's rule, so it's counted per folder.
    skipping = [
        rule.name
        for rule in rules.load_rules(ctx.config.home)
        if rule.enabled and rule.actions.skip_agent
    ]
    marks = ",".join("?" * len(skipping)) or "NULL"
    kept = {
        row["name"]: row["n"]
        for row in db.fetch_all(
            f"SELECT category AS name, COUNT(*) AS n FROM threads WHERE account = ?"  # noqa: S608
            f" AND category IS NOT NULL AND (in_inbox = 1 OR in_archive = 1) AND latest_rule IN ({marks})"
            " GROUP BY category",
            (account, *skipping),
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
        filed = sides.get(row["name"], {})
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
                ai_reads=bool(row["ai_reads"]),
                kept=min(kept.get(row["name"], 0), count),
                parent=row["parent"],
                senders_read=sum(not kept_from_ai for kept_from_ai in filed.values()),
                senders_kept=sum(filed.values()),
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
                    kept=min(kept.get(name, 0), count),
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


def _rule_conditions(
    sender: str | None, subject: str | None, conditions: list[RuleCondition] | None = None
) -> list[RuleCondition]:
    if conditions:
        return [
            condition
            for condition in conditions
            if condition.value.strip() or condition.field == "has_attachment"
        ]
    found = []
    if sender:
        found.append(RuleCondition(field="sender_exact", value=sender))
    if subject:
        found.append(RuleCondition(field="subject_prefix", value=subject))
    return found


def _likely(conditions: list[RuleCondition]) -> tuple[str, list[object]]:
    """A cheap first pass in SQL, so only emails that could match are opened and checked."""
    where: list[str] = []
    params: list[object] = []
    for condition in conditions:
        value = condition.value.strip().lower()
        if condition.field in {"sender", "sender_exact"}:
            where.append("LOWER(m.from_addr || ' ' || m.from_name) LIKE ?")
            params.append(f"%{value}%")
        elif condition.field in {"subject", "subject_prefix", "tag"}:
            where.append("LOWER(m.subject) LIKE ?")
            params.append(f"%{value}%")
        elif condition.field == "subject_words":
            # Close enough for a count: each word somewhere in the subject.
            for word in value.split():
                where.append("LOWER(m.subject) LIKE ?")
                params.append(f"%{word}%")
        elif condition.field == "has_attachment":
            where.append("m.has_attachments = 1")
    return "".join(f" AND {part}" for part in where), params


def _latest_matching(ctx: Context, conditions: list[RuleCondition]) -> list[sqlite3.Row]:
    """Each conversation's newest email, where it could match these conditions."""
    likely, params = _likely(conditions)
    return ctx.bus.db.fetch_all(
        "SELECT m.id,m.thread_id FROM messages m WHERE m.account=? AND m.id=(SELECT id FROM"  # noqa: S608
        f" messages WHERE thread_id=m.thread_id ORDER BY date DESC,id DESC LIMIT 1){likely}",
        (accounts.current_account(ctx.config), *params),
    )


RULE_EXAMPLES = 3


@mail_module.query("rules.preview")
def preview_whole_rule(query: PreviewRule, ctx: Context) -> RulePreview:
    """What a rule as written would catch among the mail already here: how many conversations,
    how many of those a person's reply named the person in, and a few to show. Nothing is saved."""
    rule = query.rule.model_copy(update={"enabled": True})
    conditions = [c for c in rule.conditions if c.value.strip() or c.field == "has_attachment"]
    if not conditions:
        return RulePreview(conversations=0, named=0, examples=[])
    rule = rule.model_copy(update={"conditions": conditions})
    # With any, each condition alone can match, so SQL can only narrow by one when there is one.
    rows = _latest_matching(ctx, conditions if rule.match == "all" else [])
    caught = []
    for row in rows:
        raw = store.raw_of(ctx.bus.db, row["id"])
        if raw is not None and rules.rule_matches(rule, parse_message(raw)):
            caught.append(row["thread_id"])
    if not caught:
        return RulePreview(conversations=0, named=0, examples=[])
    marks = ",".join("?" * len(caught))
    threads = ctx.bus.db.fetch_all(
        "SELECT t.id, t.subject, t.last_date, t.named, (SELECT COALESCE(NULLIF(from_name,''),"  # noqa: S608
        " from_addr) FROM messages WHERE thread_id = t.id ORDER BY date DESC, id DESC LIMIT 1)"
        f" AS sender FROM threads t WHERE t.id IN ({marks})"
        " ORDER BY t.named IS NULL, t.last_date DESC",
        tuple(caught),
    )
    named = [row for row in threads if row["named"]]
    shown = [*[row for row in threads if not row["named"]][: RULE_EXAMPLES - 1], *named[:1]]
    return RulePreview(
        conversations=len(threads),
        named=len(named),
        examples=[
            RuleExample(
                thread=row["id"],
                subject=row["subject"],
                sender=row["sender"] or "",
                date=row["last_date"],
                named=row["named"],
            )
            for row in (shown or threads[:RULE_EXAMPLES])
        ],
    )


def preview_rule(ctx: Context, conditions: list[RuleCondition]) -> int:
    """How many conversations already here these conditions would file. Nothing is saved."""
    conditions = _rule_conditions(None, None, conditions)
    if not conditions:
        return 0
    probe = MailRule(name="preview", conditions=conditions, actions=RuleActions(category="preview"))
    found = 0
    for row in _latest_matching(ctx, conditions):
        raw = store.raw_of(ctx.bus.db, row["id"])
        if raw is not None and rules.evaluate(parse_message(raw), [probe]) is not None:
            found += 1
    return found


def _apply_category_rule(
    ctx: Context,
    name: str,
    sender: str | None,
    subject: str | None,
    *,
    refile: bool = True,
    conditions: list[RuleCondition] | None = None,
) -> int:
    """Mail from now on follows the rule, and what's already here is filed too. In a folder kept
    from the AI the rule keeps its mail away; in one the AI reads it only files it."""
    conditions = _rule_conditions(sender, subject, conditions)
    rule_name = CATEGORY_RULE_PREFIX + name
    side = ctx.bus.db.fetch_all("SELECT ai_reads FROM mail_categories WHERE name=?", (name,))
    reads = bool(side[0]["ai_reads"]) if side else False

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
                    actions=RuleActions(category=name, skip_agent=not reads),
                )
            )
        return kept

    rules.change_rules(ctx.config.home, changed)
    if not conditions or not refile:
        return 0
    active = accounts.current_account(ctx.config)
    _, profiles = accounts.read_accounts(ctx.config)
    profile = profiles.get(active)
    domain = own_domain_of(profile.address or profile.auth.user) if profile else None
    engine = rule_engine(ctx, domain)
    changed_threads: set[int] = set()
    rows = _latest_matching(ctx, conditions)
    # Latest-message provenance and filing are decided together. One folder per conversation.
    with ctx.bus.db.transaction() as tx:
        for row in rows:
            raw = store.raw_of(ctx.bus.db, row["id"])
            if raw is None:
                continue
            match = engine.match(parse_message(raw))
            if not match or match.actions.category != name:
                continue
            tx.execute(
                "UPDATE messages SET rule=?,why=? WHERE id=?", (match.name, match.why, row["id"])
            )
            tx.execute(
                "UPDATE threads SET latest_rule=? WHERE id=?", (match.name, row["thread_id"])
            )
            filed = tx.execute(
                "UPDATE threads SET category=?,category_source='rule',why=? WHERE id=?"
                " AND COALESCE(category_source,'')!='user'",
                (name, match.why, row["thread_id"]),
            ).rowcount
            if filed:
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


def _automated_folder(ctx: Context) -> None:
    """Every Home has the Automated folder the header rules file into, older ones too. Only
    added, never changed: Updates and the others stay as the person has them."""
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO mail_categories (name, source, mode, description, in_priority,"
            " ai_reads, created) VALUES (?, 'rule', 'exact', ?, 0, 0, ?)",
            (rules.AUTOMATED, rules.AUTOMATED, datetime.now(UTC).isoformat()),
        )
        # It's always kept from the AI, at the top of Kept from the AI.
        tx.execute(
            "UPDATE mail_categories SET ai_reads = 0, parent = NULL WHERE name = ?"
            " AND (ai_reads != 0 OR parent IS NOT NULL)",
            (rules.AUTOMATED,),
        )


def _organization_defaults(ctx: Context) -> None:
    """Idempotent upgrades for existing Homes; never reinstate a folder the person removed."""
    marker = "mail_organization_defaults_001"
    if ctx.bus.db.fetch_all("SELECT 1 FROM migrations WHERE id = ?", (marker,)):
        return
    # One folder for mail tools send; the person's own folders come from the Sort step.
    defaults = {rules.AUTOMATED: "exact"}
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
        _, profiles = accounts.read_accounts(ctx.config)
        engines: dict[str | None, rules.Engine] = {}
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
                    if domain not in engines:
                        engines[domain] = rule_engine(ctx, domain)
                    match = engines[domain].match(parse_message(raw))
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


def rule_engine(ctx: Context, own_domain: str | None) -> rules.Engine:
    """The one door every email passes before the AI. Switched off in the settings, every email
    reaches the AI and none is filed by a rule."""
    return rules.Engine(
        ordered_rules(ctx),
        own_domain,
        folder_modes(ctx),
        on=ctx.config.mail.rules_on,
        me=who_am_i(ctx),
    )


def who_am_i(ctx: Context) -> MailMe:
    """Who the person is, as they last said, or as their account and sent mail say."""
    saved = mentions.load(ctx.config.home)
    if saved is not None:
        return saved
    _, profiles = accounts.read_accounts(ctx.config)
    own = sorted(
        {
            address.lower()
            for profile in profiles.values()
            for address in (profile.address or "", profile.auth.user)
            if "@" in address
        }
    )
    marks = ",".join("?" * len(own))
    sent = (
        ctx.bus.db.fetch_all(
            f"SELECT from_name FROM messages WHERE LOWER(from_addr) IN ({marks}) LIMIT 500",  # noqa: S608
            tuple(own),
        )
        if own
        else []
    )
    return mentions.found(mentions.name_from([row["from_name"] for row in sent]), own)


@mail_module.query("me.get")
def get_me(query: GetMailMe, ctx: Context) -> MailMe:
    return who_am_i(ctx)


@mail_module.command("me.save")
def save_me(command: MailMe, ctx: Context) -> MailMe:
    clean = MailMe(
        **{
            field: list(dict.fromkeys(item.strip() for item in values if item.strip()))
            for field, values in command.model_dump().items()
        }
    )
    mentions.save(ctx.config.home, clean)
    with ctx.bus.unit_of_work() as work:
        _mark_named(ctx, work, clean)
        work.emit("rules.changed", {"count": 0}, source="mail", trace_id=ctx.trace_id)
    return clean


# Whether a stored email is one whose naming the person counts: a person's reply, or a tool
# passing a mention on. It never changes, so each is read from its raw mail once.
_counts_here: dict[tuple[str, int], bool] = {}
EXAMPLES_SHOWN = 3


def _hidden_mail(ctx: Context) -> list[sqlite3.Row]:
    """Every email kept from the AI, newest first, with what it says in its own words."""
    return ctx.bus.db.fetch_all(
        "SELECT m.id, m.thread_id, m.subject, m.from_name, m.from_addr, m.clean_text, m.named,"
        " t.category, (SELECT COUNT(*) FROM messages x WHERE x.thread_id = m.thread_id) AS emails"
        " FROM messages m JOIN threads t ON t.id = m.thread_id WHERE m.account = ?"
        f" AND COALESCE(t.category, '') IN {store.KEPT_FOLDERS} ORDER BY m.date DESC",  # noqa: S608
        (accounts.current_account(ctx.config),),
    )


def _naming(ctx: Context, me: MailMe) -> list[tuple[sqlite3.Row, str, list[str]]]:
    """Hidden mail that names the person, as the rules judge it when it arrives: each email, the
    words that named them, and which of their names it used. A tool's "mentioned you" uses none."""
    _, profiles = accounts.read_accounts(ctx.config)
    profile = profiles.get(accounts.current_account(ctx.config))
    domain = own_domain_of(profile.address or profile.auth.user) if profile else None
    engine = rules.Engine([], domain, me=me)
    home = str(ctx.config.home)
    find = mentions.finder(me)
    found = []
    for row in _hidden_mail(ctx):
        told = mentions.TOLD.search(row["subject"]) is not None
        words = [] if told else find(row["clean_text"], row["from_addr"])
        if not told and not words:
            continue
        # Only a reply can count, and one says so in its subject or has mail before it: tool mail
        # that greets them by name, most of it, needs no closer look.
        if not told and not SUBJECT_PREFIX.match(row["subject"]) and row["emails"] < 2:
            continue
        # Only now, for the few left, the raw mail: is it a person's reply?
        key = (home, int(row["id"]))
        if key not in _counts_here:
            raw = store.raw_of(ctx.bus.db, int(row["id"]))
            parsed = parse_message(raw) if raw else None
            _counts_here[key] = bool(
                parsed and (mentions.told(parsed) or engine.person_replying(parsed))
            )
        if not _counts_here[key]:
            continue
        said = (
            row["subject"].strip()
            if told
            else mentions.named_in(row["clean_text"], row["from_addr"], me)
        )
        if said:
            found.append((row, said, words))
    return found


def _mark_named(ctx: Context, work: Any, me: MailMe) -> None:
    """Hidden mail that names the person as they now say they're named reaches the AI, and what
    named them by a name they took away goes back behind its folder."""
    hits = {int(row["id"]): (row, said) for row, said, _ in _naming(ctx, me)}
    threads: dict[int, str | None] = {}
    for row in _hidden_mail(ctx):
        hit = hits.get(int(row["id"]))
        value = f"{row['from_name'] or row['from_addr']}: {hit[1]}" if hit else None
        if value != row["named"]:
            work.tx.execute("UPDATE messages SET named = ? WHERE id = ?", (value, row["id"]))
        # Newest first, so a conversation takes its newest email that named them.
        thread = int(row["thread_id"])
        if threads.get(thread) is None:
            threads[thread] = value
    before = {
        int(row["id"]): row["named"]
        for row in ctx.bus.db.fetch_all(
            "SELECT id, named FROM threads WHERE account = ?"
            f" AND COALESCE(category, '') IN {store.KEPT_FOLDERS}",  # noqa: S608
            (accounts.current_account(ctx.config),),
        )
    }
    for thread, value in threads.items():
        if thread in before and before[thread] != value:
            work.tx.execute("UPDATE threads SET named = ? WHERE id = ?", (value, thread))
            _changed(work, ctx, thread, "named", value, before[thread])


@mail_module.query("me.preview")
def preview_me(query: PreviewMe, ctx: Context) -> MePreview:
    """What a list of names would let through, before it's saved: how many hidden replies each
    name, and all of them, would let the AI read, and the newest few, with the words that did."""
    saved = who_am_i(ctx)
    names = list(dict.fromkeys(item.strip() for item in query.names if item.strip()))
    ids = {item.casefold() for item in saved.ids}
    me = saved.model_copy(
        update={
            "names": [item for item in names if item.casefold() not in ids],
            "ids": [item for item in names if item.casefold() in ids],
        }
    )
    found = _naming(ctx, me)
    folded = {item.casefold(): item for item in names}
    counts = dict.fromkeys(names, 0)
    for _, _, words in found:
        for word in {folded[w.casefold()] for w in words if w.casefold() in folded}:
            counts[word] += 1
    return MePreview(
        counts=counts,
        total=len(found),
        examples=[
            MeExample(
                sender=row["from_name"] or row["from_addr"],
                folder=row["category"],
                quote=said,
                word=next((w for w in words if w.casefold() in folded), ""),
            )
            for row, said, words in found[:EXAMPLES_SHOWN]
        ],
    )


NAMED_SHOWN = 20


@mail_module.query("me.named")
def named_you(query: GetNamedYou, ctx: Context) -> NamedYouList:
    """Mail kept from the AI that it read anyway, because a person named the person: the newest."""
    rows = ctx.bus.db.fetch_all(
        "SELECT id, subject, category, named, last_date FROM threads WHERE account = ?"
        " AND named IS NOT NULL ORDER BY last_date DESC LIMIT ?",
        (accounts.current_account(ctx.config), NAMED_SHOWN),
    )
    found = []
    for row in rows:
        sender, _, quote = str(row["named"]).partition(": ")
        found.append(
            NamedYou(
                thread=row["id"],
                subject=row["subject"],
                sender=sender,
                folder=row["category"],
                quote=quote or sender,
                date=row["last_date"],
            )
        )
    return NamedYouList(items=found)


@mail_module.command("me.notAboutMe")
def not_about_me(command: NotAboutMe, ctx: Context) -> MailMe:
    """The conversation goes back behind its folder, and the name that misled is fixed."""
    me = who_am_i(ctx)
    if command.not_you and command.not_you.strip():
        me = me.model_copy(update={"not_you": [*me.not_you, command.not_you.strip()]})
    if command.stop:
        stop = command.stop.strip().casefold()
        me = me.model_copy(
            update={
                field: [item for item in getattr(me, field) if item.casefold() != stop]
                for field in ("names", "addresses", "ids")
            }
        )
    mentions.save(ctx.config.home, me)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("UPDATE threads SET named = NULL WHERE id = ?", (command.thread,))
        work.tx.execute("UPDATE messages SET named = NULL WHERE thread_id = ?", (command.thread,))
        _changed(work, ctx, command.thread, "named", None)
    return me


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
                            "skip_agent": not folder["ai_reads"],
                            "read_replies": False,
                        }
                    )
                    if canonical
                    else RuleActions(category=folder["name"], skip_agent=not folder["ai_reads"]),
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
    """A new folder, or the same one saved again. Inside a folder, it takes that folder's side;
    at the top, ai_reads says which home. A rule of any shape, or the AI by its description."""
    conditions = _rule_conditions(command.sender, command.subject, command.conditions)
    mode = command.mode or ("exact" if conditions else "smart")
    if mode == "exact" and not conditions:
        raise CommandError(
            "category.rule_required", "A folder filled by a rule needs at least one condition.", 422
        )
    db = ctx.bus.db
    existing = folders.find(db, command.name)
    # Saved again by its own name, it's updated; any other folder by that name is a clash.
    name = (
        existing["name"]
        if existing is not None and existing["name"] == command.name.strip()
        else folders.check_name(db, command.name)
    )
    parent = folders.find(db, command.parent) if command.parent else None
    if command.parent and parent is None:
        raise CommandError("category.not_found", f"There's no folder called {command.parent}.", 404)
    reads = bool(parent["ai_reads"]) if parent is not None else command.ai_reads
    if mode == "smart" and not reads:
        raise CommandError(
            "category.kept_smart",
            "The AI doesn't read mail kept from it, so a folder there is filled by a rule.",
            422,
        )
    sender = command.sender if not command.conditions else None
    subject = command.subject if not command.conditions else None
    with db.transaction() as tx:
        # A suggestion the person turned down never stands in the way of their own folder.
        tx.execute(
            "DELETE FROM mail_categories WHERE name = ? COLLATE NOCASE AND name != ? AND proposed != 0",
            (name, name),
        )
        tx.execute(
            "INSERT INTO mail_categories (name, source, in_priority, proposed, sender, subject, created)"
            " VALUES (?, ?, ?, 0, ?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
            " in_priority = excluded.in_priority, proposed = 0, sender = excluded.sender,"
            " subject = excluded.subject",
            (
                name,
                command.source,
                int(command.in_priority),
                sender,
                subject,
                datetime.now(UTC).isoformat(),
            ),
        )
        tx.execute(
            "UPDATE mail_categories SET mode = ?, description = ? WHERE name = ?",
            (mode, command.description.strip() or name, name),
        )
        if existing is None or command.parent is not None or "ai_reads" in command.model_fields_set:
            folders.move(tx, name, parent["name"] if parent is not None else None, reads)
    filed = _apply_category_rule(
        ctx,
        name,
        sender if mode == "exact" else None,
        subject if mode == "exact" else None,
        conditions=command.conditions if mode == "exact" else None,
        refile=command.file_existing,
    )
    _categories_changed(ctx)
    return CategorySaved(categories=category_rows(ctx), filed=filed)


@mail_module.query("categories.preview")
def preview_category_rule(query: PreviewCategoryRule, ctx: Context) -> CategoryRulePreview:
    return CategoryRulePreview(conversations=preview_rule(ctx, query.conditions))


def _rename_folder(ctx: Context, old: str, new: str) -> None:
    """One folder's new name, everywhere it's used: the folders inside it, its mail, its rules,
    and the emails those rules marked. Nothing else about it changes."""
    if old == new:
        return
    old_rule, new_rule = CATEGORY_RULE_PREFIX + old, CATEGORY_RULE_PREFIX + new

    def renamed_rule(name: str) -> str:
        if name == old_rule:
            return new_rule
        if name.startswith(old_rule + ": "):
            return new_rule + name[len(old_rule) :]
        return name

    names: dict[str, str] = {}
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE mail_categories SET name = ? WHERE name = ?", (new, old))
        tx.execute("UPDATE mail_categories SET parent = ? WHERE parent = ?", (new, old))
        tx.execute("UPDATE threads SET category = ? WHERE category = ?", (new, old))
        tx.execute("UPDATE OR IGNORE mail_category_votes SET name = ? WHERE name = ?", (new, old))
        _rename_extras(tx, {old}, new)
        for rule in rules.load_rules(ctx.config.home):
            if renamed_rule(rule.name) != rule.name:
                names[rule.name] = renamed_rule(rule.name)
        for before, after in names.items():
            tx.execute("UPDATE messages SET rule = ? WHERE rule = ?", (after, before))
            tx.execute("UPDATE threads SET latest_rule = ? WHERE latest_rule = ?", (after, before))
    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            rule.model_copy(
                update={
                    "name": renamed_rule(rule.name),
                    "actions": rule.actions.model_copy(update={"category": new})
                    if rule.actions.category == old
                    else rule.actions,
                }
            )
            for rule in existing
        ],
    )


@mail_module.command("categories.update")
def update_category(command: UpdateCategory, ctx: Context) -> CategoryList:
    db = ctx.bus.db
    rows = db.fetch_all("SELECT * FROM mail_categories WHERE name = ?", (command.name,))
    row = rows[0] if rows else None
    in_use = db.fetch_all("SELECT 1 FROM threads WHERE category = ? LIMIT 1", (command.name,))
    if row is None and not in_use:
        raise CommandError("category.not_found", "That category no longer exists.", 404)
    new_name = (
        folders.check_name(db, command.new_name, keep=command.name)
        if command.new_name
        else command.name
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
    # Filed by its senders' own rules, as sorting does: those are its rules, and a guessed
    # sender would give one of them a second.
    # Its own rule with more than a sender and a subject, as the New folder dialog makes, is
    # its rule too.
    by_senders = any(
        rule.actions.category == command.name
        and (
            rule.name != CATEGORY_RULE_PREFIX + command.name
            or any(
                condition.field not in {"sender", "sender_exact", "subject", "subject_prefix"}
                for condition in rule.conditions
            )
            or (not (row and (row["sender"] or row["subject"])) and bool(rule.conditions))
        )
        for rule in rules.load_rules(ctx.config.home)
    )
    if (
        mode == "exact"
        and not (sender or subject)
        and not by_senders
        and command.name not in {"Updates", "Promotions", "Forums", "Social", rules.AUTOMATED}
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
            "UPDATE mail_categories SET in_priority = ?, sender = ?, subject = ?,"
            " proposed = 0, updated = ?, mode = ?, description = ? WHERE name = ?",
            (int(in_priority), sender, subject, now, mode, description, command.name),
        )
    _rename_folder(ctx, command.name, new_name)
    # A rule with more than a sender and a subject stays as it was written; the rest follow
    # the folder's settings.
    own = next(
        (
            rule
            for rule in rules.load_rules(ctx.config.home)
            if rule.name == CATEGORY_RULE_PREFIX + new_name
        ),
        None,
    )
    shaped = own is not None and any(
        condition.field not in {"sender", "sender_exact", "subject", "subject_prefix"}
        for condition in own.conditions
    )
    # Made in the New folder dialog, a rule of conditions is the folder's own, and stays as
    # written unless a sender or subject is set in its place.
    written = (
        own is not None
        and not (row and (row["sender"] or row["subject"]))
        and not command.clear_rule
        and not {"sender", "subject"} & command.model_fields_set
    )
    if not ((shaped or written) and mode == "exact"):
        _apply_category_rule(
            ctx,
            new_name,
            sender if mode == "exact" else None,
            subject if mode == "exact" else None,
            refile=False,
        )
    if command.parent is not None:
        _move_folder(ctx, new_name, command.parent or None, command.ai_reads)
    elif command.ai_reads is not None:
        _set_reads(ctx, new_name, command.ai_reads)
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


def _move_folder(ctx: Context, name: str, parent: str | None, reads: bool | None) -> None:
    """Into another folder, or to the top of a home. Every folder that changes sides takes its
    senders with it, each keeping its one rule."""
    if name in folders.KEPT_WHOLE and (parent or reads):
        raise CommandError("category.kept_whole", f"{name} is always kept from the AI.", 409)
    with ctx.bus.db.transaction() as tx:
        changed = folders.move(tx, name, parent, reads)
    for folder in changed:
        _follow_side(ctx, folder)


def _set_reads(ctx: Context, name: str, reads: bool) -> None:
    """A whole folder to the other side. A folder takes its side from its home, so it goes to
    the top of the other one, with everything in it. Automated and Calendar are always kept."""
    row = folders.find(ctx.bus.db, name)
    if row is not None and bool(row["ai_reads"]) == reads and not row["parent"]:
        # Already there; the senders still follow, in case a rule says otherwise.
        _follow_side(ctx, row["name"])
        return
    if reads and name in folders.KEPT_WHOLE:
        raise CommandError(
            "category.kept_whole",
            f"{name} is always kept from the AI. Move its senders to another folder.",
            409,
        )
    if row is None:
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories (name, source, mode, description, created)"
                " VALUES (?, 'rule', 'exact', ?, ?)",
                (name, name, datetime.now(UTC).isoformat()),
            )
    _move_folder(ctx, name, None, reads)


def _follow_side(ctx: Context, name: str) -> None:
    """Each sender a rule files into this folder, and the folder's own rule, on its side."""
    row = folders.find(ctx.bus.db, name)
    if row is None:
        return
    reads = bool(row["ai_reads"])
    senders = {
        (condition.value or "").strip().lower()
        for rule in rules.load_rules(ctx.config.home)
        if rule.actions.category == name and rule.name != CATEGORY_RULE_PREFIX + name
        for condition in rule.conditions
        if condition.field in {"sender", "sender_exact"} and "@" in (condition.value or "")
    }
    for sender in sorted(senders):
        sorting.move_sender(ctx, sender, reads=reads, folder=name)
    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            rule.model_copy(
                update={"actions": rule.actions.model_copy(update={"skip_agent": not reads})}
            )
            if rule.name == CATEGORY_RULE_PREFIX + name
            else rule
            for rule in existing
        ],
    )


@mail_module.command("categories.merge")
def merge_categories(command: MergeCategories, ctx: Context) -> CategoryList:
    db = ctx.bus.db
    now = datetime.now(UTC).isoformat()
    others = [name for name in command.names if name != command.into]
    if folders.find(db, command.into) is None:
        folders.check_name(db, command.into)
    with db.transaction() as tx:
        for name in others:
            tx.execute(
                "UPDATE mail_categories SET parent = ? WHERE parent = ?", (command.into, name)
            )
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
    """Its mail and the folders in it go to where it was: its parent, or the top of its home.
    Mail kept from the AI stays kept."""
    row = folders.find(ctx.bus.db, command.name)
    if command.name.casefold() == folders.AUTOMATED.casefold():
        raise CommandError("category.kept_whole", f"{folders.AUTOMATED} can't be removed.", 409)
    into = (row["parent"] if row is not None else None) or (
        None if row is None or row["ai_reads"] else folders.AUTOMATED
    )
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM mail_categories WHERE name = ?", (command.name,))
        tx.execute(
            "UPDATE mail_categories SET parent = ? WHERE parent = ?",
            (row["parent"] if row is not None else None, command.name),
        )
        tx.execute(
            "UPDATE threads SET category = ?, category_source = CASE WHEN ? IS NULL THEN NULL"
            " ELSE category_source END WHERE category = ?",
            (into, into, command.name),
        )
        _rename_extras(tx, {command.name}, None)
    own = CATEGORY_RULE_PREFIX + command.name

    def moved(existing: list[MailRule]) -> list[MailRule]:
        """Its rules file into where its mail went. Its own rule, when that's the Inbox, goes."""
        kept = []
        for rule in existing:
            if rule.actions.category != command.name and not rule.name.startswith(own + ": "):
                kept.append(rule)
                continue
            if into is None and (rule.name == own or rule.name.startswith(own + ": ")):
                continue
            name = (
                f"{CATEGORY_RULE_PREFIX}{into}: from {rule.name[len(CATEGORY_RULE_PREFIX) :]}"[:120]
                if rule.name == own or rule.name.startswith(own + ": ")
                else rule.name
            )
            kept.append(
                rule.model_copy(
                    update={
                        "name": name,
                        "actions": rule.actions.model_copy(update={"category": into}),
                    }
                )
            )
        return kept

    rules.change_rules(ctx.config.home, moved)
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


def _sender_emails(ctx: Context, senders: list[str]) -> dict[str, int]:
    if not senders:
        return {}
    marks = ",".join("?" * len(senders))
    return {
        row["sender"]: row["n"]
        for row in ctx.bus.db.fetch_all(
            "SELECT LOWER(from_addr) AS sender, COUNT(*) AS n FROM messages"  # noqa: S608
            f" WHERE account = ? AND LOWER(from_addr) IN ({marks}) GROUP BY LOWER(from_addr)",
            (accounts.current_account(ctx.config), *senders),
        )
    }


def _by_size(senders: list[str], emails: dict[str, int]) -> list[SenderCount]:
    return sorted(
        (SenderCount(sender=sender, emails=emails.get(sender, 0)) for sender in senders),
        key=lambda item: (-item.emails, item.sender),
    )


@mail_module.query("categories.mixed")
def mixed_folders(query: ListMixedFolders, ctx: Context) -> MixedFolders:
    """Folders on both sides: some senders the AI reads, some it doesn't. Each is split once, so
    every folder lives in one place."""
    found = []
    for name, senders in sorted(sender_sides(ctx).items()):
        row = folders.find(ctx.bus.db, name)
        if row is None or not row["ai_reads"] or name in folders.KEPT_WHOLE:
            continue
        read = sorted(sender for sender, kept in senders.items() if not kept)
        kept = sorted(sender for sender, kept in senders.items() if kept)
        if not read or not kept:
            continue
        emails = _sender_emails(ctx, read + kept)
        found.append(
            MixedFolder(
                name=name,
                read_senders=_by_size(read, emails),
                kept_senders=_by_size(kept, emails),
                read_emails=sum(emails.get(sender, 0) for sender in read),
                kept_emails=sum(emails.get(sender, 0) for sender in kept),
                suggested=folders.suggest_kept_name(ctx.bus.db, name, kept),
            )
        )
    return MixedFolders(folders=found)


@mail_module.command("categories.split")
def split_folders(command: SplitFolders, ctx: Context) -> CategoryList:
    """The half the AI reads keeps the name; the half kept from it becomes a folder of its own
    at the top of Kept from the AI, its senders' mail and rules with it. Undo puts it back."""
    for split in command.splits:
        if command.undo:
            _unsplit(ctx, split.name, split.kept_name)
            continue
        sides = sender_sides(ctx).get(split.name, {})
        kept = sorted(sender for sender, is_kept in sides.items() if is_kept)
        if not kept:
            continue
        _make_kept_folder(ctx, split.kept_name)
        for sender in kept:
            sorting.move_sender(
                ctx, sender, reads=False, folder=split.kept_name, keep_folder=False, refile=True
            )
    _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


def _make_kept_folder(ctx: Context, name: str) -> None:
    """A new folder at the top of Kept from the AI. One already there by that name is joined."""
    existing = folders.find(ctx.bus.db, name)
    if existing is not None and not existing["ai_reads"]:
        return
    name = folders.check_name(ctx.bus.db, name)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_categories (name, source, in_priority, proposed, why, created, mode,"
            " description, ai_reads) VALUES (?, 'user', 0, 0, ?, ?, 'exact', ?, 0)",
            (name, "Split from a folder on both sides", datetime.now(UTC).isoformat(), name),
        )


def _unsplit(ctx: Context, name: str, kept_name: str) -> None:
    senders = sorted(sender_sides(ctx).get(kept_name, {}))
    for sender in senders:
        sorting.move_sender(
            ctx, sender, reads=False, folder=name, keep_folder=False, refile=True, strict=False
        )
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE mail_categories SET parent = NULL WHERE parent = ?", (kept_name,))
        tx.execute("DELETE FROM mail_categories WHERE name = ?", (kept_name,))


FOLDER_TREE_UPGRADE = "mail_folder_tree_upgrade_001"


def _folder_tree_upgrade(ctx: Context) -> None:
    """Once for each Home: folders named like paths become folders inside folders, those under
    Automated move to the top of Kept from the AI, and a folder whose every rule keeps its mail
    from the AI is put there too. A folder with senders on both sides waits for its split."""
    db = ctx.bus.db
    if db.fetch_all("SELECT 1 FROM migrations WHERE id = ?", (FOLDER_TREE_UPGRADE,)):
        return
    paths = sorted(
        (
            row["name"]
            for row in db.fetch_all("SELECT name FROM mail_categories WHERE name LIKE '%/%'")
        ),
        key=lambda name: name.count("/"),
    )
    became: dict[str, str] = {}
    for path in paths:
        above, _, leaf = path.rpartition("/")
        new = folders.free_name(db, leaf.strip() or path.replace("/", " "), keep=path)
        if new.casefold() == path.casefold():
            new = path.replace("/", " ")
        _rename_folder(ctx, path, new)
        parent = None if above == folders.AUTOMATED else became.get(above, above)
        with db.transaction() as tx:
            if parent and folders.find(tx, parent) is not None:
                folders.move(tx, new, parent, None)
            else:
                folders.move(tx, new, None, False if above == folders.AUTOMATED else None)
        became[path] = new
    stored = rules.load_rules(ctx.config.home)
    moved = bool(paths)
    with db.transaction() as tx:
        for row in tx.execute(
            "SELECT name FROM mail_categories WHERE ai_reads = 1 AND parent IS NULL AND proposed = 0"
            " AND mode = 'exact'"
        ).fetchall():
            skips = [
                rule.actions.skip_agent
                for rule in stored
                if rule.enabled and rule.actions.category == row["name"]
            ]
            if skips and all(skips):
                folders.move(tx, row["name"], None, False)
                moved = True
        tx.execute("INSERT INTO migrations (id) VALUES (?)", (FOLDER_TREE_UPGRADE,))
    if moved:
        _categories_changed(ctx)


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
            saved,
            profile,
            _sender_name(ctx),
            in_reply_to,
            references,
            draft_marker=marker,
            files=outgoing.files_of(ctx, saved),
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
        saved = work.tx.execute(
            "SELECT body FROM mail_drafts WHERE id = ?", (command.id,)
        ).fetchone()
        if saved:
            outgoing.forget_uploads(work.tx, Draft.model_validate_json(saved["body"]))
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


@mail_module.query("mail.forwardDraft")
def forward_draft(query: ForwardContext, ctx: Context) -> ReplyDraft:
    return ReplyDraft(draft=outgoing.forward(ctx, query.message_id), dropped=[])


@mail_module.query("mail.suggestRecipients")
def suggest_recipients(query: SuggestRecipients, ctx: Context) -> RecipientSuggestions:
    _, profiles = accounts.read_accounts(ctx.config)
    own = {
        address
        for profile in profiles.values()
        for address in ((profile.address or "").lower(), profile.auth.user.lower())
        if "@" in address
    }
    return outgoing.suggest(ctx, _account(ctx), own, query.text)


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
    if ATTACHED_WORDS.search(draft.body) and not draft.attachments:
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
        decision=rules.Decision(True, "Your own sent mail"),
        config=ctx.config.mail,
    )
    if stored:
        work.emit(
            "mail.changed",
            MailChanged(threads=1, reason="sent").model_dump(),
            source="mail",
            trace_id=ctx.trace_id,
        )
        # No Sent folder to sync it back from, so this is where it's announced.
        work.emit(
            "mail.sent",
            MailSent(message_id=stored.message, thread_id=stored.thread).model_dump(),
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
    message = send.build_message(
        draft,
        profile,
        _sender_name(ctx),
        in_reply_to,
        references,
        files=outgoing.files_of(ctx, draft),
    )
    try:
        send.send(message, draft, profile, password, ctx.config.mail.connect_timeout_seconds)
    except send.SendFailed as error:
        raise CommandError("mail.send_failed", str(error), 502) from error
    log.info("mail_sent", recipients=len(draft.to) + len(draft.cc) + len(draft.bcc))
    with ctx.bus.unit_of_work() as work:
        outgoing.forget_uploads(work.tx, draft)
        if draft.id is not None:
            work.tx.execute("DELETE FROM mail_drafts WHERE id = ?", (draft.id,))
            _outbox(work.tx, active, "delete_drafts", {"draft": str(draft.id)})
        if profile.protocol == "pop3":
            _keep_sent_copy(work, ctx, active, message.as_bytes())
        # Gmail files sent mail by itself, and a second copy would show up twice.
        elif "gmail.com" not in profile.smtp.host:
            _outbox(work.tx, active, "append", {"role": "sent", "raw": message.as_bytes().hex()})
        # mail.sent comes once the copy is stored, when its message and conversation are known:
        # above for POP3, from syncing Sent otherwise.
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
        "SELECT t.id,m.id AS message,t.decision_version FROM threads t JOIN messages m ON m.id=(SELECT id FROM messages WHERE thread_id=t.id ORDER BY date DESC,id DESC LIMIT 1) WHERE t.account=? AND t.in_trash=0 AND t.in_junk=0 AND COALESCE(t.category_source,'')!='user'"
        f" AND NOT {rules.FILED_BY_RULE} ORDER BY t.last_date DESC,t.id DESC",
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


# Sorting mail before the AI reads it


@mail_module.query("mail.sort.get")
def get_mail_sort(query: GetMailSort, ctx: Context) -> MailSort:
    return sorting.status(ctx)


@mail_module.command("mail.sort.prepare")
def prepare_mail_sort(command: PrepareMailSort, ctx: Context) -> MailSort:
    sorting.prepare(ctx, again=command.again)
    return sorting.status(ctx)


@mail_module.command("mail.sort.apply")
def apply_mail_sort(command: ApplyMailSort, ctx: Context) -> MailSortApplied:
    moved = sorting.apply(ctx, command)
    _categories_changed(ctx)
    return MailSortApplied(moved=moved)


@mail_module.command("mail.sort.skip")
def skip_mail_sort(command: SkipMailSort, ctx: Context) -> MailSort:
    sorting.skip(ctx)
    return sorting.status(ctx)
