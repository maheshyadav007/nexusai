"""One thing going on is one conversation, and its work goes with it (docs/MATTERS_PLAN.md, phase 1)."""
# ruff: noqa: F811

import json
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from test_agent_work import (  # noqa: F401  (fixtures)
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

SENDER = "Cloud Billing <billing@cloud.example>"


def tasks(client: TestClient, include_done: bool = False) -> list[dict[str, Any]]:
    return client.post("/api/queries/tasks.list", json={"include_done": include_done}).json()[
        "tasks"
    ]


def reminders(client: TestClient) -> list[dict[str, Any]]:
    return client.post("/api/queries/reminders.list", json={}).json()["reminders"]


def status(client: TestClient, thread: int, value: str) -> None:
    response = client.post("/api/commands/thread.setStatus", json={"id": thread, "status": value})
    assert response.status_code == 200, response.text


def test_a_reminder_email_joins_the_open_conversation_and_moves_its_task(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(tasks=[{"title": "Verify the billing account", "due": "2099-01-10"}]),
        triage_reply(
            tasks=[{"title": "Complete the account verification now", "due": "2099-01-05"}]
        ),
    ]
    fake.state.deliver(make_mail(subject="Verify your billing account", sender=SENDER))
    first = triaged(client, "Verify your billing account")
    wait(lambda: tasks(client), "first task")
    fake.state.deliver(make_mail(subject="Reminder: Verify your billing account", sender=SENDER))
    wait(lambda: len(script.requests) == 2, "second judgement")
    joined = wait(
        lambda: (lambda t: t if t["message_count"] == 2 else None)(
            thread_named(client, "billing account")
        ),
        "joined",
    )
    assert joined["id"] == first["id"]
    # Its open task is in front of the AI: in its matter, or listed for the conversation.
    shown = script.requests[-1].messages[-1].text
    assert "Already open for this conversation" in shown or "open: [task:" in shown
    found = wait(
        lambda: (lambda rows: rows if rows[0]["due"] == "2099-01-05" else None)(tasks(client)),
        "moved",
    )
    assert [(t["title"], t["thread"]) for t in found] == [
        ("Verify the billing account", first["id"])
    ]


def test_a_resend_of_a_finished_conversation_starts_a_new_one(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Submit the monthly timesheet", sender=SENDER))
    first = triaged(client, "monthly timesheet")
    status(client, first["id"], "resolved")
    fake.state.deliver(make_mail(subject="Submit the monthly timesheet", sender=SENDER))
    wait(
        lambda: (
            len(
                [
                    t
                    for t in client.post("/api/queries/threads.list", json={}).json()["threads"]
                    if "monthly timesheet" in t["subject"]
                ]
            )
            == 2
        ),
        "second conversation",
    )


def test_a_deadline_becomes_the_task_date_and_markers_leave_titles(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            tasks=[{"title": "Review the sign-in [mail:12] attempt", "due": None}],
            deadlines=[{"what": "Sign-in review due", "due": "2099-02-01"}],
        )
    ]
    fake.state.deliver(make_mail(subject="Please verify your device"))
    triaged(client, "verify your device")
    task = wait(lambda: tasks(client), "task")[0]
    assert (task["title"], task["due"]) == ("Review the sign-in attempt", "2099-02-01")
    assert client.post("/api/queries/board.list").json()["items"] == []


def test_done_closes_the_conversations_work_and_undo_brings_it_back(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            tasks=[{"title": "Send the budget", "due": "2099-01-10"}],
            reminders=[{"title": "Budget call", "when": "2099-01-09T09:00"}],
        )
    ]
    fake.state.deliver(make_mail(subject="Budget numbers"))
    thread = triaged(client, "Budget numbers")
    wait(lambda: tasks(client) and reminders(client), "work")
    status(client, thread["id"], "resolved")
    wait(lambda: not tasks(client) and not reminders(client), "closed")
    status(client, thread["id"], "waiting_on_you")
    wait(lambda: tasks(client) and reminders(client), "back")
    assert tasks(client)[0]["status"] == "todo"


def test_ticking_the_last_task_finishes_the_conversation(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            tasks=[{"title": "Send the deck", "due": None}],
            reminders=[{"title": "Deck call", "when": "2099-01-09T09:00"}],
        )
    ]
    fake.state.deliver(make_mail(subject="The deck"))
    triaged(client, "The deck")
    task = wait(lambda: tasks(client), "task")[0]
    save = {k: task[k] for k in ("id", "title", "notes", "due", "thread")}
    client.post("/api/commands/tasks.save", json={**save, "status": "done", "proposed": False})
    wait(lambda: thread_named(client, "The deck")["status"] == "resolved", "finished")
    wait(lambda: not reminders(client), "reminder closed")
    client.post("/api/commands/tasks.save", json={**save, "status": "todo", "proposed": False})
    wait(lambda: thread_named(client, "The deck")["status"] == "waiting_on_you", "open again")
    wait(lambda: reminders(client), "reminder back")


def test_mail_filed_where_the_ai_doesnt_read_leaves_its_work_and_comes_back_with_it(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            reason="Budget due.", tasks=[{"title": "Send the budget", "due": "2099-01-10"}]
        )
    ]
    fake.state.deliver(make_mail(subject="Budget numbers"))
    thread = triaged(client, "Budget numbers")
    wait(lambda: tasks(client), "work")

    def listed(folder: str) -> set[int]:
        found = client.post("/api/queries/threads.list", json={"folder": folder}).json()
        return {row["id"] for row in found["threads"]}

    def matters() -> list[Any]:
        return client.post("/api/queries/matters.list", json={}).json()["matters"]

    assert thread["id"] in listed("priority") and matters()
    moved = client.post(
        "/api/commands/thread.setCategory", json={"id": thread["id"], "category": "Automated"}
    )
    assert moved.status_code == 200, moved.text
    # Kept from the AI now: its task closes, and it leaves Priority and the matters.
    wait(lambda: not tasks(client), "closed")
    assert thread["id"] not in listed("priority") and thread["id"] in listed("kept")
    assert not matters()
    client.post("/api/commands/thread.setCategory", json={"id": thread["id"], "category": None})
    wait(lambda: tasks(client), "back")
    assert thread["id"] in listed("priority") and matters()


def test_hide_from_ai_takes_the_sender_away_whole_and_undo_brings_it_all_back(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(reason="Bill due.", tasks=[{"title": "Pay the bill", "due": "2099-01-10"}])
    ]
    fake.state.deliver(make_mail(subject="Your bill is ready", sender=SENDER))
    thread = triaged(client, "Your bill is ready")
    wait(lambda: tasks(client), "work")

    def ask(kind: str, name: str, body: dict[str, Any]) -> Any:
        response = client.post(f"/api/{kind}/{name}", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def listed(folder: str) -> set[int]:
        return {row["id"] for row in ask("queries", "threads.list", {"folder": folder})["threads"]}

    seen = ask("queries", "mail.hide.preview", {"thread": thread["id"]})
    assert seen["sender"] == "billing@cloud.example" and seen["sender_emails"] == 1
    assert seen["folder"] == "Cloud Billing"
    hidden = ask("commands", "mail.hide", {"thread": thread["id"], "scope": "sender"})
    assert hidden["folder"] == "Cloud Billing" and hidden["emails"] == 1
    wait(lambda: not tasks(client), "its work closed")
    assert thread["id"] in listed("kept") and thread["id"] not in listed("priority")
    folders = {c["name"]: c for c in ask("queries", "categories.list", {})["categories"]}
    assert folders["Cloud Billing"]["ai_reads"] is False
    # What comes next from the sender follows, and the AI isn't asked about it.
    asked = len(script.requests)
    fake.state.deliver(make_mail(subject="Your next bill", sender=SENDER))
    later = wait(lambda: thread_named(client, "Your next bill"), "the next bill")
    assert later["category"] == "Cloud Billing" and len(script.requests) == asked

    ask("commands", "mail.hide.undo", {"undo": hidden["undo"]})
    wait(lambda: tasks(client), "its work back")
    assert thread["id"] in listed("priority")
    folders = {c["name"] for c in ask("queries", "categories.list", {})["categories"]}
    rules = ask("queries", "rules.get", {})["rules"]
    assert not any(r["actions"].get("category") == "Cloud Billing" for r in rules)
    # The bill that came while it was hidden comes back too, and the folder hiding made goes.
    assert thread_named(client, "Your next bill")["category"] is None
    assert "Cloud Billing" not in folders


def test_hide_from_ai_one_conversation_leaves_the_sender_alone(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(reason="A question.")]
    fake.state.deliver(make_mail(subject="Quick question"))
    thread = triaged(client, "Quick question")
    hidden = client.post(
        "/api/commands/mail.hide", json={"thread": thread["id"], "scope": "conversation"}
    ).json()
    assert hidden["folder"] == "Automated"
    rules = client.post("/api/queries/rules.get", json={}).json()["rules"]
    assert not any(r["actions"].get("skip_agent") for r in rules if "priya" in json.dumps(r))
    client.post("/api/commands/mail.hide.undo", json={"undo": hidden["undo"]})
    back = thread_named(client, "Quick question")
    assert back["category"] == thread["category"]
