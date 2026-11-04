"""Stateful regressions for email coverage, human ownership and prompt adaptation."""
# ruff: noqa: F401,F811

import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.contracts.agent import SavePreference, Schedule
from nexusai.modules.agent import facts, knowledge, mail_agent, personalization, scheduler
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.context import TurnRequest
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import (
    Script,
    app_config,
    client,
    connect,
    fake,
    run_tool,
    script,
    thread_named,
    triaged,
    wait,
)


def post(client: TestClient, name: str, value: dict[str, Any]) -> Any:
    response = client.post("/api/commands/" + name, json=value)
    assert response.is_success, response.text
    return response.json()


def test_dispatch_registers_input_before_submission_and_rolls_back_failed_registration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = agent.current()
    session = post(client, "session.create", {})["id"]
    submitted = []

    def submit(session: str, turn: int, *_: Any) -> None:
        row = runtime.db.fetch_all(
            "SELECT value FROM agent_defaults WHERE key=?", (f"reservation-{turn}",)
        )
        submitted.append(row[0]["value"])

    monkeypatch.setattr(runtime, "_submit", submit)

    def prepare(tx: Any, turn: int) -> None:
        tx.execute("INSERT INTO agent_defaults VALUES(?,?)", (f"reservation-{turn}", "registered"))

    runtime.dispatch(TurnRequest(session, "Test"), prepare=prepare)
    assert submitted == ["registered"]
    another = post(client, "session.create", {})["id"]

    def broken(tx: Any, turn: int) -> None:
        raise ValueError("registration failed")

    with pytest.raises(ValueError):
        runtime.dispatch(TurnRequest(another, "Test"), prepare=broken)
    assert runtime.db.fetch_all("SELECT 1 FROM agent_turns WHERE session=?", (another,)) == []
    assert submitted == ["registered"]


def test_five_thread_burst_claims_three_and_preserves_the_rest(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    threads = []
    for index in range(5):
        subject = f"Coverage {index}"
        fake.state.deliver(make_mail(subject=subject))
        threads.append(thread_named(client, subject)["id"])
    script.default = [TextChunk("Reviewed the supplied conversations.")]
    script.gate = threading.Event()
    trigger = post(
        client,
        "triggers.save",
        {
            "title": "Coverage",
            "event": "mail.urgent",
            "prompt": "Review each supplied conversation.",
        },
    )
    identifier = next(r["id"] for r in trigger["triggers"] if r["title"] == "Coverage")
    dispatcher = agent._triggers
    assert dispatcher is not None
    with dispatcher.lock:
        with agent.current().db.transaction() as tx:
            for index, thread in enumerate(threads):
                tx.execute(
                    "INSERT INTO trigger_runs(trigger,event,time,status,thread) VALUES(?,?,?,'pending',?)",
                    (identifier, f"coverage-{index}", mail_agent._now(), thread),
                )
        dispatcher._start_custom()
        rows = agent.current().db.fetch_all(
            "SELECT status,COUNT(*) n FROM trigger_runs WHERE trigger=? GROUP BY status",
            (identifier,),
        )
        assert {r["status"]: r["n"] for r in rows} == {"pending": 2, "running": 3}
    script.gate.set()
    wait(
        lambda: (
            agent.current().db.fetch_all(
                "SELECT COUNT(*) n FROM trigger_runs WHERE trigger=? AND status='done'",
                (identifier,),
            )[0]["n"]
            == 5
        )
    )
    supplied = "\n".join(m.text for request in script.requests for m in request.messages)
    assert all(f"Coverage {index}" in supplied for index in range(5))


def test_user_correction_survives_an_inflight_and_retried_judgement(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.gate = threading.Event()
    fake.state.deliver(make_mail(subject="Human owns importance"))
    thread = thread_named(client, "Human owns importance")
    wait(lambda: len(script.requests) > 0)
    post(client, "thread.setImportance", {"id": thread["id"], "importance": "high"})
    script.gate.set()
    result = triaged(client, "Human owns importance")
    assert result["importance"] == "high"
    assert len(script.requests) >= 2
    wait(
        lambda: all(
            row["status"] == "done"
            for row in agent.current().db.fetch_all(
                "SELECT status FROM trigger_runs WHERE thread=?", (thread["id"],)
            )
        )
    )


def test_same_thread_new_message_discards_the_old_judgement(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.gate = threading.Event()
    fake.state.deliver(make_mail(subject="Changed request", message_id="<fence-first@example.com>"))
    thread = thread_named(client, "Changed request")
    wait(lambda: len(script.requests) > 0)
    fake.state.deliver(
        make_mail(
            subject="Re: Changed request",
            message_id="<fence-next@example.com>",
            in_reply_to="<fence-first@example.com>",
            body="The requested action has changed.",
        )
    )
    wait(lambda: thread_named(client, "Changed request")["message_count"] == 2)
    # Persistence and listener delivery are separate. Hold the response until both inputs
    # are queued, so this specifically tests one stale run followed by one combined retry.
    wait(lambda: agent.current().db.fetch_all(
        "SELECT COUNT(*) n FROM trigger_runs WHERE thread=?", (thread["id"],)
    )[0]["n"] == 2)
    script.gate.set()
    triaged(client, "Changed request")
    wait(
        lambda: (
            agent.current().db.fetch_all(
                "SELECT COUNT(*) n FROM trigger_runs WHERE thread=? AND status IN ('pending','running')",
                (thread["id"],),
            )[0]["n"]
            == 0
        )
    )
    assert len(script.requests) >= 2
    assert (
        agent.current().db.fetch_all(
            "SELECT COUNT(DISTINCT turn) n FROM triage_runs WHERE thread=? AND status='done'",
            (thread["id"],),
        )[0]["n"]
        == 1
    )


def test_preferences_require_review_and_remain_scoped_and_versioned(client: TestClient) -> None:
    ctx = agent.current().ctx
    proposal = personalization.save(
        ctx,
        SavePreference(
            account="work",
            sender="priya@example.com",
            purpose="mail",
            instruction="Interview requests matter while my search is active.",
        ),
        proposed=True,
    )
    assert personalization.layer(ctx, "mail", "priya@example.com interview", "work") == ""
    body = {k: v for k, v in proposal.model_dump().items() if k not in {"created", "updated"}}
    body["status"] = "active"
    active = post(client, "preferences.save", body)["preferences"][0]
    assert "Interview requests" in personalization.layer(
        ctx, "mail", "priya@example.com interview", "work"
    )
    assert personalization.layer(ctx, "mail", "priya@example.com interview", "personal") == ""
    assert personalization.layer(ctx, "draft-reply", "priya@example.com interview", "work") == ""
    body.update(revision=active["revision"], instruction="My search has ended.", status="retired")
    retired = post(client, "preferences.save", body)["preferences"][0]
    assert personalization.layer(ctx, "mail", "priya@example.com interview", "work") == ""
    conflict = client.post("/api/commands/preferences.save", json=body)
    assert conflict.status_code == 409
    restored = post(
        client,
        "preferences.restore",
        {
            "id": retired["id"],
            "revision": retired["revision"],
            "restore_revision": active["revision"],
        },
    )["preferences"][0]
    assert restored["revision"] == 4 and restored["status"] == "active"


def test_expired_instruction_never_enters_context_and_invalid_expiry_is_rejected(
    client: TestClient,
) -> None:
    post(
        client,
        "preferences.save",
        {"instruction": "Expired preference", "expires_at": "2020-01-01T00:00:00Z"},
    )
    assert "Expired preference" not in personalization.layer(
        agent.current().ctx, "mail", "anything", None
    )
    response = client.post(
        "/api/commands/preferences.save", json={"instruction": "Bad date", "expires_at": "tomorrow"}
    )
    assert response.status_code == 422


def test_scoped_fact_confirmation_and_expiry(client: TestClient) -> None:
    ctx = agent.current().ctx
    from nexusai.modules.agent import memory

    memory.add_learned(ctx.config.home, ["Considering a new role"])
    facts.sync(ctx)
    row = ctx.bus.db.fetch_all("SELECT * FROM learned_facts")[0]
    assert "<untrusted>" in facts.layer(ctx, None, "role", 4000)
    post(client, "memory.confirmNote", {"line": row["line"]})
    confirmed = ctx.bus.db.fetch_all("SELECT * FROM learned_facts")[0]
    assert confirmed["status"] == "confirmed"
    post(
        client,
        "memory.expireNote",
        {
            "line": row["line"],
            "revision": confirmed["revision"],
            "expires_at": "2020-01-01T00:00:00Z",
        },
    )
    assert "Considering a new role" not in facts.layer(ctx, None, "role", 4000)
    assert len(ctx.bus.db.fetch_all("SELECT * FROM learned_fact_versions")) == 3


def test_brief_runs_without_history_and_feedback_targets_immutable_artifact(
    client: TestClient, script: Script
) -> None:
    script.default = [TextChunk("First brief.")]
    db = agent.current().db
    with db.transaction() as tx:
        tx.execute("DELETE FROM agent_defaults WHERE key='mail_learning'")
        tx.execute("INSERT OR REPLACE INTO agent_defaults VALUES('mail_learn_emails','0')")
    identifier = db.fetch_all("SELECT id FROM schedules WHERE kind='mail-brief'")[0]["id"]
    post(client, "schedules.runNow", {"id": identifier})
    first = wait(
        lambda: (lambda d: d if d["prep_text"] == "First brief." else None)(
            client.post("/api/queries/today.view").json()
        )
    )
    script.default = [TextChunk("Second brief.")]
    wait(lambda: agent.current().active_turn(first["prep_session"]) is None)
    post(client, "schedules.runNow", {"id": identifier})
    second = wait(
        lambda: (lambda d: d if d["prep_text"] == "Second brief." else None)(
            client.post("/api/queries/today.view").json()
        )
    )
    assert first["prep_artifact"] != second["prep_artifact"]
    post(
        client,
        "brief.react",
        {
            "session": first["prep_session"],
            "artifact": first["prep_artifact"],
            "rating": "down",
            "comment": "Make the first one shorter.",
        },
    )
    current = client.post("/api/queries/today.view").json()
    assert current["prep_rating"] is None and current["prep_comment"] == ""
    reaction = db.fetch_all(
        "SELECT a.text,f.comment FROM brief_artifact_feedback f JOIN brief_artifacts a ON a.id=f.artifact"
    )[0]
    assert (
        reaction["text"] == "First brief." and reaction["comment"] == "Make the first one shorter."
    )
    script.default = [TextChunk("An unrelated chat answer.")]
    with client.stream(
        "POST",
        "/api/sessions/chat",
        json={"id": first["prep_session"], "text": "Another request", "acknowledge_managed": True},
    ) as response:
        list(response.iter_lines())
    assert client.post("/api/queries/today.view").json()["prep_text"] == "Second brief."


@pytest.mark.parametrize(
    ("after", "time", "expected"),
    [
        ("2026-03-08T05:00:00+00:00", "02:30", "2026-03-08T07:30:00+00:00"),
        ("2026-11-01T04:00:00+00:00", "01:30", "2026-11-01T05:30:00+00:00"),
        ("2026-11-01T06:15:00+00:00", "01:30", "2026-11-02T06:30:00+00:00"),
    ],
)
def test_schedule_dst_policy(after: str, time: str, expected: str) -> None:
    schedule = Schedule(title="Named zone", timezone="America/New_York", time=time, every="day")
    assert scheduler.next_scheduled_run(schedule, datetime.fromisoformat(after)) == expected


def test_one_run_cannot_spend_the_next_runs_message_budget(app_config: Any, script: Script) -> None:
    from dataclasses import replace

    from nexusai.api.app import create_app

    limited = replace(app_config, agent=replace(app_config.agent, max_agent_messages_per_run=1))
    with TestClient(create_app(limited), base_url="http://127.0.0.1:4100") as client:
        ctx = agent.current().ctx
        session = post(client, "session.create", {})["id"]
        script.replies = [
            [
                ToolCall("a", "post_to_agents", {"text": "First"}),
                ToolCall("b", "post_to_agents", {"text": "Second"}),
            ],
            [TextChunk("Done")],
        ]
        with client.stream(
            "POST", "/api/sessions/chat", json={"id": session, "text": "Post"}
        ) as response:
            list(response.iter_lines())
        assert (
            len(ctx.bus.db.fetch_all("SELECT * FROM agent_channel WHERE sender=?", (session,))) == 1
        )
        _, result = run_tool(
            client, script, ToolCall("c", "post_to_agents", {"text": "Next run"}), session=session
        )
        assert result.startswith("Posted")
        assert (
            len(ctx.bus.db.fetch_all("SELECT * FROM agent_channel WHERE sender=?", (session,))) == 2
        )


def test_digest_cursor_catches_up_in_bounded_batches_only_after_success(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Digest coverage"))
    thread = triaged(client, "Digest coverage")
    wait(lambda: agent.current().active_turn(mail_agent.SESSION_ID) is None)
    ctx = agent.current().ctx
    message = ctx.bus.db.fetch_all("SELECT id FROM messages WHERE thread_id=?", (thread["id"],))[0][
        "id"
    ]
    with ctx.bus.db.transaction() as tx:
        for index in range(150):
            tx.execute(
                "INSERT INTO triage_runs(message,thread,time,status,summary) VALUES(?,?,?,'done',?)",
                (message, thread["id"], mail_agent._now(), f"Judgement {index}"),
            )
    prepared = mail_agent.digest_turn(ctx, 0)
    assert prepared and prepared[1] == 100
    following = mail_agent.digest_turn(ctx, 100)
    assert following and following[1] == 151
    script.default = [TextChunk("Digest outcome.")]
    script.gate = threading.Event()
    post(client, "mailAgent.runNow", {})
    wait(lambda: any("bounded catch-up" in m.text for r in script.requests for m in r.messages))
    assert not ctx.bus.db.fetch_all(
        "SELECT value FROM agent_defaults WHERE key LIKE 'last_digest_id:%'"
    )
    script.gate.set()
    wait(
        lambda: (lambda rows: rows and rows[0]["value"] == "151")(
            ctx.bus.db.fetch_all(
                "SELECT value FROM agent_defaults WHERE key LIKE 'last_digest_id:%'"
            )
        )
    )
    assert mail_agent.digest_turn(ctx, 151) is None


def test_preview_never_applies_decisions_and_keeps_human_overrides(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Read-only preview"))
    thread = thread_named(client, "Read-only preview")
    post(client, "thread.setImportance", {"id": thread["id"], "importance": "high"})
    before = agent.current().db.fetch_all("SELECT COUNT(*) n FROM triage_runs")[0]["n"]
    result = post(
        client,
        "preferences.simulate",
        {"purpose": "mail", "instruction": "Treat this kind of request as normal importance."},
    )
    assert result["decisions"][0]["after"].startswith("high")
    assert thread_named(client, "Read-only preview")["importance"] == "high"
    assert agent.current().db.fetch_all("SELECT COUNT(*) n FROM triage_runs")[0]["n"] == before
    assert agent.current().db.fetch_all("SELECT 1 FROM preferences") == []


def test_summary_backfill_uses_message_identity_not_message_count(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Source coverage",
            message_id="<summary-new@x>",
            body="Newest decision.",
            date="Tue, 3 Nov 2026 12:00:00 +0000",
        )
    )
    thread = thread_named(client, "Source coverage")
    script.default = [TextChunk("Initial summary.")]
    first = post(client, "thread.summarize", {"id": thread["id"]})
    assert first["covered"] == 1
    fake.state.deliver(
        make_mail(
            subject="Re: Source coverage",
            message_id="<summary-old@x>",
            in_reply_to="<summary-new@x>",
            body="Earlier contract details.",
            date="Tue, 3 Nov 2026 10:00:00 +0000",
        )
    )
    wait(lambda: thread_named(client, "Source coverage")["message_count"] == 2)
    post(client, "thread.summarize", {"id": thread["id"]})
    text = script.requests[-1].messages[0].text
    assert (
        "Earlier contract details." in text
        and "Newest decision." not in text
        and "Initial summary." in text
    )


def test_large_summary_advances_partial_source_coverage_without_claiming_omitted_text(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Large source", body="Start " + ("long source words " * 3000) + " END_TOKEN"
        )
    )
    thread = thread_named(client, "Large source")
    script.default = [TextChunk("A bounded summary.")]
    first = post(client, "thread.summarize", {"id": thread["id"]})
    assert first["partial"] and first["covered"] == 0 and first["new_messages"] == 1
    for _ in range(8):
        latest = post(client, "thread.summarize", {"id": thread["id"]})
        if latest["new_messages"] == 0:
            break
    assert latest["covered"] == 1 and not latest["partial"]
    assert "END_TOKEN" in script.requests[-1].messages[0].text


def test_confirmation_preserves_fact_expiry(client: TestClient) -> None:
    from nexusai.modules.agent import memory

    ctx = agent.current().ctx
    memory.add_learned(ctx.config.home, ["Temporary launch project"])
    facts.sync(ctx)
    line = ctx.bus.db.fetch_all("SELECT line FROM learned_facts")[0]["line"]
    facts.change(ctx, line, expires_at="2030-01-01T00:00:00+00:00")
    post(client, "memory.confirmNote", {"line": line})
    assert (
        ctx.bus.db.fetch_all("SELECT expires_at FROM learned_facts")[0]["expires_at"]
        == "2030-01-01T00:00:00+00:00"
    )


def test_reply_rejects_a_conversation_that_changes_during_generation(
    client: TestClient, script: Script, fake: FakeMail, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexusai.modules.agent import gateway

    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Changing draft"))
    thread = thread_named(client, "Changing draft")
    original = gateway.call_model

    def changed(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        with agent.current().db.transaction() as tx:
            tx.execute(
                "UPDATE threads SET decision_version=decision_version+1 WHERE id=?", (thread["id"],)
            )
        return result

    monkeypatch.setattr(gateway, "call_model", changed)
    script.default = [TextChunk("Old reply")]
    response = client.post("/api/commands/thread.draftReply", json={"id": thread["id"]})
    assert response.status_code == 409
    assert agent.current().db.fetch_all("SELECT id FROM mail_drafts") == []


def test_large_confirmed_memory_does_not_discard_every_constraint(client: TestClient) -> None:
    from nexusai.modules.agent import memory

    home = agent.current().ctx.config.home
    memory.save_file(
        home,
        "user/confirmed.md",
        "confirmed",
        "user",
        None,
        "\n".join(f"- Confirmed constraint {index}" for index in range(100)),
    )
    selected = memory.relevant(home, "mail", "unrelated task", 250, include_learned=False)
    assert "Confirmed constraint 0" in selected and len(selected) <= 250


def test_empty_digest_does_not_advance_cursor_and_can_be_retried(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Outcome required"))
    triaged(client, "Outcome required")
    wait(lambda: agent.current().active_turn(mail_agent.SESSION_ID) is None)
    script.default = []
    post(client, "mailAgent.runNow", {})
    db = agent.current().db
    failed = wait(
        lambda: db.fetch_all(
            "SELECT id FROM trigger_runs WHERE trigger='mail-digest' AND status='failed'"
        )
    )
    assert db.fetch_all("SELECT value FROM agent_defaults WHERE key LIKE 'last_digest_id:%'") == []
    script.default = [TextChunk("Reviewed the supplied results.")]
    post(client, "agentQueue.act", {"id": failed[0]["id"], "action": "retry"})
    wait(lambda: db.fetch_all("SELECT value FROM agent_defaults WHERE key LIKE 'last_digest_id:%'"))
    # The cursor is recorded before queue completion; wait for the actual terminal state.
    wait(lambda: db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (failed[0]["id"],))[0]["status"] == "done")
    assert (
        db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (failed[0]["id"],))[0]["status"]
        == "done"
    )


def test_plain_legacy_learned_notes_remain_untrusted_context(client: TestClient) -> None:
    from nexusai.modules.agent import memory

    ctx = agent.current().ctx
    memory.replace_learned(ctx.config.home, "Role: engineer.")
    selected = facts.layer(ctx, None, "engineering", 1000)
    assert "<untrusted>" in selected and "Role: engineer." in selected


def test_handoff_requires_recipient_outcome_and_unreported_work_is_blocked(
    client: TestClient, script: Script
) -> None:
    owner = post(client, "session.create", {})["id"]
    recipient = post(client, "session.create", {})["id"]
    script.default = [TextChunk("I reviewed the assignment.")]
    run_tool(
        client,
        script,
        ToolCall(
            "assign",
            "post_to_agents",
            {
                "text": "Review the open commitments.",
                "to_session": recipient,
                "purpose": "Find unresolved commitments",
                "expected_output": "Report source IDs and what remains open",
                "evidence": [],
            },
        ),
        session=owner,
    )
    db = agent.current().db
    row = wait(
        lambda: db.fetch_all(
            "SELECT * FROM agent_channel WHERE recipient=? AND state='blocked'", (recipient,)
        )
    )[0]
    assert row["owner_turn"] is not None
    _, refused = run_tool(
        client,
        script,
        ToolCall(
            "wrong-owner",
            "report_handoff",
            {"id": row["id"], "state": "reported", "outcome": "Done"},
        ),
        session=owner,
    )
    assert "not open" in refused
    _, recorded = run_tool(
        client,
        script,
        ToolCall(
            "right-owner",
            "report_handoff",
            {
                "id": row["id"],
                "state": "reported",
                "outcome": "No unresolved commitments found in the supplied evidence.",
            },
        ),
        session=recipient,
    )
    assert "Outcome recorded" in recorded
    assert (
        db.fetch_all("SELECT state FROM agent_channel WHERE id=?", (row["id"],))[0]["state"]
        == "reported"
    )


def test_digest_scope_and_cursor_are_separate_for_each_mail_account(
    client: TestClient, fake: FakeMail
) -> None:
    from nexusai.modules.mail import accounts

    post(client, "schedules.setDefaults", {"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Account A request", message_id="<account-a@x>"))
    fake.state.deliver(make_mail(subject="Account B request", message_id="<account-b@x>"))
    first = thread_named(client, "Account A request")
    second = thread_named(client, "Account B request")
    ctx = agent.current().ctx
    active, profiles = accounts.read_accounts(ctx.config)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET account='other' WHERE id=?", (second["id"],))
        for thread in (first, second):
            message = tx.execute(
                "SELECT id FROM messages WHERE thread_id=?", (thread["id"],)
            ).fetchone()["id"]
            tx.execute(
                "INSERT INTO triage_runs(message,thread,time,status,summary) VALUES(?,?,?,'done',?)",
                (message, thread["id"], mail_agent._now(), thread["subject"]),
            )
    dispatcher = agent._triggers
    assert dispatcher is not None
    key_a = dispatcher._digest_key()
    result = mail_agent.digest_turn(ctx, 0)
    assert (
        result
        and "Account A request" in result[0].task
        and "Account B request" not in result[0].task
    )
    profiles["other"] = profiles[active]
    accounts.write_accounts(ctx.config, "other", profiles)
    result = mail_agent.digest_turn(ctx, 0)
    assert (
        result
        and "Account B request" in result[0].task
        and "Account A request" not in result[0].task
    )
    assert result[0].context == {"account": "other"}
    assert dispatcher._digest_key() != key_a
