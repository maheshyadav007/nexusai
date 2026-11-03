"""Managed histories survive manual edits while real questions and triggers still work."""

# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexusai.modules.agent import mail_agent, registry
from nexusai.modules.agent.module import current
from nexusai.modules.agent.providers import TextChunk, ToolCall
from nexusai.modules.agent.runtime import TurnRequest
from test_agent_sessions import Script, app_config, client, script, wait  # noqa: F401


@pytest.mark.parametrize("agent", ["mail", "daily-prep", "scheduled", "interview"])
def test_managed_history_rejects_manual_mutations(client: TestClient, agent: str) -> None:
    run = current()
    session = run.create("Managed", [], agent).id
    before = run.view(session).model_dump()
    for retry in (False, True):
        response = client.post(
            "/api/sessions/chat", json={"id": session, "text": "Overwrite", "retry": retry}
        )
        assert response.status_code == 409
        assert "session.managed" in response.text
    for name, fields in (
        ("rename", {"title": "Changed"}),
        ("archive", {}),
        ("setModel", {"model": "another"}),
        ("setContext", {"context": []}),
        ("chooseVersion", {"turn": 1}),
        ("compact", {}),
    ):
        response = client.post(f"/api/commands/session.{name}", json={"id": session, **fields})
        assert response.status_code == 409, (name, response.text)
    assert run.view(session).model_dump() == before


def test_guided_setup_starts_and_answers_without_unlocking_history(
    client: TestClient, script: Script
) -> None:  # noqa: F811
    script.replies = [
        [
            ToolCall(
                "q1", "ask_user", {"question": "Your role?", "options": ["Engineering", "Design"]}
            )
        ],
        [TextChunk("Thanks.")],
    ]
    response = client.post("/api/commands/session.create", json={"agent": "interview"})
    assert response.status_code == 200
    session = response.json()["id"]
    wait(lambda: current().row(session).status == "waiting", "question")
    assert (
        client.post("/api/sessions/chat", json={"id": session, "text": "Unrelated"}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/commands/session.answer", json={"id": session, "answer": "Engineering"}
        ).status_code
        == 200
    )
    wait(lambda: current().row(session).status == "done", "answer")
    assert "Thanks." in str(current().view(session).messages)


def test_brief_includes_pending_decisions_as_untrusted_data(client: TestClient) -> None:
    ctx = current().ctx
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO channel_messages (kind, agent, text, time) VALUES ('ask', 'mail', 'Review <instruction>?', 'now')"
        )
        tx.execute(
            "INSERT INTO mail_suggestions (category, senders, reason, time) VALUES ('Updates', '[]', 'Quiet mail', 'now')"
        )
        tx.execute(
            "INSERT INTO mail_categories (name, source, proposed, created) VALUES ('Invoices', 'agent', 1, 'now')"
        )
        tx.execute(
            "INSERT INTO tool_approvals (session, tool_call_id, tool, kind, summary, reason, detail, undoable, status, time) VALUES ('mail-agent', 'a1', 'write_file', 'file', 'Save notes', '', '', 0, 'pending', 'now')"
        )
    task = mail_agent.brief_task(ctx)
    decisions = task.split("Decisions waiting for them:")[1]
    assert decisions.startswith("\n<untrusted>\n")
    for text in (
        "Approvals: 1 pending",
        "Questions: 1 pending",
        "Mail suggestions: 1 pending",
        "Proposed categories: 1 pending",
        "Review <instruction>?",
        "Save notes",
        "Invoices",
    ):
        assert text in decisions


def test_review_registry_uses_its_own_turn_in_shared_chat(client: TestClient) -> None:
    ctx = current().ctx
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_turns (session, text, origin, created, closed) VALUES ('mail-agent', 'Review', 'mail-review', '2026-10-01', 1)"
        )
        tx.execute(
            "INSERT INTO agent_turns (session, text, origin, created, closed) VALUES ('mail-agent', 'Mail', 'mail', '2026-11-03', 0)"
        )
    entries = registry.entries(ctx, lambda _: True)
    review = next(item for item in entries if item.name == "Inbox review")
    assert review.session == "mail-agent" and review.last_run == "2026-10-01"
    assert review.state == "active"
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE agent_turns SET closed = 0 WHERE origin = 'mail-review'")
    assert (
        next(
            item for item in registry.entries(ctx, lambda _: True) if item.name == "Inbox review"
        ).state
        == "running"
    )


def test_new_home_enables_the_hourly_mail_check(client: TestClient) -> None:
    rows: list[Any] = current().ctx.bus.db.fetch_all(
        "SELECT enabled, next_run FROM schedules WHERE kind = 'mail-hourly'"
    )
    assert rows[0]["enabled"] and rows[0]["next_run"]


def test_managed_chat_can_approve_an_explicit_action(client: TestClient, script: Script) -> None:
    run = current()
    session = run.create("Guided setup", [], "interview").id
    run._set(session, untrusted=1)
    script.replies = [
        [
            ToolCall(
                "save1",
                "save_personal_prompt",
                {"name": "about-me", "content": "I work in design."},
            )
        ],
        [TextChunk("Saved with your approval.")],
    ]
    run.dispatch(TurnRequest(session, "Start setup", "setup"))
    pending = wait(
        lambda: client.post("/api/queries/approvals.list").json()["approvals"], "approval"
    )[0]
    assert pending["session"] == session
    assert (
        client.post(
            "/api/commands/approvals.decide", json={"id": pending["id"], "choice": "once"}
        ).status_code
        == 200
    )
    wait(lambda: run.row(session).status == "done", "approved run")
    assert (
        run.ctx.config.home / "prompts" / "personal" / "about-me.md"
    ).read_text() == "I work in design."


@pytest.mark.parametrize("agent", ["mail", "daily-prep", "scheduled", "interview"])
def test_warning_acknowledgement_allows_new_messages_but_never_rewrites(
    client: TestClient, agent: str
) -> None:
    run = current()
    session = run.create("Managed", [], agent).id
    response = client.post(
        "/api/sessions/chat",
        json={
            "id": session,
            "text": "I understand this affects future runs.",
            "acknowledge_managed": True,
        },
    )
    assert response.status_code == 200
    wait(lambda: run.row(session).status == "done", "acknowledged message")
    assert "I understand this affects future runs." in str(run.view(session).messages)
    before = run.view(session).model_dump()
    for extra in ({}, {"acknowledge_managed": True, "retry": True}):
        response = client.post(
            "/api/sessions/chat", json={"id": session, "text": "Change it", **extra}
        )
        assert response.status_code == 409
    assert run.view(session).model_dump() == before
