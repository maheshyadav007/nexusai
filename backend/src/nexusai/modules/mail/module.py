import json
import re
import threading
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path

import structlog

from nexusai.contracts.mail import (
    AddPstImport,
    CategoryList,
    CategoryName,
    CategorySaved,
    CheckDraft,
    ConnectionResult,
    DecideCategory,
    Draft,
    DraftList,
    GetMailAccounts,
    GetMailStatus,
    GetPstImports,
    GetRules,
    GetSendChecks,
    GetThread,
    ListCategories,
    ListDrafts,
    ListThreads,
    MailAccounts,
    MailAccountView,
    MailCategory,
    MailChanged,
    MailDone,
    MailProfile,
    MailRule,
    MailStatus,
    MailTestResult,
    MoveThread,
    PstImport,
    PstImportAction,
    PstImports,
    Recipient,
    RemoveDraft,
    RemoveMailAccount,
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
    SetThreadCategory,
    SetThreadFlag,
    SetThreadRead,
    SetThreadStatus,
    TestMailAccount,
    ThreadList,
    ThreadUpdated,
    ThreadView,
)
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail import accounts, pst, rules, send, store
from nexusai.modules.mail.imap import test_imap
from nexusai.modules.mail.parse import normalize_subject
from nexusai.modules.mail.sync import MailSync

log = structlog.get_logger()
ATTACHED_WORDS = re.compile(r"\b(attached|attachment|enclosed|첨부)\b|첨부", re.I)
mail_module = Module(name="mail", migrations=[*store.MIGRATIONS, pst.MIGRATION])

_sync: MailSync | None = None
_sync_lock = threading.Lock()


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
        if password is None or accounts.require_encrypted(profile):
            return
        _sync = MailSync(ctx, active, profile, password)
        _sync.start()


def _startup(ctx: Context) -> None:
    accounts.adopt_earlier_accounts(ctx.config)
    _start_sync(ctx)
    # An import that was running when the app closed carries on from its saved position.
    pst.runner.kick(ctx)


def _shutdown() -> None:
    global _sync
    with _sync_lock:
        if _sync:
            _sync.stop()
            _sync = None


mail_module.on_start.append(_startup)
mail_module.on_stop.append(_shutdown)
mail_module.on_stop.append(pst.runner.stop)


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
    if problem := accounts.require_encrypted(command.profile):
        raise CommandError("mail.not_encrypted", problem, 422)
    password = command.password or accounts.get_password(ctx.config, command.profile.auth.user)
    if not password:
        raise CommandError("mail.no_password", "Enter the password first.", 422)
    timeout = ctx.config.mail.connect_timeout_seconds
    imap_problem = test_imap(command.profile, password, timeout)
    smtp_problem = send.test_smtp(command.profile, password, timeout)
    return MailTestResult(
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
    if problem := accounts.require_encrypted(command.profile):
        raise CommandError("mail.not_encrypted", problem, 422)
    active, profiles = accounts.read_accounts(ctx.config)
    profiles[command.name] = command.profile
    if command.password:
        accounts.set_password(ctx.config, command.profile.auth.user, command.password)
    accounts.write_accounts(ctx.config, command.name if command.make_active else active, profiles)
    _start_sync(ctx)
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "mail.accountsChanged", {"name": command.name}, source="mail", trace_id=ctx.trace_id
        )
    return _accounts_view(ctx)


@mail_module.command("mail.accounts.remove")
def remove_account(command: RemoveMailAccount, ctx: Context) -> MailAccounts:
    active, profiles = accounts.read_accounts(ctx.config)
    profiles.pop(command.name, None)
    accounts.write_accounts(ctx.config, None if active == command.name else active, profiles)
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
    if _sync is None:
        return MailStatus(account=active, state="off", messages=count)
    return MailStatus(
        account=active,
        state=_sync.status.state,
        message=_sync.status.message,
        messages=count,
        backfill_remaining=_sync.status.backfill_remaining,
    )


# Reading


@mail_module.query("threads.list")
def list_threads(query: ListThreads, ctx: Context) -> ThreadList:
    account = accounts.current_account(ctx.config)
    return store.list_threads(
        ctx.bus.db, account, query.folder, query.category, query.before, query.limit
    )


@mail_module.query("thread.get")
def get_thread(query: GetThread, ctx: Context) -> ThreadView:
    view = store.thread_view(ctx.bus.db, query.id)
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
    return store.search(ctx.bus.db, accounts.current_account(ctx.config), query)


# Changing state: saved here at once, and sent to the server through the outbox


def _outbox(work_tx: object, account: str, op: str, payload: dict[str, object]) -> None:
    work_tx.execute(  # type: ignore[attr-defined]
        "INSERT INTO mail_outbox (account, op, payload) VALUES (?, ?, ?)",
        (account, op, json.dumps(payload)),
    )


def _thread_messages(ctx: Context, thread: int) -> list[dict[str, object]]:
    rows = ctx.bus.db.fetch_all("SELECT * FROM messages WHERE thread_id = ?", (thread,))
    if not rows:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    return [dict(row) for row in rows]


def _changed(work: object, ctx: Context, thread: int, field: str, value: object) -> None:
    work.emit(  # type: ignore[attr-defined]
        "thread.updated",
        ThreadUpdated(thread_id=thread, field=field, value=value).model_dump(),
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
                _outbox(
                    work.tx,
                    str(message["account"]),
                    "read",
                    {
                        "message": message["id"],
                        "folder": message["folder"],
                        "uid": message["uid"],
                        "value": command.read,
                    },
                )
        store.refresh_thread(work.tx, command.id)
        _changed(work, ctx, command.id, "read", command.read)
    _wake()
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
            _outbox(
                work.tx,
                str(message["account"]),
                "flag",
                {
                    "message": message["id"],
                    "folder": message["folder"],
                    "uid": message["uid"],
                    "value": command.flagged,
                },
            )
        store.refresh_thread(work.tx, command.id)
        _changed(work, ctx, command.id, "flagged", command.flagged)
    _wake()
    return MailDone()


@mail_module.command("thread.move")
def move_thread(command: MoveThread, ctx: Context) -> MailDone:
    messages = _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        for message in messages:
            if message["folder_role"] != "inbox":
                continue
            _outbox(
                work.tx,
                str(message["account"]),
                "move",
                {
                    "message": message["id"],
                    "folder": message["folder"],
                    "uid": message["uid"],
                    "role": command.to,
                },
            )
            # It returns from the server with its new folder's UID on the next sync.
            store.remove_message(work.tx, int(str(message["id"])))
        _changed(work, ctx, command.id, "folder", command.to)
    _wake()
    return MailDone()


@mail_module.command("thread.setStatus")
def set_status(command: SetThreadStatus, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("UPDATE threads SET status = ? WHERE id = ?", (command.status, command.id))
        _changed(work, ctx, command.id, "status", command.status)
    return MailDone()


@mail_module.command("thread.setCategory")
def set_category(command: SetThreadCategory, ctx: Context) -> MailDone:
    _thread_messages(ctx, command.id)
    with ctx.bus.unit_of_work() as work:
        source = "user" if command.category else None
        why = "You chose this category" if command.category else None
        work.tx.execute(
            "UPDATE threads SET category = ?, category_source = ?, why = ? WHERE id = ?",
            (command.category, source, why, command.id),
        )
        _changed(work, ctx, command.id, "category", command.category)
    return MailDone()


# Rules


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

CATEGORY_RULE_PREFIX = "Category: "
SUGGESTED, DECLINED = 1, 2


def category_rows(ctx: Context) -> list[MailCategory]:
    db = ctx.bus.db
    account = accounts.current_account(ctx.config)
    counts = {
        row["category"]: (row["n"], row["unread"])
        for row in db.fetch_all(
            "SELECT category, COUNT(*) AS n, SUM(unread_count > 0) AS unread FROM threads"
            " WHERE account = ? AND category IS NOT NULL AND (in_inbox = 1 OR in_archive = 1)"
            " GROUP BY category",
            (account,),
        )
    }
    found = []
    named = set()
    for row in db.fetch_all("SELECT * FROM mail_categories ORDER BY name"):
        named.add(row["name"])
        # One the person turned down stays recorded, so it isn't suggested again.
        if row["proposed"] == DECLINED:
            continue
        count, unread = counts.get(row["name"], (0, 0))
        found.append(
            MailCategory(
                name=row["name"],
                source=row["source"],
                in_priority=bool(row["in_priority"]),
                proposed=row["proposed"] == SUGGESTED,
                why=row["why"],
                sender=row["sender"],
                subject=row["subject"],
                count=count,
                unread=unread or 0,
            )
        )
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
    return sorted(found, key=lambda category: category.name.casefold())


def _apply_category_rule(ctx: Context, name: str, sender: str | None, subject: str | None) -> int:
    """Mail from now on follows the rule, and what's already here is filed too."""
    conditions = []
    if sender:
        conditions.append(RuleCondition(field="sender", value=sender))
    if subject:
        conditions.append(RuleCondition(field="subject", value=subject))
    rule_name = CATEGORY_RULE_PREFIX + name
    kept = [rule for rule in rules.load_rules(ctx.config.home) if rule.name != rule_name]
    if conditions:
        kept.append(
            MailRule(name=rule_name, conditions=conditions, actions=RuleActions(category=name))
        )
    rules.save_rules(ctx.config.home, RuleSet(rules=kept))
    if not conditions:
        return 0
    where = ["t.id = m.thread_id"]
    params: list[object] = []
    if sender:
        where.append("(m.from_addr LIKE ? OR m.from_name LIKE ?)")
        params += [f"%{sender}%", f"%{sender}%"]
    if subject:
        where.append("m.subject LIKE ?")
        params.append(f"%{subject}%")
    with ctx.bus.db.transaction() as tx:
        cursor = tx.execute(
            "UPDATE threads AS t SET category = ?, category_source = 'rule', why = ? WHERE"  # noqa: S608
            " COALESCE(t.category_source, '') != 'user' AND EXISTS"
            f" (SELECT 1 FROM messages m WHERE {' AND '.join(where)})",
            (name, f"Matched the category “{name}”", *params),
        )
        return int(cursor.rowcount)


def _categories_changed(ctx: Context) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit("categories.changed", {}, source="mail", trace_id=ctx.trace_id)
        work.emit(
            "mail.changed",
            {"threads": 0, "reason": "categories"},
            source="mail",
            trace_id=ctx.trace_id,
        )


@mail_module.query("categories.list")
def list_categories(query: ListCategories, ctx: Context) -> CategoryList:
    return CategoryList(categories=category_rows(ctx))


@mail_module.command("categories.save")
def save_category(command: SaveCategory, ctx: Context) -> CategorySaved:
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
    filed = _apply_category_rule(ctx, command.name, command.sender, command.subject)
    _categories_changed(ctx)
    return CategorySaved(categories=category_rows(ctx), filed=filed)


@mail_module.command("categories.remove")
def remove_category(command: CategoryName, ctx: Context) -> CategoryList:
    """Its mail stays where it is, only without this label."""
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM mail_categories WHERE name = ?", (command.name,))
        tx.execute(
            "UPDATE threads SET category = NULL, category_source = NULL WHERE category = ?",
            (command.name,),
        )
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
        save_category(
            SaveCategory(
                name=row["name"],
                in_priority=bool(row["in_priority"]),
                sender=row["sender"],
                subject=row["subject"],
                source="agent",
            ),
            ctx,
        )
    else:
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE mail_categories SET proposed = ? WHERE name = ?", (DECLINED, command.name)
            )
        _categories_changed(ctx)
    return CategoryList(categories=category_rows(ctx))


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
        # The server keeps one copy of each draft: the old one goes before the new one lands.
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
    me = profile.auth.user.lower()
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
    domain = profiles[active].auth.user.rsplit("@", 1)[-1].lower() if active else ""
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
        # Gmail files sent mail by itself, and a second copy would show up twice.
        if "gmail.com" not in profile.smtp.host:
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
