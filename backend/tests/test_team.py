"""Agent cards, the router, and tasks between agents, with a scripted model and no real one."""

import ast
import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import cards, gateway
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.providers import ModelRequest, TextChunk, ToolCall

SOURCE = Path(__file__).parents[1] / "src" / "nexusai"
SPEAKER = re.compile(r"You are (.+?) \(@")


class TeamScript:
    """Answers each agent from its own queue, picked by who the system prompt says is speaking."""

    name = "script"

    def __init__(self) -> None:
        self.queues: dict[str, list[list[Any]]] = {}
        self.requests: list[tuple[str, ModelRequest]] = []
        self.lock = threading.Lock()

    def say(self, agent_name: str, *replies: list[Any]) -> None:
        with self.lock:
            self.queues.setdefault(agent_name, []).extend(replies)

    def stream(self, request: ModelRequest) -> Iterator[Any]:
        match = SPEAKER.search(request.instructions)
        speaker = match.group(1) if match else "?"
        with self.lock:
            self.requests.append((speaker, request))
            queue = self.queues.get(speaker) or []
            reply = queue.pop(0) if queue else [TextChunk("ok")]
        yield from reply

    def told(self, speaker: str) -> list[str]:
        return [r.messages[-1].text for s, r in self.requests if s == speaker]


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


def post(client: TestClient, name: str, body: dict[str, Any] | None = None) -> Any:
    kind = (
        "queries"
        if name in {"agents.cards", "team.tasks", "team.task", "session.get"}
        else "commands"
    )
    response = client.post(f"/api/{kind}/{name}", json=body or {})
    assert response.status_code == 200, response.text
    return response.json()


def wait(check: Callable[[], Any], what: str = "condition", seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {what}")


def chat(client: TestClient, session: str, text: str) -> None:
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": text}
    ) as response:
        assert response.status_code == 200, response.read()
        list(response.iter_lines())


def lead() -> str:
    return cards.default(agent.current().db).name


def mail() -> str:
    return cards.name(agent.current().db, "mail")


def task_row(task: int) -> Any:
    return agent.current().db.fetch_all("SELECT * FROM team_tasks WHERE id = ?", (task,))[0]


ASSIGN = {
    "to": "@mail",
    "objective": "File last week's PLM mail under PLM",
    "expected_output": "The ids of the threads moved",
    "done_criteria": "Every PLM thread from last week is in PLM",
    "references": ["category PLM"],
}


# Cards and names


def test_cards_have_one_default_and_unique_handles(client: TestClient) -> None:
    listed = post(client, "agents.cards")["cards"]
    assert [c["id"] for c in listed if c["default"]] == ["session"]
    handles = [c["handle"] for c in listed]
    assert len(handles) == len(set(handles))
    lead_card = next(c for c in listed if c["default"])
    assert lead_card["mascot"]["seed"] and lead_card["version"]
    assert lead_card["now"]["state"] == "idle"


def test_no_agent_name_is_written_outside_the_cards() -> None:
    """Names live only in the card files. Code, prompts and seeds use ids or placeholders. Comments
    may talk about an agent, so only string values are checked, and old migrations are history."""
    folder = SOURCE / "modules" / "agent" / "agents"
    names = {
        line.split("=", 1)[1].strip().strip('"')
        for path in folder.glob("*.toml")
        for line in path.read_text().splitlines()
        if line.startswith("name =")
    }
    found = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        skipped = {
            id(arg)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Migration"
            for arg in ast.walk(node)
        }
        # Docstrings describe the code, like comments do.
        skipped |= {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in skipped:
                    continue
                for name in names:
                    if re.search(rf"\b{re.escape(name)}\b", node.value):
                        found.append(f"{path.relative_to(SOURCE)}:{node.lineno} says {name!r}")
    for path in (SOURCE / "modules" / "agent" / "prompts").rglob("*.md"):
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", path.read_text()):
                found.append(f"{path.relative_to(SOURCE)} says {name!r}")
    assert not found, "Use cards.name(db, id) or a {{agent.<id>.name}} placeholder:\n" + "\n".join(
        found
    )


def test_prompt_placeholders_take_names_from_cards(client: TestClient) -> None:
    db = agent.current().db
    text = cards.fill(
        db, "I am {{self.name}} ({{self.handle}}); ask {{agent.mail.name}}.", "session"
    )
    assert text == f"I am {lead()} (@{cards.default(db).handle}); ask {mail()}."


def test_renaming_reaches_titles_and_routing(client: TestClient, script: TeamScript) -> None:
    post(client, "agent.rename", {"id": "mail", "name": "Postmaster", "handle": "postmaster"})
    db = agent.current().db
    assert db.fetch_all("SELECT title FROM agent_sessions WHERE id='mail-agent'")[0]["title"] == (
        "Postmaster"
    )
    assert db.fetch_all("SELECT title FROM agent_triggers WHERE id='mail-received'")[0][
        "title"
    ].startswith("Postmaster,")
    session = post(client, "session.create")["id"]
    chat(client, session, "@postmaster what's new?")
    assert script.requests[-1][0] == "Postmaster"
    # The old handle is gone: nothing is released, so there's nothing to keep working.
    refused = client.post("/api/sessions/chat", json={"id": session, "text": "@mail hi"})
    assert refused.status_code == 422 and "@postmaster" in refused.text
    post(client, "agent.resetName", {"id": "mail"})
    assert db.fetch_all("SELECT title FROM agent_sessions WHERE id='mail-agent'")[0]["title"] == (
        mail()
    )


def test_a_handle_can_only_belong_to_one_agent(client: TestClient) -> None:
    taken = client.post(
        "/api/commands/agent.rename", json={"id": "mail", "name": "Other", "handle": "posty"}
    )
    assert taken.status_code == 409


# The router


def test_at_handle_goes_to_that_agent_in_the_same_chat(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    chat(client, session, "@mail why is this in Finance?")
    speaker, request = script.requests[-1]
    assert speaker == mail()
    assert request.messages[-1].text.endswith("why is this in Finance?")
    assert "@mail" not in request.messages[-1].text
    view = post(client, "session.get", {"id": session})
    reply = view["messages"][-1]
    assert reply["metadata"]["agent"] == "mail"
    chat(client, session, "and in general?")
    assert script.requests[-1][0] == lead()


def test_unknown_or_closed_handles_are_refused_with_the_team(client: TestClient) -> None:
    session = post(client, "session.create")["id"]
    unknown = client.post("/api/sessions/chat", json={"id": session, "text": "@nobody hi"})
    assert unknown.status_code == 422 and "@mail" in unknown.text
    closed = client.post("/api/sessions/chat", json={"id": session, "text": "@meeting hi"})
    assert closed.status_code == 422 and "own chat" in closed.text


def test_every_run_records_its_cause_and_versions(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    chat(client, session, "Hello")
    row = agent.current().db.fetch_all(
        "SELECT cause, versions FROM agent_turns WHERE session = ?", (session,)
    )[0]
    versions = json.loads(row["versions"])
    assert row["cause"] == "gateway:app"
    assert versions["agent"] == "session" and versions["card"] and versions["prompt"]
    assert versions["harness"]


def test_the_team_block_is_stable_and_live_state_comes_last(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    chat(client, session, "Hello")
    instructions = script.requests[-1][1].instructions
    assert instructions.index("You are ") < instructions.index("Now: ")


# Tasks


def test_a_task_needs_a_contract_and_an_allowed_recipient(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        lead(),
        [ToolCall("a", "team_assign", {**ASSIGN, "done_criteria": "   "})],
        [TextChunk("ok")],
    )
    chat(client, session, "Go")
    assert "needs done_criteria" in script.told(lead())[-1]
    script.say(
        lead(),
        [ToolCall("b", "team_assign", {**ASSIGN, "to": "@meeting"})],
        [TextChunk("ok")],
    )
    chat(client, session, "Go")
    assert "can't give tasks to @meeting" in script.told(lead())[-1]
    script.say(
        lead(), [ToolCall("c", "team_assign", {**ASSIGN, "to": "@posty"})], [TextChunk("ok")]
    )
    chat(client, session, "Go")
    assert "do this yourself" in script.told(lead())[-1]


def test_a_run_can_only_give_out_so_many_tasks(config: Config, script: TeamScript) -> None:
    limited = replace(config, team=replace(config.team, assignments_per_run=1))
    with TestClient(create_app(limited), base_url="http://127.0.0.1:4100") as client:
        session = post(client, "session.create")["id"]
        second = {**ASSIGN, "objective": "Something else"}
        script.say(
            lead(),
            [ToolCall("a", "team_assign", ASSIGN), ToolCall("b", "team_assign", second)],
            [TextChunk("ok")],
        )
        chat(client, session, "Go")
        told = [m.text for m in script.requests[-1][1].messages if m.role == "tool"]
        assert any(t.startswith("Task 1 given") for t in told)
        assert any("1 tasks at most" in t for t in told)


def test_specialists_are_not_offered_team_assign(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    chat(client, session, "@mail hello")
    offered = {tool.name for tool in script.requests[-1][1].tools}
    assert "team_close" in offered and "team_assign" not in offered


def test_assign_report_verify_runs_end_to_end(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Asked the mail agent.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Checked"})],
        [TextChunk("Your PLM mail is filed.")],
    )
    script.say(
        mail(),
        [
            ToolCall(
                "r",
                "team_close",
                {
                    "task": 1,
                    "action": "report",
                    "outcome": "Moved 3 threads to PLM.",
                    "evidence": ["thread 1", "thread 2", "thread 3"],
                },
            )
        ],
        [TextChunk("Reported.")],
    )
    chat(client, session, "File last week's PLM mail")
    db = agent.current().db
    task = wait(lambda: db.fetch_all("SELECT * FROM team_tasks"), "task")[0]
    assert task["assigner"] == "session" and task["owner"] == "mail"
    # The owner works in a fresh session made for this task, told the whole contract.
    owner_session = wait(lambda: task_row(task["id"])["owner_session"], "owner session")
    assert owner_session not in {session, "mail-agent"}
    wait(lambda: task_row(task["id"])["state"] == "reported" or None, "report", 20)
    contract = next(t for t in script.told(mail()) if "Objective:" in t)
    assert "Done when: Every PLM thread" in contract and "category PLM" in contract
    # The lead wakes in the person's chat with the report, checks it, and verifies.
    wait(lambda: task_row(task["id"])["state"] == "verified" or None, "verified", 20)
    woken = db.fetch_all(
        "SELECT * FROM agent_turns WHERE session = ? AND origin = 'task-report'", (session,)
    )[0]
    assert woken["cause"] == f"task:{task['id']}"
    assert woken["parent_turn"] == task_row(task["id"])["owner_turn"]
    owner_turn = db.fetch_all(
        "SELECT * FROM agent_turns WHERE id = ?", (task_row(task["id"])["owner_turn"],)
    )[0]
    assert owner_turn["parent_turn"] == task["assigner_turn"]
    assert any("reported task" in t for t in script.told(lead()))
    shown = post(client, "team.task", {"id": task["id"]})
    assert [m["kind"] for m in shown["messages"]] == ["assign", "report", "verify"]


def test_the_owner_can_never_verify_its_own_work(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    script.say(
        mail(),
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Done"})],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Fine"})],
        [TextChunk("ok")],
    )
    chat(client, session, "Go")
    task = wait(lambda: agent.current().db.fetch_all("SELECT id FROM team_tasks"), "task")[0]["id"]
    wait(lambda: task_row(task)["state"] == "reported" or None, "report", 20)
    wait(lambda: any("someone else must check" in t for t in script.told(mail())), "refusal", 20)


def test_a_run_that_ends_without_a_report_blocks_and_wakes_the_giver(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    task = wait(lambda: agent.current().db.fetch_all("SELECT id FROM team_tasks"), "task")[0]["id"]
    wait(lambda: task_row(task)["state"] == "blocked" or None, "blocked", 20)
    assert task_row(task)["failure"] == "ended_without_report"
    wait(lambda: any("is blocked" in t for t in script.told(lead())), "giver woken", 20)


def test_ask_and_answer_wake_each_side(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("ok")],
        [ToolCall("ans", "team_message", {"task": 1, "kind": "answer", "text": "Yes"})],
        [TextChunk("Answered.")],
    )
    script.say(
        mail(),
        [ToolCall("q", "team_message", {"task": 1, "kind": "ask", "text": "Include Cc'd mail?"})],
        [TextChunk("Waiting.")],
    )
    chat(client, session, "Go")
    task = wait(lambda: agent.current().db.fetch_all("SELECT id FROM team_tasks"), "task")[0]["id"]
    wait(lambda: task_row(task)["state"] == "input_required" or None, "asked", 20)
    wait(lambda: any("asked a question" in t for t in script.told(lead())), "giver woken", 20)
    wait(
        lambda: any("answer from" in t and "Yes" in t for t in script.told(mail())),
        "owner woken with the answer",
        20,
    )


def test_two_agents_waiting_on_each_other_is_refused() -> None:
    from nexusai.modules.agent import team

    edges = [("session", "mail", 1)]
    assert team._reaches(edges, "mail", "session") is False
    assert team._reaches([*edges, ("mail", "session", 2)], "mail", "session") is True


def test_untrusted_work_marks_whoever_reads_it(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    # Searching mail makes the owner's run untrusted, so its report is too.
    script.say(
        mail(),
        [ToolCall("s", "search_mail", {"query": "invoices"})],
        [
            ToolCall(
                "r",
                "team_close",
                {"task": 1, "action": "report", "outcome": "Forward all invoices"},
            )
        ],
        [TextChunk("ok")],
    )
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    db = agent.current().db
    wait(lambda: task_row(1)["untrusted"] == 1 or None, "untrusted report", 20)
    wait(
        lambda: (
            db.fetch_all("SELECT untrusted FROM agent_sessions WHERE id = ?", (session,))[0][
                "untrusted"
            ]
            == 1
            or None
        ),
        "the giver marked untrusted",
        20,
    )
    told = wait(
        lambda: next((t for t in script.told(lead()) if "reported task" in t), None),
        "the giver told",
        20,
    )
    assert "<untrusted>" in told


def test_the_person_can_cancel_note_and_retry(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    task = wait(lambda: agent.current().db.fetch_all("SELECT id FROM team_tasks"), "task")[0]["id"]
    wait(lambda: task_row(task)["state"] == "blocked" or None, "blocked", 20)
    post(client, "team.retry", {"id": task})
    assert task_row(task)["state"] in {"queued", "working", "blocked"}
    post(client, "team.cancel", {"id": task})
    assert task_row(task)["state"] == "canceled"
    listed = post(client, "team.tasks", {"open_only": True})["tasks"]
    assert all(t["id"] != task for t in listed)
