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
