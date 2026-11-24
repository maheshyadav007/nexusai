import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import PASSWORD, FakeMail, make_mail, start_fake_mail
from nexusai.api.app import create_app
from nexusai.contracts.agent import QuietHours, Schedule
from nexusai.kernel.config import Config
from nexusai.modules.agent import channel, gateway, scheduler
from nexusai.modules.agent.providers import (
    ModelFlagged,
    ModelRequest,
    ModelUnavailable,
    ReasoningChunk,
    TextChunk,
    ToolCall,
    Usage,
)


def triage_reply(**fields: Any) -> list[Any]:
    base = {
        "category": "Action",
        "importance": "normal",
        "status": "waiting_on_you",
        "summary": "A request.",
        "reason": "It asks you something.",
        "facts": ["Due Friday"],
        "suggested_action": "Reply",
        "deadlines": [],
        "tasks": [],
        "reminders": [],
        "draft": None,
        "memory": None,
        "question": None,
    }
    return [ToolCall("t1", "record_triage", {**base, **fields})]


class Script:
    name = "script"

    def __init__(self) -> None:
        self.replies: list[list[Any]] = []
        self.default: list[Any] | None = None
        self.requests: list[ModelRequest] = []
        self.gate: threading.Event | None = None

    def stream(self, request: ModelRequest) -> Iterator[Any]:
        self.requests.append(request)
        if self.gate and not self.gate.wait(60):
            raise TimeoutError("The test did not release its model-response gate")
        reply = (
            self.replies.pop(0)
            if self.replies
            else (self.default if self.default is not None else triage_reply())
        )
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
def fake() -> Iterator[FakeMail]:
    server = start_fake_mail()
    yield server
    server.stop()


@pytest.fixture
def app_config(config: Config) -> Config:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
    )
    agent = replace(config.agent, triage_retry_seconds=0.1)
    return replace(config, mail=mail, agent=agent)


@pytest.fixture
def client(app_config: Config, script: Script) -> Iterator[TestClient]:
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:4100") as test:
        yield test


def wait(check: Callable[[], Any], what: str = "condition", seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def connect(client: TestClient, fake: FakeMail, *, sorted_first: bool = True) -> None:
    """A mailbox the person already sorted, or chose not to, so learning starts as it did
    before sorting existed. Tests of the sorting step itself pass sorted_first=False."""
    if sorted_first:
        assert client.post("/api/commands/mail.sort.skip", json={}).status_code == 200
    client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "t", "profile": fake.profile(), "password": PASSWORD},
    )
    wait(lambda: client.post("/api/queries/mail.status").json()["state"] == "live", "live")


def thread_named(client: TestClient, subject: str) -> dict[str, Any]:
    return wait(
        lambda: next(
            (
                t
                for t in client.post("/api/queries/threads.list", json={}).json()["threads"]
                if subject in t["subject"]
            ),
            None,
        ),
        subject,
    )


def triaged(client: TestClient, subject: str) -> dict[str, Any]:
    return wait(
        lambda: (lambda t: t if t["category_source"] == "agent" else None)(
            thread_named(client, subject)
        ),
        f"{subject} triaged",
    )


def test_new_mail_gets_judged_and_shows_why(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Please review", body="Can you review by Friday?"))
    thread = triaged(client, "Please review")
    assert (thread["category"], thread["importance"], thread["status"]) == (
        None,
        "normal",
        "waiting_on_you",
    )
    assert thread["why"] == "It asks you something."
    runs = client.post("/api/queries/triage.runs", json={"thread": thread["id"]}).json()["runs"]
    assert runs[0]["summary"] == "A request." and runs[0]["facts"] == ["Due Friday"]
    sent = script.requests[0]
    assert "<untrusted>" in sent.messages[0].text and "review by Friday" in sent.messages[0].text


def test_rule_matched_mail_never_reaches_the_model(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Build passed", sender="no-reply@ci.example"))
    assert thread_named(client, "Build passed")["category"] == "Automated"
    time.sleep(0.3)
    assert script.requests == []


def test_older_mail_is_not_judged_unless_asked_with_an_estimate_first(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    fake.state.deliver(make_mail(subject="Old one"))
    fake.state.deliver(make_mail(subject="Old two"))
    connect(client, fake)
    time.sleep(0.3)
    assert script.requests == []
    estimate = client.post("/api/queries/triage.estimate").json()
    assert estimate["untriaged"] == 2 and estimate["approx_tokens"] > 0
    assert client.post("/api/commands/triage.existing", json={}).json()["untriaged"] == 2
    time.sleep(0.2)
    assert script.requests == []
    client.post("/api/commands/triage.existing", json={"confirm": True})
    triaged(client, "Old one")
    triaged(client, "Old two")


def test_a_burst_is_grouped_by_conversation(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.gate = threading.Event()
    fake.state.deliver(make_mail(subject="Starter", message_id="<s@x>"))
    wait(lambda: script.requests, "first run to start")
    for number in range(4):
        fake.state.deliver(
            make_mail(
                subject="Re: Starter",
                message_id=f"<r{number}@x>",
                in_reply_to="<s@x>",
                references="<s@x>",
            )
        )
    wait(lambda: client.post("/api/queries/mail.status").json()["messages"] == 5, "all stored")
    wait(
        lambda: client.post("/api/queries/triage.estimate").json()["queued"] >= 4,
        "the burst to queue",
    )
    assert script.gate
    script.gate.set()
    wait(
        lambda: client.post("/api/queries/triage.estimate").json()["queued"] == 0,
        "the queue to empty",
    )
    assert len(script.requests) == 2
    assert script.requests[1].messages[-1].text.count("From ") >= 4


def test_triage_waits_for_the_model_and_catches_up(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.default = [ModelUnavailable("down")]
    fake.state.deliver(make_mail(subject="While down"))
    wait(lambda: len(script.requests) >= 2, "retries")
    assert thread_named(client, "While down")["category"] is None
    jobs = client.post("/api/queries/jobs.list").json()["jobs"]
    assert next(j for j in jobs if j["kind"] == "triage")["status"] == "waiting for the model"
    script.default = None
    triaged(client, "While down")
    wait(
        lambda: (
            not [
                j
                for j in client.post("/api/queries/jobs.list").json()["jobs"]
                if j["kind"] == "triage"
            ]
        ),
        "the run to finish",
    )


def test_flagged_mail_stays_uncategorized_and_shows_the_error(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [[ModelFlagged("The model refused this content under its policy.")]]
    fake.state.deliver(make_mail(subject="Flag me"))
    thread = wait(
        lambda: (lambda t: t if t["why"] else None)(thread_named(client, "Flag me")), "error shown"
    )
    assert thread["category"] is None and "refused" in thread["why"]
    assert client.post("/api/queries/triage.estimate").json()["queued"] == 0
    runs = client.post("/api/queries/triage.runs", json={"thread": thread["id"]}).json()["runs"]
    assert runs[0]["status"] == "failed"


def test_what_the_person_chose_isnt_overwritten(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Mine", message_id="<m1@x>"))
    thread = triaged(client, "Mine")
    client.post(
        "/api/commands/thread.setCategory", json={"id": thread["id"], "category": "Personal"}
    )
    fake.state.deliver(make_mail(subject="Re: Mine", message_id="<m2@x>", in_reply_to="<m1@x>"))
    wait(lambda: len(script.requests) == 2, "second run")
    time.sleep(0.2)
    assert thread_named(client, "Mine")["category"] == "Personal"


def test_importance_can_change_with_a_new_message(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Rising", message_id="<u1@x>"))
    triaged(client, "Rising")
    script.replies = [triage_reply(importance="high", reason="The customer escalated.")]
    fake.state.deliver(make_mail(subject="Re: Rising", message_id="<u2@x>", in_reply_to="<u1@x>"))
    thread = wait(
        lambda: (lambda t: t if t["importance"] == "high" else None)(
            thread_named(client, "Rising")
        ),
        "raised",
    )
    assert thread["why"] == "The customer escalated."
    notices = wait(
        lambda: client.post("/api/queries/notifications.list", json={"kind": "urgent-mail"}).json()[
            "items"
        ],
        "alert",
    )
    assert "Rising" in notices[0]["title"]


def test_proposals_wait_for_the_person(client: TestClient, script: Script, fake: FakeMail) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            deadlines=[{"what": "Contract due", "due": "2099-01-15"}],
            tasks=[{"title": "Review the contract", "due": "2099-01-10"}],
            reminders=[{"title": "Chase legal", "when": "2099-01-09T09:00"}],
            draft="Thanks, I'll review it.",
            learned=["Priya runs procurement."],
        )
    ]
    fake.state.deliver(make_mail(subject="Contract"))
    thread = triaged(client, "Contract")
    task = wait(lambda: client.post("/api/queries/tasks.list", json={}).json()["tasks"], "task")[0]
    assert task["proposed"] is True and task["source"] == "agent" and task["thread"] == thread["id"]
    # With a task, the deadline is the task's date rather than a second line beside it.
    assert task["due"] == "2099-01-10"
    assert client.post("/api/queries/board.list").json()["items"] == []
    reminder = client.post("/api/queries/reminders.list").json()["reminders"][0]
    assert reminder["proposed"] is True
    draft = client.post("/api/queries/drafts.list").json()["drafts"][0]
    assert draft["source"] == "agent" and draft["subject"] == "Re: Contract"
    assert fake.sent == []
    # What it learns is kept at once, marked with the email it came from, for them to remove.
    kept = client.post("/api/queries/memory.list", json={}).json()
    assert kept["proposals"] == []
    assert any(
        f"Priya runs procurement. [mail:{thread['id']}]" in file["content"]
        for file in kept["files"]
    )


def test_a_question_gives_a_best_guess_then_updates_when_answered(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(question="Is this urgent?", importance="normal", reason="Looks routine.")
    ]
    fake.state.deliver(make_mail(subject="Maybe urgent"))
    thread = triaged(client, "Maybe urgent")
    assert "best guess" in thread["why"]
    ask = wait(lambda: client.post("/api/queries/channel.list").json()["messages"], "ask")[0]
    assert (ask["kind"], ask["text"], ask["thread"]) == ("ask", "Is this urgent?", thread["id"])
    script.replies = [triage_reply(importance="high", reason="You said it's urgent.")]
    client.post("/api/commands/channel.respond", json={"id": ask["id"], "answer": "Yes, today"})
    updated = wait(
        lambda: (lambda t: t if t["importance"] == "high" else None)(
            thread_named(client, "Maybe urgent")
        ),
        "update",
    )
    assert updated["why"] == "You said it's urgent."
    assert "Yes, today" in script.requests[-1].messages[-1].text
    assert client.post("/api/queries/channel.list").json()["messages"] == []


def test_an_answered_question_is_not_asked_again_and_nothing_doubles(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    same = {
        "question": "Is this urgent?",
        "tasks": [{"title": "Reply", "due": None}],
        "reminders": [{"title": "Check back", "when": "2031-05-01T09:00"}],
        "learned": ["They run payroll."],
        "draft": "Thanks.",
    }
    script.replies = [triage_reply(**same), triage_reply(**same)]
    fake.state.deliver(make_mail(subject="Twice judged"))
    thread = triaged(client, "Twice judged")
    ask = wait(lambda: client.post("/api/queries/channel.list").json()["messages"], "ask")[0]
    client.post("/api/commands/channel.respond", json={"id": ask["id"], "answer": "Yes"})
    wait(
        lambda: len(script.requests) == 2 and "Yes" in script.requests[-1].messages[-1].text,
        "second",
    )
    wait(lambda: "best guess" not in thread_named(client, "Twice judged")["why"], "settled")
    assert client.post("/api/queries/channel.list").json()["messages"] == []
    tasks = client.post("/api/queries/tasks.list", json={}).json()["tasks"]
    assert [t["title"] for t in tasks if t["thread"] == thread["id"]] == ["Reply"]
    reminders = client.post("/api/queries/reminders.list", json={}).json()["reminders"]
    assert [r["title"] for r in reminders if r["thread"] == thread["id"]] == ["Check back"]
    files = client.post("/api/queries/memory.list", json={"query": ""}).json()["files"]
    assert sum(f["content"].count("They run payroll.") for f in files) == 1
    drafts = client.post("/api/queries/drafts.list", json={}).json()["drafts"]
    assert [d["body"] for d in drafts if d["thread_id"] == thread["id"]] == ["Thanks."]


def test_mail_agent_is_one_entry_with_a_record_per_run(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="First"))
    triaged(client, "First")
    fake.state.deliver(make_mail(subject="Second"))
    triaged(client, "Second")
    sessions = client.post("/api/queries/sessions.list", json={}).json()["sessions"]
    assert [s["title"] for s in sessions].count("Mail agent") == 1
    view = client.post("/api/queries/session.get", json={"id": "mail-agent"}).json()
    said = [m for m in view["messages"] if m["role"] == "user"]
    assert [m["parts"][0]["text"] for m in said] == [
        "New email from Priya Nair: First. Triage it.",
        "New email from Priya Nair: Second. Triage it.",
    ]
    assert {m["metadata"]["origin"] for m in said} == {"mail"}


def test_turning_the_mail_agent_off_stops_new_runs(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    listed = client.post(
        "/api/commands/schedules.setDefaults", json={"live_mail_enabled": False}
    ).json()
    assert listed["live_mail_enabled"] is False
    fake.state.deliver(make_mail(subject="Ignored"))
    thread_named(client, "Ignored")
    time.sleep(0.3)
    assert script.requests == []


def test_summaries_only_run_when_asked_are_stored_and_update_from_new_mail(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    client.post("/api/commands/schedules.setDefaults", json={"live_mail_enabled": False})
    fake.state.deliver(
        make_mail(
            subject="Long",
            message_id="<l1@x>",
            body="First point",
            date="Mon, 5 Jan 2026 10:00:00 +0000",
        )
    )
    thread = thread_named(client, "Long")
    assert (
        client.post("/api/queries/thread.summary", json={"id": thread["id"]}).json()["text"] is None
    )
    assert script.requests == []
    script.replies = [[TextChunk("Summary one.")]]
    done = client.post("/api/commands/thread.summarize", json={"id": thread["id"]}).json()
    assert (done["text"], done["covered"], done["new_messages"]) == ("Summary one.", 1, 0)

    fake.state.deliver(
        make_mail(
            subject="Re: Long",
            message_id="<l2@x>",
            in_reply_to="<l1@x>",
            body="Second point",
            date="Mon, 5 Jan 2026 11:00:00 +0000",
        )
    )
    wait(
        lambda: (
            client.post("/api/queries/thread.summary", json={"id": thread["id"]}).json()[
                "new_messages"
            ]
            == 1
        ),
        "new message noticed",
    )
    script.replies = [[TextChunk("Summary two.")]]
    updated = client.post("/api/commands/thread.summarize", json={"id": thread["id"]}).json()
    assert updated["text"] == "Summary two."
    sent = script.requests[-1].messages[0].text
    assert "Second point" in sent and "First point" not in sent and "Summary one." in sent


def test_prompts_join_every_run_and_outside_edits_are_picked_up(
    client: TestClient, script: Script, config: Config
) -> None:
    client.post(
        "/api/commands/prompts.save",
        json={"kind": "personal", "name": "about-me", "content": "I lead procurement."},
    )
    client.post(
        "/api/commands/prompts.save",
        json={"kind": "agent", "name": "session", "content": "Always answer in French."},
    )
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.default = [TextChunk("ok")]
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": "Hi"}
    ) as response:
        list(response.iter_lines())
    call = client.post("/api/queries/modelCall.get", json={"session": session}).json()
    names = [layer["name"] for layer in call["layers"]]
    assert names == [
        "System prompt",
        "Who you are",
        "Agent prompt",
        "About the person",
        "Personalized prompts",
        "Your other tools",
        "This run",
        "Task content",
    ]
    assert (
        "I lead procurement." in call["layers"][4]["real"]
        and "Always answer in French." in call["layers"][2]["real"]
    )

    (config.home / "prompts" / "personal" / "about-me.md").write_text("I lead audit now.")
    other = client.post("/api/commands/session.create", json={}).json()["id"]
    with client.stream("POST", "/api/sessions/chat", json={"id": other, "text": "Hi"}) as response:
        list(response.iter_lines())
    assert "I lead audit now." in script.requests[-1].instructions
    listed = {p["name"]: p for p in client.post("/api/queries/prompts.list").json()["prompts"]}
    assert listed["about-me"]["content"] == "I lead audit now."
    assert listed["mail"]["base"]
    # Each agent shows the whole prompt a run sends, part by part, with names filled in.
    parts = {layer["name"]: layer["text"] for layer in listed["session"]["layers"]}
    assert list(parts)[:3] == ["System prompt", "Who you are", "Agent prompt"]
    assert "their chief of staff" in parts["System prompt"]
    assert "{{" not in parts["System prompt"]
    mail = {layer["name"]: layer["text"] for layer in listed["mail"]["layers"]}
    assert "chief of staff for email" not in mail["Agent prompt"]
    assert listed["scheduled"]["group"] == "schedules" and listed["mail"]["group"] == "agents"


def test_starter_priorities_fill_in_but_never_overwrite(client: TestClient, config: Config) -> None:
    client.post(
        "/api/commands/prompts.save",
        json={"kind": "personal", "name": "importance", "content": "Mine."},
    )
    client.post("/api/commands/prompts.useStarters", json={})
    listed = {
        p["name"]: p["content"] for p in client.post("/api/queries/prompts.list").json()["prompts"]
    }
    assert listed["importance"] == "Mine." and "My mail categories" in listed["categories"]


def test_memory_files_can_be_edited_searched_and_only_relevant_ones_load(
    client: TestClient, script: Script, config: Config
) -> None:
    client.post(
        "/api/commands/memory.save",
        json={"name": "budget", "content": "The budget owner is Priya."},
    )
    client.post(
        "/api/commands/memory.save", json={"name": "gardening", "content": "Roses need pruning."}
    )
    client.post(
        "/api/commands/memory.save",
        json={
            "name": "mine",
            "level": "agent",
            "agent": "mail",
            "content": "Budget reports are routine.",
        },
    )
    files = client.post("/api/queries/memory.list", json={"query": "priya"}).json()["files"]
    assert [f["name"] for f in files] == ["budget"]
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.default = [TextChunk("ok")]
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": "Who owns the budget?"}
    ) as response:
        list(response.iter_lines())
    prompt = script.requests[-1].instructions
    assert "Priya" in prompt and "Roses" not in prompt and "routine" not in prompt
    assert (
        client.post(
            "/api/commands/memory.save",
            json={"path": "../../system/x.md", "name": "x", "content": "y"},
        ).status_code
        == 422
    )
    client.post("/api/commands/memory.remove", json={"path": "user/gardening.md"})
    assert not (config.home / "memory" / "user" / "gardening.md").exists()


def run_tool(
    client: TestClient, script: Script, call: ToolCall, text: str = "Go", session: str | None = None
) -> tuple[str, str]:
    session = session or client.post("/api/commands/session.create", json={}).json()["id"]
    script.replies = [[call], [TextChunk("ok")]]
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": text}
    ) as response:
        list(response.iter_lines())
    return session, script.requests[-1].messages[-1].text


def test_session_can_ask_and_waits_for_the_answer(client: TestClient, script: Script) -> None:
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.replies = [
        [ToolCall("c1", "ask_user", {"question": "Which file?", "options": ["A", "B"]})],
        [TextChunk("Thanks.")],
    ]
    done: list[bool] = []

    def run() -> None:
        with client.stream(
            "POST", "/api/sessions/chat", json={"id": session, "text": "Go"}
        ) as response:
            list(response.iter_lines())
        done.append(True)

    threading.Thread(target=run, daemon=True).start()
    ask = wait(lambda: client.post("/api/queries/channel.list").json()["messages"], "ask")[0]
    assert ask["options"] == ["A", "B"] and ask["session"] == session
    wait(
        lambda: (
            client.post("/api/queries/session.get", json={"id": session}).json()["session"][
                "status"
            ]
            == "waiting"
        ),
        "waiting",
    )
    client.post("/api/commands/channel.respond", json={"id": ask["id"], "answer": "B"})
    wait(lambda: done, "finish")
    assert script.requests[-1].messages[-1].text == "They answered: B"


def test_suggest_and_tell_dont_wait_and_repeats_group(client: TestClient, script: Script) -> None:
    run_tool(client, script, ToolCall("c1", "tell", {"text": "Vendor confirmed Friday."}))
    run_tool(client, script, ToolCall("c2", "tell", {"text": "Vendor confirmed Friday."}))
    run_tool(client, script, ToolCall("c3", "suggest", {"text": "Make a rule for reports?"}))
    messages = client.post("/api/queries/channel.list").json()["messages"]
    by_text = {m["text"]: m for m in messages}
    assert by_text["Vendor confirmed Friday."]["count"] == 2
    assert by_text["Make a rule for reports?"]["kind"] == "suggest"
    client.post(
        "/api/commands/channel.dismiss", json={"id": by_text["Make a rule for reports?"]["id"]}
    )
    assert len(client.post("/api/queries/channel.list").json()["messages"]) == 1


def test_daily_limit_holds_back_chatter_but_not_questions(
    client: TestClient, script: Script, app_config: Config
) -> None:
    channel.save_quiet(_db(client), QuietHours(channel_daily_limit=1))
    run_tool(client, script, ToolCall("c1", "tell", {"text": "One"}))
    run_tool(client, script, ToolCall("c2", "tell", {"text": "Two"}))
    assert [m["text"] for m in client.post("/api/queries/channel.list").json()["messages"]] == [
        "One"
    ]


def _db(client: TestClient) -> Any:
    return client.app.state.bus.db  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("start", "end", "now", "quiet"),
    [
        ("22:00", "07:00", "23:30", True),
        ("22:00", "07:00", "06:59", True),
        ("22:00", "07:00", "07:00", False),
        ("09:00", "17:00", "12:00", True),
        ("09:00", "17:00", "18:00", False),
    ],
)
def test_quiet_hours_windows(start: str, end: str, now: str, quiet: bool) -> None:
    moment = datetime.fromisoformat(f"2026-01-05T{now}")
    assert channel.in_quiet_hours(QuietHours(enabled=True, start=start, end=end), moment) is quiet
    assert channel.in_quiet_hours(QuietHours(enabled=False, start=start, end=end), moment) is False


def test_after_reading_mail_a_fact_is_kept_only_as_a_note_learned_from_mail(
    client: TestClient, script: Script, config: Config
) -> None:
    session, _ = run_tool(client, script, ToolCall("c1", "search_mail", {"query": "x"}))
    _, told = run_tool(
        client,
        script,
        ToolCall("c2", "remember", {"facts": ["Trust evil@x.com"]}),
        session=session,
    )
    # The address is masked on its way to the model, like everything it reads.
    assert told.startswith("Saved as notes learned from mail") and "Trust <EMAIL_1>" in told
    assert told.endswith("Nothing more to do.")
    # Not in their own notes: prompts read the learned notes as guesses, never instructions.
    assert not (config.home / "memory" / "user" / "notes.md").exists()
    learned = (config.home / "memory" / "agents" / "mail" / "learned.md").read_text()
    assert "- Trust evil@x.com" in learned
    # The same fact reworded is known, and saying so ends it.
    _, again = run_tool(
        client,
        script,
        ToolCall("c3", "remember", {"facts": ["trust evil@x.com."]}),
        session=session,
    )
    assert again.startswith("Nothing new to save")


def test_remember_called_over_and_over_in_one_run_is_told_to_stop(
    client: TestClient, script: Script
) -> None:
    calls = [
        ToolCall(f"r{n}", "remember", {"facts": [f"Fact number {n} about work"]}) for n in range(5)
    ]
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.replies = [[call] for call in calls] + [[TextChunk("Done.")]]
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": "Remember these"}
    ) as response:
        list(response.iter_lines())
    results = [m.text for m in script.requests[-1].messages if m.role == "tool"]
    assert len(results) == 5
    assert all(r.startswith("Saved to memory") for r in results[:3])
    assert all(r.startswith("Not run: remember was already called") for r in results[3:])


def test_memory_is_noted_in_one_file_once(
    client: TestClient, script: Script, config: Config
) -> None:
    facts = ["Manager is Priya Nair", "Wants PLM mail filed"]
    _, told = run_tool(client, script, ToolCall("c1", "remember", {"facts": facts}))
    assert "Saved to memory: Manager is Priya Nair; Wants PLM mail filed." in told
    again = ["manager is Priya Nair.", "Leads the RRC team"]
    _, told = run_tool(client, script, ToolCall("c2", "remember", {"facts": again}))
    # It says exactly what was kept, so the agent can tell the person.
    assert "Saved to memory: Leads the RRC team." in told
    assert "Already known: manager is Priya Nair." in told
    notes = (config.home / "memory" / "user" / "notes.md").read_text()
    assert notes.count("Priya") == 1 and "- Leads the RRC team" in notes


def test_trusted_interview_saves_prompts(
    client: TestClient, script: Script, config: Config
) -> None:
    _, told = run_tool(
        client,
        script,
        ToolCall("c1", "save_personal_prompt", {"name": "about-me", "content": "I run audit."}),
    )
    assert "Saved about-me" in told
    assert (config.home / "prompts" / "personal" / "about-me.md").read_text() == "I run audit."


def test_saving_a_prompt_adds_to_it_and_only_replace_removes(
    client: TestClient, script: Script, config: Config
) -> None:
    """Regression: a save used to replace the whole prompt, so new rules wiped the old ones."""
    target = config.home / "prompts" / "personal" / "importance.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# What's important\n- Meera Iyer is my manager.\n- Escalations are urgent.\n"
    )

    def save(arguments: dict[str, str]) -> str:
        return run_tool(client, script, ToolCall("p", "save_personal_prompt", arguments))[1]

    told = save({"name": "importance", "content": "- escalations are URGENT.\n- Payslips are low."})
    assert "Adds 1 line" in told
    text = target.read_text()
    assert "Meera Iyer is my manager" in text and "Escalations are urgent" in text
    assert text.count("scalations") == 1 and text.rstrip().endswith("- Payslips are low.")

    assert "Nothing to save" in save({"name": "importance", "content": "- Payslips are low."})

    told = save({"name": "importance", "content": "- Payslips are low.", "mode": "replace"})
    assert "removing 3 lines" in told and "Meera Iyer is my manager." in told
    assert target.read_text() == "- Payslips are low."


def test_context_is_attached_as_data_can_be_removed_and_marks_untrusted(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    client.post("/api/commands/schedules.setDefaults", json={"live_mail_enabled": False})
    fake.state.deliver(make_mail(subject="Attach me", body="Secret plan details"))
    thread = thread_named(client, "Attach me")
    session = client.post(
        "/api/commands/session.create",
        json={"context": [f"thread:{thread['id']}", "text:Some words"]},
    ).json()["id"]
    items = client.post("/api/queries/session.context", json={"id": session}).json()["items"]
    assert [i["label"] for i in items] == ["Attach me", "Some words"]
    client.post(
        "/api/commands/session.setContext",
        json={"id": session, "context": [f"thread:{thread['id']}"]},
    )
    script.default = [TextChunk("ok")]
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": "Summarize this"}
    ) as response:
        list(response.iter_lines())
    sent = script.requests[-1].messages[0].text
    assert (
        "Secret plan details" in sent
        and "Some words" not in sent
        and sent.startswith("<untrusted>")
    )
    assert (
        client.post("/api/queries/session.get", json={"id": session}).json()["session"]["untrusted"]
        is True
    )
    assert client.post("/api/queries/session.context", json={"id": session}).json()["items"] == []
    user = client.post("/api/queries/session.get", json={"id": session}).json()["messages"][0]
    assert user["parts"][0]["text"] == "Summarize this"


def test_tasks_and_reminders_work_by_hand(client: TestClient) -> None:
    assert (
        client.post(
            "/api/commands/tasks.save", json={"title": "Do it", "due": "2099-01-01"}
        ).status_code
        == 200
    )
    task = client.post("/api/queries/tasks.list", json={}).json()["tasks"][0]
    assert task["source"] == "user" and task["proposed"] is False
    client.post(
        "/api/commands/tasks.save",
        json={**{k: task[k] for k in ("id", "title", "notes", "due", "thread")}, "status": "done"},
    )
    assert client.post("/api/queries/tasks.list", json={}).json()["tasks"] == []
    assert (
        len(client.post("/api/queries/tasks.list", json={"include_done": True}).json()["tasks"])
        == 1
    )
    client.post(
        "/api/commands/reminders.save",
        json={"title": "Call", "when": "2099-01-01T09:00", "repeat": "week"},
    )
    reminder = client.post("/api/queries/reminders.list").json()["reminders"][0]
    # An edit is stored like a new one, so seconds can't make it come due a minute late.
    client.post(
        "/api/commands/reminders.save",
        json={
            "id": reminder["id"],
            "title": "Call",
            "when": "2099-01-01T09:00:00",
            "repeat": "week",
        },
    )
    assert client.post("/api/queries/reminders.list").json()["reminders"][0]["when"] == (
        "2099-01-01T09:00"
    )
    client.post("/api/commands/reminders.snooze", json={"id": reminder["id"], "minutes": 30})
    assert client.post("/api/queries/reminders.list").json()["reminders"][0]["when"] < "2099"
    client.post("/api/commands/reminders.remove", json={"id": reminder["id"]})
    assert client.post("/api/queries/reminders.list").json()["reminders"] == []


def test_reminders_fire_on_time_and_repeat_into_the_future(client: TestClient) -> None:
    past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M")
    client.post("/api/commands/reminders.save", json={"title": "Once", "when": past})
    client.post(
        "/api/commands/reminders.save", json={"title": "Weekly", "when": past, "repeat": "week"}
    )
    notices = wait(
        lambda: (lambda items: items if len(items) == 2 else None)(
            client.post("/api/queries/notifications.list", json={"kind": "reminder"}).json()[
                "items"
            ]
        ),
        "both reminders",
    )
    assert {n["title"] for n in notices} == {"Once", "Weekly"}
    left = client.post("/api/queries/reminders.list").json()["reminders"]
    assert [r["title"] for r in left] == ["Weekly"] and left[0]["when"] > datetime.now().strftime(
        "%Y-%m-%dT%H:%M"
    )


def test_proposed_reminders_dont_fire_until_accepted(client: TestClient) -> None:
    past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
    client.post("/api/commands/reminders.save", json={"title": "Real", "when": "2099-01-01T09:00"})
    reminder = client.post("/api/queries/reminders.list").json()["reminders"][0]
    client.post(
        "/api/commands/reminders.save",
        json={"id": reminder["id"], "title": "Real", "when": past, "proposed": True},
    )
    time.sleep(0.3)
    assert (
        client.post("/api/queries/notifications.list", json={"kind": "reminder"}).json()["items"]
        == []
    )


@pytest.mark.parametrize(
    ("schedule", "after", "expected"),
    [
        (Schedule(title="d", every="day", time="08:00"), "2026-01-05T07:00", "2026-01-05T08:00"),
        (Schedule(title="d", every="day", time="08:00"), "2026-01-05T08:00", "2026-01-06T08:00"),
        (
            Schedule(title="w", every="week", time="08:00", weekday=4),
            "2026-01-05T07:00",
            "2026-01-09T08:00",
        ),
        (
            Schedule(title="w", every="week", time="08:00", weekday=0),
            "2026-01-05T09:00",
            "2026-01-12T08:00",
        ),
        (
            Schedule(title="o", every="once", time="08:00", date="2026-03-01"),
            "2026-01-05T09:00",
            "2026-03-01T08:00",
        ),
    ],
)
def test_next_run_times(schedule: Schedule, after: str, expected: str) -> None:
    assert scheduler.next_run_after(schedule, datetime.fromisoformat(after)) == expected


def test_schedules_run_miss_catch_up_and_keep_history(client: TestClient, script: Script) -> None:
    script.default = [TextChunk("Friday summary.")]
    made = client.post(
        "/api/commands/schedules.save",
        json={"title": "Friday summary", "prompt": "Summarize", "every": "week", "time": "08:00"},
    ).json()
    row = made["schedules"][0]
    assert row["next_run"] and row["last_run"] is None
    # As if the laptop was closed through the due time.
    with _db(client).transaction() as tx:
        tx.execute("UPDATE schedules SET next_run = '2020-01-01T08:00' WHERE id = ?", (row["id"],))
    client.post(
        "/api/commands/reminders.save", json={"title": "Wake it", "when": "2099-01-01T09:00"}
    )
    done = wait(
        lambda: (lambda s: s if s["last_session"] else None)(
            client.post("/api/queries/schedules.list").json()["schedules"][0]
        ),
        "missed run to happen",
    )
    assert done["next_run"] > "2021" and done["last_run"]
    wait(
        lambda: (
            client.post("/api/queries/session.get", json={"id": done["last_session"]}).json()[
                "session"
            ]["status"]
            == "done"
        ),
        "session",
    )
    view = client.post("/api/queries/session.get", json={"id": done["last_session"]}).json()
    assert (
        view["session"]["title"] == "Friday summary"
        and view["session"]["agent"] == f"schedule-{row['id']}"
    )


def test_a_one_time_schedule_runs_once(client: TestClient, script: Script) -> None:
    script.default = [TextChunk("ok")]
    row = client.post(
        "/api/commands/schedules.save",
        json={
            "title": "Once",
            "prompt": "x",
            "every": "once",
            "date": "2020-01-01",
            "time": "08:00",
        },
    ).json()["schedules"][0]
    client.post(
        "/api/commands/reminders.save", json={"title": "Wake it", "when": "2099-01-01T09:00"}
    )
    done = wait(
        lambda: (lambda s: s if s["last_session"] else None)(
            client.post("/api/queries/schedules.list").json()["schedules"][0]
        ),
        "run",
    )
    assert done["id"] == row["id"] and done["next_run"] is None and done["enabled"] is False


def test_a_scheduled_run_stops_at_its_token_limit_and_keeps_its_work(
    client: TestClient, script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "run_limits_on", lambda _ctx: True)
    saved = client.post(
        "/api/commands/schedules.save",
        json={"title": "Small prep", "prompt": "Use a tool", "token_limit": 1},
    ).json()["schedules"]
    schedule = next(row for row in saved if row["title"] == "Small prep")
    script.replies = [
        [Usage(input_tokens=10, output_tokens=5), ToolCall("c1", "read_work_board", {})],
        ["This call must not happen"],
    ]
    client.post("/api/commands/schedules.runNow", json={"id": schedule["id"]})
    row = wait(
        lambda: next(
            (
                s
                for s in client.post("/api/queries/sessions.list", json={}).json()["sessions"]
                if s["title"] == "Small prep" and s["status"] == "stopped"
            ),
            None,
        ),
        "stopped",
    )
    assert "limit of 1 tokens" in row["error"]
    assert len(script.requests) == 1
    assert client.post("/api/queries/usage.get").json()["total_today"] == 15


def test_with_run_limits_off_a_run_goes_past_its_token_limit(
    client: TestClient, script: Script
) -> None:
    """Per-run limits are off by default for now, so a tiny limit stops nothing."""
    saved = client.post(
        "/api/commands/schedules.save",
        json={"title": "Unlimited prep", "prompt": "Use a tool", "token_limit": 1},
    ).json()["schedules"]
    schedule = next(row for row in saved if row["title"] == "Unlimited prep")
    script.replies = [
        [Usage(input_tokens=10, output_tokens=5), ToolCall("c1", "read_work_board", {})],
        ["Done."],
    ]
    client.post("/api/commands/schedules.runNow", json={"id": schedule["id"]})
    row = wait(
        lambda: next(
            (
                s
                for s in client.post("/api/queries/sessions.list", json={}).json()["sessions"]
                if s["title"] == "Unlimited prep" and s["status"] in {"done", "stopped", "failed"}
            ),
            None,
        ),
        "finished",
    )
    assert row["status"] == "done", row
    assert len(script.requests) == 2


def test_daily_prep_shows_on_today(client: TestClient, script: Script, fake: FakeMail) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(importance="high", status="waiting_on_you"),
        triage_reply(status="waiting_on_others"),
    ]
    fake.state.deliver(make_mail(subject="Needs me"))
    triaged(client, "Needs me")
    fake.state.deliver(make_mail(subject="Waiting one"))
    triaged(client, "Waiting one")
    fake.state.deliver(make_mail(subject="Robot", sender="no-reply@x.com"))
    thread_named(client, "Robot")
    today = wait(
        lambda: (lambda v: v if v["automated_count"] == 1 else None)(
            client.post("/api/queries/today.view").json()
        ),
        "today",
    )
    assert [t["subject"] for t in today["needs_you"]] == ["Needs me"]
    assert [t["subject"] for t in today["waiting"]] == ["Waiting one"]
    assert today["brief"] == "1 important email to look at."
    assert today["prep_text"] is None

    script.replies = [
        [ToolCall("b", "update_brief", {"lead": "Your morning: one thing needs you."})],
        [TextChunk("Updated.")],
    ]
    made = client.post(
        "/api/commands/schedules.save",
        json={"title": "Daily prep", "kind": "daily-prep", "every": "day", "time": "06:00"},
    ).json()
    client.post("/api/commands/schedules.runNow", json={"id": made["schedules"][0]["id"]})
    prepared = wait(lambda: client.post("/api/queries/today.view").json()["prep_text"], "prep")
    assert "one thing needs you" in prepared


def test_overdue_deadlines_notify_once_without_a_model(client: TestClient, script: Script) -> None:
    ctx_bus = client.app.state.bus  # type: ignore[attr-defined]
    with ctx_bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO work_board (kind, title, due, by, updated) VALUES ('deadline', 'Audit report', '2020-01-01', 'x', 'x')"
        )
    client.post(
        "/api/commands/reminders.save", json={"title": "Wake it", "when": "2099-01-01T09:00"}
    )
    notices = wait(
        lambda: client.post("/api/queries/notifications.list", json={"kind": "overdue"}).json()[
            "items"
        ],
        "overdue notice",
    )
    assert notices[0]["title"] == "Overdue: Audit report"
    assert script.requests == []
    items = client.post("/api/queries/board.list").json()["items"]
    assert len(items) == 1 and items[0]["title"] == "Audit report"


def test_activity_records_commands_as_not_undoable(client: TestClient, script: Script) -> None:
    client.post("/api/commands/permissions.save", json={"command": "allow"})
    run_tool(client, script, ToolCall("c1", "run_command", {"command": "echo hi"}))
    item = client.post("/api/queries/activity.list").json()["items"][0]
    assert item["summary"].startswith("Ran: echo hi") and item["undoable"] is False
    assert client.post("/api/commands/activity.undo", json={"id": item["id"]}).status_code == 422


def test_draft_tool_saves_and_never_sends(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    client.post("/api/commands/schedules.setDefaults", json={"live_mail_enabled": False})
    fake.state.deliver(make_mail(subject="Answer me"))
    thread = thread_named(client, "Answer me")
    _, told = run_tool(
        client, script, ToolCall("c1", "draft_reply", {"thread_id": thread["id"], "body": "Sure."})
    )
    assert "Nothing was sent" in told
    assert client.post("/api/queries/drafts.list").json()["drafts"][0]["source"] == "agent"
    assert fake.sent == []


def test_a_reply_is_drafted_when_asked_and_nothing_is_saved_or_sent(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(draft=None)]
    fake.state.deliver(make_mail(subject="Numbers please"))
    thread = triaged(client, "Numbers please")
    script.replies = [[ReasoningChunk("Keep it short."), TextChunk("Sending them Friday.\n\nMaya")]]
    answer = client.post("/api/commands/thread.draftReply", json={"id": thread["id"]}).json()
    assert answer == {"body": "Sending them Friday.\n\nMaya", "draft_id": None}
    assert "Numbers please" in script.requests[-1].messages[0].text
    assert client.post("/api/queries/drafts.list").json()["drafts"] == []
    assert fake.sent == []


def test_a_draft_the_agent_already_wrote_is_used_without_another_model_call(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(draft="Happy to.")]
    fake.state.deliver(make_mail(subject="Can you help"))
    thread = triaged(client, "Can you help")
    calls = len(script.requests)
    answer = client.post("/api/commands/thread.draftReply", json={"id": thread["id"]}).json()
    assert answer["body"] == "Happy to." and answer["draft_id"]
    assert len(script.requests) == calls


def test_no_model_call_for_a_draft_to_an_address_nobody_reads(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(draft=None)]
    fake.state.deliver(make_mail(subject="Job alert", sender="alerts-noreply@jobs.example"))
    thread = wait(lambda: thread_named(client, "Job alert"))
    calls = len(script.requests)
    answer = client.post("/api/commands/thread.draftReply", json={"id": thread["id"]})
    assert answer.status_code == 409 and answer.json()["code"] == "draft.no_reply"
    assert len(script.requests) == calls


def test_agent_can_discover_and_read_an_email_attachment(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    client.post("/api/commands/schedules.setDefaults", json={"live_mail_enabled": False})
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Attachment evidence",
            attachments=[("brief.txt", "text/plain", b"The launch date is Friday.")],
        )
    )
    thread = thread_named(client, "Attachment evidence")
    session, output = run_tool(
        client, script, ToolCall("attachment-list", "read_thread", {"thread_ids": [thread["id"]]})
    )
    assert "brief.txt" in output and "read_document key m:" in output
    import re

    key = re.search(r"read_document key (m:\d+:\d+)", output)
    assert key is not None
    _, text = run_tool(
        client,
        script,
        ToolCall("attachment-read", "read_document", {"key": key.group(1)}),
        session=session,
    )
    assert "The launch date is Friday." in text


def test_memory_suggestions_waiting_from_before_are_kept_as_learned_notes(
    client: TestClient, config: Config
) -> None:
    from nexusai.modules.agent import memory

    db = client.app.state.bus.db  # type: ignore[attr-defined]
    memory.propose(db, "Posty", "Ravi leads the RRC team", None)
    assert memory.settle_proposals(db, config.home) == 1
    assert client.post("/api/queries/memory.list", json={}).json()["proposals"] == []
    learned = (config.home / "memory" / "agents" / "mail" / "learned.md").read_text()
    assert "- Ravi leads the RRC team" in learned
    assert memory.settle_proposals(db, config.home) == 0


def test_reading_past_mail_is_one_running_job_not_three(client: TestClient) -> None:
    from nexusai.modules.agent import mail_agent

    db = client.app.state.bus.db  # type: ignore[attr-defined]
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO agent_defaults (key, value) VALUES (?, 'reading')",
            (mail_agent.LEARNING_STATE,),
        )
        tx.execute(
            "INSERT OR REPLACE INTO agent_defaults (key, value) VALUES (?, '10')",
            (mail_agent.LEARNING_TOTAL,),
        )
        tx.execute(
            "INSERT INTO trigger_runs (trigger, event, time, status) VALUES (?, 'learn-group-1', 'now', 'pending')",
            (mail_agent.MAIL_TRIGGER,),
        )
        tx.execute(
            "INSERT OR IGNORE INTO agent_sessions (id, title, agent, status, untrusted, created, updated)"
            " VALUES (?, 'Mail agent', 'mail', 'running', 1, 'now', 'now')",
            (mail_agent.SESSION_ID,),
        )
        tx.execute(
            "UPDATE agent_sessions SET status = 'running' WHERE id = ?", (mail_agent.SESSION_ID,)
        )
    jobs = client.post("/api/queries/jobs.list", json={}).json()["jobs"]
    assert [job["id"] for job in jobs if job["link"].endswith(mail_agent.SESSION_ID)] == [
        "mail-learning"
    ]
    # New mail arriving meanwhile shows as the queue, once.
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO trigger_runs (trigger, event, time, status, thread) VALUES (?, 'm-1', 'now', 'pending', 1)",
            (mail_agent.MAIL_TRIGGER,),
        )
    jobs = client.post("/api/queries/jobs.list", json={}).json()["jobs"]
    assert [job["id"] for job in jobs if job["link"].endswith(mail_agent.SESSION_ID)] == [
        "mail-learning",
        "triage",
    ]
