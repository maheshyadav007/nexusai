from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GuardAction = Literal["mask", "block"]


class GuardRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern=r"^[A-Z][A-Z_]*$", max_length=32)
    pattern: str = Field(min_length=1, max_length=2000)
    action: GuardAction = "mask"
    enabled: bool = True


class GuardRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[GuardRule] = Field(max_length=200)


class GetGuardRules(BaseModel):
    pass


class TestGuardRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[GuardRule] = Field(max_length=200)
    sample: str = Field(max_length=20000)


class GuardFinding(BaseModel):
    rule: str
    value: str
    action: GuardAction


class GuardTestResult(BaseModel):
    masked: str
    findings: list[GuardFinding]
    errors: list[str]


class PromptLayerView(BaseModel):
    name: str
    real: str
    masked: str


class ModelCallView(BaseModel):
    id: int
    time: str
    session: str | None
    agent: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    layers: list[PromptLayerView]
    status: str
    error: str | None = None


class GetModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    session: str | None = Field(default=None, max_length=64)


class GetUsage(BaseModel):
    pass


class UsageRow(BaseModel):
    agent: str
    input_tokens: int
    output_tokens: int
    calls: int


class UsageView(BaseModel):
    today: list[UsageRow]
    total_today: int
    daily_cap: int
    near_cap: bool


class SetDailyCap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_cap: int = Field(ge=0)


class AgentChanged(BaseModel):
    """Short facts only."""

    kind: str
    id: str | int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


SessionStatus = Literal["queued", "running", "waiting", "done", "failed", "stopped"]
Permission = Literal["off", "ask", "allow"]
ApprovalStatus = Literal["pending", "approved", "denied"]
ApprovalChoice = Literal["once", "session", "deny"]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    context: list[str] = Field(default_factory=list, max_length=20)
    agent: Literal["session", "interview"] = "session"
    # Empty means the model chosen in Settings.
    model: str | None = Field(default=None, max_length=128)


class SessionRow(BaseModel):
    id: str
    title: str
    agent: str
    status: SessionStatus
    step: str | None
    error: str | None
    untrusted: bool
    input_tokens: int
    output_tokens: int
    created: str
    updated: str
    archived: bool
    model: str | None = None


class ListSessions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200)
    archived: bool = False


class SessionList(BaseModel):
    sessions: list[SessionRow]
    running: int
    limit: int


class SessionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class RenameSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    title: str = Field(min_length=1, max_length=200)


class SetSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    model: str | None = Field(default=None, max_length=128)


class ChooseVersion(BaseModel):
    """Which answer to keep going from, after trying a message again."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    turn: int


class RateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int
    value: Literal["up", "down"] | None = None


class SessionCompaction(BaseModel):
    after_turn: int
    time: str
    before_tokens: int
    after_tokens: int
    how: str


class SessionView(BaseModel):
    session: SessionRow
    messages: list[dict[str, Any]]
    active: bool
    compactions: list[SessionCompaction] = Field(default_factory=list)


class ApprovalPreview(BaseModel):
    """What's being approved, briefly, with all of it a click away."""

    kind: Literal["command", "file", "mail", "change", "other"]
    summary: str
    language: str = "text"
    content: str = ""
    location: str | None = None


class ToolApproval(BaseModel):
    preview: ApprovalPreview | None = None
    id: int
    session: str
    session_title: str
    tool_call_id: str
    tool: str
    summary: str
    reason: str
    detail: str
    undoable: bool
    status: ApprovalStatus
    time: str
    tool_label: str = ""
    # Whether saying yes for the rest of the session would actually hold.
    can_remember: bool = False


class ListApprovals(BaseModel):
    pass


class ApprovalList(BaseModel):
    approvals: list[ToolApproval]


class DecideApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    choice: ApprovalChoice


class DecideApprovals(BaseModel):
    """Several at once, so a run making many calls doesn't take as many clicks."""

    model_config = ConfigDict(extra="forbid")

    allow: list[int] = Field(default_factory=list, max_length=500)
    deny: list[int] = Field(default_factory=list, max_length=500)
    remember: bool = False


class AgentDone(BaseModel):
    ok: bool = True


class GetPermissions(BaseModel):
    pass


class Permissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: Permission = "allow"
    write: Permission = "allow"
    command: Permission = "ask"
    # Changes to the person's own data, such as tasks, reminders and categories.
    data: Permission = "allow"
    # One tool's setting, which wins over the groups above.
    tools: dict[str, Permission] = Field(default_factory=dict)
    folders: list[str] = Field(default_factory=list, max_length=100)
    full_computer_access: bool = False


class ToolInfo(BaseModel):
    name: str
    group: str
    label: str
    description: str
    level: Permission
    # Sending always asks, so "allow" isn't offered.
    can_allow: bool = True


class GetToolCatalog(BaseModel):
    pass


class ToolCatalog(BaseModel):
    tools: list[ToolInfo]


class AnswerSession(BaseModel):
    """Answers whatever the session is asking, from its card or the message box."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    answer: str = Field(min_length=1, max_length=20000)


class ActivityRow(BaseModel):
    id: int
    time: str
    session: str | None
    summary: str
    undoable: bool
    undone: bool


class ListActivity(BaseModel):
    pass


class ActivityList(BaseModel):
    items: list[ActivityRow]


class UndoActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class SessionChat(BaseModel):
    """What the chat screen sends: which session, and what the person typed."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=200000)
    # Asks the latest message again, keeping the answer it already has.
    retry: bool = False


MemoryLevel = Literal["user", "agent"]


class MemoryFile(BaseModel):
    path: str
    level: MemoryLevel
    agent: str | None
    name: str
    content: str
    source: str | None = None
    updated: str


class ListMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200)


class MemoryList(BaseModel):
    files: list[MemoryFile]
    proposals: list["MemoryProposal"]


class MemoryProposal(BaseModel):
    id: int
    agent: str
    text: str
    source: str | None
    time: str


class SaveMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, max_length=300)
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .-]+$")
    level: MemoryLevel = "user"
    agent: str | None = Field(default=None, max_length=64)
    content: str = Field(max_length=100000)


class RemoveMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=300)


class DecideMemoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    accept: bool


class PromptFile(BaseModel):
    name: str
    title: str
    kind: Literal["personal", "agent"]
    content: str
    base: str | None = None
    # What it was filled with to begin with, so an edit can be told from an untouched starter.
    starter: str | None = None


class ListPrompts(BaseModel):
    pass


class PromptList(BaseModel):
    prompts: list[PromptFile]


class SavePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["personal", "agent"]
    name: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    content: str = Field(max_length=100000)


class ChannelMessage(BaseModel):
    id: int
    kind: Literal["ask", "suggest", "tell"]
    agent: str
    session: str | None
    thread: int | None
    text: str
    options: list[str]
    multiple: bool = False
    status: Literal["open", "answered", "dismissed"]
    answer: str | None
    time: str
    urgent: bool
    count: int


class ListChannel(BaseModel):
    pass


class ChannelList(BaseModel):
    messages: list[ChannelMessage]


class RespondChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    answer: str = Field(min_length=1, max_length=4000)


class DismissChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class BoardItem(BaseModel):
    id: int
    kind: str
    title: str
    thread: int | None
    due: str | None
    by: str
    updated: str
    done: bool


class ListBoard(BaseModel):
    pass


class BoardList(BaseModel):
    items: list[BoardItem]


class AgentChannelMessage(BaseModel):
    id: int
    sender: str
    recipient: str | None
    topic: str | None
    text: str
    time: str
    untrusted: bool


class ListAgentChannel(BaseModel):
    pass


class AgentChannelList(BaseModel):
    messages: list[AgentChannelMessage]
    muted: list[str]


class SetTopicMuted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(max_length=64)
    muted: bool


class TriageRun(BaseModel):
    id: int
    message: int
    thread: int
    time: str
    status: Literal["done", "failed"]
    summary: str | None
    reason: str | None
    facts: list[str]
    suggested_action: str | None
    provisional: bool
    error: str | None
    call_id: int | None


class GetThreadRuns(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread: int


class ThreadRuns(BaseModel):
    runs: list[TriageRun]


class TriageExisting(BaseModel):
    """Older mail is only triaged on request, after showing how much work it is."""

    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


class TriageEstimate(BaseModel):
    untriaged: int
    queued: int
    approx_tokens: int


class SummarizeThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class DraftThreadReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class DraftedReply(BaseModel):
    body: str
    # Set when it's a draft already saved, so changes to it go there and not to a second one.
    draft_id: int | None = None


class ThreadSummary(BaseModel):
    thread: int
    text: str | None
    covered: int
    new_messages: int
    updated: str | None


class Job(BaseModel):
    id: str
    kind: Literal[
        "sync",
        "pst",
        "pst-search",
        "pst-upload",
        "triage",
        "session",
        "schedule",
        "trigger",
        "model",
        "index",
        "reading",
    ]
    title: str
    status: str
    progress: int | None = None
    total: int | None = None
    link: str | None = None


class ListJobs(BaseModel):
    pass


class PipelineFact(BaseModel):
    label: str
    value: str


class Pipeline(BaseModel):
    """Work that runs on a timer with no agent or model involved."""

    id: str
    title: str
    cadence: str
    state: Literal["running", "waiting", "stopped", "problem"]
    # What's going on, when that isn't just waiting for the next run.
    message: str | None = None
    facts: list[PipelineFact] = Field(default_factory=list)
    last_run: str | None = None
    next_run: str | None = None
    # False when there's nothing it could do yet, such as no account to sync.
    available: bool = True
    # Older work is still coming, so Stop means something. Get more is offered once it's done.
    history_open: bool = False
    # How much is still out there to get.
    left: int = 0
    link: str | None = None


class ListPipelines(BaseModel):
    pass


class PipelineList(BaseModel):
    pipelines: list[Pipeline]


class PausePipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    paused: bool


class RunPipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class PipelineMore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    # Empty means all that's left.
    count: int | None = Field(default=None, ge=1)


class UpcomingRun(BaseModel):
    id: int
    title: str
    when: str


class HealthItem(BaseModel):
    id: str
    label: str
    state: Literal["ok", "working", "problem", "off"]
    detail: str
    link: str | None = None
    when: str | None = None


ContextMode = Literal["trim", "auto_compact"]
TriggerEvent = Literal["mail.received", "mail.urgent"]


class Trigger(BaseModel):
    """Something that starts an agent. The built-in one looks after new mail."""

    id: str
    title: str
    kind: Literal["mail", "custom"]
    event: str
    prompt: str = ""
    enabled: bool = True
    token_limit: int = 0
    context_mode: ContextMode | None = None
    keep_messages: int | None = None
    session: str | None = None


class TriggerChoice(BaseModel):
    event: str
    label: str


class GetTriggers(BaseModel):
    pass


class TriggerList(BaseModel):
    triggers: list[Trigger]
    events: list[TriggerChoice]


class SaveTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    # Only from this list, because an event an agent can cause could set off a loop.
    event: TriggerEvent = "mail.urgent"
    prompt: str = Field(default="", max_length=20000)
    enabled: bool = True
    token_limit: int = Field(default=0, ge=0)
    context_mode: ContextMode | None = None
    keep_messages: int | None = Field(default=None, ge=0, le=1000)


class RemoveTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class GetCockpit(BaseModel):
    pass


class Cockpit(BaseModel):
    """What's going on in the app, right now."""

    jobs: list[Job]
    upcoming: list[UpcomingRun]
    health: list[HealthItem]


class GetCockpitEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: Literal["all", "agents", "mail", "indexing", "problems"] = "all"
    before: int | None = None
    limit: int = Field(default=50, ge=1, le=200)


class CockpitEvent(BaseModel):
    seq: int
    time: str
    type: str
    group: str
    title: str
    detail: str | None = None
    link: str | None = None
    problem: bool = False


class CockpitEvents(BaseModel):
    events: list[CockpitEvent]


class JobList(BaseModel):
    jobs: list[Job]


class SetSessionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    context: list[str] = Field(max_length=20)


class ContextItem(BaseModel):
    ref: str
    label: str


class SessionContext(BaseModel):
    items: list[ContextItem]


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    start: str = Field(default="22:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="07:00", pattern=r"^\d{2}:\d{2}$")
    channel_daily_limit: int = Field(default=20, ge=0, le=500)


class GetQuietHours(BaseModel):
    pass


class ContextProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ContextMode = "trim"
    keep_messages: int = Field(default=40, ge=0, le=1000)
    trim_saved_history: bool = False


class CompactSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_tokens: int = Field(default=15000, ge=1000)
    keep_messages: int = Field(default=12, ge=0, le=1000)
    summarize_up_to_tokens: int = Field(default=4000, ge=500)


class ToolResultSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clear_after_tokens: int = Field(default=100000, ge=1000)
    keep_recent: int = Field(default=3, ge=0, le=100)


class ContextSettings(BaseModel):
    """How much of a conversation the model is sent. The chat always shows all of it."""

    model_config = ConfigDict(extra="forbid")

    chat: ContextProfile
    triggered: ContextProfile
    compact: CompactSettings
    tool_results: ToolResultSettings


class GetContextSettings(BaseModel):
    pass


class CompactResult(BaseModel):
    compacted: bool


MailMode = Literal["each", "hourly", "both"]


class MailAgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: MailMode = "both"
    # How many past emails the rule engine didn't catch it reads before going live.
    learn_emails: int | None = Field(default=None, ge=0, le=5000)
    # Filled in when read, to say how that's going.
    learning_state: str | None = None
    learning_done: int | None = None
    learning_total: int | None = None
    tokens_per_email: int | None = None
    # What it does on its own besides judging each email.
    morning_brief: bool | None = None
    inbox_review: bool | None = None


class GetMailAgentSettings(BaseModel):
    pass


class RunMailAgent(BaseModel):
    pass


class MailAgentRun(BaseModel):
    outcome: Literal["started", "nothing"]


class Schedule(BaseModel):
    id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=20000)
    kind: Literal["prompt", "daily-prep", "mail-hourly", "mail-brief", "mail-review"] = "prompt"
    every: Literal["once", "hour", "day", "week"] = "day"
    time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=0, ge=0, le=6)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    enabled: bool = True
    token_limit: int = Field(default=0, ge=0)
    # Empty means the default for events and schedules.
    context_mode: ContextMode | None = None
    keep_messages: int | None = Field(default=None, ge=0, le=1000)


class ScheduleRow(Schedule):
    next_run: str | None
    last_run: str | None
    last_session: str | None
    created: str | None = None
    updated: str | None = None


class ListSchedules(BaseModel):
    pass


class ScheduleList(BaseModel):
    schedules: list[ScheduleRow]
    time_check_enabled: bool
    live_mail_enabled: bool


class RemoveSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class RunSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class SetDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_check_enabled: bool | None = None
    live_mail_enabled: bool | None = None


class TodayThread(BaseModel):
    id: int
    subject: str
    people: list[str]
    importance: str
    status: str
    category: str | None
    last_date: str
    why: str | None
    # How long since anyone wrote, for mail that's waiting on someone else.
    quiet_days: int = 0
    next_action: str | None = None
    follow_up_on: str | None = None


class DueItem(BaseModel):
    kind: Literal["task", "reminder", "deadline"]
    title: str
    when: str
    overdue: bool
    link: str
    task_id: int | None = None


class SinceLastLook(BaseModel):
    since: str | None
    mail: int
    important: int
    filed: int
    judged: int
    proposed: int


class ReactToBrief(BaseModel):
    """What the person thought of a morning brief, which the next one goes by."""

    model_config = ConfigDict(extra="forbid")

    session: str = Field(max_length=64)
    rating: Literal["up", "down"] | None = None
    comment: str = Field(default="", max_length=2000)


class BriefReaction(BaseModel):
    day: str
    rating: str | None = None
    comment: str = ""


class BriefReacted(BaseModel):
    rating: str | None = None
    comment: str = ""


class AgentEntry(BaseModel):
    id: str
    name: str
    does: str
    state: Literal["running", "active", "finished", "off", "past"]
    when: str
    next_run: str | None = None
    # What it's waiting for, when that isn't a time.
    next_condition: str | None = None
    last_run: str | None = None
    session: str | None = None
    tokens: int = 0


class ListAgents(BaseModel):
    pass


class AgentRegistry(BaseModel):
    agents: list[AgentEntry]


class TodayView(BaseModel):
    brief: str
    needs_you: list[TodayThread]
    # Waiting on someone, and it's time to chase them.
    follow_ups: list[TodayThread] = Field(default_factory=list)
    waiting: list[TodayThread]
    automated_count: int
    prep_session: str | None
    prep_text: str | None
    prep_at: str | None = None
    prep_rating: str | None = None
    prep_comment: str = ""
    due: list[DueItem] = Field(default_factory=list)
    since_last_look: SinceLastLook | None = None


class MarkTodaySeen(BaseModel):
    pass


class MailSuggestion(BaseModel):
    id: int
    category: str
    senders: list[str]
    reason: str
    # Also keeps this mail away from the agent, and archives what's old and read.
    quiet: bool
    emails: int
    # Counted by the app, so the person never has to take the agent's word for it.
    opened: int
    replied: int
    to_archive: int


class ListMailSuggestions(BaseModel):
    pass


class MailSuggestionList(BaseModel):
    suggestions: list[MailSuggestion]


class DecideMailSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    accept: bool


class ContactRow(BaseModel):
    address: str
    written: int
    last: str


class CorrectionRow(BaseModel):
    sender: str
    field: str
    value: str
    said: str
    times: int
    latest: str


class LearnedNote(BaseModel):
    line: str
    text: str
    section: str
    thread: int | None
    # The person said it's true, so it's always kept and treated as what they said.
    confirmed: bool = False


class KnowledgeLayer(BaseModel):
    name: str
    text: str
    trust: str


class AgentKnowledge(BaseModel):
    brief_reactions: list[BriefReaction] = Field(default_factory=list)
    layers: list[KnowledgeLayer]
    notes: list[LearnedNote]
    corrections: list[CorrectionRow]
    contacts: list[ContactRow]
    judged: int
    learning_state: str
    learning_done: int
    learning_total: int
    conversations_unread: int


class GetAgentKnowledge(BaseModel):
    pass


class PreviewMail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread: int


class MailPreview(BaseModel):
    layers: list[KnowledgeLayer]
    given: str
    instruction: str
    approx_tokens: int


class ChangeLearnedNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: str = Field(min_length=1, max_length=2000)


class ReadMoreMail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=5000)


class GetToday(BaseModel):
    pass


MemoryList.model_rebuild()
