import json
import threading
from datetime import datetime
from typing import Any

from nexusai.contracts.agent import (
    ActivityList,
    ActivityRow,
    AgentChannelList,
    AgentDone,
    ApprovalList,
    BoardList,
    ChannelList,
    ContextItem,
    CreateSession,
    DecideApproval,
    DecideMemoryProposal,
    DismissChannel,
    GetGuardRules,
    GetModelCall,
    GetPermissions,
    GetQuietHours,
    GetThreadRuns,
    GetToday,
    GetUsage,
    GuardRules,
    GuardTestResult,
    Job,
    JobList,
    ListActivity,
    ListAgentChannel,
    ListApprovals,
    ListBoard,
    ListChannel,
    ListJobs,
    ListMemory,
    ListPrompts,
    ListSchedules,
    ListSessions,
    MemoryList,
    ModelCallView,
    Permissions,
    PromptFile,
    PromptList,
    QuietHours,
    RemoveMemory,
    RemoveSchedule,
    RenameSession,
    RespondChannel,
    RunSchedule,
    SaveMemory,
    SavePrompt,
    Schedule,
    ScheduleList,
    SessionAction,
    SessionContext,
    SessionList,
    SessionRow,
    SessionView,
    SetDailyCap,
    SetDefaults,
    SetSessionContext,
    SetTopicMuted,
    SummarizeThread,
    TestGuardRules,
    ThreadRuns,
    ThreadSummary,
    TodayThread,
    TodayView,
    TriageEstimate,
    TriageExisting,
    UndoActivity,
    UsageView,
)
from nexusai.contracts.events import AppEvent
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.agent import (
    channel,
    gateway,
    guard,
    mail_agent,
    memory,
    policy,
    prompts_builder,
    runtime,
    scheduler,
    tools,
)
from nexusai.modules.mail import accounts

PERSONAL_PROMPTS = (
    ("about-me", "About me"),
    ("importance", "What's important"),
    ("categories", "Mail categories"),
    ("senders", "Instructions for specific people"),
    ("topics", "Instructions for specific topics"),
)
AGENT_PROMPTS = (("mail", "Mail agent"), ("session", "Sessions"), ("daily-prep", "Daily prep"))

agent_module = Module(
    name="agent",
    migrations=[
        guard.MIGRATION,
        gateway.MIGRATION,
        policy.MIGRATION,
        tools.MIGRATION,
        runtime.MIGRATION,
        memory.MIGRATION,
        channel.MIGRATION,
        mail_agent.MIGRATION,
        scheduler.MIGRATION,
    ],
)
_runtime: runtime.SessionRuntime | None = None
_mail_agent: mail_agent.MailAgent | None = None
_scheduler: scheduler.Scheduler | None = None
_runtime_lock = threading.Lock()


def _run_schedule(schedule: Schedule) -> str:
    agent = "daily-prep" if schedule.kind == "daily-prep" else "scheduled"
    prompt = schedule.prompt or "Prepare my morning from the work board."
    return current().run_scheduled(schedule.title, prompt, agent)


def _startup(ctx: Context) -> None:
    global _runtime, _mail_agent, _scheduler
    guard.load_rules(ctx.config.home)
    with _runtime_lock:
        _runtime = runtime.SessionRuntime(ctx)
        _runtime.resume_after_restart()
        _mail_agent = mail_agent.MailAgent(ctx)
        _mail_agent.start()
        _scheduler = scheduler.Scheduler(ctx, _run_schedule)
        _scheduler.start()


def _shutdown() -> None:
    global _runtime, _mail_agent, _scheduler
    with _runtime_lock:
        if _scheduler:
            _scheduler.stop()
            _scheduler = None
        if _mail_agent:
            _mail_agent.stop()
            _mail_agent = None
        if _runtime:
            _runtime.close()
            _runtime = None


@agent_module.on("mail.needsTriage", "agent.triage")
def needs_triage(event: AppEvent, ctx: Context) -> None:
    mail_agent.on_needs_triage(event, ctx, _mail_agent)


@agent_module.on("reminders.changed", "agent.scheduler_reminders")
def reminders_changed(event: AppEvent, ctx: Context) -> None:
    if _scheduler:
        _scheduler.poke()


agent_module.on_start.append(_startup)
agent_module.on_stop.append(_shutdown)


def current() -> runtime.SessionRuntime:
    if _runtime is None:
        raise CommandError("agent.not_ready", "The agent isn't ready yet.", 409)
    return _runtime


@agent_module.command("session.create")
def create_session(command: CreateSession, ctx: Context) -> SessionRow:
    return current().create(command.title, command.context, command.agent)


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


@agent_module.query("session.context")
def session_context(query: SessionAction, ctx: Context) -> SessionContext:
    rows = ctx.bus.db.fetch_all("SELECT context FROM agent_sessions WHERE id = ?", (query.id,))
    refs = json.loads(rows[0]["context"]) if rows else []
    return SessionContext(
        items=[ContextItem(ref=ref, label=runtime.context_label(ctx, ref)) for ref in refs]
    )


@agent_module.command("session.setContext")
def set_session_context(command: SetSessionContext, ctx: Context) -> AgentDone:
    current().row(command.id)
    current()._set(command.id, context=json.dumps(command.context))
    return AgentDone()


# Memory and prompts


def _personal_files(ctx: Context) -> list[PromptFile]:
    folder = ctx.config.home / "prompts" / "personal"

    def read(name: str) -> str:
        path = folder / f"{name}.md"
        return path.read_text("utf-8") if path.exists() else ""

    return [
        PromptFile(name=name, title=title, kind="personal", content=read(name))
        for name, title in PERSONAL_PROMPTS
    ]


@agent_module.query("prompts.list")
def list_prompts(query: ListPrompts, ctx: Context) -> PromptList:
    agents = []
    folder = ctx.config.home / "prompts" / "agents"
    for name, title in AGENT_PROMPTS:
        path = folder / f"{name}.md"
        agents.append(
            PromptFile(
                name=name,
                title=title,
                kind="agent",
                content=path.read_text("utf-8") if path.exists() else "",
                base=prompts_builder.packaged(f"{name}.md"),
            )
        )
    return PromptList(prompts=[*_personal_files(ctx), *agents])


@agent_module.command("prompts.save")
def save_prompt(command: SavePrompt, ctx: Context) -> AgentDone:
    folder = ctx.config.home / "prompts" / ("personal" if command.kind == "personal" else "agents")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{command.name}.md").write_text(command.content, "utf-8")
    with ctx.bus.unit_of_work() as work:
        work.emit("prompts.changed", {"name": command.name}, source="agent", trace_id=ctx.trace_id)
    return AgentDone()


@agent_module.command("prompts.useStarters")
def use_starter_prompts(command: ListPrompts, ctx: Context) -> AgentDone:
    """Fills empty priorities with a starter set for the person to edit. Nothing is overwritten."""
    folder = ctx.config.home / "prompts" / "personal"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("importance", "categories"):
        path = folder / f"{name}.md"
        if not path.exists():
            path.write_text(prompts_builder.packaged(f"starter-{name}.md"), "utf-8")
    with ctx.bus.unit_of_work() as work:
        work.emit("prompts.changed", {}, source="agent", trace_id=ctx.trace_id)
    return AgentDone()


@agent_module.query("memory.list")
def list_memory(query: ListMemory, ctx: Context) -> MemoryList:
    return MemoryList(
        files=memory.list_files(ctx.config.home, query.query),
        proposals=memory.proposals(ctx.bus.db),
    )


@agent_module.command("memory.save")
def save_memory(command: SaveMemory, ctx: Context) -> AgentDone:
    memory.save_file(
        ctx.config.home, command.path, command.name, command.level, command.agent, command.content
    )
    _memory_changed(ctx)
    return AgentDone()


@agent_module.command("memory.remove")
def remove_memory(command: RemoveMemory, ctx: Context) -> AgentDone:
    memory.remove_file(ctx.config.home, command.path)
    _memory_changed(ctx)
    return AgentDone()


@agent_module.command("memory.decide")
def decide_memory(command: DecideMemoryProposal, ctx: Context) -> AgentDone:
    memory.decide_proposal(ctx.bus.db, ctx.config.home, command.id, command.accept)
    _memory_changed(ctx)
    return AgentDone()


def _memory_changed(ctx: Context) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit("memory.changed", {}, source="agent", trace_id=ctx.trace_id)


# Channels and the work board


@agent_module.query("channel.list")
def list_channel(query: ListChannel, ctx: Context) -> ChannelList:
    return channel.messages(ctx.bus.db)


@agent_module.command("channel.respond")
def respond_channel(command: RespondChannel, ctx: Context) -> AgentDone:
    row = channel.get(ctx.bus.db, command.id)
    channel.close(ctx, command.id, "answered", command.answer)
    if row["triage_message"]:
        # The Mail agent's best guess gets corrected with the real answer.
        mail_agent.enqueue(ctx, row["triage_message"], row["thread"], command.answer)
        if _mail_agent:
            _mail_agent.wake.set()
    if row["session"] and row["session"] != mail_agent.SESSION_ID:
        current().answered(row["session"])
    return AgentDone()


@agent_module.command("channel.dismiss")
def dismiss_channel(command: DismissChannel, ctx: Context) -> AgentDone:
    row = channel.get(ctx.bus.db, command.id)
    channel.close(ctx, command.id, "dismissed", None)
    if row["session"] and row["session"] != mail_agent.SESSION_ID and row["kind"] == "ask":
        current().answered(row["session"])
    return AgentDone()


@agent_module.query("board.list")
def list_board(query: ListBoard, ctx: Context) -> BoardList:
    return channel.board(ctx.bus.db)


@agent_module.query("agentChannel.list")
def list_agent_channel(query: ListAgentChannel, ctx: Context) -> AgentChannelList:
    return channel.agent_messages(ctx.bus.db)


@agent_module.command("agentChannel.setMuted")
def set_topic_muted(command: SetTopicMuted, ctx: Context) -> AgentDone:
    channel.set_muted(ctx.bus.db, command.topic, command.muted)
    with ctx.bus.unit_of_work() as work:
        work.emit("agentChannel.posted", {}, source="agent", trace_id=ctx.trace_id)
    return AgentDone()


@agent_module.query("quietHours.get")
def get_quiet_hours(query: GetQuietHours, ctx: Context) -> QuietHours:
    return channel.load_quiet(ctx.bus.db)


@agent_module.command("quietHours.save")
def save_quiet_hours(command: QuietHours, ctx: Context) -> QuietHours:
    channel.save_quiet(ctx.bus.db, command)
    return command


# Mail agent


@agent_module.query("triage.runs")
def thread_runs(query: GetThreadRuns, ctx: Context) -> ThreadRuns:
    return mail_agent.thread_runs(ctx, query.thread)


@agent_module.query("triage.estimate")
def triage_estimate(query: ListJobs, ctx: Context) -> TriageEstimate:
    return mail_agent.estimate(ctx)


@agent_module.command("triage.existing")
def triage_existing(command: TriageExisting, ctx: Context) -> TriageEstimate:
    if command.confirm:
        mail_agent.queue_existing(ctx)
        if _mail_agent:
            _mail_agent.wake.set()
    return mail_agent.estimate(ctx)


@agent_module.query("thread.summary")
def thread_summary(query: SummarizeThread, ctx: Context) -> ThreadSummary:
    return mail_agent.summary_view(ctx, query.id)


@agent_module.command("thread.summarize")
def summarize_thread(command: SummarizeThread, ctx: Context) -> ThreadSummary:
    return mail_agent.summarize(ctx, command.id)


# Schedules


def _schedule_list(ctx: Context) -> ScheduleList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM schedules ORDER BY id")
    return ScheduleList(
        schedules=[scheduler.row_to_schedule(row) for row in rows],
        time_check_enabled=scheduler.time_check_enabled(ctx),
        live_mail_enabled=mail_agent.enabled(ctx),
    )


@agent_module.query("schedules.list")
def list_schedules(query: ListSchedules, ctx: Context) -> ScheduleList:
    return _schedule_list(ctx)


@agent_module.command("schedules.save")
def save_schedule(command: Schedule, ctx: Context) -> ScheduleList:
    next_run = (
        scheduler.next_run_after(command, datetime.now().astimezone().replace(tzinfo=None))
        if command.enabled
        else None
    )
    values = (
        command.title,
        command.prompt,
        command.kind,
        command.every,
        command.time,
        command.weekday,
        command.date,
        int(command.enabled),
        command.token_limit,
        next_run,
    )
    with ctx.bus.unit_of_work() as work:
        if command.id is None:
            work.tx.execute(
                "INSERT INTO schedules (title, prompt, kind, every, time, weekday, date, enabled, token_limit, next_run) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        else:
            work.tx.execute(
                "UPDATE schedules SET title = ?, prompt = ?, kind = ?, every = ?, time = ?, weekday = ?, date = ?, enabled = ?, token_limit = ?, next_run = ? WHERE id = ?",
                (*values, command.id),
            )
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    if _scheduler:
        _scheduler.poke()
    return _schedule_list(ctx)


@agent_module.command("schedules.remove")
def remove_schedule(command: RemoveSchedule, ctx: Context) -> ScheduleList:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM schedules WHERE id = ?", (command.id,))
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    return _schedule_list(ctx)


@agent_module.command("schedules.runNow")
def run_schedule_now(command: RunSchedule, ctx: Context) -> AgentDone:
    rows = ctx.bus.db.fetch_all("SELECT * FROM schedules WHERE id = ?", (command.id,))
    if not rows:
        raise CommandError("schedule.not_found", "That schedule no longer exists.", 404)
    session = _run_schedule(scheduler.row_to_schedule(rows[0]))
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE schedules SET last_session = ?, last_run = ? WHERE id = ?",
            (session, datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M"), command.id),
        )
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    return AgentDone()


@agent_module.command("schedules.setDefaults")
def set_defaults(command: SetDefaults, ctx: Context) -> ScheduleList:
    if command.time_check_enabled is not None:
        scheduler.set_default(ctx, "time_check_enabled", command.time_check_enabled)
    if command.live_mail_enabled is not None:
        scheduler.set_default(ctx, "live_mail_enabled", command.live_mail_enabled)
        if _mail_agent:
            _mail_agent.wake.set()
    with ctx.bus.unit_of_work() as work:
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    return _schedule_list(ctx)


# Background and Today


@agent_module.query("jobs.list")
def list_jobs(query: ListJobs, ctx: Context) -> JobList:
    db = ctx.bus.db
    jobs: list[Job] = []
    for row in db.fetch_all(
        "SELECT * FROM pst_imports WHERE status IN ('queued', 'running', 'paused', 'failed') ORDER BY id DESC"
    ):
        jobs.append(
            Job(
                id=f"pst-{row['id']}",
                kind="pst",
                title=row["name"],
                status=row["status"],
                progress=row["position"],
                total=row["total"],
                link="/mail/archive",
            )
        )
    waiting = db.fetch_all("SELECT COUNT(*) AS n FROM triage_queue")[0]["n"]
    if waiting:
        status = (
            "waiting for the model" if _mail_agent and _mail_agent.waiting_for_model else "running"
        )
        jobs.append(
            Job(
                id="triage",
                kind="triage",
                title="Mail agent",
                status=status,
                progress=None,
                total=waiting,
                link=f"/agent/sessions/{mail_agent.SESSION_ID}",
            )
        )
    for row in db.fetch_all(
        "SELECT id, title, status, agent FROM agent_sessions WHERE status IN ('queued', 'running', 'waiting') ORDER BY updated DESC"
    ):
        jobs.append(
            Job(
                id=f"session-{row['id']}",
                kind="schedule" if row["agent"] in {"scheduled", "daily-prep"} else "session",
                title=row["title"],
                status=row["status"],
                link=f"/agent/sessions/{row['id']}",
            )
        )
    return JobList(jobs=jobs)


def _today_thread(row: Any) -> TodayThread:
    return TodayThread(
        id=row["id"], subject=row["subject"], people=json.loads(row["participants"])[:3], importance=row["importance"],
        status=row["status"], category=row["category"], last_date=row["last_date"], why=row["why"],
    )  # fmt: skip


@agent_module.query("today.view")
def today_view(query: GetToday, ctx: Context) -> TodayView:
    db = ctx.bus.db
    account = accounts.current_account(ctx.config)
    needs = db.fetch_all(
        "SELECT * FROM threads WHERE account = ? AND in_inbox = 1 AND (status = 'waiting_on_you' OR (importance = 'high' AND status != 'resolved'))"
        " ORDER BY importance = 'high' DESC, last_date DESC LIMIT 20",
        (account,),
    )
    waiting = db.fetch_all(
        "SELECT * FROM threads WHERE account = ? AND in_inbox = 1 AND status = 'waiting_on_others' ORDER BY last_date DESC LIMIT 20",
        (account,),
    )
    automated = db.fetch_all(
        "SELECT COUNT(*) AS n FROM threads WHERE account = ? AND in_inbox = 1 AND unread_count > 0 AND category_source = 'rule'",
        (account,),
    )[0]["n"]
    prep = db.fetch_all(
        "SELECT id FROM agent_sessions WHERE agent = 'daily-prep' AND status = 'done' ORDER BY updated DESC LIMIT 1"
    )
    prep_session = prep[0]["id"] if prep else None
    prep_text = None
    if prep_session:
        view = current().view(prep_session)
        last = [m for m in view.messages if m["role"] == "assistant"]
        if last:
            prep_text = (
                "".join(p.get("text", "") for p in last[-1]["parts"] if p.get("type") == "text")
                or None
            )
    brief = f"{len(needs)} need you, {len(waiting)} waiting on others, {automated} automated."
    return TodayView(
        brief=brief,
        needs_you=[_today_thread(row) for row in needs],
        waiting=[_today_thread(row) for row in waiting],
        automated_count=automated,
        prep_session=prep_session,
        prep_text=prep_text,
    )
