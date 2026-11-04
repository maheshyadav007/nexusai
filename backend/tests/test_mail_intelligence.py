"""What the Mail agent is told, what it does with it, and what the person can see of all of it."""
# ruff: noqa: F811

import json
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import USER, FakeMail, make_mail
from nexusai.kernel.config import Config
from nexusai.modules.agent import mail_agent, memory, scheduler, signals, tools
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import (  # noqa: F401
    Script,
    app_config,
    client,
    connect,
    fake,
    script,
    thread_named,
    triage_reply,
    wait,
)


def post(client: TestClient, name: str, kind: str = "queries", /, **body: Any) -> Any:
    answer = client.post(f"/api/{kind}/{name}", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


def told(request: Any) -> str:
    """All the model was sent: its instructions, and what it was given to read."""
    said = "\n".join(str(getattr(message, "text", "")) for message in request.messages)
    return f"{request.instructions}\n{said}"


def judged(client: TestClient, subject: str) -> dict[str, Any]:
    return wait(
        lambda: next(
            (
                t
                for t in post(client, "threads.list")["threads"]
                if subject in t["subject"] and t["status"] != "none"
            ),
            None,
        ),
        f"{subject} judged",
    )


def row(client: TestClient, thread: int) -> Any:
    return client.app.state.bus.db.fetch_all(  # type: ignore[attr-defined]
        "SELECT * FROM threads WHERE id = ?", (thread,)
    )[0]


def test_it_sees_who_mail_is_to_and_how_the_person_behaves(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Budget", message_id="<a1@x>", cc=USER, to="boss@x.com"))
    judged(client, "Budget")
    sent = told(script.requests[-1])
    assert "only in Cc" in sent
    assert "is new in this account: this is the first email from them" in sent
    assert "Cc: " in sent and "(the person)" in sent


def test_what_the_person_wrote_in_their_profile_reaches_every_agent(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    post(
        client,
        "profile.update",
        "commands",
        name="Sam Doe",
        role="Staff engineer",
        vips="Priya is my manager",
        about="Looking for a new role",
    )
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Hello there", message_id="<b1@x>"))
    judged(client, "Hello there")
    sent = told(script.requests[-1])
    assert "Priya is my manager" in sent and "Looking for a new role" in sent
    assert "Staff engineer" in sent and "Their mail addresses" in sent


def test_judging_one_email_only_offers_what_it_needs(client: TestClient) -> None:
    assert tools.allowed_for("mail", "mail", True) == tools.TRIAGE_TOOLS
    assert "draft_reply" not in tools.TRIAGE_TOOLS
    assert "recommend_mail_change" not in tools.allowed_for("mail", "mail-hourly", False)  # type: ignore[operator]
    assert "recommend_mail_change" in tools.allowed_for("mail", "mail-review", False)  # type: ignore[operator]
    assert "recommend_priority" in tools.allowed_for("mail", "mail-review", False)  # type: ignore[operator]
    assert "recommend_priority" not in tools.allowed_for("mail", "mail-hourly", False)  # type: ignore[operator]


def test_a_correction_is_used_from_then_on_but_an_agents_own_change_isnt(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="First one", message_id="<c1@x>"))
    first = judged(client, "First one")
    post(client, "thread.setCategory", "commands", id=first["id"], category="Legal")
    wait(lambda: post(client, "mailAgent.knowledge")["corrections"], "the correction to be noted")
    fake.state.deliver(make_mail(subject="Second one", message_id="<c2@x>"))
    judged(client, "Second one")
    sent = told(script.requests[-1])
    assert "Observed corrections to specific decisions" in sent
    assert "filed under Legal" in sent
    assert "corrections for this sender" in sent


def test_the_same_correction_three_times_offers_to_make_it_automatic(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    for number in range(3):
        fake.state.deliver(make_mail(subject=f"Habit {number}", message_id=f"<h{number}@x>"))
        thread = judged(client, f"Habit {number}")
        post(client, "thread.setCategory", "commands", id=thread["id"], category="Legal")
    found = wait(lambda: post(client, "suggestions.list")["suggestions"], "the suggestion")
    assert found[0]["category"] == "Legal" and found[0]["senders"] == ["priya@example.com"]


def test_sending_takes_it_off_their_plate_at_once_then_the_agent_says_when_to_chase(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Contract", message_id="<d1@x>"))
    thread = judged(client, "Contract")
    assert thread["status"] == "waiting_on_you"
    assert post(client, "today.view")["needs_you"]
    script.default = triage_reply(status="waiting_on_others", follow_up_on="2020-01-02")
    fake.state.deliver(
        make_mail(
            subject="Re: Contract",
            sender=USER,
            to="priya@example.com",
            message_id="<d2@x>",
            in_reply_to="<d1@x>",
        ),
        box="Sent",
    )
    wait(lambda: row(client, thread["id"])["follow_up_on"] == "2020-01-02", "the follow-up date")
    today = post(client, "today.view")
    assert not today["needs_you"]
    assert [t["id"] for t in today["follow_ups"]] == [thread["id"]]


def test_a_follow_up_tells_them_once_and_an_answer_stops_it(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.default = triage_reply(status="waiting_on_others", follow_up_on="2020-01-02")
    fake.state.deliver(make_mail(subject="Chase me", message_id="<e1@x>"))
    thread = judged(client, "Chase me")
    ctx = client.app.state.bus  # type: ignore[attr-defined]
    with ctx.db.transaction() as tx:
        tx.execute("UPDATE threads SET follow_up_on = '2020-01-02' WHERE id = ?", (thread["id"],))
    check = scheduler.Scheduler(mail_context(client))
    now = scheduler._local_now()
    check._follow_ups(now)
    check._follow_ups(now)
    notices = ctx.db.fetch_all("SELECT payload FROM events WHERE type = 'notification.requested'")
    assert sum("No answer yet" in n["payload"] for n in notices) == 1
    script.default = triage_reply(status="waiting_on_you")
    fake.state.deliver(make_mail(subject="Re: Chase me", message_id="<e2@x>", in_reply_to="<e1@x>"))
    wait(lambda: row(client, thread["id"])["follow_up_on"] is None, "the answer to stop it")
    assert row(client, thread["id"])["status"] == "waiting_on_you"


def mail_context(client: TestClient) -> Any:
    return _triggers().ctx


def test_automated_mail_is_only_read_when_it_could_matter(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Your weekly tips", sender="no-reply@x.com", message_id="<f1@x>")
    )
    thread_named(client, "Your weekly tips")
    fake.state.deliver(
        make_mail(subject="Payment due Friday", sender="no-reply@bank.com", message_id="<f2@x>")
    )
    judged(client, "Payment due")
    assert all("Your weekly tips" not in told(request) for request in script.requests)


def test_a_filed_reply_in_their_own_conversation_is_still_read(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Hiring", sender=USER, to="jobs@x.com", message_id="<g1@x>"), box="Sent"
    )
    wait(lambda: any("Hiring" in told(r) for r in script.requests), "their own mail to be read")
    script.requests.clear()
    fake.state.deliver(
        make_mail(
            subject="Re: Hiring",
            sender="no-reply@x.com",
            message_id="<g2@x>",
            in_reply_to="<g1@x>",
            body="Thanks, we'd like to talk.",
        )
    )
    wait(lambda: any("we'd like to talk" in told(r) for r in script.requests), "a judgement")


def test_interrupting_is_decided_apart_from_importance(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    bus = client.app.state.bus  # type: ignore[attr-defined]

    def notices() -> list[str]:
        rows = bus.db.fetch_all("SELECT payload FROM events WHERE type = 'notification.requested'")
        return [json.loads(item["payload"])["title"] for item in rows]

    script.replies.append(triage_reply(importance="high", notify=False))
    script.replies.append(triage_reply(importance="normal", notify=True, next_action="reply"))
    fake.state.deliver(make_mail(subject="High but quiet", message_id="<n1@x>"))
    judged(client, "High but quiet")
    assert not any("High but quiet" in title for title in notices())
    fake.state.deliver(make_mail(subject="Normal but now", message_id="<n2@x>"))
    judged(client, "Normal but now")
    wait(lambda: "Reply needed: Normal but now" in notices(), "the notice")


def test_it_stops_asking_once_enough_questions_are_open(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.default = triage_reply(question="Who is this?")
    for number in range(mail_agent.MOST_OPEN_ASKS + 2):
        script.default = triage_reply(question=f"Who is number {number}?")
        fake.state.deliver(make_mail(subject=f"Asks {number}", message_id=f"<q{number}@x>"))
        judged(client, f"Asks {number}")
    asks = [m for m in post(client, "channel.list")["messages"] if m["kind"] == "ask"]
    assert len(asks) == mail_agent.MOST_OPEN_ASKS


def test_replying_closes_the_question_about_that_conversation(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.default = triage_reply(question="Who is this?")
    fake.state.deliver(make_mail(subject="Unknown", message_id="<r1@x>"))
    judged(client, "Unknown")
    wait(lambda: post(client, "channel.list")["messages"], "the question")
    script.default = triage_reply(status="resolved")
    fake.state.deliver(
        make_mail(
            subject="Re: Unknown",
            sender=USER,
            to="priya@example.com",
            message_id="<r2@x>",
            in_reply_to="<r1@x>",
        ),
        box="Sent",
    )
    wait(lambda: not post(client, "channel.list")["messages"], "the question to close")


@pytest.fixture
def small_read(app_config: Config, script: Script) -> Any:
    from nexusai.api.app import create_app

    agent = replace(app_config.agent, learn_emails=2)
    with TestClient(
        create_app(replace(app_config, agent=agent)), base_url="http://127.0.0.1:4100"
    ) as test:
        yield test


def test_reading_past_mail_starts_with_conversations_they_wrote_in(
    small_read: TestClient, fake: FakeMail, script: Script
) -> None:
    fake.state.deliver(
        make_mail(
            subject="Old talk",
            sender=USER,
            to="friend@x.com",
            message_id="<t1@x>",
            date="Mon, 01 Jan 2024 10:00:00 +0000",
        ),
        box="Sent",
    )
    for number in range(4):
        fake.state.deliver(
            make_mail(
                subject=f"Recent {number}",
                message_id=f"<t2{number}@x>",
                date=f"Mon, 0{number + 1} Sep 2025 10:00:00 +0000",
            )
        )
    connect(small_read, fake)
    wait(
        lambda: any("Old talk" in told(request) for request in script.requests),
        "their own conversation to be read",
    )


def test_a_note_says_where_it_came_from_and_can_be_confirmed_or_removed(
    client: TestClient, app_config: Config
) -> None:
    home = app_config.home
    memory.add_learned(home, ["Works on Atlas"], 12)
    memory.add_learned(home, ["Works on Atlas", "Likes tea"], 13)
    assert memory.learned(home).splitlines() == [
        "- Works on Atlas [mail:12]",
        "- Likes tea [mail:13]",
    ]
    notes = post(client, "mailAgent.knowledge")["notes"]
    assert notes[0]["text"] == "Works on Atlas" and notes[0]["thread"] == 12
    post(client, "memory.confirmNote", "commands", line=notes[0]["line"])
    post(client, "memory.removeNote", "commands", line=notes[1]["line"])
    assert memory.learned(home).strip() == ""
    from nexusai.modules.agent import knowledge
    from nexusai.modules.agent.module import current

    recalled = next(
        layer.text
        for layer in knowledge.layers_for(current().ctx, "mail", "anything")
        if layer.name == "Scoped facts"
    )
    assert "- Works on Atlas" in recalled and "source mail:12" in recalled
    assert "<untrusted>" not in recalled.split("Works on Atlas")[0]


def test_long_notes_keep_what_bears_on_this_email_rather_than_only_the_newest(
    app_config: Config,
) -> None:
    home = app_config.home
    memory.add_learned(home, ["Interviewing with Recraft for a Staff role"], 1)
    memory.add_learned(home, [f"Filler note number {n} about nothing much" for n in range(300)], 2)
    recalled = memory.relevant(home, "mail", "Recraft interview tomorrow", 2000)
    assert "Interviewing with Recraft" in recalled
    assert recalled.startswith("[learned]\n<untrusted>") and len(recalled) < 2000


def suggest(client: TestClient, **values: Any) -> str:
    from nexusai.modules.agent import suggestions

    return suggestions.add(mail_context(client), **values)


def test_a_recommendation_needs_real_senders_and_shows_the_apps_own_counts(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Statement", sender="a@bank.com", message_id="<u1@x>"))
    judged(client, "Statement")
    made_up = suggest(
        client, category="Finance", senders=["x@nowhere.com"], reason="r", quiet=False
    )
    assert "None of those" in made_up
    suggest(client, category="Finance", senders=["a@bank.com"], reason="Your bank", quiet=False)
    assert suggest(client, category="Finance", senders=["a@bank.com"], reason="r", quiet=False) == (
        "That's been suggested already."
    )
    found = post(client, "suggestions.list")["suggestions"]
    assert [(s["category"], s["emails"]) for s in found] == [("Finance", 1)]


def test_accepting_files_whats_here_and_whats_coming_and_declining_is_remembered(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Statement", sender="a@bank.com", message_id="<v1@x>"))
    thread = judged(client, "Statement")
    suggest(client, category="Finance", senders=["a@bank.com"], reason="Your bank", quiet=False)
    found = post(client, "suggestions.list")["suggestions"][0]
    post(client, "suggestions.decide", "commands", id=found["id"], accept=True)
    assert row(client, thread["id"])["category"] == "Finance"
    fake.state.deliver(make_mail(subject="Next one", sender="a@bank.com", message_id="<v2@x>"))
    assert thread_named(client, "Next one")["category"] == "Finance"
    suggest(client, category="Junk", senders=["a@bank.com"], reason="No", quiet=False)
    other = post(client, "suggestions.list")["suggestions"][0]
    post(client, "suggestions.decide", "commands", id=other["id"], accept=False)
    again = suggest(client, category="Junk", senders=["a@bank.com"], reason="No", quiet=False)
    assert again == "That's been suggested already."


def test_quiet_only_archives_what_was_read_long_ago_and_never_deletes(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.default = triage_reply(status="fyi")
    fake.state.deliver(
        make_mail(
            subject="Old read",
            sender="a@news.com",
            message_id="<w1@x>",
            date="Mon, 01 Jan 2024 10:00:00 +0000",
        ),
        flags={"\\Seen"},
    )
    fake.state.deliver(make_mail(subject="New unread", sender="a@news.com", message_id="<w2@x>"))
    old = thread_named(client, "Old read")
    new = thread_named(client, "New unread")
    suggest(client, category="News", senders=["a@news.com"], reason="Never read", quiet=True)
    found = post(client, "suggestions.list")["suggestions"][0]
    assert found["to_archive"] == 1
    post(client, "suggestions.decide", "commands", id=found["id"], accept=True)
    assert row(client, old["id"])["in_inbox"] == 0
    assert row(client, new["id"])["in_inbox"] == 1


def test_what_it_knows_is_what_a_real_run_is_sent(
    client: TestClient, fake: FakeMail, script: Script, app_config: Config
) -> None:
    post(client, "profile.update", "commands", name="Sam Doe", vips="Priya")
    post(
        client,
        "prompts.save",
        "commands",
        kind="personal",
        name="importance",
        content="Watch Atlas",
    )
    memory.add_learned(app_config.home, ["Works on Atlas"], 1)
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Atlas plan", message_id="<k1@x>"))
    thread = judged(client, "Atlas plan")
    sent = told(script.requests[-1])
    known = post(client, "mailAgent.knowledge")
    names = [layer["name"] for layer in known["layers"]]
    assert names[:4] == [
        "System prompt",
        "Agent prompt",
        "About the person",
        "Personalized prompts",
    ]
    shown = post(client, "mailAgent.preview", thread=thread["id"])
    # The system prompt also says what's on right now, which only a running turn works out.
    for layer in shown["layers"][1:]:
        assert layer["text"] in sent, layer["name"]
    assert "Atlas plan" in shown["given"] and shown["approx_tokens"] > 0


def test_a_review_recommends_and_runs_again_only_when_due(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    for number in range(5):
        fake.state.deliver(
            make_mail(
                subject=f"Deal {number}",
                sender="deals@shop.com",
                message_id=f"<x{number}@x>",
                headers={"List-Unsubscribe": "<mailto:u@shop.com>"},
            )
        )
    wait(lambda: len(post(client, "threads.list")["threads"]) == 5, "the mail", 15)
    script.replies.append(
        [
            ToolCall(
                "call-1",
                "recommend_mail_change",
                {
                    "category": "Shopping",
                    "senders": ["deals@shop.com"],
                    "reason": "You opened 0 of 5",
                    "quiet": True,
                },
            )
        ]
    )
    script.replies.append([TextChunk("Recommended one group.")])
    triggers = _triggers()
    triggers.review_now("test-review")
    triggers.wake.set()
    found = wait(lambda: post(client, "suggestions.list")["suggestions"], "the recommendation")
    assert found[0]["category"] == "Shopping" and found[0]["emails"] == 5


def _triggers() -> Any:
    from nexusai.modules.agent import module

    return module._triggers


def test_the_brief_can_explain_a_quiet_day_without_history_learning(
    client: TestClient, script: Script
) -> None:
    rows = client.app.state.bus.db.fetch_all(  # type: ignore[attr-defined]
        "SELECT id FROM schedules WHERE kind = 'mail-brief'"
    )
    script.default = [TextChunk("There are no open obligations yet. Mail may still be syncing.")]
    triggers = _triggers()
    triggers.fire_schedule("brief-now", rows[0]["id"])
    wait(
        lambda: client.app.state.bus.db.fetch_all(
            "SELECT 1 FROM trigger_runs WHERE event='brief-now' AND status='done'"
        ),
        "quiet-day brief",
    )  # type: ignore[attr-defined]
    assert len(script.requests) == 1
    assert post(client, "today.view")["prep_text"].startswith("There are no open obligations")


def test_the_built_ins_can_be_turned_off(client: TestClient) -> None:
    current = post(client, "mailAgent.get")
    assert current["morning_brief"] and current["inbox_review"]
    post(client, "mailAgent.save", "commands", mode="both", morning_brief=False)
    current = post(client, "mailAgent.get")
    assert not current["morning_brief"] and current["inbox_review"]


def test_near_duplicate_category_names_become_one_and_it_cant_make_endless_ones(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.replies.append(triage_reply(category="Atlas launch"))
    script.replies.append(triage_reply(category="atlas"))
    fake.state.deliver(make_mail(subject="Name one", message_id="<y1@x>"))
    assert judged(client, "Name one")["category"] == "Atlas launch"
    fake.state.deliver(make_mail(subject="Name two", message_id="<y2@x>"))
    assert judged(client, "Name two")["category"] == "Atlas launch"
    with client.app.state.bus.db.transaction() as tx:  # type: ignore[attr-defined]
        for number in range(mail_agent.MOST_AGENT_CATEGORIES):
            tx.execute(
                "INSERT INTO mail_categories (name, source, created) VALUES (?, 'agent', 'now')",
                (f"Made {number}",),
            )
    script.replies.append(triage_reply(category="Brand new"))
    fake.state.deliver(make_mail(subject="Name three", message_id="<y3@x>"))
    assert judged(client, "Name three")["category"] is None


def crowd(count: int) -> str:
    domains = ["big.example"] * (count - 2) + ["other.example"] * 2
    return ", ".join(f"person{n}@{domain}" for n, domain in enumerate(domains))


def test_a_broadcast_is_a_count_and_not_a_list_and_the_list_can_still_be_searched(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="All hands", to=f"{crowd(5000)}, {USER}", message_id="<z1@x>")
    )
    thread = judged(client, "All hands")
    sent = told(script.requests[-1])
    assert "broadcast to 5,001 people" in sent and "The person is in To." in sent
    assert "person42@" not in sent and "big.example" not in sent
    # The whole request stays small, whatever size the list is.
    assert len(sent) < 40_000
    assert "read_recipients" in {tool.name for tool in script.requests[-1].tools}

    ctx = mail_context(client)
    summary = signals.read_recipients(ctx, thread["id"])
    assert summary.startswith("5,001 recipients.")
    assert "big.example 4,998" in summary
    assert len(summary.splitlines()) < signals.MOST_RECIPIENTS_READ + 4
    assert "read on from offset 50" in summary
    found = signals.read_recipients(ctx, thread["id"], "other.example")
    assert "2 match" in found and "person4998@other.example (To)" in found
    assert "person100@" in signals.read_recipients(ctx, thread["id"], offset=100)


def test_a_small_group_is_still_named(client: TestClient, fake: FakeMail, script: Script) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Few people", to=f"{crowd(4)}, {USER}", message_id="<z2@x>")
    )
    judged(client, "Few people")
    assert "broadcast" not in told(script.requests[-1]).split("Few people")[1].split("Counted")[0]


def test_their_own_mass_mail_doesnt_make_everyone_a_contact(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="To all", sender=USER, to=crowd(50), message_id="<z3@x>"), box="Sent"
    )
    fake.state.deliver(
        make_mail(subject="To one", sender=USER, to="friend@x.example", message_id="<z4@x>"),
        box="Sent",
    )
    wait(lambda: signals.contacts(mail_context(client)), "the count")
    assert [c.address for c in signals.contacts(mail_context(client))] == ["friend@x.example"]


def test_the_same_mail_isnt_offered_twice_under_another_name(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Deal", sender="a@shop.com", message_id="<aa1@x>"))
    judged(client, "Deal")
    suggest(client, category="Shopping", senders=["a@shop.com"], reason="r", quiet=False)
    again = suggest(
        client, category="Shopping & Food", senders=["a@shop.com"], reason="r", quiet=False
    )
    assert again == "That's been suggested already."
    assert len(post(client, "suggestions.list")["suggestions"]) == 1


def test_the_agent_can_refile_a_header_guess_in_their_conversation_but_not_their_own_rule(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Interview",
            sender="no-reply@ats.example",
            message_id="<ab1@x>",
            headers={"List-Unsubscribe": "<mailto:u@ats.example>"},
        )
    )
    first = thread_named(client, "Interview")
    assert first["category"] == "Promotions"
    script.default = triage_reply(category="Job search", status="waiting_on_others")
    fake.state.deliver(
        make_mail(
            subject="Re: Interview",
            sender=USER,
            to="no-reply@ats.example",
            message_id="<ab2@x>",
            in_reply_to="<ab1@x>",
        ),
        box="Sent",
    )
    wait(lambda: row(client, first["id"])["status"] == "waiting_on_others", "their reply")
    fake.state.deliver(
        make_mail(
            subject="Re: Interview",
            sender="no-reply@ats.example",
            message_id="<ab3@x>",
            in_reply_to="<ab2@x>",
        )
    )
    wait(lambda: row(client, first["id"])["category"] == "Job search", "the agent to refile it")


def test_read_more_reads_only_conversations_they_wrote_in(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    with client.app.state.bus.db.transaction() as tx:  # type: ignore[attr-defined]
        tx.execute("UPDATE agent_triggers SET enabled = 0 WHERE id = ?", (mail_agent.MAIL_TRIGGER,))
    fake.state.deliver(make_mail(subject="Not theirs", message_id="<ac1@x>"))
    fake.state.deliver(
        make_mail(subject="Theirs", sender=USER, to="b@x.example", message_id="<ac2@x>"), box="Sent"
    )
    thread_named(client, "Not theirs")
    wait(lambda: mail_agent.conversations_not_read(mail_context(client)), "their conversation")
    assert mail_agent.queue_learning(mail_context(client), 5) == 1
