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
    # A no-reply notice the agent never sees still joins the matter it's about.
    fake.state.deliver(make_mail(subject="Swarm: Divya Menon approved change 88213", sender=SWARM))
    found = wait(
        lambda: (lambda rows: rows if rows and rows[0]["threads"] == 2 else None)(matters(client)),
        "joined",
    )
    assert len(found) == 1
    matter = found[0]
    assert matter["state"] == "waiting_on_you" and matter["next"] == "Get CL 88213 merged"
    detail = query(client, "matters.get", id=matter["id"])
    kinds = [event["kind"] for event in detail["events"]]
    assert kinds[0] == "started" and sorted(kinds[1:]) == ["joined", "task"]
    joined = next(event for event in detail["events"] if event["kind"] == "joined")
    assert joined["why"] == "Both mention 88213" and joined["source"]["kind"] == "mail"


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
    assert brief["next"][0]["what"] == "Send the RCA"


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
