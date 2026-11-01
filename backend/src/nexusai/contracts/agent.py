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
