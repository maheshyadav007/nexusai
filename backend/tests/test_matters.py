"""Matters: one record for each real thing going on (docs/MATTERS_PLAN.md, phase 2)."""
# ruff: noqa: F811

from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.modules.agent.matters import ids_in
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

KARTHIK = "Karthik Nair <karthik.nair@corp.example>"
SWARM = "Swarm <swarm-noreply@corp.example>"


def query(client: TestClient, name: str, **body: Any) -> Any:
    response = client.post(f"/api/queries/{name}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def command(client: TestClient, name: str, **body: Any) -> Any:
    response = client.post(f"/api/commands/{name}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def matters(client: TestClient) -> list[dict[str, Any]]:
    return query(client, "matters.list")["matters"]


def test_ids_are_found_in_any_spelling_and_years_are_not_ids() -> None:
    assert {"eco1104", "1104"} <= ids_in("Re: [ECO-1104] release")
    assert "88213" in ids_in("Swarm: Divya Menon approved change 88213")
    assert ids_in("Plan for 2026 and Q4") == set()
    assert ids_in("Your GitHub account, maheshyadav007, will soon require 2FA") == set()


def test_one_change_from_different_senders_is_one_matter(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(reason="Karthik needs 88213 merged before the freeze.",
                     tasks=[{"title": "Get CL 88213 merged", "due": "2099-01-08"}]),
        triage_reply(reason="Divya approved the change."),
    ]  # fmt: skip
    fake.state.deliver(make_mail(subject="CL 88213 is the last blocker for MR-Nov", sender=KARTHIK))
    triaged(client, "88213 is the last blocker")
    # A no-reply notice is kept from the AI, so it never joins a matter, which the AI works from.
    fake.state.deliver(make_mail(subject="Swarm: approved change 88213", sender=SWARM))
    # A person writing about the same change does.
    fake.state.deliver(
        make_mail(subject="Divya Menon approved change 88213", sender="Divya <divya@corp.example>")
    )
    triaged(client, "Divya Menon approved")
    found = wait(
        lambda: (lambda rows: rows if rows and rows[0]["threads"] == 2 else None)(matters(client)),
        "joined",
    )
    assert len(found) == 1
    matter = found[0]
    # The task is only suggested, so it's the work listed, not yet their next step.
    assert matter["state"] == "waiting_on_you" and matter["next"] != "Get CL 88213 merged"
    assert [(w["title"], w["proposed"]) for w in matter["work"]] == [("Get CL 88213 merged", True)]
    detail = query(client, "matters.get", id=matter["id"])
    assert not any(t["subject"].startswith("Swarm") for t in detail["threads"])
    kinds = [event["kind"] for event in detail["events"]]
    assert kinds[0] == "started" and sorted(kinds[1:]) == ["joined", "suggested"]
    joined = next(event for event in detail["events"] if event["kind"] == "joined")
    assert joined["why"] == "Both mention 88213" and joined["source"]["kind"] == "mail"


def test_the_timeline_tells_it_in_date_order_when_the_older_half_joins_later(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(reason="Karthik needs 88213 merged.", tasks=[{"title": "Merge CL 88213"}]),
        triage_reply(reason="Divya asked for 88213 last week."),
    ]  # fmt: skip
    # The newer conversation is read first and starts the matter.
    fake.state.deliver(
        make_mail(subject="CL 88213 is the last blocker", sender=KARTHIK,
                  date="Mon, 16 Nov 2026 10:00:00 +0000")
    )  # fmt: skip
    triaged(client, "88213 is the last blocker")
    # The older one, about the same change, comes in after and joins it.
    fake.state.deliver(
        make_mail(subject="Please review change 88213", sender="Divya <divya@corp.example>",
                  date="Mon, 9 Nov 2026 10:00:00 +0000")
    )  # fmt: skip
    triaged(client, "Please review change 88213")
    matter = wait(
        lambda: (lambda rows: rows[0] if rows and rows[0]["threads"] == 2 else None)(
            matters(client)
        ),
        "joined",
    )
    detail = query(client, "matters.get", id=matter["id"])
    mail = [e for e in detail["events"] if e["kind"] in {"started", "joined", "mail", "sent"}]
    # Started is the earliest email; the later conversation is linked, with the real reason.
    assert [e["kind"] for e in mail] == ["started", "joined"]
    assert mail[0]["text"].startswith("Please review change 88213")
    assert mail[1]["why"] == "Both mention 88213"
    times = [e["time"] for e in detail["events"]]
    assert times == sorted(times)
    assert detail["matter"]["started"].startswith("2026-11-09")


def test_mail_that_needs_nothing_makes_no_matter(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(status="fyi", importance="low", reason="A newsletter.")]
    fake.state.deliver(make_mail(subject="Cafeteria menu for this week"))
    triaged(client, "Cafeteria menu")
    assert matters(client) == []


def test_the_brief_lists_what_changed_and_what_is_coming(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            reason="RCA needed by tomorrow.", tasks=[{"title": "Send the RCA", "due": "2000-01-01"}]
        )
    ]
    fake.state.deliver(
        make_mail(subject="[ESCALATION] Field call drops on carrier X", sender=KARTHIK)
    )
    triaged(client, "Field call drops")
    brief = wait(
        lambda: (lambda b: b if b["needs_you"] else None)(query(client, "matters.brief")), "brief"
    )
    assert brief["needs_you"][0]["title"] == "Field call drops on carrier X"
    assert [c["kind"] for c in brief["changes"]][-1] == "started"
    # A suggested task isn't coming up until it's kept; it waits in For your decision.
    assert brief["next"] == []


def test_done_closes_every_conversation_and_undo_brings_it_back(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Enrol in the MFA app", "due": "2099-01-09"}])]
    fake.state.deliver(make_mail(subject="Mandatory: enrol in the new MFA app by Friday"))
    triaged(client, "MFA app")
    matter = wait(lambda: matters(client), "matter")[0]
    assert command(client, "matters.done", id=matter["id"])["closed"] == 1
    assert matters(client) == []
    assert query(client, "tasks.list", include_done=False)["tasks"] == []
    command(client, "matters.reopen", id=matter["id"])
    back = matters(client)
    assert [m["id"] for m in back] == [matter["id"]] and back[0]["work"][0][
        "title"
    ] == "Enrol in the MFA app"


def test_a_wrong_join_is_undone_in_one_step(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Ticket 44871 laptop", sender=KARTHIK))
    triaged(client, "laptop")
    fake.state.deliver(
        make_mail(subject="Order 44871 shipped", sender="Wei Zhang <wei.zhang@corp.example>")
    )
    second = triaged(client, "shipped")
    wait(lambda: matters(client) and matters(client)[0]["threads"] == 2, "joined")
    command(client, "matters.unlink", thread=second["id"])
    rows = matters(client)
    assert sorted(m["threads"] for m in rows) == [1, 1]


def test_the_week_has_a_lane_per_matter_with_its_emails(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Review the T311 CR draft"))
    triaged(client, "T311")
    week = wait(
        lambda: (lambda w: w if w["lanes"] else None)(query(client, "matters.week")), "week"
    )
    lane = week["lanes"][0]
    assert lane["matter"]["title"] == "Review the T311 CR draft"
    assert [mark["kind"] for mark in lane["marks"]] == ["in"]
    # The Week tab scrolls: a range that starts weeks back and runs weeks on has the same mark.
    start = (date.today() - timedelta(days=21)).isoformat()
    longer = query(client, "matters.week", start=start, days=42)
    assert longer["start"] == start and [m["kind"] for m in longer["lanes"][0]["marks"]] == ["in"]


def test_every_step_on_a_task_shows_on_the_week_in_order(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Send the RCA", "due": "2099-01-08"}])]
    fake.state.deliver(make_mail(subject="RCA for the field call drops", sender=KARTHIK))
    triaged(client, "field call drops")
    wait(lambda: matters(client), "matter")
    task = query(client, "tasks.list", include_done=True)["tasks"][0]
    save = {"id": task["id"], "title": task["title"], "thread": task["thread"]}
    command(client, "tasks.save", **save, proposed=False)
    command(client, "tasks.save", **save, status="done")
    command(client, "tasks.save", **save, status="todo")
    command(client, "tasks.save", **save, status="done")

    def steps() -> list[str] | None:
        marks = query(client, "matters.week")["lanes"][0]["marks"]
        said = [m["label"] for m in marks if "Send the RCA" in m["label"]]
        return said if len(said) == 5 else None

    assert wait(steps, "steps") == [
        'Suggested: To-do: "Send the RCA"',
        'Accepted: To-do: "Send the RCA"',
        'Task done: "Send the RCA"',
        'Task opened again: "Send the RCA"',
        'Task done: "Send the RCA"',
    ]


def test_a_task_the_person_keeps_makes_a_matter_of_mail_that_needed_nothing(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(status="fyi", importance="low", reason="An update.")]
    fake.state.deliver(make_mail(subject="Lab move next month"))
    thread = triaged(client, "Lab move")
    assert matters(client) == []
    command(client, "tasks.save", title="Book a slot in the new lab", thread=thread["id"])
    found = wait(lambda: matters(client), "matter")
    assert [m["title"] for m in found] == ["Lab move next month"]


def test_mail_read_late_goes_on_the_timeline_on_its_own_day_not_today(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [triage_reply(tasks=[{"title": "Send the RCA", "due": None}])]
    fake.state.deliver(
        make_mail(
            subject="[ESCALATION] Old drops",
            sender=KARTHIK,
            date="Mon, 01 Jun 2026 09:00:00 +0000",
        )
    )
    triaged(client, "Old drops")
    matter = wait(lambda: matters(client), "matter")[0]
    story = query(client, "matters.get", id=matter["id"])["events"]
    suggested = [e for e in story if e["kind"] == "suggested"]
    assert suggested and suggested[0]["time"].startswith("2026-06-01")
    assert not query(client, "matters.brief")["changes"]


def tasks(client: TestClient) -> list[dict[str, Any]]:
    return query(client, "tasks.list")["tasks"]


def test_a_later_email_drops_a_suggestion_it_shows_done_and_marks_a_kept_task(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(tasks=[{"title": "Send the RCA", "due": None}]),
        triage_reply(tasks=[{"title": "Book the lab", "due": None}]),
    ]
    fake.state.deliver(make_mail(subject="RCA please", sender=KARTHIK, message_id="<r1@x>"))
    triaged(client, "RCA please")
    fake.state.deliver(make_mail(subject="Lab booking", sender=KARTHIK, message_id="<l1@x>"))
    triaged(client, "Lab booking")
    found = wait(lambda: (lambda t: t if len(t) == 2 else None)(tasks(client)), "both suggested")
    rca = next(t for t in found if t["title"] == "Send the RCA")
    lab = next(t for t in found if t["title"] == "Book the lab")
    command(
        client,
        "tasks.save",
        **{
            **{k: rca[k] for k in ("id", "title", "notes", "status", "due", "thread")},
            "proposed": False,
        },
    )
    script.replies = [
        triage_reply(
            status="resolved",
            reason="Karthik confirms the RCA arrived.",
            finished=[f"task:{rca['id']}"],
        ),
        triage_reply(
            status="resolved", reason="The lab is booked.", finished=[f"task:{lab['id']}"]
        ),
    ]
    fake.state.deliver(
        make_mail(
            subject="Re: RCA please",
            sender=KARTHIK,
            in_reply_to="<r1@x>",
            references="<r1@x>",
            body="Got the RCA, thanks.",
        )
    )
    fake.state.deliver(
        make_mail(
            subject="Re: Lab booking",
            sender=KARTHIK,
            in_reply_to="<l1@x>",
            references="<l1@x>",
            body="Booked it myself.",
        )
    )
    kept = wait(
        lambda: next((t for t in tasks(client) if t["id"] == rca["id"] and t["looks_done"]), None),
        "marked",
    )
    assert kept["status"] != "done" and "RCA arrived" in kept["looks_done"]
    wait(lambda: all(t["id"] != lab["id"] for t in tasks(client)) or None, "suggestion dropped")


def test_only_a_kept_task_puts_a_matter_on_waiting_on_you(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = [
        triage_reply(
            status="fyi",
            importance="high",
            tasks=[{"title": "Book the venue", "due": "2000-01-01"}],
        )
    ]
    fake.state.deliver(make_mail(subject="Offsite plans", sender=KARTHIK))
    triaged(client, "Offsite plans")
    brief = wait(
        lambda: (lambda b: b if b["suggested"] else None)(query(client, "matters.brief")),
        "suggested",
    )
    # A suggestion alone doesn't make it theirs: not waiting on them, no next step, no date.
    assert brief["needs_you"] == [] and brief["next"] == []
    shown = brief["suggested"][0]
    assert shown["next"] is None and shown["due"] is None
    task = tasks(client)[0]
    command(
        client,
        "tasks.save",
        **{k: task[k] for k in ("id", "title", "notes", "status", "due", "thread")},
        proposed=False,
    )
    brief = wait(
        lambda: (lambda b: b if b["needs_you"] else None)(query(client, "matters.brief")),
        "kept",
    )
    assert brief["needs_you"][0]["next"] == "Book the venue" and brief["suggested"] == []


def test_what_got_done_since_yesterday_is_listed_by_the_app(client: TestClient) -> None:
    command(client, "tasks.save", title="Share the test plan")
    task = tasks(client)[0]
    command(
        client,
        "tasks.save",
        **{k: task[k] for k in ("id", "title", "notes", "due", "thread")},
        status="done",
    )
    command(client, "tasks.save", title="Still to do")
    done = query(client, "today.view")["prep_done"]
    assert [item["title"] for item in done] == ["Share the test plan"]
