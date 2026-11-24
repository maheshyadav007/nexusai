"""A matter owns its work: children follow their parent, the rest of the matter is asked about,
and the AI picks a matter from the few code shows it (the matter object model)."""
# ruff: noqa: F811

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.modules.agent.matters import adopt_all
from test_agent_work import (  # noqa: F401  (fixtures)
    Script,
    app_config,
    client,
    connect,
    fake,
    script,
    triage_reply,
    triaged,
    wait,
)
from test_matters import KARTHIK, command, matters, query

HR = "HR Desk <hr-desk@corp.example>"


def open_tasks(client: TestClient) -> list[dict[str, Any]]:
    return query(client, "tasks.list", include_done=False)["tasks"]


def open_reminders(client: TestClient) -> list[dict[str, Any]]:
    return [r for r in query(client, "reminders.list")["reminders"] if not r["fired"]]


def save_task(client: TestClient, task: dict[str, Any], **changes: Any) -> None:
    fields = {key: task[key] for key in ("id", "title", "notes", "status", "due", "thread")}
    command(client, "tasks.save", **{**fields, "proposed": False, **changes})


def one_matter_two_tasks(client: TestClient, script: Script, fake: FakeMail) -> dict[str, Any]:
    connect(client, fake)
    script.replies = [
        triage_reply(tasks=[{"title": "Get CL 88213 merged", "due": "2099-01-08"}]),
        triage_reply(tasks=[{"title": "Sign the 88213 cost sheet", "due": "2099-01-09"}]),
    ]
    fake.state.deliver(make_mail(subject="CL 88213 is the last blocker", sender=KARTHIK))
    triaged(client, "last blocker")
    fake.state.deliver(
        make_mail(subject="Cost sheet for change 88213", sender="Ravi <ravi@corp.example>")
    )
    triaged(client, "Cost sheet")
    return wait(
        lambda: (lambda rows: rows[0] if rows and len(rows[0]["work"]) == 2 else None)(
            matters(client)
        ),
        "two tasks in one matter",
    )


def test_work_belongs_to_its_matter_and_points_to_the_email_that_asked(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter = one_matter_two_tasks(client, script, fake)
    db = client.app.state.bus.db  # type: ignore[attr-defined]
    rows = db.fetch_all("SELECT matter, source_message FROM tasks ORDER BY id")
    assert {r["matter"] for r in rows} == {matter["id"]}
    assert all(r["source_message"] for r in rows)


def test_a_reminder_goes_with_its_task(client: TestClient, script: Script, fake: FakeMail) -> None:
    one_matter_two_tasks(client, script, fake)
    task = next(t for t in open_tasks(client) if t["title"] == "Get CL 88213 merged")
    command(
        client, "reminders.save", title="Chase the merge", when="2099-01-07T09:00", task=task["id"]
    )
    # Its date moves with the task's, by as many days.
    save_task(client, task, due="2099-01-10")
    assert open_reminders(client)[0]["when"].startswith("2099-01-09T09:00")
    task = next(t for t in open_tasks(client) if t["id"] == task["id"])
    save_task(client, task, status="done")
    assert open_reminders(client) == []
    save_task(client, task, status="todo")
    assert [r["title"] for r in open_reminders(client)] == ["Chase the merge"]


def test_finishing_one_asks_about_the_rest_and_remembers_what_was_kept(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    one_matter_two_tasks(client, script, fake)
    first, second = sorted(open_tasks(client), key=lambda t: t["id"])
    trigger = f"task:{first['id']}"
    asked = query(client, "matters.related", ref=trigger)
    offered = {item["ref"]: item for item in asked["items"]}
    # Another email asked for the cost sheet, so it isn't ticked to start with.
    assert offered[f"task:{second['id']}"]["suggested"] is False
    assert f"task:{first['id']}" not in offered
    # Keeping it open is remembered: it isn't offered again for the same thing.
    command(client, "matters.closeItems", trigger=trigger, keep=[f"task:{second['id']}"])
    assert f"task:{second['id']}" not in {
        i["ref"] for i in query(client, "matters.related", ref=trigger)["items"]
    }
    # Closing what's offered, from another task's question, closes it; undo opens it again.
    other = f"task:{second['id']}"
    back = query(client, "matters.related", ref=other)
    assert f"task:{first['id']}" in {i["ref"] for i in back["items"]}
    assert (
        command(client, "matters.closeItems", trigger=other, close=[f"task:{first['id']}"])[
            "closed"
        ]
        == 1
    )
    assert [t["id"] for t in open_tasks(client)] == [second["id"]]
    command(client, "matters.reopenItems", refs=[f"task:{first['id']}"])
    assert len(open_tasks(client)) == 2
    # Nothing outside the matter can be closed this way.
    assert command(client, "matters.closeItems", trigger=other, close=["task:999"])["closed"] == 0


def test_two_matters_merge_with_their_work_and_the_merge_can_be_undone(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(tasks=[{"title": "Book the venue"}]),
        triage_reply(tasks=[{"title": "Send the invite list"}]),
    ]
    fake.state.deliver(make_mail(subject="Offsite venue options", sender=KARTHIK))
    triaged(client, "venue options")
    fake.state.deliver(make_mail(subject="Who should come in March", sender=HR))
    triaged(client, "come in March")
    first, second = wait(lambda: (lambda r: r if len(r) == 2 else None)(matters(client)), "two")
    command(client, "matters.merge", id=second["id"], into=first["id"])
    merged = matters(client)
    assert len(merged) == 1 and merged[0]["threads"] == 2 and len(merged[0]["work"]) == 2
    detail = query(client, "matters.get", id=first["id"])
    assert "merged" in [e["kind"] for e in detail["events"]]
    command(client, "matters.unmerge", id=second["id"])
    assert sorted(m["threads"] for m in matters(client)) == [1, 1]


def test_the_timeline_reads_oldest_first_and_loads_earlier_pages(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Review the T311 CR draft"))
    triaged(client, "T311")
    matter = wait(lambda: matters(client), "matter")[0]
    db = client.app.state.bus.db  # type: ignore[attr-defined]
    with db.transaction() as tx:
        for day in range(1, 61):
            tx.execute(
                "INSERT INTO matter_events (matter, time, kind, by, text) VALUES (?, ?, 'task', 'engine', ?)",
                (
                    matter["id"],
                    f"2026-01-01T00:{day:02d}:00+00:00"
                    if day < 60
                    else "2026-01-02T00:00:00+00:00",
                    f"Change {day}",
                ),
            )
    first = query(client, "matters.get", id=matter["id"])
    times = [e["time"] for e in first["events"]]
    assert times == sorted(times) and first["earlier"] is True
    page = query(client, "matters.events", id=matter["id"], before=first["events"][0]["id"])
    assert page["events"][-1]["time"] <= first["events"][0]["time"]
    seen = {e["id"] for e in first["events"]}
    while page["earlier"]:
        seen |= {e["id"] for e in page["events"]}
        page = query(client, "matters.events", id=matter["id"], before=page["events"][0]["id"])
    seen |= {e["id"] for e in page["events"]}
    # Every action, and the one email, which the timeline reads from the mail itself.
    actions = db.fetch_all(
        "SELECT COUNT(*) AS n FROM matter_events WHERE matter = ? AND kind NOT IN"
        " ('started', 'joined', 'mail', 'sent')",
        (matter["id"],),
    )[0]["n"]
    assert len(seen) == actions + 1


def test_the_ai_is_shown_related_matters_and_updates_the_task_instead_of_adding_one(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Submit Q4 timesheet", "due": "2099-01-30"}])]
    fake.state.deliver(make_mail(subject="Submit your Q4 timesheet", sender=HR))
    triaged(client, "Submit your Q4")
    matter = wait(lambda: matters(client), "matter")[0]
    task = open_tasks(client)[0]
    script.replies = [
        triage_reply(
            matter=matter["id"],
            reason="A reminder for the same timesheet.",
            tasks=[
                {
                    "title": "Submit the timesheet",
                    "due": "2099-01-28",
                    "updates": f"task:{task['id']}",
                }
            ],
        )
    ]
    fake.state.deliver(make_mail(subject="Reminder: Q4 timesheets close soon", sender=HR))
    triaged(client, "timesheets close soon")
    shown = script.requests[-1].messages[-1]
    assert "Matters this email may belong to" in str(shown) and f"task:{task['id']}" in str(shown)
    rows = wait(
        lambda: (lambda r: r if r and r[0]["threads"] == 2 else None)(matters(client)), "joined"
    )
    assert len(rows) == 1
    assert [(t["title"], t["due"]) for t in open_tasks(client)] == [
        ("Submit Q4 timesheet", "2099-01-28")
    ]


def test_the_ai_cannot_pick_a_matter_it_was_not_shown(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(), triage_reply(matter=1)]
    fake.state.deliver(make_mail(subject="Venue for the offsite", sender=KARTHIK))
    triaged(client, "Venue for")
    fake.state.deliver(make_mail(subject="Payroll cut-off moved", sender=HR))
    triaged(client, "Payroll cut-off")
    rows = wait(lambda: (lambda r: r if len(r) == 2 else None)(matters(client)), "apart")
    assert sorted(m["threads"] for m in rows) == [1, 1]


def test_an_old_deadline_beside_a_to_do_folds_into_it(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Verify the billing account"}])]
    fake.state.deliver(make_mail(subject="Your verification is past due", sender=HR))
    thread = triaged(client, "verification is past due")
    wait(lambda: matters(client), "matter")
    db = client.app.state.bus.db  # type: ignore[attr-defined]
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO work_board (kind, title, thread, due, by, updated) VALUES"
            " ('deadline', 'Complete the verification', ?, '2099-02-01', 'Mail agent', '')",
            (thread["id"],),
        )
    # What runs when the app starts.
    adopt_all(SimpleNamespace(bus=client.app.state.bus))  # type: ignore[arg-type,attr-defined]
    work = matters(client)[0]["work"]
    assert [(w["kind"], w["when"]) for w in work] == [("task", "2099-02-01")]


def test_the_ai_sees_a_big_matter_cut_short_with_a_count_and_its_work_once(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Send the RCA"}])]
    fake.state.deliver(make_mail(subject="[ESCALATION] INC-7781 call drops", sender=KARTHIK))
    thread = triaged(client, "INC-7781")
    wait(lambda: matters(client), "matter")
    for n in range(8):
        command(client, "tasks.save", title=f"Follow-up {n} on INC-7781", thread=thread["id"])
    given = query(client, "mailAgent.preview", thread=thread["id"])["given"]
    # Five open items and a count of the rest, never all of them.
    assert given.count("[task:") == 5 and "and 4 more" in given
    # Listed in the matter, so not again for the conversation.
    assert "Already open for this conversation" not in given
    assert "conversations:" in given and "lately:" in given


def test_the_morning_brief_waits_until_the_mail_is_judged_then_runs(
    client: TestClient, script: Script, fake: FakeMail, monkeypatch: Any
) -> None:
    from nexusai.modules.agent import module as agent
    from nexusai.modules.agent.providers import ToolCall

    connect(client, fake)
    db = client.app.state.bus.db  # type: ignore[attr-defined]
    triggers = agent._triggers
    assert triggers is not None and triggers._mail_settled()
    brief = db.fetch_all("SELECT id FROM schedules WHERE kind = 'mail-brief'")[0]["id"]
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO trigger_runs (trigger, event, time, status, schedule)"
            " VALUES ('schedule', 'morning', '2026-01-01', 'pending', ?)",
            (brief,),
        )
    script.replies = [[ToolCall("b", "update_brief", {"lead": "Your morning: all judged."})]]
    status = "SELECT status FROM trigger_runs WHERE event = 'morning'"
    # Mail still being judged: the brief stays pending, however often the loop looks.
    monkeypatch.setattr(triggers, "_mail_settled", lambda: False)
    for _ in range(3):
        with triggers.lock:
            triggers._start_schedules()
    assert db.fetch_all(status)[0]["status"] == "pending"
    # Judged: the next look starts it.
    monkeypatch.setattr(triggers, "_mail_settled", lambda: True)
    with triggers.lock:
        triggers._start_schedules()
    wait(lambda: db.fetch_all(status)[0]["status"] != "pending", "the brief started")
