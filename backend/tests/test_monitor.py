"""Monitoring, the agent map and run trees, with a scripted model and no real one."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import gateway, monitor
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_team import ASSIGN, TeamScript, chat, lead, mail, post, task_row, wait


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> TeamScript:
    fake = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda _: (fake, "script-model"))
    return fake


@pytest.fixture
def client(config: Config, script: TeamScript) -> Iterator[TestClient]:
    quick = replace(config, agent=replace(config.agent, triage_retry_seconds=0.1))
    with TestClient(create_app(quick), base_url="http://127.0.0.1:4100") as test:
        yield test


def query(client: TestClient, name: str, body: dict[str, Any] | None = None) -> Any:
    response = client.post(f"/api/queries/{name}", json=body or {})
    assert response.status_code == 200, response.text
    return response.json()


def spend(agent_id: str, tokens: int, when: datetime, session: str = "s") -> None:
    with agent.current().db.transaction() as tx:
        tx.execute(
            "INSERT INTO model_calls (time, day, session, agent, provider, model, input_tokens,"
            " output_tokens, layers, status) VALUES (?, ?, ?, ?, 'script', 'm', ?, 0, '[]', 'done')",
            (when.isoformat(), when.date().isoformat(), session, agent_id, tokens),
        )


def test_a_spike_raises_one_alert_and_only_notifies_when_asked(client: TestClient) -> None:
    now = datetime.now(UTC)
    spend("mail", 1000, now - timedelta(days=2))
    spend("mail", 80_000, now)
    ctx = agent.current().ctx
    monitor.check(ctx, agent.current())
    monitor.check(ctx, agent.current())
    alerts = query(client, "agents.map")["alerts"]
    spikes = [a for a in alerts if a["kind"] == "spike"]
    assert len(spikes) == 1 and "80,000 tokens" in spikes[0]["detail"]
    # Usage alerts stay on the map, out of the notifications, unless the person turns them on.
    items = query(client, "notifications.list")["items"]
    assert not any("80,000" in n["title"] for n in items)
    quiet = query(client, "quietHours.get")
    client.post("/api/commands/quietHours.save", json={**quiet, "token_alerts": True})
    spend("daily-prep", 1000, now - timedelta(days=2))
    spend("daily-prep", 90_000, now)
    monitor.check(ctx, agent.current())
    wait(
        lambda: any("90,000" in n["title"] for n in query(client, "notifications.list")["items"]),
        "the person told",
    )


def test_quiet_hours_under_the_floor_raise_nothing(client: TestClient) -> None:
    spend("mail", 10_000, datetime.now(UTC))
    monitor.check(agent.current().ctx, agent.current())
    assert query(client, "agents.map")["alerts"] == []


class FakeRuntime:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def active_turn(self, session: str) -> int | None:
        return 1

    def stop(self, session: str) -> None:
        self.stopped.append(session)


def test_a_silent_task_is_stopped_and_blocked(client: TestClient) -> None:
    db = agent.current().db
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_turns (session, text, created) VALUES ('owner', 'Task', ?)", (old,)
        )
        turn = tx.execute("SELECT MAX(id) FROM agent_turns").fetchone()[0]
        tx.execute(
            "INSERT INTO team_tasks (objective, expected_output, done_criteria, assigner, owner,"
            " owner_session, owner_turn, state, budget_tokens, created, updated)"
            " VALUES ('o', 'e', 'd', 'session', 'mail', 'owner', ?, 'working', 1000, ?, ?)",
            (turn, old, old),
        )
    runtime = FakeRuntime()
    monitor.check(agent.current().ctx, runtime)
    row = db.fetch_all("SELECT state, failure FROM team_tasks")[0]
    assert (row["state"], row["failure"]) == ("blocked", "silence")
    assert runtime.stopped == ["owner"]


def test_a_task_waiting_on_the_person_is_not_silent(client: TestClient) -> None:
    db = agent.current().db
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_sessions (id, title, agent, status, created, updated)"
            " VALUES ('owner', 'Task', 'mail', 'waiting', ?, ?)",
            (old, old),
        )
        tx.execute(
            "INSERT INTO agent_turns (session, text, created) VALUES ('owner', 'Task', ?)", (old,)
        )
        turn = tx.execute("SELECT MAX(id) FROM agent_turns").fetchone()[0]
        tx.execute(
            "INSERT INTO team_tasks (objective, expected_output, done_criteria, assigner, owner,"
            " owner_session, owner_turn, state, budget_tokens, created, updated)"
            " VALUES ('o', 'e', 'd', 'session', 'mail', 'owner', ?, 'working', 1000, ?, ?)",
            (turn, old, old),
        )
    runtime = FakeRuntime()
    # An approval to move mail, left for an hour, must still find the run there.
    monitor.check(agent.current().ctx, runtime)
    assert db.fetch_all("SELECT state FROM team_tasks")[0]["state"] == "working"
    assert runtime.stopped == []


def test_an_agent_daily_cap_stops_background_work_only(config: Config) -> None:
    capped = replace(config, team=replace(config.team, agent_tokens_per_day=100))
    with TestClient(create_app(capped), base_url="http://127.0.0.1:4100"):
        spend("mail", 500, datetime.now(UTC))
        ctx = agent.current().ctx
        assert monitor.over_daily_cap(ctx, "mail", "person") is None
        told = monitor.over_daily_cap(ctx, "mail", "task")
        assert told and "waits until tomorrow" in told


def test_two_agents_that_talk_too_much_are_cut_off(config: Config, script: TeamScript) -> None:
    chatty = replace(config, team=replace(config.team, messages_per_pair_per_hour=1))
    with TestClient(create_app(chatty), base_url="http://127.0.0.1:4100") as client:
        session = post(client, "session.create")["id"]
        script.say(
            mail(),
            [ToolCall("q", "team_message", {"task": 1, "kind": "ask", "text": "Which week?"})],
            [TextChunk("ok")],
        )
        script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
        chat(client, session, "Go")
        wait(
            lambda: any("messages with them in the last hour" in t for t in tool_results(script)),
            "the ask refused",
            20,
        )


def tool_results(script: TeamScript) -> list[str]:
    return [m.text for _, r in script.requests for m in r.messages if m.role == "tool"]


def test_the_map_shows_open_tasks_and_who_waits(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    held, release = script.hold(mail(), 1)
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    assert held.wait(15)
    shown = query(client, "agents.map")
    edge = shown["edges"][0]
    assert (edge["source"], edge["target"], edge["state"]) == ("session", "mail", "working")
    assert edge["waiting"] == "session" and shown["cycles"] == []
    release.set()


def test_a_run_tree_follows_work_from_cause_to_every_step(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        mail(),
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Done"})],
        [TextChunk("ok")],
    )
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("ok")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Checked"})],
        [TextChunk("Filed.")],
    )
    chat(client, session, "File last week's PLM mail")
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 20)
    first = agent.current().db.fetch_all(
        "SELECT id FROM agent_turns WHERE session = ? ORDER BY id LIMIT 1", (session,)
    )[0]["id"]
    tree = query(client, "run.tree", {"turn": first})
    assert tree["kind"] == "run" and tree["detail"] == "gateway:app"
    kinds = [child["kind"] for child in tree["children"]]
    assert "model" in kinds and "tool" in kinds and "message" in kinds
    owner_run = next(c for c in tree["children"] if c["kind"] == "run")
    assert owner_run["agent"] == "mail"
    woken = next(c for c in owner_run["children"] if c["kind"] == "run")
    assert woken["agent"] == "session" and woken["detail"] == "task:1"
    roots = query(client, "runs.list")["runs"]
    assert roots[0]["id"] == f"run-{first}"


def test_the_gateway_holds_background_calls_past_an_agents_cap(
    config: Config, script: TeamScript
) -> None:
    from nexusai.modules.agent.providers import Message

    capped = replace(config, team=replace(config.team, agent_tokens_per_day=100))
    with TestClient(create_app(capped), base_url="http://127.0.0.1:4100"):
        spend("mail", 500, datetime.now(UTC))
        db = agent.current().db
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO agent_turns (session, text, created, origin) VALUES ('bg', 'x', ?, 'task')",
                (datetime.now(UTC).isoformat(),),
            )
        ctx = agent.current().ctx
        with pytest.raises(gateway.DailyCapReached, match="waits until tomorrow"):
            gateway.call_model(
                ctx, agent="mail", session="bg", layers=[], messages=[Message("user", "hi")]
            )
