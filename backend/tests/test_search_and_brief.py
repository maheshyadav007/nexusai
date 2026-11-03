"""Search has to find what the person means, and the morning brief has to learn from them."""
# ruff: noqa: F811

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.contracts.mail import SearchMail
from nexusai.kernel.config import Config
from nexusai.modules.agent.module import current
from nexusai.modules.agent.providers import TextChunk, ToolCall
from nexusai.modules.mail import store
from test_agent_sessions import start_turn
from test_agent_work import (  # noqa: F401
    Script,
    app_config,
    client,
    connect,
    fake,
    run_tool,
    script,
    wait,
)
from test_chat_engine import status


def post(client: TestClient, name: str, kind: str = "queries", /, **body: Any) -> Any:
    return client.post(f"/api/{kind}/{name}", json=body)


def search(client: TestClient, query: str, **fields: Any) -> dict[str, Any]:
    return post(client, "search.run", query=query, **fields).json()


def subjects(found: dict[str, Any]) -> list[str]:
    return [hit["thread"]["subject"] for hit in found["hits"]]


@pytest.fixture
def mailbox(client: TestClient, fake: FakeMail) -> TestClient:  # noqa: F811
    connect(client, fake)
    post(client, "schedules.setDefaults", "commands", live_mail_enabled=False)
    for subject, sender, body in (
        ("Your Amazon interview process", "recruiter@amazon.com", "Next round on Friday."),
        ("Weekly digest", "news@letters.com", "Amazon shares and an interview with a founder."),
        ("Passport renewal", "office@gov.in", "Please bring your old passport."),
        ("Lunch", "friend@mail.com", "Who asked me to bring the coding test?"),
        ("Suki confirmation", "hr@suki.ai", "Your slot is confirmed."),
        ("Withdrawal receipt", "bank@hdfc.com", "Your withdrawal went through."),
    ):
        fake.state.deliver(make_mail(subject=subject, sender=sender, body=body))
    wait(lambda: len(subjects(search(client, "lunch"))) == 1, "mail")
    wait(lambda: len(subjects(search(client, "withdrawal"))) == 1, "mail")
    return client


def test_operators_become_filters() -> None:
    parsed = store.with_operators(
        SearchMail(
            query="from:priya budget to:sam has:attachment after:2025 before:2026-03 in:sent"
        )
    )
    assert parsed.query == "budget"
    assert parsed.sender == "priya" and parsed.recipient == "sam"
    assert parsed.has_attachment is True and parsed.folder == "sent"
    assert parsed.date_from == "2025-01-01" and parsed.date_to == "2026-03-01"


def test_an_operator_that_means_nothing_stays_as_words() -> None:
    parsed = store.with_operators(SearchMail(query="ratio in:bananas before:soon"))
    assert parsed.query == "ratio in:bananas before:soon" and parsed.folder is None


def test_common_words_dont_decide_a_question() -> None:
    assert store.plain_words("who asked me to do a coding test") == ["coding", "test"]
    assert store.plain_words("who are you") == ["who", "are", "you"]


def test_typing_from_in_the_search_box_filters_by_sender(mailbox: TestClient) -> None:
    assert subjects(search(mailbox, "from:recruiter@amazon.com")) == [
        "Your Amazon interview process"
    ]


def test_a_subject_match_beats_a_mention_in_a_newsletter(mailbox: TestClient) -> None:
    assert subjects(search(mailbox, "amazon interview"))[0] == "Your Amazon interview process"


def test_a_conversation_with_only_some_words_is_still_found(mailbox: TestClient) -> None:
    found = subjects(search(mailbox, "suki withdrawal"))
    assert set(found) == {"Suki confirmation", "Withdrawal receipt"}


def test_every_word_beats_some_words_even_in_your_own_conversation(
    mailbox: TestClient,
    fake: FakeMail,
) -> None:
    fake.state.deliver(make_mail(subject="Amazon parcel", sender="ship@amazon.com", body="Sent."))
    wait(lambda: "Amazon parcel" in subjects(search(mailbox, "parcel")), "mail")
    found = subjects(search(mailbox, "amazon interview"))
    assert found.index("Your Amazon interview process") < found.index("Amazon parcel")


def test_a_mistyped_word_is_corrected_and_says_so(mailbox: TestClient) -> None:
    # A word has to be in two emails to count as a real one, so a typo in one can't win.
    found = search(mailbox, "intervew")
    assert found["corrected"] == "interview"
    assert "Your Amazon interview process" in subjects(found)


def test_quotes_find_an_exact_phrase(mailbox: TestClient) -> None:
    assert subjects(search(mailbox, '"old passport"')) == ["Passport renewal"]
    assert subjects(search(mailbox, '"passport old"')) == []


def test_agent_search_shows_dates_and_takes_filters(
    mailbox: TestClient,
    script: Script,  # noqa: F811
) -> None:
    _, told = run_tool(
        mailbox, script, ToolCall("c1", "search_mail", {"query": "", "sender": "hr@suki.ai"})
    )
    assert "Suki confirmation" in told and "Withdrawal receipt" not in told
    assert re.search(r"\] \d{4}-\d{2}-\d{2} \|", told)


def test_agent_told_when_words_find_nothing(
    mailbox: TestClient,
    script: Script,  # noqa: F811
) -> None:
    _, told = run_tool(mailbox, script, ToolCall("c1", "search_mail", {"query": "zzqqxx"}))
    assert "semantic_search" in told


def test_a_prompt_only_changes_from_a_session_that_read_mail_once_the_person_agrees(
    mailbox: TestClient,
    script: Script,  # noqa: F811
    config: Config,  # noqa: F811
) -> None:
    session, _ = run_tool(mailbox, script, ToolCall("c1", "search_mail", {"query": "lunch"}))
    target = config.home / "prompts" / "personal" / "about-me.md"
    for choice, saved in (("deny", False), ("once", True)):
        script.replies = [
            [
                ToolCall(
                    f"c-{choice}", "save_personal_prompt", {"name": "about-me", "content": "Hi"}
                )
            ],
            [TextChunk("ok")],
        ]
        start_turn(mailbox, session, "Save it")
        pending = wait(lambda: post(mailbox, "approvals.list").json()["approvals"], "ask")[0]
        # What's agreed to is the words themselves, and never for the rest of the session.
        assert pending["detail"] == "Hi" and pending["can_remember"] is False
        assert not target.exists()
        post(mailbox, "approvals.decide", "commands", id=pending["id"], choice=choice)
        wait(lambda: status(mailbox, session) == "done", "finished")
        assert target.exists() is saved


def test_documents_rank_a_name_above_a_mention(
    client: TestClient,  # noqa: F811
    config: Config,  # noqa: F811
) -> None:
    for name, body in (("notes.txt", b"My resume is attached to this."), ("resume.txt", b"Work.")):
        client.post(f"/api/documents/upload?name={name}", content=body)
    wait(
        lambda: len(post(client, "documents.list", query="resume").json()["documents"]) == 2,
        "both read",
    )
    rows = post(client, "documents.list", query="resume").json()["documents"]
    assert [row["name"] for row in rows] == ["resume.txt", "notes.txt"]


def test_a_brief_reaction_reaches_the_next_brief_and_the_person_can_see_it(
    client: TestClient,  # noqa: F811
    script: Script,  # noqa: F811
    config: Config,  # noqa: F811
) -> None:
    script.replies = [[TextChunk("Reply to Priya first.")]]
    session_id = str(current().create("Morning brief", [], "daily-prep").id)
    start_turn(client, session_id, "Brief me")
    wait(lambda: post(client, "today.view").json()["prep_text"], "brief")
    wait(lambda: status(client, session_id) == "done", "brief finished")
    today = post(client, "today.view").json()
    assert today["prep_session"] == session_id and today["prep_rating"] is None

    said = post(
        client,
        "brief.react",
        "commands",
        session=session_id,
        rating="down",
        comment="Lead with recruiters.",
    )
    assert said.status_code == 200
    today = post(client, "today.view").json()
    assert today["prep_rating"] == "down" and today["prep_comment"] == "Lead with recruiters."

    knows = post(client, "mailAgent.knowledge").json()
    assert knows["brief_reactions"][0]["comment"] == "Lead with recruiters."

    # The next run is told their words, as theirs.
    script.replies = [[TextChunk("Recruiters first.")]]
    start_turn(client, session_id, "Brief me again")
    wait(
        lambda: "Recruiters" in str(post(client, "today.view").json()["prep_text"]), "second brief"
    )
    told = script.requests[-1].instructions
    assert "Lead with recruiters." in told and "liked 0 and disliked 1" in told


def test_a_bad_session_cant_be_rated(client: TestClient) -> None:  # noqa: F811
    assert post(client, "brief.react", "commands", session="nope", rating="up").status_code == 404


def test_the_registry_lists_what_runs_and_when(client: TestClient) -> None:  # noqa: F811
    agents = post(client, "agents.registry").json()["agents"]
    by_name = {agent["name"]: agent for agent in agents}
    assert {"Mail agent", "Morning brief", "Inbox review", "Know you better"} <= set(by_name)
    brief = by_name["Morning brief"]
    assert brief["when"] == "Every day at 08:30" and brief["next_run"]
    assert by_name["Inbox review"]["when"].startswith("Mondays")
    post(client, "mailAgent.save", "commands", mode="both", morning_brief=False)
    off = {a["name"]: a for a in post(client, "agents.registry").json()["agents"]}["Morning brief"]
    assert off["state"] == "off" and off["next_run"] is None
