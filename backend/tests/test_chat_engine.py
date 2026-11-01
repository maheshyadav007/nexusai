"""What the chat needs from the engine: answers, edits, follow-ups, tools and categories."""
# ruff: noqa: F811

import json
import threading
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import gateway
from nexusai.modules.agent.providers import ModelNotConfigured, TextChunk, ToolCall
from nexusai.modules.agent.ui_stream import UiTranslator, followups_part
from test_agent_work import (  # noqa: F401
    Script,
    app_config,
    client,
    connect,
    fake,
    script,
    thread_named,
    triage_reply,
    triaged,
    wait,
)


def new_session(client: TestClient, **fields: Any) -> str:
    identifier: str = client.post("/api/commands/session.create", json=fields).json()["id"]
    return identifier


def status(client: TestClient, session: str) -> str:
    view = client.post("/api/queries/session.get", json={"id": session}).json()
    result: str = view["session"]["status"]
    return result


def chat(client: TestClient, session: str, text: str, **fields: Any) -> list[dict[str, Any]]:
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": text, **fields}
    ) as response:
        lines = [line for line in response.iter_lines() if line.startswith("data: {")]
    return [json.loads(line[6:]) for line in lines]


def chat_in_background(client: TestClient, session: str, text: str) -> list[bool]:
    done: list[bool] = []

    def run() -> None:
        chat(client, session, text)
        done.append(True)

    threading.Thread(target=run, daemon=True).start()
    return done


def view(client: TestClient, session: str) -> dict[str, Any]:
    result: dict[str, Any] = client.post("/api/queries/session.get", json={"id": session}).json()
    return result


def last_tool_result(script: Script) -> str:
    text: str = script.requests[-1].messages[-1].text
    return text


def approve_when_asked(client: TestClient, choice: str = "once") -> dict[str, Any]:
    found = wait(lambda: client.post("/api/queries/approvals.list").json()["approvals"], "approval")
    approval: dict[str, Any] = found[0]
    client.post("/api/commands/approvals.decide", json={"id": approval["id"], "choice": choice})
    return approval


def use_tool(client: TestClient, script: Script, call: ToolCall) -> str:
    session = new_session(client)
    script.replies = [[call], [TextChunk("Done.")]]
    chat(client, session, "Do it")
    return last_tool_result(script)


# Asking the person


def test_a_question_is_answered_in_the_chat_and_the_run_carries_on(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    script.replies = [
        [
            ToolCall(
                "c1",
                "ask_user",
                {"question": "Which day?", "options": ["Mon", "Tue"], "multiple": True},
            )
        ],
        [TextChunk("Thanks.")],
    ]
    done = chat_in_background(client, session, "Plan it")
    wait(lambda: status(client, session) == "waiting", "waiting")
    ask = client.post("/api/queries/channel.list").json()["messages"][0]
    assert ask["multiple"] is True
    answered = client.post(
        "/api/commands/session.answer", json={"id": session, "answer": "Mon, Tue"}
    )
    assert answered.status_code == 200
    wait(lambda: done, "finish")
    assert last_tool_result(script) == "They answered: Mon, Tue"
    assert client.post("/api/queries/channel.list").json()["messages"] == []


def test_answering_with_nothing_asked_is_refused(client: TestClient) -> None:
    session = new_session(client)
    refused = client.post("/api/commands/session.answer", json={"id": session, "answer": "Hi"})
    assert (refused.status_code, refused.json()["code"]) == (409, "session.no_question")


def test_the_same_question_asked_twice_gets_asked_twice(client: TestClient, script: Script) -> None:
    session = new_session(client)
    question = {"question": "Anything else?"}
    script.replies = [[ToolCall("c1", "ask_user", question)], [TextChunk("One.")]]
    done = chat_in_background(client, session, "First")
    wait(lambda: status(client, session) == "waiting", "waiting")
    client.post("/api/commands/session.answer", json={"id": session, "answer": "Yes"})
    wait(lambda: done, "first finish")

    script.replies = [[ToolCall("c2", "ask_user", question)], [TextChunk("Two.")]]
    done = chat_in_background(client, session, "Second")
    # An old answer must not be reused for a new question.
    wait(lambda: status(client, session) == "waiting", "second waiting")
    client.post("/api/commands/session.answer", json={"id": session, "answer": "No"})
    wait(lambda: done, "second finish")
    assert last_tool_result(script) == "They answered: No"


def test_the_mail_agent_cannot_be_messaged(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply()]
    fake.state.deliver(make_mail(subject="Mail for the agent"))
    triaged(client, "Mail for the agent")
    refused = client.post("/api/sessions/chat", json={"id": "mail-agent", "text": "hi"})
    assert (refused.status_code, refused.json()["code"]) == (409, "session.not_chattable")


# Follow-ups and times


def test_follow_ups_are_kept_out_of_the_words_even_split_across_chunks() -> None:
    translator = UiTranslator(started=True)
    block = {"id": "t1", "kind": "text"}
    seen = []
    for delta in ["The answer.\n<fol", 'lowups>["One", "Two"', "]</followups>"]:
        seen += translator._visible_text(block, delta)
    seen += translator._end_text(block)
    words = "".join(part["delta"] for part in seen if part["type"] == "text-delta")
    assert words == "The answer.\n"
    assert seen[-1] == {"type": "data-followups", "data": {"questions": ["One", "Two"]}}


def test_a_less_than_sign_in_a_reply_is_still_shown() -> None:
    translator = UiTranslator(started=True)
    block = {"id": "t1", "kind": "text"}
    seen = translator._visible_text(block, "If a <") + translator._visible_text(block, " b then")
    seen += translator._end_text(block)
    assert "".join(p["delta"] for p in seen if p["type"] == "text-delta") == "If a < b then"


def test_malformed_follow_ups_are_dropped() -> None:
    assert followups_part("not json</followups>") == []
    assert followups_part('{"a": 1}</followups>') == []


def test_a_reopened_session_keeps_follow_ups_and_times(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.replies = [[TextChunk('Done.<followups>["Next"]</followups>')]]
    parts = chat(client, session, "Hello")
    assert {"type": "data-followups", "data": {"questions": ["Next"]}} in parts
    user, assistant = view(client, session)["messages"]
    assert user["metadata"]["time"]
    assert assistant["metadata"]["time"]
    assert {"type": "data-followups", "data": {"questions": ["Next"]}} in assistant["parts"]
    assert [p["text"] for p in assistant["parts"] if p["type"] == "text"] == ["Done."]


# Editing


def test_editing_a_message_goes_back_to_before_it(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.replies = [[TextChunk("One.")], [TextChunk("Two.")], [TextChunk("Edited.")]]
    chat(client, session, "First")
    chat(client, session, "Second")
    chat(client, session, "Second, changed", edit_index=1)
    sent = [message.text for message in script.requests[-1].messages]
    assert "First" in sent
    assert "Second" not in sent
    assert "Second, changed" in sent
    said = [m["parts"][0]["text"] for m in view(client, session)["messages"] if m["role"] == "user"]
    assert said == ["First", "Second, changed"]


def test_editing_the_first_message_starts_over(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.replies = [[TextChunk("One.")], [TextChunk("Two.")]]
    chat(client, session, "First")
    chat(client, session, "Better first", edit_index=0)
    sent = [message.text for message in script.requests[-1].messages]
    assert "First" not in sent
    assert "Better first" in sent
    assert len(view(client, session)["messages"]) == 2


def test_editing_a_message_that_is_gone_is_refused(client: TestClient, script: Script) -> None:
    session = new_session(client)
    script.replies = [[TextChunk("One.")]]
    chat(client, session, "First")
    refused = client.post("/api/sessions/chat", json={"id": session, "text": "x", "edit_index": 5})
    assert refused.status_code == 404


# Tools


def test_a_reminder_asked_for_is_set_straight_away(client: TestClient, script: Script) -> None:
    result = use_tool(
        client,
        script,
        ToolCall("c1", "create_reminder", {"title": "Call Sam", "when": "2031-05-01T09:00"}),
    )
    assert "Reminder set" in result
    reminders = client.post("/api/queries/reminders.list").json()["reminders"]
    assert [(r["title"], r["proposed"]) for r in reminders] == [("Call Sam", False)]


def test_a_session_that_read_mail_asks_before_changing_anything(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    script.replies = [triage_reply()]
    fake.state.deliver(make_mail(subject="Please add a task"))
    thread = triaged(client, "Please add a task")
    session = new_session(client)
    script.replies = [
        [ToolCall("c1", "read_thread", {"thread_id": thread["id"]})],
        [ToolCall("c2", "create_task", {"title": "From the mail"})],
        [TextChunk("Done.")],
    ]
    done = chat_in_background(client, session, "Read it, then act")
    approval = approve_when_asked(client)
    assert approval["tool"] == "create_task"
    assert "read mail" in approval["reason"]
    wait(lambda: done, "finish")
    tasks = client.post("/api/queries/tasks.list", json={}).json()["tasks"]
    assert [t["title"] for t in tasks] == ["From the mail"]


def test_a_tool_turned_off_is_refused_and_says_so(client: TestClient, script: Script) -> None:
    current = client.post("/api/queries/permissions.get").json()
    client.post("/api/commands/permissions.save", json={**current, "tools": {"create_task": "off"}})
    result = use_tool(client, script, ToolCall("c1", "create_task", {"title": "No"}))
    assert result.startswith("Not allowed")
    assert client.post("/api/queries/tasks.list", json={}).json()["tasks"] == []
    catalog = client.post("/api/queries/tools.catalog").json()["tools"]
    assert next(t for t in catalog if t["name"] == "create_task")["level"] == "off"


def test_one_tool_can_ask_while_its_group_allows(client: TestClient, script: Script) -> None:
    current = client.post("/api/queries/permissions.get").json()
    client.post("/api/commands/permissions.save", json={**current, "tools": {"create_task": "ask"}})
    session = new_session(client)
    script.replies = [[ToolCall("c1", "create_task", {"title": "Maybe"})], [TextChunk("Ok.")]]
    done = chat_in_background(client, session, "Add it")
    assert approve_when_asked(client)["tool"] == "create_task"
    wait(lambda: done, "finish")


def test_sending_mail_always_asks_even_if_set_to_allow(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    current = client.post("/api/queries/permissions.get").json()
    client.post("/api/commands/permissions.save", json={**current, "tools": {"send_mail": "allow"}})
    catalog = client.post("/api/queries/tools.catalog").json()["tools"]
    assert next(t for t in catalog if t["name"] == "send_mail")["can_allow"] is False
    session = new_session(client)
    arguments = {"to": ["sam@example.com"], "subject": "Numbers", "body": "Here they are."}
    script.replies = [[ToolCall("c1", "send_mail", arguments)], [TextChunk("Sent it.")]]
    done = chat_in_background(client, session, "Send it")
    approval = approve_when_asked(client)
    assert "Here they are." in approval["detail"]
    wait(lambda: done, "finish")
    assert last_tool_result(script) == "Sent."
    assert any("Here they are." in str(envelope) for envelope in fake.sent)


def test_the_database_tool_reads_only_and_only_listed_tables(
    client: TestClient, script: Script
) -> None:
    client.post("/api/commands/tasks.save", json={"title": "Findable"})
    read = lambda sql: use_tool(client, script, ToolCall("c", "read_database", {"sql": sql}))  # noqa: E731
    assert "Findable" in read("SELECT title FROM tasks")
    assert "didn't run" in read("SELECT * FROM guard_tokens")
    assert "didn't run" in read("SELECT * FROM events")
    assert "only one SELECT" in read("DELETE FROM tasks")
    assert "only one SELECT" in read("SELECT 1; DELETE FROM tasks")
    assert "didn't run" in read("WITH x AS (SELECT 1) DELETE FROM tasks")
    assert client.post("/api/queries/tasks.list", json={}).json()["tasks"]


def test_creating_an_agent_asks_first_then_schedules_it(client: TestClient, script: Script) -> None:
    session = new_session(client)
    arguments = {
        "name": "Friday note",
        "instructions": "Draft my status.",
        "every": "week",
        "weekday": 4,
    }
    script.replies = [[ToolCall("c1", "create_agent", arguments)], [TextChunk("Made it.")]]
    done = chat_in_background(client, session, "Make one")
    approval = approve_when_asked(client)
    assert "Draft my status." in approval["detail"]
    wait(lambda: done, "finish")
    rows = client.post("/api/queries/schedules.list").json()["schedules"]
    assert [(r["title"], r["every"], r["prompt"]) for r in rows] == [
        ("Friday note", "week", "Draft my status.")
    ]


# Many approvals at once


def pending(client: TestClient, count: int) -> list[dict[str, Any]]:
    def enough() -> list[dict[str, Any]] | None:
        found: list[dict[str, Any]] = client.post("/api/queries/approvals.list").json()["approvals"]
        return found if len(found) == count else None

    result: list[dict[str, Any]] = wait(enough, f"{count} approvals")
    return result


def mail_session(client: TestClient, script: Script, fake: FakeMail) -> tuple[str, int]:
    """A session that has read mail, which is when changes ask first."""
    connect(client, fake)
    script.replies = [triage_reply()]
    fake.state.deliver(make_mail(subject="Quarterly numbers"))
    thread = triaged(client, "Quarterly numbers")["id"]
    session = new_session(client)
    script.replies = [[ToolCall("r1", "read_thread", {"thread_id": thread})], [TextChunk("Read.")]]
    chat(client, session, "Read it")
    return session, thread


def file_calls(thread: int, count: int, start: int = 0) -> list[ToolCall]:
    return [
        ToolCall(
            f"f{start + n}", "set_thread_category", {"thread_id": thread, "category": "Finance"}
        )
        for n in range(count)
    ]


def test_allowing_for_the_session_settles_everything_of_that_kind_waiting(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    session, thread = mail_session(client, script, fake)
    script.replies = [file_calls(thread, 4), [TextChunk("Filed.")]]
    done = chat_in_background(client, session, "File them")
    waiting = pending(client, 4)
    assert all(item["can_remember"] for item in waiting)
    assert "“Quarterly numbers”" in waiting[0]["summary"]
    client.post(
        "/api/commands/approvals.decide", json={"id": waiting[0]["id"], "choice": "session"}
    )
    wait(lambda: done, "finish")
    assert client.post("/api/queries/approvals.list").json()["approvals"] == []
    assert status(client, session) == "done"


def test_a_session_allowance_holds_for_later_calls_even_after_reading_mail(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    session, thread = mail_session(client, script, fake)
    script.replies = [file_calls(thread, 1), [TextChunk("One.")]]
    done = chat_in_background(client, session, "File it")
    client.post(
        "/api/commands/approvals.decide",
        json={"id": pending(client, 1)[0]["id"], "choice": "session"},
    )
    wait(lambda: done, "first")
    script.replies = [file_calls(thread, 1, 10), [TextChunk("Two.")]]
    chat(client, session, "File it again")
    assert client.post("/api/queries/approvals.list").json()["approvals"] == []
    assert last_tool_result(script) == "Filed under Finance."


def test_allowing_one_tool_does_not_allow_another(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    session, thread = mail_session(client, script, fake)
    script.replies = [file_calls(thread, 1), [TextChunk("One.")]]
    done = chat_in_background(client, session, "File it")
    client.post(
        "/api/commands/approvals.decide",
        json={"id": pending(client, 1)[0]["id"], "choice": "session"},
    )
    wait(lambda: done, "first")
    script.replies = [[ToolCall("t1", "create_task", {"title": "Other"})], [TextChunk("Ok.")]]
    done = chat_in_background(client, session, "Add a task")
    assert pending(client, 1)[0]["tool"] == "create_task"
    client.post(
        "/api/commands/approvals.decide",
        json={"id": pending(client, 1)[0]["id"], "choice": "deny"},
    )
    wait(lambda: done, "second")


def test_mail_cannot_earn_a_session_allowance_for_risky_tools(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    session, _ = mail_session(client, script, fake)
    calls = {
        "run_command": {"command": "echo hi"},
        "create_agent": {"name": "Sneaky", "instructions": "Do things"},
    }
    for name, arguments in calls.items():
        script.replies = [[ToolCall(f"x-{name}", name, arguments)], [TextChunk("Ok.")]]
        done = chat_in_background(client, session, f"Use {name}")
        item = pending(client, 1)[0]
        assert item["can_remember"] is False
        # Even if asked for directly, nothing is remembered.
        client.post("/api/commands/approvals.decide", json={"id": item["id"], "choice": "session"})
        wait(lambda finished=done: finished, name)
        script.replies = [[ToolCall(f"y-{name}", name, arguments)], [TextChunk("Ok.")]]
        done = chat_in_background(client, session, f"Use {name} again")
        again = pending(client, 1)[0]
        assert again["tool"] == name
        client.post("/api/commands/approvals.decide", json={"id": again["id"], "choice": "deny"})
        wait(lambda finished=done: finished, f"{name} again")


def test_many_can_be_decided_together_with_some_declined(
    client: TestClient, script: Script
) -> None:
    current = client.post("/api/queries/permissions.get").json()
    client.post("/api/commands/permissions.save", json={**current, "tools": {"create_task": "ask"}})
    session = new_session(client)
    calls = [ToolCall(f"t{n}", "create_task", {"title": f"Task {n}"}) for n in range(3)]
    script.replies = [calls, [TextChunk("Done.")]]
    done = chat_in_background(client, session, "Add three")
    by_title = {item["summary"][-6:]: item["id"] for item in pending(client, 3)}
    client.post(
        "/api/commands/approvals.decideMany",
        json={"allow": [by_title["Task 0"], by_title["Task 2"]], "deny": [by_title["Task 1"]]},
    )
    wait(lambda: done, "finish")
    titles = {t["title"] for t in client.post("/api/queries/tasks.list", json={}).json()["tasks"]}
    assert titles == {"Task 0", "Task 2"}
    # One run carried on once, not once per decision.
    assert status(client, session) == "done"


def test_declining_one_while_remembering_the_rest_is_respected(
    client: TestClient, script: Script
) -> None:
    current = client.post("/api/queries/permissions.get").json()
    client.post("/api/commands/permissions.save", json={**current, "tools": {"create_task": "ask"}})
    session = new_session(client)
    calls = [ToolCall(f"t{n}", "create_task", {"title": f"Task {n}"}) for n in range(3)]
    script.replies = [calls, [TextChunk("Done.")]]
    done = chat_in_background(client, session, "Add three")
    by_title = {item["summary"][-6:]: item["id"] for item in pending(client, 3)}
    client.post(
        "/api/commands/approvals.decideMany",
        json={
            "allow": [by_title["Task 0"], by_title["Task 2"]],
            "deny": [by_title["Task 1"]],
            "remember": True,
        },
    )
    wait(lambda: done, "finish")
    titles = {t["title"] for t in client.post("/api/queries/tasks.list", json={}).json()["tasks"]}
    assert titles == {"Task 0", "Task 2"}


# Folders and categories


def subjects(client: TestClient, **query: Any) -> list[str]:
    threads = client.post("/api/queries/threads.list", json=query).json()["threads"]
    return [t["subject"] for t in threads]


def test_priority_inbox_is_a_filter_of_all_mail(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    script.default = None
    script.replies = [
        triage_reply(importance="high", status="waiting_on_you", category="Action"),
        triage_reply(importance="normal", status="fyi", category="Reports"),
    ]
    fake.state.deliver(make_mail(subject="Needs a decision"))
    triaged(client, "Needs a decision")
    fake.state.deliver(make_mail(subject="Monthly report"))
    triaged(client, "Monthly report")

    assert set(subjects(client, folder="all")) == {"Needs a decision", "Monthly report"}
    assert subjects(client, folder="priority") == ["Needs a decision"]
    client.post("/api/commands/categories.save", json={"name": "Reports", "in_priority": True})
    assert set(subjects(client, folder="priority")) == {"Needs a decision", "Monthly report"}
    assert subjects(client, folder="all", category="Reports") == ["Monthly report"]


def test_a_category_files_old_mail_and_new_mail(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(category="Action")]
    fake.state.deliver(make_mail(subject="Invoice one", sender="billing@vendor.example"))
    triaged(client, "Invoice one")
    saved = client.post(
        "/api/commands/categories.save", json={"name": "Invoices", "sender": "vendor.example"}
    ).json()
    assert saved["filed"] == 1
    fake.state.deliver(make_mail(subject="Invoice two", sender="billing@vendor.example"))
    wait(lambda: "Invoice two" in subjects(client, folder="all"), "new mail")
    assert set(subjects(client, folder="all", category="Invoices")) == {
        "Invoice one",
        "Invoice two",
    }
    row = next(
        c
        for c in client.post("/api/queries/categories.list").json()["categories"]
        if c["name"] == "Invoices"
    )
    assert (row["source"], row["count"]) == ("user", 2)

    client.post("/api/commands/categories.remove", json={"name": "Invoices"})
    assert subjects(client, folder="all", category="Invoices") == []
    assert set(subjects(client, folder="all")) == {"Invoice one", "Invoice two"}
    rules = client.post("/api/queries/rules.get").json()["rules"]
    assert not [rule for rule in rules if "Invoices" in rule["name"]]


def test_a_suggested_category_waits_and_a_no_is_remembered(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    suggestion = {"name": "Receipts", "sender": "shop.example", "reason": "They come every week."}
    script.replies = [
        triage_reply(suggest_category=suggestion),
        triage_reply(suggest_category=suggestion),
    ]
    fake.state.deliver(make_mail(subject="Receipt 1"))
    triaged(client, "Receipt 1")
    listed = client.post("/api/queries/categories.list").json()["categories"]
    assert next(c for c in listed if c["name"] == "Receipts")["proposed"] is True
    client.post("/api/commands/categories.decide", json={"name": "Receipts", "accept": False})
    fake.state.deliver(make_mail(subject="Receipt 2"))
    triaged(client, "Receipt 2")
    listed = client.post("/api/queries/categories.list").json()["categories"]
    assert not [c for c in listed if c["name"] == "Receipts"]


def test_accepting_a_suggested_category_makes_it_real(
    client: TestClient,
    script: Script,
    fake: FakeMail,
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            suggest_category={"name": "Receipts", "sender": "shop.example", "reason": "Weekly."}
        )
    ]
    fake.state.deliver(make_mail(subject="Receipt 1", sender="news@shop.example"))
    thread = triaged(client, "Receipt 1")
    client.post("/api/commands/categories.decide", json={"name": "Receipts", "accept": True})
    assert thread_named(client, "Receipt 1")["id"] == thread["id"]
    assert subjects(client, folder="all", category="Receipts") == ["Receipt 1"]


def test_connecting_a_model_starts_waiting_triage_straight_away(
    app_config: Config, script: Script, fake: FakeMail, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_model(_: Any) -> Any:
        raise ModelNotConfigured("Connect a model")

    real = gateway.resolve_provider
    monkeypatch.setattr(gateway, "resolve_provider", no_model)
    # A timer far longer than the wait below, so only the event can start it.
    slow = replace(app_config, agent=replace(app_config.agent, triage_retry_seconds=600))
    with TestClient(create_app(slow), base_url="http://127.0.0.1:8765") as live:
        connect(live, fake)
        script.replies = [triage_reply(importance="high")]
        fake.state.deliver(make_mail(subject="Waited for a model"))
        wait(
            lambda: any(
                job["status"] == "waiting for the model"
                for job in live.post("/api/queries/jobs.list").json()["jobs"]
            ),
            "the agent to notice there's no model",
        )
        monkeypatch.setattr(gateway, "resolve_provider", real)
        with live.app.state.bus.unit_of_work() as work:  # type: ignore[attr-defined]
            work.emit("models.changed", {"connected": True}, source="models", trace_id="t")
        wait(
            lambda: thread_named(live, "Waited for a model")["importance"] == "high",
            "triage after connecting",
            seconds=8,
        )
