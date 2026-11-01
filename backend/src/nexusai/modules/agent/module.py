import threading

from nexusai.contracts.agent import (
    ActivityList,
    ActivityRow,
    AgentDone,
    ApprovalList,
    CreateSession,
    DecideApproval,
    GetGuardRules,
    GetModelCall,
    GetPermissions,
    GetUsage,
    GuardRules,
    GuardTestResult,
    ListActivity,
    ListApprovals,
    ListSessions,
    ModelCallView,
    Permissions,
    RenameSession,
    SessionAction,
    SessionList,
    SessionRow,
    SessionView,
    SetDailyCap,
    TestGuardRules,
    UndoActivity,
    UsageView,
)
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.agent import gateway, guard, policy, runtime, tools

agent_module = Module(
    name="agent",
    migrations=[
        guard.MIGRATION,
        gateway.MIGRATION,
        policy.MIGRATION,
        tools.MIGRATION,
        runtime.MIGRATION,
    ],
)
_runtime: runtime.SessionRuntime | None = None
_runtime_lock = threading.Lock()


def _startup(ctx: Context) -> None:
    global _runtime
    guard.load_rules(ctx.config.home)
    with _runtime_lock:
        _runtime = runtime.SessionRuntime(ctx)
        _runtime.resume_after_restart()


def _shutdown() -> None:
    global _runtime
    with _runtime_lock:
        if _runtime:
            _runtime.close()
            _runtime = None


agent_module.on_start.append(_startup)
agent_module.on_stop.append(_shutdown)


def current() -> runtime.SessionRuntime:
    if _runtime is None:
        raise CommandError("agent.not_ready", "The agent isn't ready yet.", 409)
    return _runtime


@agent_module.command("session.create")
def create_session(command: CreateSession, ctx: Context) -> SessionRow:
    return current().create(command.title, command.context)


@agent_module.query("sessions.list")
def list_sessions(query: ListSessions, ctx: Context) -> SessionList:
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM agent_sessions WHERE archived = ? AND title LIKE ? ORDER BY updated DESC LIMIT 200",
        (int(query.archived), f"%{query.query}%"),
    )
    running = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM agent_sessions WHERE status = 'running'"
    )[0]["n"]
    return SessionList(
        sessions=[runtime._row(row) for row in rows],
        running=running,
        limit=ctx.config.agent.max_running_sessions,
    )


@agent_module.query("session.get")
def get_session(query: SessionAction, ctx: Context) -> SessionView:
    return current().view(query.id)


@agent_module.command("session.stop")
def stop_session(command: SessionAction, ctx: Context) -> AgentDone:
    current().stop(command.id)
    return AgentDone()


@agent_module.command("session.rename")
def rename_session(command: RenameSession, ctx: Context) -> AgentDone:
    current().row(command.id)
    current()._set(command.id, title=command.title)
    return AgentDone()


@agent_module.command("session.archive")
def archive_session(command: SessionAction, ctx: Context) -> AgentDone:
    current().row(command.id)
    current()._set(command.id, archived=1)
    return AgentDone()


@agent_module.query("approvals.list")
def list_approvals(query: ListApprovals, ctx: Context) -> ApprovalList:
    return runtime.approvals_view(ctx.bus.db)


@agent_module.command("approvals.decide")
def decide_approval(command: DecideApproval, ctx: Context) -> AgentDone:
    current().decide(command.id, command.choice)
    return AgentDone()


@agent_module.query("permissions.get")
def get_permissions(query: GetPermissions, ctx: Context) -> Permissions:
    return policy.load_permissions(ctx.bus.db)


@agent_module.command("permissions.save")
def save_permissions(command: Permissions, ctx: Context) -> Permissions:
    policy.save_permissions(ctx.bus.db, command)
    with ctx.bus.unit_of_work() as work:
        work.emit("permissions.changed", {}, source="agent", trace_id=ctx.trace_id)
    return command


@agent_module.query("guard.rules")
def get_guard_rules(query: GetGuardRules, ctx: Context) -> GuardRules:
    return guard.load_rules(ctx.config.home)


@agent_module.command("guard.save")
def save_guard_rules(command: GuardRules, ctx: Context) -> GuardRules:
    errors = guard.rule_errors(command)
    if errors:
        raise CommandError("guard.bad_rule", errors[0], 422)
    guard.save_rules(ctx.config.home, command)
    return command


@agent_module.command("guard.test")
def test_guard_rules(command: TestGuardRules, ctx: Context) -> GuardTestResult:
    return guard.test_rules(GuardRules(rules=command.rules), command.sample)


@agent_module.query("modelCall.get")
def get_model_call(query: GetModelCall, ctx: Context) -> ModelCallView:
    view = gateway.call_view(ctx.bus.db, query.id, query.session)
    if view is None:
        raise CommandError("model_call.not_found", "No model call has been made here yet.", 404)
    return view


@agent_module.query("usage.get")
def get_usage(query: GetUsage, ctx: Context) -> UsageView:
    return gateway.usage_view(ctx)


@agent_module.command("usage.setCap")
def set_daily_cap(command: SetDailyCap, ctx: Context) -> UsageView:
    gateway.set_cap(ctx.bus.db, command.daily_cap)
    return gateway.usage_view(ctx)


@agent_module.query("activity.list")
def list_activity(query: ListActivity, ctx: Context) -> ActivityList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM activity ORDER BY id DESC LIMIT 200")
    return ActivityList(
        items=[
            ActivityRow(
                id=row["id"],
                time=row["time"],
                session=row["session"],
                summary=row["summary"],
                undoable=bool(row["undo_path"]) and not row["undone"],
                undone=bool(row["undone"]),
            )
            for row in rows
        ]
    )


@agent_module.command("activity.undo")
def undo_activity(command: UndoActivity, ctx: Context) -> AgentDone:
    problem = tools.undo(ctx, command.id)
    if problem:
        raise CommandError("activity.not_undoable", problem, 422)
    return AgentDone()
