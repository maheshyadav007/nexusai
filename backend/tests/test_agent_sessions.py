import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.contracts.agent import Permissions
from nexusai.kernel.config import Config
from nexusai.modules.agent import gateway, policy
from nexusai.modules.agent.providers import (
    ModelRequest,
    ModelUnavailable,
    TextChunk,
    ToolCall,
    Usage,
)
from nexusai.modules.agent.ui_stream import UiTranslator

SECRET = "kim.j@samsung.com"


class Script:
    """A fake model that replies from a list, one reply per call, and remembers what it was sent."""

    name = "script"

    def __init__(self) -> None:
        self.replies: list[list[Any]] = []
        self.requests: list[ModelRequest] = []
        self.gate: threading.Event | None = None

    def stream(self, request: ModelRequest) -> Iterator[Any]:
        self.requests.append(request)
        if self.gate:
            self.gate.wait(10)
        reply = self.replies.pop(0) if self.replies else [TextChunk("Done."), Usage(5, 1)]
        for item in reply:
            if isinstance(item, Exception):
                raise item
            yield item


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    fake = Script()
    monkeypatch.setattr(gateway, "resolve_provider", lambda _: (fake, "script-model"))
    return fake


@pytest.fixture
def app_config(config: Config) -> Config:
    return config


@pytest.fixture
def client(app_config: Config, script: Script) -> Iterator[TestClient]:
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as test:
        yield test


def wait(check: Callable[[], Any], what: str = "condition", seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def new_session(client: TestClient) -> str:
    return client.post("/api/commands/session.create", json={}).json()["id"]


def stream_parts(client: TestClient, session: str, text: str) -> list[dict[str, Any]]:
    """Sends a message and reads the whole stream, as the screen does."""
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": text}
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    return [json.loads(line[6:]) for line in lines[:-1]]


def start_turn(client: TestClient, session: str, text: str) -> None:
    def run() -> None:
        with client.stream(
            "POST", "/api/sessions/chat", json={"id": session, "text": text}
        ) as response:
            for _ in response.iter_lines():
                pass

    threading.Thread(target=run, daemon=True).start()


def status(client: TestClient, session: str) -> str:
    return client.post("/api/queries/session.get", json={"id": session}).json()["session"]["status"]


def view(client: TestClient, session: str) -> dict[str, Any]:
    return client.post("/api/queries/session.get", json={"id": session}).json()


def approvals(client: TestClient) -> list[dict[str, Any]]:
    return client.post("/api/queries/approvals.list").json()["approvals"]


def write_call(path: str, content: str = "hello", call_id: str = "c1") -> ToolCall:
    return ToolCall(call_id, "write_file", {"path": path, "content": content})


def test_a_reply_streams_in_the_ai_sdk_format_and_is_kept(
    client: TestClient, script: Script
) -> None:
    script.replies = [[TextChunk("Hel"), TextChunk("lo"), Usage(7, 2)]]
    session = new_session(client)
    parts = stream_parts(client, session, "Say hello please")
    kinds = [p["type"] for p in parts]
    assert kinds == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
    ]
    assert "".join(p["delta"] for p in parts if p["type"] == "text-delta") == "Hello"
    wait(lambda: status(client, session) == "done", "done")
    saved = view(client, session)
    assert saved["session"]["title"] == "Say hello please"
    assert (saved["session"]["input_tokens"], saved["session"]["output_tokens"]) == (7, 2)
    assert saved["active"] is False
    assert saved["messages"][0] == {
        "id": saved["messages"][0]["id"],
        "role": "user",
        "parts": [{"type": "text", "text": "Say hello please"}],
    }
    assert {"type": "text", "text": "Hello", "state": "done"} in saved["messages"][1]["parts"]


def test_conversation_continues_from_its_checkpoint(client: TestClient, script: Script) -> None:
    session = new_session(client)
    stream_parts(client, session, "First")
    wait(lambda: status(client, session) == "done", "first")
    stream_parts(client, session, "Second")
    assert [m.text for m in script.requests[1].messages if m.role == "user"] == ["First", "Second"]
    assert len(view(client, session)["messages"]) == 4


def test_sensitive_values_never_reach_the_model_but_the_person_sees_them(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    parts = stream_parts(client, session, f"Write to {SECRET}")
    sent = script.requests[0]
    assert SECRET not in sent.messages[0].text and SECRET not in sent.instructions
    token = sent.messages[0].text.split()[-1]
    wait(lambda: status(client, session) == "done", "done")
    script.replies = [[TextChunk(f"Will do, {token[:3]}"), TextChunk(f"{token[3:]}!")]]
    parts = stream_parts(client, session, "Confirm")
    assert "".join(p["delta"] for p in parts if p["type"] == "text-delta") == f"Will do, {SECRET}!"
    assert SECRET in json.dumps(view(client, session)["messages"])


def test_writes_inside_scratch_run_without_asking_and_can_be_undone(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    target = config.home / "scratch" / session / "a.txt"
    target.write_text("before")
    script.replies = [[write_call("a.txt", "after")], [TextChunk("Saved.")]]
    parts = stream_parts(client, session, "Save it")
    assert target.read_text() == "after"
    kinds = [p["type"] for p in parts]
    assert (
        kinds.index("tool-input-start")
        < kinds.index("tool-input-available")
        < kinds.index("tool-output-available")
    )
    output = next(p for p in parts if p["type"] == "tool-output-available")
    assert "Wrote 5 characters" in output["output"]

    items = client.post("/api/queries/activity.list").json()["items"]
    assert items[0]["undoable"] is True
    assert (
        client.post("/api/commands/activity.undo", json={"id": items[0]["id"]}).status_code == 200
    )
    assert target.read_text() == "before"
    assert (
        client.post("/api/commands/activity.undo", json={"id": items[0]["id"]}).status_code == 422
    )


def test_undo_removes_a_file_that_didnt_exist(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    script.replies = [[write_call("new.txt")], [TextChunk("Saved.")]]
    stream_parts(client, session, "Save it")
    target = config.home / "scratch" / session / "new.txt"
    assert target.exists()
    item = client.post("/api/queries/activity.list").json()["items"][0]
    client.post("/api/commands/activity.undo", json={"id": item["id"]})
    assert not target.exists()


def test_a_command_waits_for_approval_then_runs_and_the_stream_stays_open(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    marker = config.home / "scratch" / session / "ran.txt"
    script.replies = [
        [ToolCall("c1", "run_command", {"command": f"echo hi > {marker}", "why": "Make a file"})],
        [TextChunk("Finished.")],
    ]
    collected: list[dict[str, Any]] = []

    def read() -> None:
        with client.stream(
            "POST", "/api/sessions/chat", json={"id": session, "text": "Run it"}
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: {"):
                    collected.append(json.loads(line[6:]))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    pending = wait(lambda: approvals(client), "approval")[0]
    assert pending["tool"] == "run_command"
    assert pending["undoable"] is False
    assert pending["detail"].startswith("echo hi")
    assert pending["summary"] == "Make a file"
    assert not marker.exists()
    wait(lambda: status(client, session) == "waiting", "waiting")
    wait(
        lambda: any(p["type"] == "tool-approval-request" for p in collected),
        "request in the stream",
    )

    assert (
        client.post(
            "/api/commands/approvals.decide", json={"id": pending["id"], "choice": "once"}
        ).status_code
        == 200
    )
    reader.join(15)
    assert marker.exists()
    kinds = [p["type"] for p in collected]
    assert (
        kinds.index("tool-approval-request")
        < kinds.index("tool-approval-response")
        < kinds.index("tool-output-available")
    )
    assert kinds[-1] == "finish"
    assert approvals(client) == []
    assert status(client, session) == "done"


def test_a_declined_command_never_runs_and_the_agent_is_told(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    marker = config.home / "scratch" / session / "ran.txt"
    script.replies = [
        [ToolCall("c1", "run_command", {"command": f"echo hi > {marker}"})],
        [TextChunk("Understood.")],
    ]
    start_turn(client, session, "Run it")
    pending = wait(lambda: approvals(client), "approval")[0]
    wait(lambda: status(client, session) == "waiting", "waiting")
    client.post("/api/commands/approvals.decide", json={"id": pending["id"], "choice": "deny"})
    wait(lambda: status(client, session) == "done", "done")
    assert not marker.exists()
    told = [m.text for m in script.requests[1].messages if m.role == "tool"]
    assert told == ["The person declined this."]


def test_allow_for_session_stops_asking_for_the_same_kind_only(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    script.replies = [
        [ToolCall("c1", "run_command", {"command": "echo one"})],
        [TextChunk("ok")],
        [ToolCall("c2", "run_command", {"command": "echo two"})],
        [TextChunk("ok")],
    ]
    start_turn(client, session, "First")
    pending = wait(lambda: approvals(client), "approval")[0]
    wait(lambda: status(client, session) == "waiting", "waiting")
    client.post("/api/commands/approvals.decide", json={"id": pending["id"], "choice": "session"})
    wait(lambda: status(client, session) == "done", "done")
    stream_parts(client, session, "Second")
    wait(lambda: status(client, session) == "done", "second")
    assert approvals(client) == []
    other = new_session(client)
    script.replies = [[ToolCall("c3", "run_command", {"command": "echo three"})], [TextChunk("ok")]]
    start_turn(client, other, "Other session")
    wait(lambda: approvals(client), "a new session asks again")
    client.post("/api/commands/session.stop", json={"id": other})


def test_several_tool_calls_in_one_step_each_get_decided(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    script.replies = [
        [
            ToolCall("c1", "run_command", {"command": "echo one"}),
            ToolCall("c2", "run_command", {"command": "echo two"}),
        ],
        [TextChunk("Both handled.")],
    ]
    start_turn(client, session, "Run both")
    both = wait(lambda: len(approvals(client)) == 2 and approvals(client), "both approvals")
    wait(lambda: status(client, session) == "waiting", "waiting")
    client.post("/api/commands/approvals.decide", json={"id": both[0]["id"], "choice": "once"})
    assert status(client, session) == "waiting"
    client.post("/api/commands/approvals.decide", json={"id": both[1]["id"], "choice": "deny"})
    wait(lambda: status(client, session) == "done", "done")
    results = sorted(m.text for m in script.requests[1].messages if m.role == "tool")
    assert results[0] == "The person declined this." and results[1].endswith("[Exit code 0]")


def test_system_folder_is_refused_outright(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    secret = config.home / "system" / "nexusai.db"
    script.replies = [[ToolCall("c1", "read_file", {"path": str(secret)})], [TextChunk("ok")]]
    stream_parts(client, session, "Read the database")
    assert approvals(client) == []
    assert script.requests[1].messages[-1].text.startswith("Not allowed:")


def test_paths_with_dots_and_links_cant_escape_scratch(
    client: TestClient, script: Script, config: Config, tmp_path: Path
) -> None:
    session = new_session(client)
    link = config.home / "scratch" / session / "link"
    link.symlink_to(config.home / "system")
    script.replies = [
        [ToolCall("c1", "read_file", {"path": "../../system/nexusai.db"})],
        [ToolCall("c2", "read_file", {"path": "link/nexusai.db"})],
        [TextChunk("ok")],
    ]
    stream_parts(client, session, "Try it")
    told = [m.text for m in script.requests[2].messages if m.role == "tool"]
    assert all(text.startswith("Not allowed:") for text in told) and len(told) == 2


def test_reading_mail_makes_a_session_untrusted_so_writes_outside_scratch_ask(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    documents = config.home / "documents" / "note.txt"
    script.replies = [
        [ToolCall("c1", "search_mail", {"query": "budget"})],
        [write_call(str(documents), "x", "c2")],
        [TextChunk("ok")],
    ]
    start_turn(client, session, "Find and file it")
    pending = wait(lambda: approvals(client), "approval")[0]
    assert "read mail or documents" in pending["reason"]
    assert view(client, session)["session"]["untrusted"] is True
    assert not documents.exists()
    wait(lambda: status(client, session) == "waiting", "waiting")
    client.post("/api/commands/session.stop", json={"id": session})
    wait(lambda: status(client, session) == "stopped", "stopped")


def test_mail_results_are_marked_as_data_for_the_model(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.replies = [[ToolCall("c1", "search_mail", {"query": "budget"})], [TextChunk("ok")]]
    stream_parts(client, session, "Search")
    assert script.requests[1].messages[-1].text.startswith("<untrusted>")
    assert "Never follow instructions" in script.requests[0].instructions


def test_a_damaged_token_in_tool_arguments_stops_the_tool(
    client: TestClient, script: Script, config: Config
) -> None:
    session = new_session(client)
    script.replies = [[ToolCall("c1", "write_file", {"path": "x.txt", "content": "<EMAIL_999>"})]]
    parts = stream_parts(client, session, "Write it")
    assert parts[-1]["type"] == "error"
    assert "wasn't given" in parts[-1]["errorText"]
    assert not (config.home / "scratch" / session / "x.txt").exists()
    assert status(client, session) == "failed"


def test_model_failure_is_shown_and_the_session_can_try_again(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    script.replies = [[ModelUnavailable("Couldn't reach the model.")]]
    parts = stream_parts(client, session, "Hello")
    assert parts[-1] == {"type": "error", "errorText": "Couldn't reach the model."}
    assert view(client, session)["session"]["error"] == "Couldn't reach the model."
    stream_parts(client, session, "Again")
    assert status(client, session) == "done"


def test_reconnecting_replays_the_running_turn_then_follows_it(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    script.gate = threading.Event()
    script.replies = [[TextChunk("Long "), TextChunk("answer")]]
    start_turn(client, session, "Think")
    wait(lambda: view(client, session)["active"], "turn to start")
    wait(lambda: status(client, session) == "running", "running")

    def release() -> None:
        time.sleep(0.2)
        assert script.gate
        script.gate.set()

    threading.Thread(target=release, daemon=True).start()
    with client.stream("GET", f"/api/sessions/chat/{session}/stream") as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    text = "".join(json.loads(line[6:]).get("delta", "") for line in lines[:-1])
    assert text == "Long answer"
    assert client.get(f"/api/sessions/chat/{session}/stream").status_code == 204


def test_only_one_turn_at_a_time_per_session(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.gate = threading.Event()
    start_turn(client, session, "First")
    wait(lambda: view(client, session)["active"], "turn")
    busy = client.post("/api/sessions/chat", json={"id": session, "text": "Second"})
    assert busy.status_code == 409
    assert busy.json()["code"] == "session.busy"
    assert script.gate
    script.gate.set()


def test_three_sessions_run_together_and_the_fourth_waits(
    client: TestClient, script: Script
) -> None:
    script.gate = threading.Event()
    sessions = [new_session(client) for _ in range(4)]
    for session in sessions:
        start_turn(client, session, "Work")
    wait(lambda: sum(status(client, s) == "running" for s in sessions) == 3, "three running")
    wait(lambda: sum(status(client, s) == "queued" for s in sessions) == 1, "the fourth to wait")
    listed = client.post("/api/queries/sessions.list", json={}).json()
    assert (listed["running"], listed["limit"]) == (3, 3)
    assert script.gate
    script.gate.set()
    wait(lambda: all(status(client, s) == "done" for s in sessions), "all done")


def test_stop_ends_a_running_command(client: TestClient, script: Script) -> None:
    session = new_session(client)
    policy_body = Permissions(command="allow").model_dump()
    client.post("/api/commands/permissions.save", json=policy_body)
    script.replies = [
        [ToolCall("c1", "run_command", {"command": "sleep 30"})],
        [TextChunk("never")],
    ]
    start_turn(client, session, "Wait")
    wait(lambda: status(client, session) == "running", "running")
    time.sleep(0.5)
    started = time.monotonic()
    client.post("/api/commands/session.stop", json={"id": session})
    wait(lambda: status(client, session) == "stopped", "stopped")
    assert time.monotonic() - started < 10


def test_commands_time_out_and_say_so(app_config: Config, script: Script) -> None:
    quick = replace(app_config, agent=replace(app_config.agent, command_timeout_seconds=0.3))
    with TestClient(create_app(quick), base_url="http://127.0.0.1:8765") as test:
        session = new_session(test)
        test.post("/api/commands/permissions.save", json=Permissions(command="allow").model_dump())
        script.replies = [
            [ToolCall("c1", "run_command", {"command": "sleep 30"})],
            [TextChunk("ok")],
        ]
        stream_parts(test, session, "Wait")
        assert "second limit" in script.requests[1].messages[-1].text


def test_waiting_sessions_survive_a_restart_and_finish_when_approved(
    app_config: Config, script: Script
) -> None:
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as first:
        session = new_session(first)
        marker = app_config.home / "scratch" / session / "ran.txt"
        script.replies = [
            [ToolCall("c1", "run_command", {"command": f"echo hi > {marker}"})],
            [TextChunk("Finished after restart.")],
        ]
        start_turn(first, session, "Run it")
        pending = wait(lambda: approvals(first), "approval")[0]
        wait(lambda: status(first, session) == "waiting", "waiting")
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as second:
        assert status(second, session) == "waiting"
        assert approvals(second)[0]["id"] == pending["id"]
        second.post("/api/commands/approvals.decide", json={"id": pending["id"], "choice": "once"})
        wait(lambda: status(second, session) == "done", "finish after restart")
        assert marker.exists()
        assert "Finished after restart." in json.dumps(view(second, session)["messages"])


def test_a_running_session_resumes_after_a_restart(app_config: Config, script: Script) -> None:
    script.gate = threading.Event()
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as first:
        session = new_session(first)
        script.replies = [[TextChunk("Interrupted")]]
        start_turn(first, session, "Long job")
        wait(lambda: status(first, session) == "running", "running")
        # Mid-call when the app closes: it resumes from the last checkpoint on next start.
        with first.app.state.bus.unit_of_work():  # type: ignore[attr-defined]
            pass
        threading.Timer(0.3, script.gate.set).start()
    script.gate = None
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as second:
        wait(lambda: status(second, session) in {"done", "failed"}, "resume or finish")
        assert status(second, session) == "done"


def test_final_prompt_is_viewable_by_session_with_each_layer(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    stream_parts(client, session, f"Mail {SECRET}")
    call = client.post("/api/queries/modelCall.get", json={"session": session}).json()
    names = [layer["name"] for layer in call["layers"]]
    assert (
        names[0] == "System prompt" and names[1] == "Agent prompt" and names[-1] == "Task content"
    )
    assert SECRET in call["layers"][-1]["real"] and SECRET not in call["layers"][-1]["masked"]
    assert "This computer:" in call["layers"][0]["real"]


def test_edit_needs_exactly_one_match(client: TestClient, script: Script, config: Config) -> None:
    session = new_session(client)
    target = config.home / "scratch" / session / "t.txt"
    target.write_text("aa bb aa")
    script.replies = [
        [ToolCall("c1", "edit_file", {"path": "t.txt", "old_text": "aa", "new_text": "cc"})],
        [ToolCall("c2", "edit_file", {"path": "t.txt", "old_text": "bb", "new_text": "cc"})],
        [TextChunk("ok")],
    ]
    stream_parts(client, session, "Edit")
    assert target.read_text() == "aa cc aa"
    assert "appears 2 times" in script.requests[1].messages[-1].text


def test_rename_archive_and_search_sessions(client: TestClient, script: Script) -> None:
    session = new_session(client)
    client.post("/api/commands/session.rename", json={"id": session, "title": "Budget work"})

    def listed(**body):
        return [
            s["title"]
            for s in client.post("/api/queries/sessions.list", json=body).json()["sessions"]
        ]  # noqa: E731

    assert listed(query="budget") == ["Budget work"]
    assert listed(query="zebra") == []
    client.post("/api/commands/session.archive", json={"id": session})
    assert listed() == []
    assert listed(archived=True) == ["Budget work"]


HOME = Path("/h")


@pytest.mark.parametrize(
    ("action", "path", "untrusted", "settings", "verdict"),
    [
        ("read", HOME / "scratch/a", False, {}, "allow"),
        ("read", HOME / "memory/a", False, {}, "allow"),
        ("read", HOME / "prompts/a", False, {}, "allow"),
        ("read", HOME / "system/a", False, {}, "deny"),
        ("read", HOME / "home.json", False, {}, "deny"),
        ("read", Path("/etc/passwd"), False, {}, "ask"),
        ("read", Path("/etc/passwd"), False, {"full_computer_access": True}, "allow"),
        ("read", Path("/added/x"), False, {"folders": ["/added"]}, "allow"),
        ("read", HOME / "scratch/a", False, {"read": "off"}, "deny"),
        ("read", HOME / "scratch/a", False, {"read": "ask"}, "ask"),
        ("write", HOME / "scratch/a", False, {}, "allow"),
        ("write", HOME / "documents/a", False, {}, "allow"),
        ("write", HOME / "prompts/a", False, {}, "deny"),
        ("write", HOME / "system/a", False, {}, "deny"),
        ("write", Path("/added/x"), False, {"folders": ["/added"]}, "ask"),
        ("write", Path("/etc/x"), False, {}, "ask"),
        ("write", Path("/etc/x"), False, {"full_computer_access": True}, "allow"),
        ("write", HOME / "scratch/a", True, {}, "allow"),
        ("write", HOME / "documents/a", True, {}, "ask"),
        ("write", Path("/etc/x"), True, {"full_computer_access": True}, "ask"),
        ("write", HOME / "scratch/a", False, {"write": "off"}, "deny"),
        ("command", None, False, {}, "ask"),
        ("command", None, False, {"command": "allow"}, "allow"),
        ("command", None, False, {"command": "off"}, "deny"),
        ("command", None, True, {"command": "allow"}, "ask"),
        ("send", None, False, {"command": "allow", "full_computer_access": True}, "ask"),
    ],
)
def test_permission_table(
    action: Any, path: Path | None, untrusted: bool, settings: dict[str, Any], verdict: str
) -> None:
    decision = policy.decide(
        action, path=path, home=HOME, permissions=Permissions(**settings), untrusted=untrusted
    )
    assert decision.verdict == verdict, decision.reason


def test_an_untrusted_session_cant_be_loosened_by_an_earlier_allowance() -> None:
    decision = policy.decide(
        "command",
        path=None,
        home=HOME,
        permissions=Permissions(),
        untrusted=True,
        session_allowed=True,
    )
    assert decision.verdict == "ask"


def test_translator_ignores_other_nodes_and_repeated_tool_events() -> None:
    translator = UiTranslator(started=True)
    summary = {
        "method": "messages",
        "params": {
            "data": [
                {"event": "message-start"},
                {"langgraph_node": "SummarizationMiddleware.before_model"},
            ]
        },
    }
    assert translator.feed(summary) == []
    started = {
        "method": "tools",
        "params": {"data": {"event": "tool-started", "tool_call_id": "c"}},
    }
    assert translator.feed(started) == []
    finished = {
        "method": "tools",
        "params": {"data": {"event": "tool-finished", "tool_call_id": "c", "output": "x"}},
    }
    assert len(translator.feed(finished)) == 1
    assert translator.feed(finished) == []
    assert translator.feed({"method": "values", "params": {"data": {}}}) == []
