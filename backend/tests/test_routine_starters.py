# ruff: noqa: F811
"""Routines that start on mail like this, checked with no model (To do 1)."""

from typing import Any

from fastapi.testclient import TestClient

from nexusai.modules.agent import triggers
from test_agent_work import (
    app_config,  # noqa: F401
    client,  # noqa: F401
    fake,  # noqa: F401
    script,  # noqa: F401
    wait,
)

INVOICE = {
    "from_addr": "billing@kite.example",
    "from_name": "Kite Accounts",
    "subject": "Invoice INV-2231 for November",
    "clean_text": "Please pay by Friday.",
}


class Db:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def fetch_all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [self.row] if self.row else []


def rule(**values: str) -> dict[str, str]:
    return {"match_from": "", "match_subject": "", "match_words": "", **values}


def test_mail_is_matched_by_sender_subject_and_words_without_a_model() -> None:
    db, event = Db(INVOICE), {"message_id": 7, "thread_id": 3}
    assert triggers.mail_matches(db, rule(), event)
    assert triggers.mail_matches(db, rule(match_from="kite.example"), event)
    assert triggers.mail_matches(db, rule(match_from="someone@else.example, kite"), event)
    assert not triggers.mail_matches(db, rule(match_from="acme.example"), event)
    # Every subject word must be there; any of the words may be.
    assert triggers.mail_matches(db, rule(match_subject="invoice november"), event)
    assert not triggers.mail_matches(db, rule(match_subject="invoice december"), event)
    assert triggers.mail_matches(db, rule(match_words="receipt, pay"), event)
    assert not triggers.mail_matches(db, rule(match_words="refund"), event)
    assert triggers.mail_matches(
        db, rule(match_from="kite", match_subject="invoice", match_words="pay"), event
    )
    # An event with no mail never matches a rule that names some.
    assert not triggers.mail_matches(db, rule(match_from="kite"), {})
    assert not triggers.mail_matches(Db(None), rule(match_from="kite"), event)


def test_a_trigger_keeps_which_mail_it_is_for(client: TestClient) -> None:
    saved = client.post(
        "/api/commands/triggers.save",
        json={
            "title": "Invoices",
            "event": "mail.received",
            "prompt": "File it and add a task to pay it.",
            "match_from": "kite.example",
            "match_subject": "invoice",
        },
    )
    assert saved.status_code == 200, saved.text
    mine = next(t for t in saved.json()["triggers"] if t["title"] == "Invoices")
    assert (mine["match_from"], mine["match_subject"], mine["match_words"]) == (
        "kite.example",
        "invoice",
        "",
    )


def test_a_check_tells_the_person_once_when_it_goes_down_and_once_when_it_is_back(
    client: TestClient, monkeypatch: Any
) -> None:
    from datetime import UTC, datetime, timedelta

    from nexusai.modules.agent import checks
    from nexusai.modules.agent import module as agent

    answers = iter(
        [
            (False, "Answered 503"),
            (False, "Answered 503"),
            (False, "Answered 503"),
            (True, "Answered 200"),
        ]
    )
    monkeypatch.setattr(checks, "look", lambda url, expect: next(answers))
    saved = client.post(
        "/api/commands/checks.save",
        json={
            "title": "Status page",
            "url": "https://status.example.com/health",
            "every_minutes": 15,
        },
    ).json()["checks"]
    check = saved[0]["id"]
    ctx = agent.current().ctx
    start = datetime(2031, 6, 2, 10, 0, tzinfo=UTC)

    def read() -> list[str]:
        found = client.post("/api/queries/notifications.list", json={"kind": "check"}).json()
        return sorted(n["title"] for n in found["items"])

    def notices(expected: int = 0) -> list[str]:
        # Saved by a listener after the event, so wait for as many as expected.
        if expected:
            found: list[str] = wait(lambda: read() if len(read()) == expected else None, "notices")
            return found
        return read()

    # One failure isn't down yet: a single slow answer doesn't raise an alarm.
    assert checks.run_due(ctx, start) == 1
    assert (
        notices() == []
        and client.post("/api/queries/checks.list").json()["checks"][0]["state"] == "unknown"
    )
    # Due again only after its interval; checking early does nothing.
    assert checks.run_due(ctx, start + timedelta(minutes=5)) == 0
    checks.run_due(ctx, start + timedelta(minutes=15))
    assert notices(1) == ["Down: Status page"]
    # Still down: not told again.
    checks.run_due(ctx, start + timedelta(minutes=30))
    assert notices() == ["Down: Status page"]
    checks.run_due(ctx, start + timedelta(minutes=45))
    assert notices(2) == ["Back up: Status page", "Down: Status page"]
    row = client.post("/api/queries/checks.list").json()["checks"][0]
    assert row["state"] == "ok" and row["last_result"] == "Answered 200" and row["failures"] == 0
    assert row["next_check"].startswith("2031-06-02T11:00")
    # Only web addresses.
    bad = client.post("/api/commands/checks.save", json={"title": "x", "url": "file:///etc/passwd"})
    assert bad.status_code == 422 and "web address" in bad.text
    client.post("/api/commands/checks.remove", json={"id": check})
    assert client.post("/api/queries/checks.list").json()["checks"] == []


def test_a_routines_runs_are_listed_and_a_failed_one_can_be_tried_again(client: TestClient) -> None:
    from nexusai.modules.agent import module as agent

    saved = client.post(
        "/api/commands/triggers.save",
        json={"title": "Watch", "event": "mail.received", "prompt": "Note it."},
    ).json()
    trigger = next(t for t in saved["triggers"] if t["title"] == "Watch")["id"]
    db = agent.current().db
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO trigger_runs (trigger, event, time, status, error) VALUES (?, 'e1', ?, 'failed', 'The model was busy')",
            (trigger, "2031-06-02T10:00:00+00:00"),
        )
        tx.execute(
            "INSERT INTO trigger_runs (trigger, event, time, status) VALUES (?, 'e2', ?, 'done')",
            (trigger, "2031-06-02T11:00:00+00:00"),
        )
    runs = client.post("/api/queries/routines.runs", json={"trigger": trigger}).json()["runs"]
    assert [r["status"] for r in runs] == ["done", "failed"] and runs[1][
        "error"
    ] == "The model was busy"
    done = client.post("/api/commands/routines.runAgain", json={"run": runs[0]["id"]})
    assert done.status_code == 409
    again = client.post("/api/commands/routines.runAgain", json={"run": runs[1]["id"]})
    assert again.status_code == 200
    status = db.fetch_all("SELECT status, error FROM trigger_runs WHERE id = ?", (runs[1]["id"],))[
        0
    ]
    # Back in the queue with the same email, or already picked up again.
    assert (
        status["status"] in {"pending", "running", "done", "failed"}
        and status["error"] != "The model was busy"
    )


def test_a_routine_on_mail_that_mentions_me_uses_my_names_without_a_model() -> None:
    from nexusai.modules.mail import mentions

    me = mentions.found("Mahesh Yadav", ["mahesh.y@corp.example"])
    event = {"message_id": 7}
    plm = {
        "from_addr": "plm@corp.example",
        "from_name": "PLM",
        "subject": "PLM-4411 assigned",
        "clean_text": "Issue PLM-4411 is now assigned to Mahesh Yadav. Please triage by Friday.",
    }
    other = {**plm, "clean_text": "Issue PLM-4412 is now assigned to Rahul Kumar."}
    told = {**other, "subject": "Rahul mentioned you in PLM-4413"}
    about_me = rule(match_from="plm@", match_words="")
    about_me_row = {**about_me, "match_me": 1}
    assert triggers.mail_matches(Db(plm), about_me_row, event, me)
    assert not triggers.mail_matches(Db(other), about_me_row, event, me)
    # A tool passing on that someone mentioned them counts too.
    assert triggers.mail_matches(Db(told), about_me_row, event, me)
    # With no names set yet, nothing is about them.
    assert not triggers.mail_matches(Db(plm), about_me_row, event, None)
    # The other conditions still apply alongside it.
    assert not triggers.mail_matches(Db(plm), {**about_me_row, "match_from": "jira@"}, event, me)


def test_a_trigger_keeps_that_it_is_for_mail_that_mentions_me(client: TestClient) -> None:
    saved = client.post(
        "/api/commands/triggers.save",
        json={
            "title": "PLM on me",
            "event": "mail.received",
            "prompt": "Add a task.",
            "match_me": True,
        },
    ).json()
    mine = next(t for t in saved["triggers"] if t["title"] == "PLM on me")
    assert mine["match_me"] is True
