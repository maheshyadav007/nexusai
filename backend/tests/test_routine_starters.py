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
