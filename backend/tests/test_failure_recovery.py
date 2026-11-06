"""Timing and failure recovery across timer, runtime, queue and IMAP boundaries."""
# ruff: noqa: F401,F811

import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from imapclient.exceptions import IMAPClientError

from nexusai.contracts.agent import GetMailAgentSettings
from nexusai.contracts.mail import GetMailStatus, MailProfile
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import bulk_learning, mail_agent, runtime, scheduler, triggers, ui_stream
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.context import TurnRequest
from nexusai.modules.mail import accounts, pst, sync
from nexusai.modules.mail import module as mail
from test_mail_organization import ctx
from test_mail_sync import fake


def test_scheduler_next_due_failure_keeps_retry_loop_alive(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    timer = scheduler.Scheduler(ctx)
    waits = []
    monkeypatch.setattr(timer, "tick", lambda _: None)

    def broken() -> None:
        raise RuntimeError("Temporary database failure")

    def wait(seconds: float) -> None:
        waits.append(seconds)
        timer.stopping.set()

    monkeypatch.setattr(timer, "_next_due", broken)
    timer.wake = SimpleNamespace(wait=wait, clear=lambda: None)
    timer._loop()
    assert waits == [60.0]


def test_bad_reminder_does_not_block_scheduled_agents(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    timer = scheduler.Scheduler(ctx)
    completed = []

    def broken(*_: Any) -> None:
        raise RuntimeError("Bad reminder")

    monkeypatch.setattr(scheduler.planner, "fire_due_reminders", broken)
    monkeypatch.setattr(timer, "_prune_events", lambda _: None)
    monkeypatch.setattr(timer, "_overdue", lambda _: completed.append("overdue"))
    monkeypatch.setattr(timer, "_follow_ups", lambda _: completed.append("follow-up"))
    monkeypatch.setattr(timer, "_run_due", lambda _: completed.append("schedule"))
    timer.tick(datetime.now(UTC))
    assert completed == ["overdue", "follow-up", "schedule"]


@pytest.mark.parametrize("every", ["day", "week", "once"])
def test_missed_schedule_catches_up_once_without_a_duplicate(ctx: Context, every: str) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO schedules(title,prompt,kind,every,time,next_run,timezone,enabled) VALUES('Recovery','Test','prompt',?,'08:30','2026-01-01T03:00:00+00:00','Asia/Kolkata',1)",
            (every,),
        )
    timer = scheduler.Scheduler(ctx)
    now = datetime(2026, 11, 6, 10, tzinfo=UTC)
    timer._run_due(now)
    timer._run_due(now)
    assert len(ctx.bus.db.fetch_all("SELECT 1 FROM events WHERE type='schedule.due'")) == 1
    saved = ctx.bus.db.fetch_all("SELECT next_run,enabled FROM schedules WHERE title='Recovery'")[0]
    assert bool(saved["enabled"]) == (every != "once")
    if saved["next_run"]:
        assert datetime.fromisoformat(saved["next_run"]) > now


@pytest.mark.parametrize(
    "ending,expected", [("finish", "done"), ("abort", "failed"), ("error", "failed")]
)
def test_restart_settles_closed_run_without_reexecuting(
    ctx: Context, monkeypatch: pytest.MonkeyPatch, ending: str, expected: str
) -> None:
    engine = runtime.SessionRuntime(ctx)
    try:
        monkeypatch.setattr(engine, "_submit", lambda *_: None)
        session = engine.create("Recovery", [], "scheduled").id
        turn = engine.dispatch(TurnRequest(session, "Test", "schedule"))
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT INTO trigger_runs(trigger,event,time,status,turn,session) VALUES('schedule','interrupted',?,'running',?,?)",
                (mail_agent._now(), turn, session),
            )
        # Persist a terminal turn, then lose its callback as if the process crashed.
        engine._finish(
            session,
            turn,
            ui_stream.UiTranslator(started=True),
            expected if expected != "failed" else "failed",
            "Test failure" if ending == "error" else None,
            ending,
        )
        dispatcher = triggers.Triggers(ctx, engine)
        dispatcher._requeue_unfinished()
        row = ctx.bus.db.fetch_all(
            "SELECT status,turn FROM trigger_runs WHERE event='interrupted'"
        )[0]
        assert row["status"] == expected and row["turn"] == turn
        assert len(ctx.bus.db.fetch_all("SELECT 1 FROM agent_turns")) == 1
    finally:
        engine.close()


def test_stopped_run_reports_incomplete_to_queue_listener(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.SessionRuntime(ctx)
    try:
        monkeypatch.setattr(engine, "_submit", lambda *_: None)
        session = engine.create("Stopped", [], "scheduled").id
        turn = engine.dispatch(TurnRequest(session, "Test", "schedule"))
        outcomes = []
        engine.on_turn_end = lambda turn, error: outcomes.append(error)
        engine._finish(
            session, turn, ui_stream.UiTranslator(started=True), "stopped", None, "abort"
        )
        assert outcomes == ["Run stopped before completion."]
    finally:
        engine.close()


def test_interview_held_for_model_reuses_session_and_retries(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.SessionRuntime(ctx)
    try:
        submitted = []
        monkeypatch.setattr(engine, "_submit", lambda *args: submitted.append(args))
        dispatcher = triggers.Triggers(ctx, engine)
        monkeypatch.setattr(dispatcher, "_model_ready", lambda: True)
        engine.on_hold = dispatcher.hold_for_model
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT INTO mail_learning_reviews(account,state,updated) VALUES('test','asking',?)",
                (mail_agent._now(),),
            )
        dispatcher._start_interview()
        session = ctx.bus.db.fetch_all("SELECT interview FROM mail_learning_reviews")[0][
            "interview"
        ]
        turn = engine.active_turn(session)
        assert engine._hold(session, turn, "Model offline")
        dispatcher._start_interview()
        assert len(submitted) == 2
        assert (
            ctx.bus.db.fetch_all("SELECT interview FROM mail_learning_reviews")[0]["interview"]
            == session
        )
        assert (
            len(ctx.bus.db.fetch_all("SELECT 1 FROM agent_sessions WHERE agent='interview'")) == 1
        )
    finally:
        engine.close()


def test_held_legacy_wrap_up_returns_to_retryable_reading(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SimpleNamespace()
    dispatcher = triggers.Triggers(ctx, engine)
    monkeypatch.setattr(dispatcher, "_model_ready", lambda: False)
    engine.active_turn = lambda _: None
    mail_agent.set_learning_state(ctx, "wrapping")
    mail_agent.set_learning_turn(ctx, 999)
    dispatcher._start_wrap_up()
    assert mail_agent.learning_state(ctx) == "reading"


def test_rejected_imap_change_is_saved_and_manual_run_retries(
    ctx: Context, fake: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = sync.MailSync(ctx, "test", MailProfile.model_validate(fake.profile()), "test-password")
    worker.status.state = "live"
    monkeypatch.setattr(mail, "_sync", worker)
    monkeypatch.setattr(accounts, "read_accounts", lambda _: ("test", {}))
    applied = []

    def apply(session: Any, op: str, payload: Any) -> None:
        if payload.get("reject"):
            raise IMAPClientError("Server rejected this change")
        applied.append(payload)

    monkeypatch.setattr(worker, "_apply", apply)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO mail_outbox(account,op,payload,attempts) VALUES('test','read',?,2)",
            (json.dumps({"reject": True}),),
        )
        tx.execute("INSERT INTO mail_outbox(account,op,payload) VALUES('test','read','{}')")
    worker._drain_outbox(None)
    saved = ctx.bus.db.fetch_all("SELECT * FROM mail_outbox")
    assert len(saved) == 1 and saved[0]["failed_at"] and saved[0]["attempts"] == 3
    assert json.loads(saved[0]["payload"]) == {"reject": True}
    assert applied == [{}]
    worker._drain_outbox(None)
    assert applied == [{}]  # Failed work doesn't poison the rest of sync or spin.
    assert mail.get_status(GetMailStatus(), ctx).state == "failed"
    mail.check_now()
    monkeypatch.setattr(worker, "_apply", lambda *args: None)
    worker._drain_outbox(None)
    assert not ctx.bus.db.fetch_all("SELECT * FROM mail_outbox")
    assert mail.get_status(GetMailStatus(), ctx).state == "live"


def test_failed_interview_has_a_manual_learning_retry(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.SessionRuntime(ctx)
    try:
        session = engine.create("Failed interview", [], "interview").id
        engine._set(session, status="failed", error="Unexpected failure")
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "INSERT INTO mail_learning_reviews(account,state,interview,updated) VALUES('test','asking',?,?)",
                (session, mail_agent._now()),
            )
        mail_agent.set_learning_state(ctx, "asking")
        assert bulk_learning.overview(ctx)["state"] == "failed"
        monkeypatch.setattr(agent, "_triggers", None)
        agent.retry_learning(GetMailAgentSettings(), ctx)
        assert bulk_learning.overview(ctx)["state"] == "asking"
        assert bulk_learning.overview(ctx)["interview"] is None
        assert engine.row(session).status == "failed"  # Keep the failed run for review.
    finally:
        engine.close()


def test_learning_answers_cannot_finalize_an_unfinished_import(ctx: Context) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute("INSERT INTO mail_learning_batches(account,groups_json) VALUES('test','[]')")
    with pytest.raises(CommandError, match="still being learned"):
        bulk_learning.finalize(ctx)
    assert mail_agent.learning_state(ctx) != "done"


def test_stopping_bulk_learning_requires_explicit_retry(ctx: Context) -> None:
    with ctx.bus.db.transaction() as tx:
        batch = tx.execute(
            "INSERT INTO mail_learning_batches(account,groups_json) VALUES('test','[]')"
        ).lastrowid
        run = tx.execute(
            "INSERT INTO trigger_runs(trigger,event,time,status) VALUES(?,?,?,'running')",
            (mail_agent.MAIL_TRIGGER, f"learn-group-{batch}", mail_agent._now()),
        ).lastrowid
    bulk_learning.after_turn(
        ctx, {"id": run, "event": f"learn-group-{batch}"}, 0, "Run stopped before completion."
    )
    assert (
        ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (run,))[0]["status"]
        == "failed"
    )
    assert mail_agent.learning_state(ctx) == "failed"


def test_quiet_hours_defer_obligation_notices_without_marking_them_sent(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO work_board(kind,title,due,by,updated) VALUES('deadline','Do this','2020-01-01','Test',?)",
            (mail_agent._now(),),
        )
    timer = scheduler.Scheduler(ctx)
    monkeypatch.setattr(scheduler.channel, "in_quiet_hours", lambda *_: True)
    timer._overdue(datetime.now(UTC))
    assert (
        ctx.bus.db.fetch_all("SELECT overdue_notified_at FROM work_board")[0]["overdue_notified_at"]
        is None
    )
    monkeypatch.setattr(scheduler.channel, "in_quiet_hours", lambda *_: False)
    timer._overdue(datetime.now(UTC))
    timer._overdue(datetime.now(UTC))
    assert ctx.bus.db.fetch_all("SELECT overdue_notified_at FROM work_board")[0][
        "overdue_notified_at"
    ]
    assert (
        len(ctx.bus.db.fetch_all("SELECT 1 FROM events WHERE type='notification.requested'")) == 1
    )


@pytest.mark.parametrize("output,code", [("not-json\n", 0), ('{"finished": true}\n', 3)])
def test_pst_worker_failure_preserves_checkpoint_and_reaps_child(
    ctx: Context, monkeypatch: pytest.MonkeyPatch, output: str, code: int
) -> None:
    stopped = []
    process = SimpleNamespace(
        stdout=io.StringIO(output),
        stderr=io.StringIO("Bad worker"),
        returncode=code,
        poll=lambda: None,
        terminate=lambda: stopped.append(True),
        kill=lambda: None,
        wait=lambda **_: code,
    )
    monkeypatch.setattr(pst.subprocess, "Popen", lambda *_, **__: process)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO pst_imports(path,name,status,position) VALUES('fake.pst','Test','queued',10)"
        )
    runner = pst.PstRunner()
    runner._drain(ctx)
    saved = ctx.bus.db.fetch_all("SELECT status,position FROM pst_imports")[0]
    assert saved["status"] == "failed" and saved["position"] == 10
    assert runner._current is None
    if output.startswith("not-json"):
        assert stopped


def test_malformed_pst_message_is_counted_and_does_not_abort_the_batch(ctx: Context) -> None:
    with ctx.bus.db.transaction() as tx:
        tx.execute("INSERT INTO pst_imports(path,name,status) VALUES('fake.pst','Test','running')")
    pst._store_batch(ctx, 1, [{"raw": "invalid hex", "seq": 0, "folder": "Archive"}])
    row = ctx.bus.db.fetch_all("SELECT failed,position FROM pst_imports")[0]
    assert row["failed"] == 1 and row["position"] == 1


def test_cockpit_retry_reopens_failed_group_learning(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexusai.contracts.agent import QueueAction

    with ctx.bus.db.transaction() as tx:
        batch = tx.execute(
            "INSERT INTO mail_learning_batches(account,groups_json,attempts) VALUES('test','[]',3)"
        ).lastrowid
        run = tx.execute(
            "INSERT INTO trigger_runs(trigger,event,time,status) VALUES(?,?,?,'failed')",
            (mail_agent.MAIL_TRIGGER, f"learn-group-{batch}", mail_agent._now()),
        ).lastrowid
        tx.execute(
            "INSERT INTO mail_learning_reviews(account,state,updated) VALUES('test','failed',?)",
            (mail_agent._now(),),
        )
    mail_agent.set_learning_state(ctx, "failed")
    monkeypatch.setattr(agent, "_triggers", None)
    agent.act_agent_queue(QueueAction(id=run, action="retry"), ctx)
    assert mail_agent.learning_state(ctx) == "reading"
    assert ctx.bus.db.fetch_all("SELECT state FROM mail_learning_reviews")[0]["state"] == "learning"
    assert ctx.bus.db.fetch_all("SELECT attempts FROM mail_learning_batches")[0]["attempts"] == 0
    assert (
        ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (run,))[0]["status"]
        == "pending"
    )


def test_learning_retry_can_requeue_a_previously_cancelled_batch(ctx: Context) -> None:
    with ctx.bus.db.transaction() as tx:
        batch = tx.execute(
            "INSERT INTO mail_learning_batches(account,groups_json) VALUES('test','[]')"
        ).lastrowid
        run = tx.execute(
            "INSERT INTO trigger_runs(trigger,event,time,status) VALUES(?,?,?,'skipped')",
            (mail_agent.MAIL_TRIGGER, f"learn-group-{batch}", mail_agent._now()),
        ).lastrowid
    bulk_learning.queue(ctx, retry_failed=True, limit_groups=0)
    assert (
        ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (run,))[0]["status"]
        == "pending"
    )


@pytest.mark.parametrize(
    "tool,held",
    [("create_tasks", False), ("search_mail", True), ("unknown_connector_action", False)],
)
def test_model_outage_never_blindly_replays_a_possible_mutation(
    ctx: Context, monkeypatch: pytest.MonkeyPatch, tool: str, held: bool
) -> None:
    engine = runtime.SessionRuntime(ctx)
    try:
        monkeypatch.setattr(engine, "_submit", lambda *_: None)
        engine.on_hold = lambda _: None
        session = engine.create("Partial work", [], "scheduled").id
        turn = engine.dispatch(TurnRequest(session, "Test", "schedule"))
        engine._append(
            turn,
            [
                {
                    "type": "tool-input-available",
                    "toolCallId": "operation",
                    "toolName": tool,
                    "input": {},
                },
                {"type": "tool-output-available", "toolCallId": "operation", "output": "Completed"},
            ],
        )
        assert engine._hold(session, turn, "Model offline") == held
        assert bool(ctx.bus.db.fetch_all("SELECT 1 FROM agent_turns WHERE id=?", (turn,))) != held
    finally:
        engine.close()


def test_finishing_worker_cannot_remove_next_turn_stop_control(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.SessionRuntime(ctx)

    class EmptyStream:
        interrupts: list[Any] = []

        def __iter__(self) -> Any:
            return iter([])

    try:
        monkeypatch.setattr(engine, "_submit", lambda *_: None)
        monkeypatch.setattr(
            engine,
            "_agent",
            lambda *_: SimpleNamespace(stream_events=lambda *args, **kwargs: EmptyStream()),
        )
        session = engine.create("Next turn", [], "session").id
        turn = engine.dispatch(TurnRequest(session, "Test"))
        next_control = runtime._Live()

        def next_turn(*_: Any) -> None:
            with engine.lock:
                engine.live[session] = next_control

        engine.on_turn_end = next_turn
        engine._run(session, turn, {"messages": []})
        assert engine.live.get(session) is next_control
    finally:
        engine.close()


def test_outbox_failure_upgrade_preserves_pending_changes(ctx: Context) -> None:
    from nexusai.api.app import MODULES
    from nexusai.kernel.database import Database
    from nexusai.kernel.event_bus import MIGRATIONS

    migrations = [
        *MIGRATIONS,
        *(migration for module in MODULES for migration in module.migrations),
    ]
    upgrade = next(m for m in migrations if m.id == "mail_outbox_failures_001")
    db = Database(ctx.config.home / "system" / "outbox-upgrade.db")
    try:
        db.migrate([m for m in migrations if m.id != upgrade.id])
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO mail_outbox(account,op,payload,attempts) VALUES('test','read','{\"value\":true}',2)"
            )
        db.migrate([upgrade])
        row = db.fetch_all("SELECT * FROM mail_outbox")[0]
        assert row["attempts"] == 2 and row["failed_at"] is None and row["error"] is None
        assert json.loads(row["payload"]) == {"value": True}
    finally:
        db.close()
