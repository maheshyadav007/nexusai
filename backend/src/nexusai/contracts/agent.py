from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

GuardAction = Literal["mask", "block"]

GenerationPhase = Literal["idle", "queued", "generating", "done", "failed", "stopped"]


class GetGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, max_length=128)
    session: str | None = Field(default=None, max_length=64)


class GenerationState(BaseModel):
    call_id: int = 0
    trace_id: str | None = None
    session: str | None = None
    phase: GenerationPhase = "idle"


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
    # The start of the last reply, for lists. Only the session list fills it.
    preview: str | None = None


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
    acknowledge_managed: bool = False


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


class PromptLayer(BaseModel):
    name: str
    text: str


class PromptFile(BaseModel):
    name: str
    title: str
    kind: Literal["personal", "agent"]
    content: str
    base: str | None = None
    # What it was filled with to begin with, so an edit can be told from an untouched starter.
    starter: str | None = None
    # An agent's whole prompt as a run sends it, part by part, with real names filled in.
    layers: list[PromptLayer] = Field(default_factory=list)
    # Schedules all share one agent's prompt, so they're listed apart from the team.
    group: Literal["agents", "schedules"] | None = None


class ListPrompts(BaseModel):
    pass


class PromptList(BaseModel):
    prompts: list[PromptFile]


class SavePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["personal", "agent"]
    name: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    content: str = Field(max_length=100000)


SourceKind = Literal["mail", "doc", "matter", "task", "reminder"]


class SourceRef(BaseModel):
    """Where something came from: an email thread, a document, a matter or a task or reminder.
    Its title, detail and date are read from the database, never written by a model."""

    kind: SourceKind
    # The thread id, or the document key.
    ref: str
    # One message in the thread, when it's that message in particular.
    message: int | None = None
    page: str | None = None
    title: str
    # Who sent it, or where the document came from.
    detail: str = ""
    date: str | None = None
    # Its number in the text that cites it. None when it was read but not cited.
    n: int | None = None
    # The matter a matter, task or reminder opens on, when it has one.
    matter: int | None = None


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
    source_ref: SourceRef | None = None


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


class AgentChannelMessage(BaseModel):
    purpose: str | None = None
    expected_output: str | None = None
    state: str = "note"
    outcome: str | None = None
    evidence: list[str] = Field(default_factory=list)
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
    partial: bool = False
    changed: bool = False
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
    # Only for mail like this, checked with no model: from an address or domain, words in the
    # subject, words anywhere in it. Empty means any. A run starts only for mail that matches all.
    match_from: str = Field(default="", max_length=200)
    match_subject: str = Field(default="", max_length=200)
    match_words: str = Field(default="", max_length=500)


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
    # Only for mail like this, checked with no model: from an address or domain, words in the
    # subject, words anywhere in it. Empty means any. A run starts only for mail that matches all.
    match_from: str = Field(default="", max_length=200)
    match_subject: str = Field(default="", max_length=200)
    match_words: str = Field(default="", max_length=500)


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
    # Token spikes and daily caps stay on the agent map. Off, they don't fill the notifications.
    token_alerts: bool = False


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

    mode: MailMode = "each"
    # How many past emails the rule engine didn't catch it reads before going live.
    learn_emails: int | None = Field(default=None, ge=0, le=5000)
    # Filled in when read, to say how that's going.
    learning_state: str | None = None
    learning_done: int | None = None
    learning_total: int | None = None
    tokens_per_email: int | None = None
    # What it does on its own besides judging each email.
    morning_brief: bool | None = None


class GetMailAgentSettings(BaseModel):
    pass


class RunMailAgent(BaseModel):
    pass


class MailAgentRun(BaseModel):
    outcome: Literal["started", "nothing"]


class Schedule(BaseModel):
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("Use a named timezone, such as Asia/Kolkata.") from error
        return value

    @field_validator("time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        datetime.strptime(value, "%H:%M")
        return value

    id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=20000)
    kind: Literal["prompt", "daily-prep", "mail-hourly", "mail-brief"] = "prompt"
    # Weekdays are Monday to Friday. A month day past the month's end runs on its last day.
    every: Literal["once", "hour", "day", "weekdays", "week", "month", "year"] = "day"
    time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=0, ge=0, le=6)
    month_day: int = Field(default=1, ge=1, le=31)
    month: int = Field(default=1, ge=1, le=12)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # The last day it runs on. Empty means it keeps going.
    until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
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


class BuiltInRoutine(BaseModel):
    """A routine that comes with the app: its plugin's routine file, and the row that runs it."""

    name: str
    title: str
    description: str
    agent: str
    plugin: str
    enabled: bool
    # HH:MM for one that runs at a time; None for one an event starts.
    time: str | None = None
    next_run: str | None = None


class SetBuiltInRoutine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool


class ScheduleList(BaseModel):
    schedules: list[ScheduleRow]
    built_in: list[BuiltInRoutine] = Field(default_factory=list)
    time_check_enabled: bool
    live_mail_enabled: bool
    # The built-in morning brief, shown with the other built-in routines.
    morning_brief_enabled: bool = False
    morning_brief_time: str | None = None
    morning_brief_next: str | None = None


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
    morning_brief_enabled: bool | None = None


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
    kind: Literal["task", "reminder"]
    title: str
    when: str
    overdue: bool
    # Where it lives in the planner.
    link: str
    task_id: int | None = None
    source_ref: SourceRef | None = None


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
    artifact: int | None = None
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
    state: Literal["running", "active", "finished", "off", "past", "failed"]
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


# Agent cards: who each agent is. Names live only in the card files and the person's renames.

TaskState = Literal[
    "queued",
    "working",
    "input_required",
    "blocked",
    "reported",
    "verified",
    "rejected",
    "failed",
    "canceled",
]
OPEN_TASK_STATES = ("queued", "working", "input_required", "blocked", "reported")
HANDLE_PATTERN = r"^[a-z][a-z0-9-]{1,23}$"


class AgentMascot(BaseModel):
    style: str
    seed: str


class AgentNow(BaseModel):
    """What the agent is doing this moment, worked out from runs and tasks."""

    state: Literal["idle", "working", "waiting", "blocked", "off"]
    task_id: int | None = None
    waiting_on: str | None = None
    since: str | None = None
    reason: str | None = None


class AgentUsage(BaseModel):
    tokens_today: int = 0
    tokens_week: int = 0
    # Its average day over the last week, so today's number has something to be read against.
    tokens_usual_day: int = 0
    messages_today: int = 0
    tasks_verified: int = 0
    tasks_rejected: int = 0
    tasks_blocked: int = 0


class AgentStart(BaseModel):
    """Something that starts an agent by itself: a built-in routine, by key, and its time if any."""

    key: Literal["on-new-mail", "every-hour", "every-morning"]
    time: str | None = None


class AgentCard(BaseModel):
    id: str
    name: str
    handle: str
    role: str
    can_do: list[str]
    default: bool
    may_assign_to: list[str]
    talks_to_person: bool
    accepts: list[str]
    mascot: AgentMascot
    version: str
    renamed: bool = False
    # "yours" for an agent the person made, named by its schedule's or trigger's title.
    kind: Literal["built_in", "yours"] = "built_in"
    tools: list[str] = Field(default_factory=list)
    now: AgentNow = Field(default_factory=lambda: AgentNow(state="idle"))
    usage: AgentUsage = Field(default_factory=AgentUsage)
    # The plugin its file came from, by its display name. None for the person's own.
    plugin: str | None = None
    # The jobs that are this agent's alone (jobs.py), in a few words each.
    jobs: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    starts: list[AgentStart] = Field(default_factory=list)
    # It reads mail from anyone, so it never gets tools that send, delete or change settings.
    reads_untrusted_mail: bool = False


class ListCards(BaseModel):
    pass


class CardList(BaseModel):
    cards: list[AgentCard]


class RenameAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=40)
    name: str = Field(min_length=1, max_length=40)
    handle: str = Field(pattern=HANDLE_PATTERN)

    @field_validator("name")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("A name can't be blank.")
        return value


class ResetAgentName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=40)


class SetMascot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=40)
    seed: str = Field(min_length=1, max_length=40)


class TeamTask(BaseModel):
    id: int
    objective: str
    expected_output: str
    done_criteria: str
    references: list[str]
    assigner: str
    owner: str
    state: TaskState
    outcome: str | None = None
    evidence: list[str] = Field(default_factory=list)
    verdict: str | None = None
    failure: str | None = None
    untrusted: bool
    parent: int | None = None
    due: str | None = None
    budget_tokens: int
    tokens_used: int = 0
    attempts: int = 0
    owner_session: str | None = None
    assigner_session: str | None = None
    created: str
    updated: str


class TeamMessage(BaseModel):
    id: int
    task_id: int | None
    kind: str
    sender: str
    recipient: str | None
    text: str
    time: str
    untrusted: bool


class ListTeamTasks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_only: bool = False


class TeamTaskList(BaseModel):
    tasks: list[TeamTask]


class GetTeamTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class TaskStep(BaseModel):
    """One tool call the agent doing a task made, for following the work as it happens."""

    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    status: str
    started: str


class TeamTaskView(BaseModel):
    task: TeamTask
    messages: list[TeamMessage]
    children: list[TeamTask]
    # The doing agent's latest steps on this task, oldest first.
    steps: list[TaskStep] = Field(default_factory=list)


class NoteOnTeamTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    text: str = Field(min_length=1, max_length=2000)


class CancelTeamTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class RetryTeamTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class BriefLine(BaseModel):
    text: str
    # The matter it's about, so the line can follow it during the day.
    matter: int | None = None
    # Code changed it since the morning: added for a matter that came up, or updated.
    mark: Literal["added", "updated"] | None = None
    at: str | None = None


class BriefSections(BaseModel):
    """The brief in the parts Today lays out: one line on what matters most, then what's new and
    what's still open, one line per matter."""

    lead: str
    new: list[BriefLine] = Field(default_factory=list)
    open: list[BriefLine] = Field(default_factory=list)


class DoneItem(BaseModel):
    title: str
    when: str | None = None
    why: str = ""


class TodayView(BaseModel):
    brief: str
    needs_you: list[TodayThread]
    # Waiting on someone, and it's time to chase them.
    follow_ups: list[TodayThread] = Field(default_factory=list)
    waiting: list[TodayThread]
    automated_count: int
    prep_session: str | None
    prep_text: str | None
    prep_sections: BriefSections | None = None
    # When code last kept the brief in step with a matter, after the run wrote it.
    prep_updated: str | None = None
    # What got done since yesterday began, worked out by the app rather than the brief.
    prep_done: list[DoneItem] = Field(default_factory=list)
    # What the brief's citation numbers point to.
    prep_sources: list[SourceRef] = Field(default_factory=list)
    prep_at: str | None = None
    prep_artifact: int | None = None
    prep_freshness: Literal["fresh", "stale", "partial", "failed", "none"] = "none"
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
    account: str | None = None
    seen_at: str | None = None
    expires_at: str | None = None
    revision: int = 1
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


class PreviewAgent(BaseModel):
    """What the brief writer or Posty would be sent, for a message like this one."""

    model_config = ConfigDict(extra="forbid")

    agent: Literal["daily-prep", "session"]
    text: str = Field(default="", max_length=2000)


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


class Preference(BaseModel):
    id: int
    purpose: Literal["all", "mail", "draft", "brief"]
    account: str | None = None
    sender: str | None = None
    topic: str | None = None
    instruction: str
    status: Literal["proposed", "active", "declined", "retired", "expired"]
    revision: int
    evidence: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    created: str
    updated: str


class SavePreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = None
    revision: int | None = None
    purpose: Literal["all", "mail", "draft", "brief"] = "all"
    account: str | None = Field(default=None, max_length=128)
    sender: str | None = Field(default=None, max_length=320)
    topic: str | None = Field(default=None, max_length=200)
    instruction: str = Field(min_length=1, max_length=4000)
    status: Literal["active", "declined", "retired"] = "active"
    evidence: list[str] = Field(default_factory=list, max_length=100)
    expires_at: str | None = None

    @field_validator("expires_at")
    @classmethod
    def valid_expiry(cls, value: str | None) -> str | None:
        if value:
            from datetime import UTC

            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("An expiry must include its timezone.")
            return parsed.astimezone(UTC).isoformat()
        return value

    @field_validator("instruction")
    @classmethod
    def nonempty_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write an instruction before saving.")
        return value.strip()


class GetPreferences(BaseModel):
    pass


class PreferenceList(BaseModel):
    preferences: list[Preference]


class PreferenceHistory(BaseModel):
    id: int


class PreferenceEvidence(BaseModel):
    time: str
    action: str
    artifact: str
    artifact_id: str
    old_value: str | None = None
    new_value: str | None = None


class PreferenceVersions(BaseModel):
    versions: list[Preference]
    evidence: list[PreferenceEvidence] = Field(default_factory=list)


class RestorePreference(BaseModel):
    id: int
    revision: int
    restore_revision: int


class RecordInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    thread: int
    action: Literal["opened"]


class PromptHistory(BaseModel):
    kind: Literal["personal", "agent"]
    name: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)


class PromptVersion(BaseModel):
    id: int
    content: str
    time: str


class PromptVersions(BaseModel):
    versions: list[PromptVersion]


class RestorePrompt(PromptHistory):
    version: int


class PreviewPreference(SavePreference):
    pass


class PreferencePreview(BaseModel):
    matched: int
    total: int
    examples: list[str]
    instruction: str
    explanation: str


class AgentQueueItem(BaseModel):
    id: int
    title: str
    status: str
    time: str
    error: str | None = None
    session: str | None = None


class GetAgentQueue(BaseModel):
    pass


class AgentQueue(BaseModel):
    pending: int
    running: int
    failed: int
    oldest_pending: str | None = None
    items: list[AgentQueueItem]


class QueueAction(BaseModel):
    id: int
    action: Literal["retry", "cancel"]


class ExpireLearnedNote(BaseModel):
    line: str = Field(max_length=3000)
    revision: int
    expires_at: datetime | None = None


class SimulatePreference(SavePreference):
    pass


class PreferenceDecision(BaseModel):
    thread: int
    subject: str
    before: str
    after: str
    reason: str


class PreferenceSimulation(BaseModel):
    decisions: list[PreferenceDecision]


# Skills: know-how an agent loads when it needs it.


class SkillFile(BaseModel):
    path: str
    text: str


class Skill(BaseModel):
    name: str
    description: str
    origin: Literal["built_in", "yours"]
    active: bool
    problem: str | None = None
    agents: list[str]
    needs_tools: list[str]
    files: list[str]
    body: str
    loads: int = 0
    last_loaded: str | None = None


class SkillProposal(BaseModel):
    id: int
    name: str
    description: str
    agents: list[str]
    needs_tools: list[str]
    source: str
    files: list[SkillFile]
    flags: list[str]
    status: Literal["waiting", "approved", "rejected"]
    proposed_by: str
    created: str


class ListSkills(BaseModel):
    pass


class SkillList(BaseModel):
    skills: list[Skill]
    proposals: list[SkillProposal]


class AddSkill(BaseModel):
    """From a link, or the text of a SKILL.md. Either way it's a proposal to review first."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=200_000)


class DecideSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    approve: bool


class SkillName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


# Monitoring and the agent map


class MonitorAlert(BaseModel):
    id: int
    kind: str
    agent: str | None = None
    task_id: int | None = None
    detail: str
    time: str
    seen: bool = False


class MapEdge(BaseModel):
    """One open task between two agents: who gave it, who has it, and how it's going."""

    task_id: int
    source: str
    target: str
    state: str
    objective: str
    messages: int
    waiting: str
    trouble: str | None = None


class GetAgentMap(BaseModel):
    pass


class AgentMap(BaseModel):
    cards: list[AgentCard]
    edges: list[MapEdge]
    cycles: list[list[str]]
    alerts: list[MonitorAlert]


class RunSpan(BaseModel):
    """One step of a run: the run itself, a model call, a tool call, a skill load or a message."""

    kind: Literal["run", "model", "tool", "skill", "message"]
    id: str
    name: str
    agent: str | None = None
    time: str
    status: str | None = None
    detail: str | None = None
    tokens: int = 0
    children: list["RunSpan"] = Field(default_factory=list)


class ListRuns(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=30, ge=1, le=200)


class RunList(BaseModel):
    runs: list[RunSpan]


class GetRunTree(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int


class SeeAlerts(BaseModel):
    pass


# Matters: one record for each real thing going on (docs/MATTERS_PLAN.md).
MatterState = Literal["waiting_on_you", "waiting_on_others", "fyi", "done"]
MatterEventKind = Literal[
    "started",
    "joined",
    "mail",
    "sent",
    "task",
    "due",
    "closed",
    "done",
    "reopened",
    "moved",
    "merged",
    "linked",
    "kept",
    "looks_done",
    "suggested",
    "accepted",
    "declined",
]
MatterMarkKind = Literal["in", "sent", "due", "reminder", "closed", "reopened", "step"]


class MatterWork(BaseModel):
    kind: Literal["task", "reminder"]
    id: int
    title: str
    when: str | None = None
    thread: int | None = None
    proposed: bool = False
    # A reminder that belongs to a task names it: it's listed under it, and goes with it.
    parent: int | None = None


class MatterRow(BaseModel):
    id: int
    title: str
    state: MatterState
    # What happens next, in a few words: the open task, or what the latest email asks.
    next: str | None = None
    due: str | None = None
    importance: str = "normal"
    people: list[str] = Field(default_factory=list)
    emails: int = 0
    threads: int = 0
    work: list[MatterWork] = Field(default_factory=list)
    last_date: str
    quiet_days: int = 0
    started: str | None = None
    # The newest conversation in it, to open the email itself.
    latest: SourceRef | None = None


class MatterChange(BaseModel):
    id: int
    matter: int
    title: str
    time: str
    kind: MatterEventKind
    text: str
    why: str = ""
    source: SourceRef | None = None


class MatterDue(BaseModel):
    matter: int
    title: str
    what: str
    when: str
    kind: Literal["task", "reminder"]


class MattersBrief(BaseModel):
    seen: str | None = None
    changes: list[MatterChange]
    needs_you: list[MatterRow]
    waiting: list[MatterRow]
    fyi: list[MatterRow]
    # Matters with only Posty's suggestions open, for the "show suggested too" switch.
    suggested: list[MatterRow] = Field(default_factory=list)
    next: list[MatterDue]


class MatterMark(BaseModel):
    time: str
    kind: MatterMarkKind
    label: str


class MatterLane(BaseModel):
    matter: MatterRow
    marks: list[MatterMark]


class MattersWeek(BaseModel):
    start: str
    lanes: list[MatterLane]


class MatterThread(BaseModel):
    id: int
    subject: str
    status: str
    emails: int
    last_date: str
    how: str
    why: str


class MatterLinkRow(BaseModel):
    """Another matter this one is like, without being the same thing."""

    matter: int
    title: str
    state: MatterState
    why: str


class MatterFile(BaseModel):
    ref: str
    title: str
    # The email it came with, when it came by mail.
    source: SourceRef | None = None


class MatterDetail(BaseModel):
    matter: MatterRow
    # The latest changes, oldest first; `earlier` says there are more before them.
    events: list[MatterChange]
    earlier: bool = False
    threads: list[MatterThread]
    people: list[str]
    related: list[MatterLinkRow] = Field(default_factory=list)
    files: list[MatterFile] = Field(default_factory=list)
    # What's finished in it, newest first, shown closed under its open work.
    done: list[MatterWork] = Field(default_factory=list)


class GetMatterEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    # The oldest change shown so far; the page before it comes back.
    before: int


class MatterEvents(BaseModel):
    events: list[MatterChange]
    earlier: bool


class MatterItem(BaseModel):
    """Something else open in the matter, offered when one thing in it is finished."""

    ref: str
    kind: Literal["task", "reminder", "thread"]
    title: str
    when: str | None = None
    # Ticked to start with: the same email asked for it, so it's most likely finished too.
    suggested: bool = False
    # An AI suggestion not yet accepted, shown as one wherever it appears.
    proposed: bool = False
    why: str = ""


class GetMatterRelated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # What was just finished, as "task:88" or "thread:12".
    ref: str = Field(max_length=40)


class MatterRelated(BaseModel):
    matter: int | None = None
    title: str = ""
    items: list[MatterItem] = Field(default_factory=list)


class CloseMatterItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: str = Field(max_length=40)
    close: list[str] = Field(default_factory=list, max_length=100)
    # Left open on purpose, so they aren't offered again for the same thing.
    keep: list[str] = Field(default_factory=list, max_length=100)


class ReopenMatterItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refs: list[str] = Field(max_length=100)


class MergeMatters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    into: int


class AttachToMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter: int
    ref: str = Field(max_length=40)
    why: str = Field(default="", max_length=300)


class GetMattersBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetMattersWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The Monday the week starts on; the current week when left out.
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # How many days from there. The Week tab loads more as it's scrolled, up to half a year.
    days: int = Field(default=7, ge=1, le=186)


class ListMatters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_done: bool = False


class MatterList(BaseModel):
    matters: list[MatterRow]


class GetMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class MatterAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class UnlinkThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread: int


class MatterDone(BaseModel):
    closed: int = 0
