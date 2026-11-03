import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from nexusai.contracts.agent import (
    ActivityList,
    ActivityRow,
    AgentChannelList,
    AgentDone,
    AgentKnowledge,
    AgentRegistry,
    AnswerSession,
    ApprovalList,
    BoardList,
    BriefReacted,
    ChangeLearnedNote,
    ChannelList,
    ChooseVersion,
    Cockpit,
    CockpitEvents,
    CompactResult,
    ContextItem,
    ContextSettings,
    CreateSession,
    DecideApproval,
    DecideApprovals,
    DecideMailSuggestion,
    DecideMemoryProposal,
    DismissChannel,
    DueItem,
    GetAgentKnowledge,
    GetCockpit,
    GetCockpitEvents,
    GetContextSettings,
    GetGuardRules,
    GetMailAgentSettings,
    GetModelCall,
    GetPermissions,
    GetQuietHours,
    GetThreadRuns,
    GetToday,
    GetToolCatalog,
    GetTriggers,
    GetUsage,
    GuardRules,
    GuardTestResult,
    HealthItem,
    Job,
    JobList,
    ListActivity,
    ListAgentChannel,
    ListAgents,
    ListApprovals,
    ListBoard,
    ListChannel,
    ListJobs,
    ListMailSuggestions,
    ListMemory,
    ListPipelines,
    ListPrompts,
    ListSchedules,
    ListSessions,
    MailAgentRun,
    MailAgentSettings,
    MailPreview,
    MailSuggestionList,
    MarkTodaySeen,
    MemoryList,
    ModelCallView,
    PausePipeline,
    Permissions,
    PipelineList,
    PipelineMore,
    PreviewMail,
    PromptFile,
    PromptList,
    QuietHours,
    RateMessage,
    ReactToBrief,
    ReadMoreMail,
    RemoveMemory,
    RemoveSchedule,
    RemoveTrigger,
    RenameSession,
    RespondChannel,
    RunMailAgent,
    RunPipeline,
    RunSchedule,
    SaveMemory,
    SavePrompt,
    SaveTrigger,
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
    SetSessionModel,
    SetTopicMuted,
    SinceLastLook,
    SummarizeThread,
    TestGuardRules,
    ThreadRuns,
    ThreadSummary,
    TodayThread,
    TodayView,
    ToolCatalog,
    ToolInfo,
    TriageEstimate,
    TriageExisting,
    TriggerList,
    UndoActivity,
    UpcomingRun,
    UsageView,
)
from nexusai.contracts.events import AppEvent
from nexusai.contracts.mail import GetMailStatus, MailStatus
from nexusai.contracts.semantic import IndexInfo
from nexusai.kernel import backups
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.agent import (
    channel,
    citations,
    cockpit,
    context,
    feedback,
    gateway,
    guard,
    knowledge,
    mail_agent,
    memory,
    pipelines,
    policy,
    prompts_builder,
    providers,
    registry,
    runtime,
    scheduler,
    signals,
    suggestions,
    tools,
    triggers,
)
from nexusai.modules.connectors import module as connectors
from nexusai.modules.mail import accounts, pst_search, pst_upload
from nexusai.modules.mail import module as mail
from nexusai.modules.semantic import module as semantic

STARTER_PROMPTS = ("importance", "categories")
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
        gateway.RUN_LIMIT_MIGRATION,
        gateway.RUN_LIMIT_SINCE_MIGRATION,
        policy.MIGRATION,
        tools.MIGRATION,
        runtime.MIGRATION,
        runtime.EDIT_MIGRATION,
        runtime.RETRY_MIGRATION,
        runtime.COMPACTIONS_MIGRATION,
        citations.MIGRATION,
        runtime.TRIGGER_MIGRATION,
        memory.MIGRATION,
        channel.MIGRATION,
        channel.QUESTIONS_MIGRATION,
        mail_agent.MIGRATION,
        mail_agent.TRIGGER_MIGRATION,
        scheduler.MIGRATION,
        scheduler.TIMES_MIGRATION,
        scheduler.CONTEXT_MIGRATION,
        triggers.MIGRATION,
        scheduler.BUILT_IN_MIGRATION,
        feedback.MIGRATION,
        feedback.BRIEF_MIGRATION,
        Migration(
            "agent_know_you_better_001",
            "UPDATE agent_sessions SET title = 'Know you better'"
            " WHERE agent = 'interview' AND title = 'Interview';",
        ),
        suggestions.MIGRATION,
    ],
)
_runtime: runtime.SessionRuntime | None = None
_triggers: triggers.Triggers | None = None
_scheduler: scheduler.Scheduler | None = None
_runtime_lock = threading.Lock()


def _startup(ctx: Context) -> None:
    global _runtime, _triggers, _scheduler
    guard.load_rules(ctx.config.home)
    with _runtime_lock:
        _runtime = runtime.SessionRuntime(ctx)
        _runtime.resume_after_restart()
        _triggers = triggers.Triggers(ctx, _runtime)
        _triggers.start()
        # By default it runs on each email and on the hour. Choosing otherwise is remembered.
        if mail_agent.mode(ctx) != "each":
            scheduler.set_hourly(ctx, True)
        scheduler.start_built_ins(ctx)
        _scheduler = scheduler.Scheduler(ctx)
        _scheduler.start()
        # Mail may have finished coming down while this wasn't running, or before it existed.
        synced = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
        _triggers.consider_learning(history_finished=synced.history_finished)


def _shutdown() -> None:
    global _runtime, _triggers, _scheduler
    with _runtime_lock:
        if _scheduler:
            _scheduler.stop()
            _scheduler = None
        if _triggers:
            _triggers.stop()
            _triggers = None
        if _runtime:
            _runtime.close()
            _runtime = None


@agent_module.on("mail.needsTriage", "agent.triage")
def needs_triage(event: AppEvent, ctx: Context) -> None:
    if mail_agent.enabled(ctx):
        mail_agent.enqueue(
            ctx, int(event.payload["message_id"]), int(event.payload["thread_id"]), event=event.id
        )
        if _triggers:
            _triggers.wake.set()


@agent_module.on("mail.sent", "agent.person_replied")
def person_replied(event: AppEvent, ctx: Context) -> None:
    message, thread = int(event.payload["message_id"]), int(event.payload["thread_id"])
    mail_agent.person_replied(ctx, thread)
    if mail_agent.enabled(ctx):
        mail_agent.enqueue(ctx, message, thread, event=f"{mail_agent.SENT_PREFIX}{message}")
        if _triggers:
            _triggers.wake.set()


@agent_module.on("mail.received", "agent.they_answered")
def they_answered(event: AppEvent, ctx: Context) -> None:
    mail_agent.they_answered(ctx, int(event.payload["message_id"]), int(event.payload["thread_id"]))


@agent_module.on("thread.updated", "agent.learn_from_corrections")
def learn_from_corrections(event: AppEvent, ctx: Context) -> None:
    """What the person changes teaches the agent. What an agent changes doesn't count."""
    if event.payload.get("by", "person") != "person":
        return
    habit = feedback.note(
        ctx.bus.db,
        int(event.payload["thread_id"]),
        str(event.payload["field"]),
        event.payload.get("value"),
        signals.own_addresses(ctx),
    )
    if habit:
        sender, category = habit
        suggestions.add(
            ctx,
            category,
            [sender],
            f"You've filed {sender} under {category} {feedback.HABIT} times, so this would do it for you.",
            False,
            by="habit",
        )


@agent_module.on("mail.changed", "agent.learn_when_enough_mail")
def learn_when_enough_mail(event: AppEvent, ctx: Context) -> None:
    if _triggers:
        _triggers.consider_learning()


@agent_module.on("mail.historyFinished", "agent.learn_when_history_finished")
def learn_when_history_finished(event: AppEvent, ctx: Context) -> None:
    if _triggers:
        _triggers.consider_learning(history_finished=True)


@agent_module.on("mail.*", "agent.custom_triggers")
def custom_triggers(event: AppEvent, ctx: Context) -> None:
    if _triggers and event.type in triggers.EVENT_CHOICES:
        _triggers.on_event(event)


@agent_module.on("schedule.due", "agent.schedule_due")
def schedule_due(event: AppEvent, ctx: Context) -> None:
    if _triggers:
        _triggers.fire_schedule(event.id, int(event.payload["id"]))


@agent_module.on("models.changed", "agent.triage_model_back")
def model_changed(event: AppEvent, ctx: Context) -> None:
    if _triggers:
        _triggers.model_changed()


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
    return current().create(command.title, command.context, command.agent, command.model)


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


@agent_module.command("approvals.decideMany")
def decide_approvals(command: DecideApprovals, ctx: Context) -> AgentDone:
    current().decide_many(command.allow, command.deny, command.remember)
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


@agent_module.command("session.setModel")
def set_session_model(command: SetSessionModel, ctx: Context) -> AgentDone:
    current().row(command.id)
    current()._set(command.id, model=command.model)
    return AgentDone()


@agent_module.command("session.chooseVersion")
def choose_version(command: ChooseVersion, ctx: Context) -> SessionView:
    current().choose_version(command.id, command.turn)
    return current().view(command.id)


@agent_module.command("message.rate")
def rate_message(command: RateMessage, ctx: Context) -> AgentDone:
    current().rate(command.turn, command.value)
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
        PromptFile(
            name=name,
            title=title,
            kind="personal",
            content=read(name),
            starter=prompts_builder.packaged(f"starter-{name}.md")
            if name in STARTER_PROMPTS
            else None,
        )
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
    for name in STARTER_PROMPTS:
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
        if _triggers:
            _triggers.wake.set()
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
        if _triggers:
            _triggers.wake.set()
    return mail_agent.estimate(ctx)


@agent_module.query("thread.summary")
def thread_summary(query: SummarizeThread, ctx: Context) -> ThreadSummary:
    return mail_agent.summary_view(ctx, query.id)


@agent_module.command("thread.summarize")
def summarize_thread(command: SummarizeThread, ctx: Context) -> ThreadSummary:
    return mail_agent.summarize(ctx, command.id)


# Schedules


def _schedule_list(ctx: Context) -> ScheduleList:
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM schedules WHERE kind NOT IN (?, ?, ?) ORDER BY id", scheduler.BUILT_IN_KINDS
    )
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
    if command.kind in scheduler.BUILT_IN_KINDS:
        raise CommandError("schedule.reserved", "That schedule belongs to the Mail agent.", 422)
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
        command.context_mode,
        command.keep_messages,
    )
    now = datetime.now(UTC).isoformat()
    with ctx.bus.unit_of_work() as work:
        if command.id is None:
            work.tx.execute(
                "INSERT INTO schedules (title, prompt, kind, every, time, weekday, date, enabled, token_limit, next_run, context_mode, keep_messages, created, updated)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, now, now),
            )
        else:
            work.tx.execute(
                "UPDATE schedules SET title = ?, prompt = ?, kind = ?, every = ?, time = ?, weekday = ?, date = ?, enabled = ?, token_limit = ?, next_run = ?, context_mode = ?, keep_messages = ?, updated = ? WHERE id = ?",
                (*values, now, command.id),
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
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE schedules SET last_run = ? WHERE id = ?",
            (datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M"), command.id),
        )
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    if _triggers:
        _triggers.fire_schedule(uuid.uuid4().hex, command.id)
        _triggers.tick()
    return AgentDone()


@agent_module.query("mailAgent.get")
def get_mail_agent(query: GetMailAgentSettings, ctx: Context) -> MailAgentSettings:
    done, total = mail_agent.learning_progress(ctx)
    return MailAgentSettings(
        mode=mail_agent.mode(ctx),
        learn_emails=mail_agent.learn_count(ctx),
        learning_state=mail_agent.learning_state(ctx),
        learning_done=done,
        learning_total=total,
        tokens_per_email=mail_agent.APPROX_TOKENS_PER_MESSAGE,
        morning_brief=scheduler.built_in_on(ctx, scheduler.BRIEF_KIND),
        inbox_review=scheduler.built_in_on(ctx, scheduler.REVIEW_KIND),
    )


@agent_module.command("mailAgent.save")
def save_mail_agent(command: MailAgentSettings, ctx: Context) -> MailAgentSettings:
    scheduler.set_default(ctx, "mail_mode", command.mode)
    scheduler.set_hourly(ctx, command.mode != "each")
    if command.learn_emails is not None:
        mail_agent.set_learn_count(ctx, command.learn_emails)
    if command.morning_brief is not None:
        scheduler.set_built_in(ctx, scheduler.BRIEF_KIND, command.morning_brief)
    if command.inbox_review is not None:
        scheduler.set_built_in(ctx, scheduler.REVIEW_KIND, command.inbox_review)
    with ctx.bus.unit_of_work() as work:
        work.emit("mailAgent.changed", {}, source="agent", trace_id=ctx.trace_id)
    if _scheduler:
        _scheduler.poke()
    if _triggers:
        _triggers.wake.set()
    return command


@agent_module.query("mailAgent.knowledge")
def mail_agent_knowledge(query: GetAgentKnowledge, ctx: Context) -> AgentKnowledge:
    return knowledge.view(ctx)


@agent_module.query("mailAgent.preview")
def mail_agent_preview(query: PreviewMail, ctx: Context) -> MailPreview:
    return knowledge.preview(ctx, query.thread)


@agent_module.command("mailAgent.readMore")
def mail_agent_read_more(command: ReadMoreMail, ctx: Context) -> AgentDone:
    if _triggers is None:
        raise CommandError("agent.not_ready", "The agent isn't ready yet.", 409)
    _triggers.read_more(command.count)
    with ctx.bus.unit_of_work() as work:
        work.emit("mailAgent.changed", {}, source="agent", trace_id=ctx.trace_id)
    return AgentDone()


@agent_module.command("memory.removeNote")
def remove_note(command: ChangeLearnedNote, ctx: Context) -> AgentDone:
    memory.remove_learned(ctx.config.home, command.line)
    _memory_changed(ctx)
    return AgentDone()


@agent_module.command("memory.confirmNote")
def confirm_note(command: ChangeLearnedNote, ctx: Context) -> AgentDone:
    memory.confirm_learned(ctx.config.home, command.line)
    _memory_changed(ctx)
    return AgentDone()


@agent_module.query("suggestions.list")
def list_suggestions(query: ListMailSuggestions, ctx: Context) -> MailSuggestionList:
    return MailSuggestionList(suggestions=suggestions.waiting(ctx))


@agent_module.command("suggestions.decide")
def decide_suggestion(command: DecideMailSuggestion, ctx: Context) -> AgentDone:
    suggestions.decide(ctx, command.id, command.accept)
    return AgentDone()


@agent_module.command("mailAgent.runNow")
def run_mail_agent(command: RunMailAgent, ctx: Context) -> MailAgentRun:
    if _triggers is None:
        raise CommandError("agent.not_ready", "The agent isn't ready yet.", 409)
    outcome = _triggers.run_mail_now()
    return MailAgentRun(outcome="started" if outcome == "started" else "nothing")


@agent_module.query("context.get")
def get_context(query: GetContextSettings, ctx: Context) -> ContextSettings:
    return context.load_settings(ctx.bus.db, ctx.config)


@agent_module.command("context.save")
def save_context(command: ContextSettings, ctx: Context) -> ContextSettings:
    context.save_settings(ctx.bus.db, command)
    with ctx.bus.unit_of_work() as work:
        work.emit("context.changed", {}, source="agent", trace_id=ctx.trace_id)
    return command


@agent_module.command("session.compact")
def compact_session(command: SessionAction, ctx: Context) -> CompactResult:
    return CompactResult(compacted=current().compact(command.id))


def _brief_text(parts: list[dict[str, Any]]) -> str | None:
    """What it replied, or what it posted, since a brief can arrive either way."""
    said = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
    if said:
        return said
    posted = [part["input"]["text"] for part in parts if part.get("type") == "tool-tell"]
    return posted[-1] if posted else None


@agent_module.command("brief.react")
def react_to_brief(command: ReactToBrief, ctx: Context) -> BriefReacted:
    """The next brief reads this, and the person sees it under What it knows."""
    rows = ctx.bus.db.fetch_all(
        "SELECT updated FROM agent_sessions WHERE id = ?", (command.session,)
    )
    if not rows:
        raise CommandError("brief.not_found", "That brief is no longer here.", 404)
    view = current().view(command.session)
    last = [m for m in view.messages if m["role"] == "assistant"]
    text = (_brief_text(last[-1]["parts"]) or "") if last else ""
    feedback.save_brief_reaction(
        ctx.bus.db, command.session, rows[0]["updated"][:10], command.rating, command.comment, text
    )
    return BriefReacted(rating=command.rating, comment=command.comment.strip())


@agent_module.query("agents.registry")
def agents_registry(query: ListAgents, ctx: Context) -> AgentRegistry:
    runtime = current()
    return AgentRegistry(
        agents=registry.entries(ctx, lambda session: runtime.active_turn(session) is not None)
    )


@agent_module.query("triggers.list")
def list_triggers(query: GetTriggers, ctx: Context) -> TriggerList:
    return triggers.list_triggers(ctx)


@agent_module.command("triggers.save")
def save_trigger(command: SaveTrigger, ctx: Context) -> TriggerList:
    result = triggers.save_trigger(ctx, command)
    if _triggers:
        _triggers.wake.set()
    return result


@agent_module.command("triggers.remove")
def remove_trigger(command: RemoveTrigger, ctx: Context) -> TriggerList:
    return triggers.remove_trigger(ctx, command.id)


@agent_module.command("schedules.setDefaults")
def set_defaults(command: SetDefaults, ctx: Context) -> ScheduleList:
    if command.time_check_enabled is not None:
        scheduler.set_default(ctx, "time_check_enabled", command.time_check_enabled)
    if command.live_mail_enabled is not None:
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE agent_triggers SET enabled = ? WHERE id = ?",
                (int(command.live_mail_enabled), mail_agent.MAIL_TRIGGER),
            )
        if _triggers:
            _triggers.wake.set()
    with ctx.bus.unit_of_work() as work:
        work.emit("schedule.changed", {}, source="agent", trace_id=ctx.trace_id)
    return _schedule_list(ctx)


# Background and Today


INDEX_NAMES = {"mail": "Mail", "document": "Documents"}
LAST_SEEN = "today_last_seen"
DUE_LIMIT = 10


def _index_health(info: IndexInfo) -> tuple[Any, str]:
    counts = f"{info.indexed} of {info.total} ready"
    if info.state == "off":
        return "off", "Search by meaning is off"
    if info.state == "out_of_date":
        return "problem", f"{info.stale} built with older settings"
    return ("working", counts) if info.state == "partial" else ("ok", counts)


def _health(ctx: Context) -> list[HealthItem]:
    status = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    mail_states: dict[str, tuple[Any, str]] = {
        "live": ("ok", f"Up to date, {status.messages} messages"),
        "off": ("off", "Not connected"),
        "paused": ("off", "Paused"),
        "failed": ("problem", status.message or "It couldn't sign in"),
        "offline": ("problem", status.message or "It can't reach the server"),
    }
    mail_state, mail_detail = mail_states.get(status.state, ("working", "Downloading"))
    try:
        gateway.resolve_provider(ctx)
        waiting = _triggers.waiting_for_model if _triggers else None
        model = ("problem", waiting) if waiting else ("ok", "Connected")
    except providers.ModelNotConfigured:
        model = ("off", "Not connected")
    engine = semantic.engine()
    meaning = engine.status() if engine is not None else None
    indexes = [
        (
            f"index-{info.kind}",
            f"{INDEX_NAMES[info.kind]} index",
            _index_health(info),
            "/settings?section=local-models",
        )
        for info in (meaning.indexes if meaning else [])
    ]
    linked = [row for row in connectors.list_mcp(ctx)]
    broken = [row for row in linked if row["state"] != "ok"]
    outside = (
        ("off", "None added")
        if not linked
        else ("problem", f"{len(broken)} of {len(linked)} need a look")
        if broken
        else ("ok", f"{len(linked)} connected")
    )
    copies = backups.listing(ctx.config.home)
    backup = ("ok", "Saved") if copies else ("off", "None yet")
    failed = len(ctx.bus.failed_events())
    listeners = ("problem", f"{failed} failed") if failed else ("ok", "None failed")
    rows = [
        ("mail", "Mail", (mail_state, mail_detail), "/connectors"),
        ("connectors", "Other connectors", outside, "/connectors"),
        ("model", "Model", model, "/settings?section=models"),
        *indexes,
        ("backup", "Last backup", backup, "/settings?section=home"),
        ("events", "Background handlers", listeners, "/logs"),
    ]
    return [
        HealthItem(
            id=key,
            label=label,
            state=shown[0],
            detail=shown[1],
            link=link,
            when=copies[0].time.isoformat() if key == "backup" and copies else None,
        )
        for key, label, shown, link in rows
    ]


@agent_module.query("cockpit.view")
def cockpit_view(query: GetCockpit, ctx: Context) -> Cockpit:
    rows = ctx.bus.db.fetch_all(
        "SELECT id, title, kind, next_run FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL"
        " ORDER BY next_run LIMIT 5"
    )
    return Cockpit(
        jobs=cast(JobList, list_jobs(ListJobs(), ctx)).jobs,
        upcoming=[UpcomingRun(id=r["id"], title=r["title"], when=r["next_run"]) for r in rows],
        health=_health(ctx),
    )


@agent_module.query("pipelines.list")
def list_pipelines(query: ListPipelines, ctx: Context) -> PipelineList:
    return PipelineList(pipelines=pipelines.views(ctx))


@agent_module.command("pipelines.pause")
def pause_pipeline(command: PausePipeline, ctx: Context) -> PipelineList:
    pipelines.entry(command.id).pause(ctx, command.paused)
    return PipelineList(pipelines=pipelines.views(ctx))


@agent_module.command("pipelines.stop")
def stop_pipeline(command: RunPipeline, ctx: Context) -> PipelineList:
    entry = pipelines.entry(command.id)
    if entry.stop is None:
        raise CommandError("pipelines.cant_stop", "This one has nothing to stop.", 409)
    entry.stop(ctx)
    return PipelineList(pipelines=pipelines.views(ctx))


@agent_module.command("pipelines.more")
def more_pipeline(command: PipelineMore, ctx: Context) -> PipelineList:
    entry = pipelines.entry(command.id)
    if entry.more is None:
        raise CommandError("pipelines.cant_stop", "This one has no more to fetch.", 409)
    entry.more(ctx, command.count)
    return PipelineList(pipelines=pipelines.views(ctx))


@agent_module.command("pipelines.run")
def run_pipeline(command: RunPipeline, ctx: Context) -> PipelineList:
    pipelines.entry(command.id).run(ctx)
    return PipelineList(pipelines=pipelines.views(ctx))


@agent_module.query("cockpit.events")
def cockpit_events(query: GetCockpitEvents, ctx: Context) -> CockpitEvents:
    return cockpit.events(query, ctx)


@agent_module.query("jobs.list")
def list_jobs(query: ListJobs, ctx: Context) -> JobList:
    db = ctx.bus.db
    jobs: list[Job] = []
    reading, read_total = mail_agent.learning_progress(ctx)
    if mail_agent.learning_state(ctx) == "reading" and read_total:
        jobs.append(
            Job(
                id="mail-learning",
                kind="trigger",
                title="Mail agent reading your past mail",
                status="running",
                progress=reading,
                total=read_total,
                link=f"/agent/sessions/{mail_agent.SESSION_ID}",
            )
        )
    syncing = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    if syncing.state in {"syncing", "backfilling"}:
        jobs.append(
            Job(
                id="mail-sync",
                kind="sync",
                title="Downloading mail",
                status=syncing.state,
                progress=syncing.done if syncing.total else None,
                total=syncing.total or None,
                link="/connectors",
            )
        )
    looking = pst_search.search.status
    if looking.state == "running":
        jobs.append(
            Job(
                id="pst-search",
                kind="pst-search",
                title="Looking for PST files",
                status=looking.place or "running",
                link="/connectors",
            )
        )
    for identifier, upload in pst_upload.in_progress():
        jobs.append(
            Job(
                id=f"upload-{identifier}",
                kind="pst-upload",
                title=f"Sending {upload.name}",
                status="running",
                progress=upload.received,
                total=upload.size,
                link="/connectors",
            )
        )
    reading = db.fetch_all("SELECT COUNT(*) AS n FROM documents WHERE status = 'pending'")[0]["n"]
    if reading:
        jobs.append(
            Job(
                id="documents-reading",
                kind="reading",
                title="Reading documents",
                status="running",
                total=reading,
                link="/documents/uploaded",
            )
        )
    for row in db.fetch_all(
        "SELECT * FROM pst_imports WHERE status IN ('queued', 'running', 'paused') ORDER BY id DESC"
    ):
        jobs.append(
            Job(
                id=f"pst-{row['id']}",
                kind="pst",
                title=row["name"],
                status=row["status"],
                progress=row["position"],
                total=row["total"],
                link="/connectors",
            )
        )
    engine = semantic.engine()
    if engine is not None:
        semantic_status = engine.status()
        jobs += [
            Job(
                id=f"model-{model.id}",
                kind="model",
                title="Downloading the search model",
                status="downloading",
                progress=model.downloaded_bytes,
                total=model.size_bytes,
                link="/settings?section=local-models",
            )
            for model in semantic_status.models
            if model.state == "downloading"
        ]
        if semantic_status.indexing:
            jobs.append(
                Job(
                    id="semantic-index",
                    kind="index",
                    title="Preparing search by meaning",
                    status="running",
                    progress=semantic_status.indexed,
                    total=semantic_status.total,
                    link="/settings?section=local-models",
                )
            )
    waiting = mail_agent.waiting_count(ctx)
    if waiting:
        status = "waiting for the model" if _triggers and _triggers.waiting_for_model else "running"
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


def _quiet_days(last_date: str) -> int:
    try:
        return max((datetime.now(UTC) - datetime.fromisoformat(last_date)).days, 0)
    except (TypeError, ValueError):
        return 0


def _today_thread(row: Any) -> TodayThread:
    return TodayThread(
        id=row["id"], subject=row["subject"], people=json.loads(row["participants"])[:3], importance=row["importance"],
        status=row["status"], category=row["category"], last_date=row["last_date"], why=row["why"],
        quiet_days=_quiet_days(row["last_date"]), next_action=row["next_action"], follow_up_on=row["follow_up_on"],
    )  # fmt: skip


@agent_module.query("today.view")
def today_view(query: GetToday, ctx: Context) -> TodayView:
    db = ctx.bus.db
    account = accounts.current_account(ctx.config)
    needs = db.fetch_all(
        "SELECT * FROM threads WHERE account = ? AND in_inbox = 1 AND (status = 'waiting_on_you'"
        " OR (importance = 'high' AND status IN ('none', 'fyi')))"
        " ORDER BY importance = 'high' DESC, last_date DESC LIMIT 20",
        (account,),
    )
    local_day = datetime.now().astimezone().strftime("%Y-%m-%d")
    chase = db.fetch_all(
        "SELECT * FROM threads WHERE account = ? AND in_trash = 0 AND status = 'waiting_on_others'"
        " AND follow_up_on IS NOT NULL AND follow_up_on <= ? ORDER BY follow_up_on LIMIT 20",
        (account, local_day),
    )
    waiting = db.fetch_all(
        "SELECT * FROM threads WHERE account = ? AND in_trash = 0 AND status = 'waiting_on_others'"
        " AND (follow_up_on IS NULL OR follow_up_on > ?) ORDER BY last_date DESC LIMIT 20",
        (account, local_day),
    )
    automated = db.fetch_all(
        "SELECT COUNT(*) AS n FROM threads WHERE account = ? AND in_inbox = 1 AND unread_count > 0 AND category_source = 'rule'",
        (account,),
    )[0]["n"]
    prep = db.fetch_all(
        "SELECT id, updated FROM agent_sessions WHERE agent = 'daily-prep' AND status = 'done' ORDER BY updated DESC LIMIT 1"
    )
    prep_session = prep[0]["id"] if prep else None
    prep_text = None
    prep_at = None
    if prep_session:
        view = current().view(prep_session)
        prep_at = prep[0]["updated"]
        last = [m for m in view.messages if m["role"] == "assistant"]
        if last:
            prep_text = _brief_text(last[-1]["parts"])
    due = _due_items(ctx)
    rating, comment = (
        feedback.brief_reaction(db, prep_session, prep_at[:10])
        if prep_session and prep_at
        else (None, "")
    )
    return TodayView(
        brief=_brief(_waiting_for_person(ctx), due, len(needs)),
        needs_you=[_today_thread(row) for row in needs],
        follow_ups=[_today_thread(row) for row in chase],
        waiting=[_today_thread(row) for row in waiting],
        automated_count=automated,
        prep_session=prep_session,
        prep_text=prep_text,
        prep_at=prep_at,
        prep_rating=rating,
        prep_comment=comment,
        due=due,
        since_last_look=_since_last_look(ctx),
    )


def _waiting_for_person(ctx: Context) -> int:
    """Everything an agent is holding for an answer, the same as the Needs you list."""
    return int(
        ctx.bus.db.fetch_all(
            "SELECT (SELECT COUNT(*) FROM tool_approvals WHERE status = 'pending')"
            " + (SELECT COUNT(*) FROM channel_messages WHERE kind = 'ask' AND status = 'open')"
            " + (SELECT COUNT(*) FROM tasks WHERE proposed = 1 AND status != 'done')"
            " + (SELECT COUNT(*) FROM reminders WHERE proposed = 1 AND fired = 0)"
            " + (SELECT COUNT(*) FROM mail_categories WHERE proposed = 1)"
            " + (SELECT COUNT(*) FROM mail_suggestions WHERE status = 'open')"
            " + (SELECT COUNT(*) FROM memory_proposals WHERE status = 'pending') AS n"
        )[0]["n"]
    )


def _brief(waiting: int, due: list[DueItem], important: int) -> str:
    """Built from facts with no model call, so the page never waits on one."""
    if waiting:
        first = (
            f"{waiting} thing{'' if waiting == 1 else 's'} need{'s' if waiting == 1 else ''} you."
        )
    elif important:
        first = f"{important} important email{'' if important == 1 else 's'} to look at."
    else:
        first = "Nothing needs you right now."
    if not due:
        return first
    late = next((item for item in due if item.overdue), None)
    item = late or due[0]
    return f"{first} {item.title} is {'overdue' if late else 'due today'}."


def _due_items(ctx: Context) -> list[DueItem]:
    db = ctx.bus.db
    now = datetime.now().astimezone()
    today = now.strftime("%Y-%m-%d")
    items: list[DueItem] = []
    for row in db.fetch_all(
        "SELECT title, due, thread FROM tasks WHERE proposed = 0 AND status != 'done' AND due IS NOT NULL AND due <= ? ORDER BY due",
        (today,),
    ):
        link = f"/mail/thread/{row['thread']}" if row["thread"] else "/planner/tasks"
        items.append(
            DueItem(
                kind="task",
                title=row["title"],
                when=row["due"],
                overdue=row["due"] < today,
                link=link,
            )
        )
    for row in db.fetch_all(
        "SELECT title, due_at, thread FROM reminders WHERE proposed = 0 AND fired = 0 AND due_at <= ? ORDER BY due_at",
        (f"{today}T23:59",),
    ):
        link = f"/mail/thread/{row['thread']}" if row["thread"] else "/planner/reminders"
        items.append(
            DueItem(
                kind="reminder",
                title=row["title"],
                when=row["due_at"],
                overdue=row["due_at"][:10] < today,
                link=link,
            )
        )
    for row in db.fetch_all(
        "SELECT title, due, thread FROM work_board WHERE done = 0 AND kind = 'deadline' AND due IS NOT NULL AND due <= ? ORDER BY due",
        (today,),
    ):
        link = f"/mail/thread/{row['thread']}" if row["thread"] else "/today"
        items.append(
            DueItem(
                kind="deadline",
                title=row["title"],
                when=row["due"],
                overdue=row["due"] < today,
                link=link,
            )
        )
    items.sort(key=lambda item: (not item.overdue, item.when))
    return items[:DUE_LIMIT]


def _since_last_look(ctx: Context) -> SinceLastLook:
    db = ctx.bus.db
    rows = db.fetch_all("SELECT value FROM agent_defaults WHERE key = ?", (LAST_SEEN,))
    since = rows[0]["value"] if rows else None
    after = since or ""
    counted = db.fetch_all(
        "SELECT COUNT(*) AS mail, COALESCE(SUM(json_extract(payload, '$.rule') IS NOT NULL), 0) AS filed"
        " FROM events WHERE type = 'mail.received' AND time > ?",
        (after,),
    )[0]
    judged = db.fetch_all(
        "SELECT COUNT(DISTINCT r.thread) AS judged, COUNT(DISTINCT CASE WHEN t.importance = 'high' THEN r.thread END) AS important"
        " FROM triage_runs r JOIN threads t ON t.id = r.thread WHERE r.status = 'done' AND r.time > ?",
        (after,),
    )[0]
    proposed = db.fetch_all(
        "SELECT (SELECT COUNT(*) FROM tasks WHERE proposed = 1 AND created > ?) AS n", (after,)
    )[0]["n"]
    return SinceLastLook(
        since=since,
        mail=counted["mail"],
        important=judged["important"],
        filed=counted["filed"],
        judged=judged["judged"],
        proposed=proposed,
    )


@agent_module.command("today.markSeen")
def mark_today_seen(command: MarkTodaySeen, ctx: Context) -> AgentDone:
    scheduler.set_default(ctx, LAST_SEEN, datetime.now(UTC).isoformat())
    return AgentDone()


@agent_module.command("session.answer")
def answer_session(command: AnswerSession, ctx: Context) -> AgentDone:
    current().answer(command.id, command.answer)
    return AgentDone()


@agent_module.query("tools.catalog")
def tool_catalog(query: GetToolCatalog, ctx: Context) -> ToolCatalog:
    permissions = policy.load_permissions(ctx.bus.db)
    return ToolCatalog(
        tools=[
            ToolInfo(
                name=entry.name,
                group=entry.group,
                label=entry.label,
                description=entry.description,
                level=policy.tool_level(permissions, entry),
                can_allow=entry.action != "send",
            )
            for entry in policy.TOOL_ENTRIES
        ]
    )
