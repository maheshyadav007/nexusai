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


class SessionView(BaseModel):
    session: SessionRow
    messages: list[dict[str, Any]]
    active: bool


class ToolApproval(BaseModel):
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


class ListApprovals(BaseModel):
    pass


class ApprovalList(BaseModel):
    approvals: list[ToolApproval]


class DecideApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    choice: ApprovalChoice


class AgentDone(BaseModel):
    ok: bool = True


class GetPermissions(BaseModel):
    pass


class Permissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: Permission = "allow"
    write: Permission = "allow"
    command: Permission = "ask"
    folders: list[str] = Field(default_factory=list, max_length=100)
    full_computer_access: bool = False


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


class ThreadSummary(BaseModel):
    thread: int
    text: str | None
    covered: int
    new_messages: int
    updated: str | None


class Job(BaseModel):
    id: str
    kind: Literal["sync", "pst", "triage", "session", "schedule"]
    title: str
    status: str
    progress: int | None = None
    total: int | None = None
    link: str | None = None


class ListJobs(BaseModel):
    pass


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


class Schedule(BaseModel):
    id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=20000)
    kind: Literal["prompt", "daily-prep"] = "prompt"
    every: Literal["once", "day", "week"] = "day"
    time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=0, ge=0, le=6)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    enabled: bool = True
    token_limit: int = Field(default=0, ge=0)


class ScheduleRow(Schedule):
    next_run: str | None
    last_run: str | None
    last_session: str | None


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


class TodayView(BaseModel):
    brief: str
    needs_you: list[TodayThread]
    waiting: list[TodayThread]
    automated_count: int
    prep_session: str | None
    prep_text: str | None


class GetToday(BaseModel):
    pass


MemoryList.model_rebuild()
