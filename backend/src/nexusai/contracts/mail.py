from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ThreadStatus = Literal["none", "waiting_on_you", "waiting_on_others", "resolved", "fyi"]
Importance = Literal["low", "normal", "high"]
FolderRole = Literal["inbox", "sent", "drafts", "trash", "archive", "other"]
SyncState = Literal[
    "off", "paused", "connecting", "syncing", "backfilling", "live", "offline", "failed"
]


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    secure: bool = True


class MailAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["password"] = "password"
    user: str = Field(min_length=1, max_length=320)


class MailProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    imap: ServerSettings
    smtp: ServerSettings
    auth: MailAuth
    mailboxes: list[str] = Field(default_factory=lambda: ["INBOX"])
    # When the login isn't the person's mail address, as with many company accounts.
    address: str | None = Field(default=None, max_length=320)


class GetMailAccounts(BaseModel):
    pass


class MailAccountView(BaseModel):
    name: str
    profile: MailProfile
    has_password: bool


class MailAccounts(BaseModel):
    active: str | None
    accounts: list[MailAccountView]


class SaveMailAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    profile: MailProfile
    password: str | None = Field(default=None, max_length=1024)
    make_active: bool = True
    # The newest this many come down, and new mail always does. Empty means all of it.
    pull_limit: int | None = Field(default=None, ge=1)


class TestMailAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: MailProfile
    password: str | None = Field(default=None, max_length=1024)


class ConnectionResult(BaseModel):
    service: Literal["imap", "smtp"]
    ok: bool
    message: str


class MailFolderCount(BaseModel):
    role: str
    messages: int


class MailTestResult(BaseModel):
    ok: bool
    results: list[ConnectionResult]
    # What's in the folders that get downloaded, so the person can choose how much to pull.
    counts: list[MailFolderCount] = Field(default_factory=list)
    suggested_pull: int = 0


class SetPullLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pull_limit: int | None = Field(default=None, ge=1)


class MailPulled(BaseModel):
    found: int
    pulled: int


class RemoveMailAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)


class GetMailStatus(BaseModel):
    pass


class MailStatus(BaseModel):
    account: str | None
    state: SyncState
    message: str | None = None
    messages: int = 0
    backfill_remaining: bool = False
    # How much of what's wanted from the server has come down so far.
    total: int = 0
    done: int = 0
    pull_limit: int | None = None
    # Everything in the downloaded folders, whether wanted or not, and how much of it is here.
    server_total: int = 0
    pulled: int = 0
    check_every_seconds: int = 0
    last_check: str | None = None
    next_check: str | None = None
    last_found: int = 0
    last_pulled: int = 0
    last_found_at: str | None = None


class ProbeServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")


class ServerProbe(BaseModel):
    imap_port: int
    smtp_host: str
    smtp_port: int


class GetMailPresets(BaseModel):
    pass


class MailPreset(BaseModel):
    """Server details known in advance, so most people only need a login and password."""

    domain: str
    label: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    secure: bool = True
    password_hint: str | None = None


class MailPresets(BaseModel):
    presets: list[MailPreset]


class ListThreads(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: FolderRole | Literal["priority", "all"] = "inbox"
    category: str | None = Field(default=None, max_length=64)
    before: str | None = Field(default=None, max_length=64, description="Paging cursor")
    limit: int = Field(default=100, ge=1, le=500)


class ThreadRow(BaseModel):
    # The latest sender's name, when a list has looked it up.
    sender_name: str | None = None
    id: int
    subject: str
    participants: list[str]
    last_date: str
    snippet: str
    message_count: int
    unread_count: int
    flagged: bool
    has_attachments: bool
    category: str | None
    category_source: str | None
    why: str | None
    status: ThreadStatus
    importance: Importance


class ThreadList(BaseModel):
    threads: list[ThreadRow]
    next_before: str | None
    categories: list[str]


class GetThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class AttachmentView(BaseModel):
    index: int
    filename: str
    content_type: str
    size: int
    kind: Literal["signature", "inline", "attachment", "calendar", "risky"]


class MessageView(BaseModel):
    id: int
    subject: str
    from_name: str
    from_addr: str
    to: list[str]
    cc: list[str]
    date: str
    own_text: str
    text: str
    html: str | None
    read: bool
    flagged: bool
    folder: FolderRole
    encrypted: Literal["smime", "pgp"] | None
    signed: bool
    why: str | None
    added: list[str]
    dropped: list[str]
    attachments: list[AttachmentView]
    hidden_attachments: int


class ThreadView(BaseModel):
    thread: ThreadRow
    messages: list[MessageView]


class SetThreadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    read: bool


class SetThreadFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    flagged: bool


class MoveThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    to: FolderRole


class SetThreadStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    status: ThreadStatus


class SetThreadCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    category: str | None = Field(default=None, max_length=64)


class MailDone(BaseModel):
    ok: bool = True


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["subject", "body", "sender", "header", "has_attachment"]
    value: str = Field(default="", max_length=500)
    header: str | None = Field(default=None, max_length=100)


class RuleActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=64)
    mark_read: bool = False
    skip_agent: bool = False
    notify: bool = False
    tag: str | None = Field(default=None, max_length=64)


class MailRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    conditions: list[RuleCondition] = Field(min_length=1, max_length=20)
    actions: RuleActions


class MailCategory(BaseModel):
    name: str
    source: Literal["user", "agent", "rule"]
    in_priority: bool
    proposed: bool
    why: str | None = None
    sender: str | None = None
    subject: str | None = None
    count: int = 0
    unread: int = 0
    created: str | None = None
    updated: str | None = None


class ListCategories(BaseModel):
    pass


class CategoryList(BaseModel):
    categories: list[MailCategory]


class SaveCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    in_priority: bool = False
    sender: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=500)
    source: Literal["user", "agent"] = "user"


class CategorySaved(CategoryList):
    filed: int = 0


class UpdateCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    new_name: str | None = Field(default=None, min_length=1, max_length=64)
    in_priority: bool | None = None
    sender: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=500)
    clear_rule: bool = False


class MergeCategories(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(min_length=1, max_length=200)
    into: str = Field(min_length=1, max_length=64)


class ReorderCategories(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(max_length=500)


class CategoryName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


class DecideCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    accept: bool


class GetRules(BaseModel):
    pass


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[MailRule] = Field(max_length=500)


class Recipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    address: str = Field(max_length=320, pattern=r"^[^@\s<>]+@[^@\s<>]+$")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    thread_id: int | None = None
    reply_to_message_id: int | None = None
    to: list[Recipient] = Field(default_factory=list, max_length=500)
    cc: list[Recipient] = Field(default_factory=list, max_length=500)
    bcc: list[Recipient] = Field(default_factory=list, max_length=500)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=2_000_000)
    source: Literal["user", "agent"] = "user"


class SendDraft(BaseModel):
    """Sending is the person's own click; nothing else calls this without their approval."""

    model_config = ConfigDict(extra="forbid")

    draft: Draft


class ListDrafts(BaseModel):
    pass


class DraftList(BaseModel):
    drafts: list[Draft]


class RemoveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class ReplyContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int
    reply_all: bool = True


class ReplyDraft(BaseModel):
    """A starting draft, plus anyone from the conversation who won't get it (THR-9)."""

    draft: Draft
    dropped: list[str]


class SearchMail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    sender: str | None = Field(default=None, max_length=320)
    date_from: str | None = Field(default=None, max_length=32)
    date_to: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=64)
    has_attachment: bool | None = None
    folder: FolderRole | None = None
    limit: int = Field(default=100, ge=1, le=500)


class SearchHit(BaseModel):
    thread: ThreadRow
    message_id: int
    excerpt: str
    matched_attachment: bool
    # words, meaning or both, so the person can see why it's here.
    matched_by: str = "words"


class SearchResults(BaseModel):
    hits: list[SearchHit]


class MailChanged(BaseModel):
    """Counts and IDs only, never content."""

    threads: int
    reason: str


class MailSyncChanged(BaseModel):
    state: SyncState


class MailReceived(BaseModel):
    message_id: int
    thread_id: int
    rule: str | None


class ThreadUpdated(BaseModel):
    thread_id: int
    field: str
    value: Any = None


PstStatus = Literal["queued", "running", "paused", "done", "failed"]


class GetPstImports(BaseModel):
    pass


class PstImport(BaseModel):
    id: int
    name: str
    path: str
    status: PstStatus
    total: int
    position: int
    imported: int
    duplicates: int
    failed: int
    error: str | None


class PstImports(BaseModel):
    imports: list[PstImport]


class AddPstImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


class FindPst(BaseModel):
    model_config = ConfigDict(extra="forbid")

    everywhere: bool = False


class GetPstSearch(BaseModel):
    pass


class FoundPst(BaseModel):
    path: str
    name: str
    size: int
    modified: str


class PstSearchStatus(BaseModel):
    state: Literal["idle", "running", "done", "stopped"]
    everywhere: bool = False
    place: str | None = None
    scanned: int = 0
    found: list[FoundPst] = Field(default_factory=list)


class StartPstUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0)
    modified: int = 0


class PstUploadStarted(BaseModel):
    id: str
    received: int


class PstUploadStatus(BaseModel):
    received: int
    size: int
    # Set once the whole file is here.
    path: str | None = None


class PstImportAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


CheckLevel = Literal["off", "warn", "block"]


class SendCheckSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_recipient: CheckLevel = "warn"
    missing_attachment: CheckLevel = "warn"
    newer_reply: CheckLevel = "warn"
    undo_seconds: int = Field(default=5, ge=0, le=60)


class GetSendChecks(BaseModel):
    pass


class CheckDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: Draft
    written_after: str | None = Field(default=None, max_length=64)


class SendProblem(BaseModel):
    check: str
    level: Literal["warn", "block"]
    message: str


class SendCheckResult(BaseModel):
    problems: list[SendProblem]
    undo_seconds: int
