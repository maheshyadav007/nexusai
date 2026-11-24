from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ThreadStatus = Literal["none", "waiting_on_you", "waiting_on_others", "resolved", "fyi"]
Importance = Literal["low", "normal", "high"]
FolderRole = Literal["inbox", "sent", "drafts", "trash", "archive", "other", "junk"]
SyncState = Literal[
    "off", "paused", "connecting", "syncing", "backfilling", "live", "offline", "failed"
]


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    secure: bool = True
    # Only POP3 can turn this off, for a company server with its own certificate.
    verify_cert: bool = True


class MailAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["password"] = "password"
    user: str = Field(min_length=1, max_length=320)


class MailProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    protocol: Literal["imap", "pop3"] = "imap"
    # Its servers come from the system settings, which win over anything saved here.
    system: bool = False
    # The server mail comes from, whichever protocol it speaks.
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
    # How many older emails to bring down. New mail always comes. Empty means all of them.
    pull_limit: int | None = Field(default=None, ge=0)


class TestMailAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: MailProfile
    password: str | None = Field(default=None, max_length=1024)


class ConnectionResult(BaseModel):
    service: Literal["imap", "smtp"]
    ok: bool
    message: str


class MailFolderCount(BaseModel):
    name: str
    role: str
    messages: int


class MailTestResult(BaseModel):
    ok: bool
    results: list[ConnectionResult]
    # What's on the server, so the person can choose how much to pull.
    counts: list[MailFolderCount] = Field(default_factory=list)
    # How many different emails that is. On Gmail one email can be in many folders.
    total: int = 0
    suggested_pull: int = 0


class GetMoreMail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Empty means everything still on the server.
    count: int | None = Field(default=None, ge=1)
    # Just from this folder, or from all of them in turn.
    folder: str | None = Field(default=None, max_length=500)


class SetSenderImages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=1, max_length=320)
    allow: bool


class StopHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetNeverDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool


class ChangeThreadFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    folder: str = Field(min_length=1, max_length=500)


class ChangeThreadCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str = Field(min_length=1, max_length=64)


class ListMailFolders(BaseModel):
    pass


class MailFolder(BaseModel):
    name: str
    # The last part of its path, and where it sits, for showing nested folders.
    label: str
    parent: str | None = None
    role: str
    on_server: int = 0
    here: int = 0
    unread: int = 0
    # Gmail's own Starred and Important: the app's views of the same names stand for them.
    shown_elsewhere: bool = False


class MailFolders(BaseModel):
    folders: list[MailFolder]
    # Unread conversations in the fixed folders, like priority and all.
    counts: dict[str, int] = Field(default_factory=dict)


class MailHistoryFinished(BaseModel):
    pulled: int
    total: int
    reason: Literal["enough", "everything"]


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
    # Older emails still allowed to come down. Empty means all of them.
    history_budget: int | None = None
    history_finished: bool = False
    never_delete: bool = True
    # Every different email on the server, whether wanted or not, and how many are here.
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
    protocol: Literal["imap", "pop3"] = "imap"
    # Set by whoever runs this app, so the person only gives a username and password.
    system: bool = False
    # Makes the mail address for a login with no @ in it.
    address_domain: str | None = None


class MailPresets(BaseModel):
    presets: list[MailPreset]


class ListThreads(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: FolderRole | Literal["priority", "important", "starred", "all", "reads", "kept"] = (
        "inbox"
    )
    # One folder on the server, by its full name. This takes the place of folder.
    location: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=64)
    before: str | None = Field(default=None, max_length=64, description="Paging cursor")
    # For jumping to a place in the list, which a scrollbar can do.
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class MarkFolderRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: FolderRole | Literal["priority", "important", "starred", "all", "reads", "kept"] = "all"
    location: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=64)


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
    extra_categories: list[str] = Field(default_factory=list)
    why: str | None
    status: ThreadStatus
    importance: Importance
    # Kept from the AI by its folder, but a person replying named the person, so the AI reads it:
    # who, and the words that named them.
    named: str | None = None


class ThreadList(BaseModel):
    threads: list[ThreadRow]
    next_before: str | None
    categories: list[str]
    # How many conversations the whole list has, however many came in this page.
    total: int


class GetThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class AttachmentView(BaseModel):
    index: int
    filename: str
    content_type: str
    size: int
    kind: Literal["signature", "inline", "attachment", "calendar", "risky"]


class MailFolderRef(BaseModel):
    name: str
    role: str


class MessageView(BaseModel):
    # Every folder this one email is in.
    folders: list[MailFolderRef] = Field(default_factory=list)
    # Whether its outside images load without asking.
    show_images: bool = True
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


class SetThreadImportance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    importance: Importance


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


class ThreadToInbox(BaseModel):
    """Back to the Inbox the person sees, for the AI to read. With always, the sender's mail to
    come gets there too."""

    model_config = ConfigDict(extra="forbid")

    id: int
    always: bool = False


class HideFromAi(BaseModel):
    """Takes mail away from the AI from wherever it's seen: everything from the conversation's
    sender, or just the conversation."""

    model_config = ConfigDict(extra="forbid")

    thread: int
    scope: Literal["sender", "conversation"] = "sender"


class HidePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread: int


class HideFromAiPreview(BaseModel):
    # Who "everything from" means; empty when only the person wrote in the conversation.
    sender: str = ""
    sender_name: str = ""
    sender_emails: int = 0
    conversation_emails: int = 0
    # The folder its mail would go to.
    folder: str = ""


class HiddenFromAi(BaseModel):
    undo: int
    folder: str
    emails: int


class UndoHide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    undo: int


class ThreadInInbox(BaseModel):
    # Who "always" would apply to; empty when the conversation has no sender to go by.
    sender: str = ""


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal[
        "subject",
        "subject_prefix",
        # Every one of these words, in any order, as whole words: "otp login".
        "subject_words",
        "tag",
        "body",
        "sender",
        "sender_exact",
        # Who it's sent to: To or Cc has this.
        "to",
        "header",
        "has_attachment",
    ]
    value: str = Field(default="", max_length=500)
    header: str | None = Field(default=None, max_length=100)


class RuleActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=64)
    mark_read: bool = False
    skip_agent: bool = False
    # Skips what a system sends, but a reply means a person got involved, so the agent reads that.
    read_replies: bool = False
    notify: bool = False
    tag: str | None = Field(default=None, max_length=64)
    # Skipped mail that names the person still goes to the agent: their address and name.
    mentions: list[str] = Field(default_factory=list, max_length=4)


class MailRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    # Every condition must hold, or any one is enough.
    match: Literal["all", "any"] = "all"
    conditions: list[RuleCondition] = Field(min_length=1, max_length=20)
    # Mail that matches any of these is left alone, whatever the conditions say.
    exceptions: list[RuleCondition] = Field(default_factory=list, max_length=20)
    actions: RuleActions


class MailCategory(BaseModel):
    mode: Literal["exact", "smart"] = "smart"
    description: str = ""
    name: str
    source: Literal["user", "agent", "rule"]
    in_priority: bool
    proposed: bool
    priority_suggested: bool = False
    priority_why: str | None = None
    needed_you: int = 0
    why: str | None = None
    sender: str | None = None
    subject: str | None = None
    count: int = 0
    unread: int = 0
    created: str | None = None
    updated: str | None = None
    # False for folders the AI skips, like Automated and what the Sort step files under it.
    ai_reads: bool = True
    # Of its conversations, how many a sorting rule keeps from the AI. Sorting decides by
    # sender, so a folder can hold both: Shopping's store mail kept, a delivery question read.
    kept: int = 0
    # The folder it's inside, or none at the top of its home. Its side comes from its home.
    parent: str | None = None
    # How many senders a rule files here on each side; both above zero means it needs splitting.
    senders_read: int = 0
    senders_kept: int = 0


class ListCategories(BaseModel):
    pass


class CategoryList(BaseModel):
    categories: list[MailCategory]


class SaveCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    in_priority: bool = True
    mode: Literal["exact", "smart"] | None = None
    description: str = Field(default="", max_length=500)
    sender: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=500)
    source: Literal["user", "agent"] = "user"
    # Inside this folder, or empty for the top of a home; then ai_reads says which home.
    parent: str | None = Field(default=None, max_length=64)
    ai_reads: bool = True
    # A rule of any shape, every condition matching; takes the place of sender and subject.
    conditions: list["RuleCondition"] = Field(default_factory=list, max_length=10)
    # Whether mail already here that matches is filed too, or only what comes from now on.
    file_existing: bool = True


class PreviewCategoryRule(BaseModel):
    """How many conversations already here a folder's rule would file, saving nothing."""

    model_config = ConfigDict(extra="forbid")

    conditions: list["RuleCondition"] = Field(min_length=1, max_length=10)


class CategoryRulePreview(BaseModel):
    conversations: int


class MixedFolder(BaseModel):
    """A folder with senders on both sides, and what its two halves would be."""

    name: str
    read_senders: list["SenderCount"]
    kept_senders: list["SenderCount"]
    read_emails: int
    kept_emails: int
    suggested: str


class SenderCount(BaseModel):
    sender: str
    emails: int


class ListMixedFolders(BaseModel):
    pass


class MixedFolders(BaseModel):
    folders: list[MixedFolder]


class FolderSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    # What the half kept from the AI is called; the half the AI reads keeps the name.
    kept_name: str = Field(min_length=1, max_length=64)


class SplitFolders(BaseModel):
    model_config = ConfigDict(extra="forbid")

    splits: list[FolderSplit] = Field(min_length=1, max_length=100)
    # Puts each kept half back into the folder it came from.
    undo: bool = False


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
    mode: Literal["exact", "smart"] | None = None
    description: str | None = Field(default=None, max_length=500)
    # Whether the AI reads it. Every sender filed there moves to that side with it. A folder
    # inside another takes its parent's side, so this moves it to the top of the other home.
    ai_reads: bool | None = None
    # Moves it inside this folder; empty moves it to the top of its home (or of ai_reads').
    parent: str | None = Field(default=None, max_length=64)


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


class DecidePriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    accept: bool


class DecideCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    accept: bool


class GetRules(BaseModel):
    pass


class MailMe(BaseModel):
    """Who the person is, as people write it. A person replying on mail the AI doesn't read who
    uses one of these has named them, and the AI reads that reply."""

    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=list, max_length=20)
    addresses: list[str] = Field(default_factory=list, max_length=20)
    # How tools and colleagues tag them: myadav01, m.yadav.
    ids: list[str] = Field(default_factory=list, max_length=20)
    # Other people whose names look like theirs: Mahesh Kumar, Maheshwari.
    not_you: list[str] = Field(default_factory=list, max_length=50)


class GetMailMe(BaseModel):
    pass


class PreviewMe(BaseModel):
    """The names a person is trying, before saving them: theirs and their teams', in one list."""

    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=list, max_length=40)


class MeExample(BaseModel):
    """One reply in hidden mail that one of the names would let through, and the name it used."""

    sender: str
    folder: str | None
    quote: str
    word: str


class MePreview(BaseModel):
    # How many hidden replies each name lets through, and how many all of them do together.
    counts: dict[str, int]
    total: int
    examples: list[MeExample]


class NamedYou(BaseModel):
    thread: int
    subject: str
    sender: str
    folder: str | None
    quote: str
    date: str


class NamedYouList(BaseModel):
    items: list[NamedYou]


class GetNamedYou(BaseModel):
    pass


class PreviewRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: MailRule


class RuleExample(BaseModel):
    thread: int
    subject: str
    sender: str
    date: str
    # A reply on it named the person, so the AI still reads it.
    named: str | None = None


class RulePreview(BaseModel):
    conversations: int
    named: int
    examples: list[RuleExample]


class NotAboutMe(BaseModel):
    """A reply that named the person wasn't about them. It goes back to its folder for the AI,
    and, when given, the name that misled is fixed so it holds from now on."""

    model_config = ConfigDict(extra="forbid")

    thread: int
    # Someone else's name, to add to Not you.
    not_you: str | None = Field(default=None, max_length=120)
    # One of the person's names, to stop counting.
    stop: str | None = Field(default=None, max_length=120)


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Sorting writes one per sender, so a big mailbox has thousands.
    rules: list[MailRule] = Field(max_length=5000)


class Recipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    address: str = Field(max_length=320, pattern=r"^[^@\s<>]+@[^@\s<>]+$")


class DraftAttachment(BaseModel):
    """A file going out with a draft: one added in the composer, or one already in NexusAI."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=500)
    size: int = Field(default=0, ge=0)
    # A file added in the composer, kept until the draft is sent or thrown away.
    upload: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    # Or a document, or an email's attachment such as m:123:2, read when the mail goes.
    key: str | None = Field(default=None, max_length=300)


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
    attachments: list[DraftAttachment] = Field(default_factory=list, max_length=50)


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


class ForwardContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int


class SuggestRecipients(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=200)


class RecipientSuggestions(BaseModel):
    people: list[Recipient]


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
    folder: (
        FolderRole | Literal["priority", "important", "starred", "all", "reads", "kept"] | None
    ) = None
    # One folder on the server, by its full name.
    location: str | None = Field(default=None, max_length=500)
    recipient: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=500)
    unread: bool | None = None
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
    # Nothing matched as typed, so these words were used instead.
    corrected: str | None = None
    # How many hits, from the top, have every word. The rest only have some.
    with_every_word: int = 0


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
    old_value: Any = None
    thread_id: int
    field: str
    value: Any = None
    by: str = "person"


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


class LearningGroupView(BaseModel):
    id: str
    sender: str
    subject: str
    note: str
    importance: Importance


class FolderMergeSuggestion(BaseModel):
    into: str
    names: list[str]


class LearningFolderSuggestion(BaseModel):
    name: str
    senders: int
    emails: int


class MissedConversation(BaseModel):
    id: int
    subject: str


class MailOrganization(BaseModel):
    metrics: dict[str, int] = Field(default_factory=dict)
    state: str
    interview: str | None = None
    groups: list[LearningGroupView] = Field(default_factory=list)
    done: int = 0
    total: int = 0
    missed: list[MissedConversation] = Field(default_factory=list)
    merges: list[FolderMergeSuggestion] = Field(default_factory=list)
    suggestions: list[LearningFolderSuggestion] = Field(default_factory=list)


class FinishMailLearning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    importance: dict[str, Importance] = Field(default_factory=dict, max_length=1000)


class SortCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    confirm: bool = False


class CategorySortEstimate(BaseModel):
    conversations: int
    estimated_tokens: int
    queued: int = 0


# Sorting mail before the AI reads it


class GetMailSort(BaseModel):
    pass


class PrepareMailSort(BaseModel):
    # Opened again after sorting: every sender, each on the side its rule puts it now.
    again: bool = False


class SkipMailSort(BaseModel):
    pass


class SortEmail(BaseModel):
    subject: str
    sender: str
    sender_name: str
    when: str
    snippet: str


class SortKind(BaseModel):
    """One kind of mail from a sender: its tag, if any, and the words nearly all of it carries."""

    tag: str = ""
    words: list[str]
    count: int
    examples: list[str] = Field(default_factory=list)


class SortSender(BaseModel):
    """One sender on the sorting page: how automated it looks, and which side it starts on."""

    sender: str
    label: str
    count: int
    # The strongest of the four signs, from 0 to 1. At half or more the AI ignores it.
    score: float
    repeats: float
    bulk: float
    one_way: bool
    # The address says it takes no replies: noreply, no-reply, do-not-reply.
    no_reply: bool = False
    side: Literal["reads", "ignores"]
    # Why it stays with the AI whatever its score, if it does.
    kept: str
    # Starts as a category of its own under Automated, rather than going straight into it.
    own: bool
    examples: list[str]
    emails: list[SortEmail]
    # The folder a rule already files this sender's mail into, when one does. Its side is
    # the rule's, so the page shows what's true now.
    folder: str = ""
    # The kinds of mail it sends, found from its subjects. Kept from the AI, it gets a rule for
    # each, with the sender, rather than one for everything it sends; `odd` emails fit none,
    # and mail like them still reaches the AI.
    kinds: list[SortKind] = Field(default_factory=list)
    odd: int = 0
    odd_examples: list[str] = Field(default_factory=list)


class MailSort(BaseModel):
    state: Literal["none", "preparing", "ready", "failed", "done", "skipped"]
    done: int = 0
    total: int = 0
    error: str = ""
    owner_name: str = ""
    emails: int = 0
    reach_ai: int = 0
    # Invitations and replies, kept from the AI whatever happens to their senders.
    calendar: int = 0
    # Emails the person's own rules already file, left as they are and out of the list.
    already_sorted: int = 0
    senders: list[SortSender] = Field(default_factory=list)
    # Once sorted or skipped, the page can still be opened to change it; this is how far the
    # look at the mailbox for that has got.
    review: Literal["none", "preparing", "ready", "failed"] = "none"


class SortSenderChoice(BaseModel):
    """Where the person put one sender. On the ignored side, `own` gives it a category of its
    own, named `name`; senders given the same name share one."""

    model_config = ConfigDict(extra="forbid")

    sender: str = Field(max_length=320)
    side: Literal["reads", "ignores"]
    own: bool = False
    name: str = Field(default="", max_length=60)
    # Put in this exact folder, mail and all, as the one rule for this sender: one the page
    # showed, or one made there. Empty is the Inbox. Unset, it's sorted by side, own and name.
    folder: str | None = Field(default=None, max_length=64)


class ApplyMailSort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    senders: list[SortSenderChoice] = Field(default_factory=list, max_length=20000)


class MailSortApplied(BaseModel):
    moved: int
