"""What the Mail agent is told, what it does with it, and what the person can see of all of it."""
# ruff: noqa: F811

import json
import time
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import USER, FakeMail, make_mail
from nexusai.contracts.mail import MailMe
from nexusai.kernel.config import Config
from nexusai.modules.agent import (
    bulk_learning,
    mail_agent,
    memory,
    providers,
    scheduler,
    signals,
    tools,
)
from nexusai.modules.agent.providers import TextChunk, ToolCall
from nexusai.modules.mail import mentions
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


def test_the_same_correction_three_times_becomes_a_preference_at_once(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    for number in range(3):
        fake.state.deliver(make_mail(subject=f"Habit {number}", message_id=f"<h{number}@x>"))
        thread = judged(client, f"Habit {number}")
        post(client, "thread.setCategory", "commands", id=thread["id"], category="Legal")
    found = wait(lambda: post(client, "preferences.list")["preferences"], "the preference")
    assert found[0]["status"] == "active" and found[0]["sender"] == "priya@example.com"
    assert "category = Legal" in found[0]["instruction"]
    # Filing the sender's mail is the person's to set up; nothing is offered for it.
    assert post(client, "suggestions.list")["suggestions"] == []


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


def test_automated_mail_is_never_read_whatever_its_subject_says(
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
    # Filed where the AI doesn't read, so even a consequential subject isn't shown to it.
    assert thread_named(client, "Payment due")["category"] == "Automated"
    fake.state.deliver(make_mail(subject="Lunch on Friday?", message_id="<f3@x>"))
    judged(client, "Lunch on Friday")
    assert all(
        "Your weekly tips" not in told(request) and "Payment due" not in told(request)
        for request in script.requests
    )


def test_a_header_match_without_a_consequential_subject_uses_no_model(
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
    thread_named(client, "Hiring")
    time.sleep(0.2)
    assert not any("we'd like to talk" in told(r) for r in script.requests)


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
        "- Works on Atlas [mail:13]",
        "- Likes tea [mail:13]",
    ]
    notes = post(client, "mailAgent.knowledge")["notes"]
    assert notes[0]["text"] == "Works on Atlas" and notes[0]["thread"] == 12
    post(client, "memory.confirmNote", "commands", line=notes[0]["line"])
    for note in notes[1:]:
        post(client, "memory.removeNote", "commands", line=note["line"])
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
    assert names[:5] == [
        "System prompt",
        "Who you are",
        "Agent prompt",
        "About the person",
        "Personalized prompts",
    ]
    shown = post(client, "mailAgent.preview", thread=thread["id"])
    # The system prompt also says what's on right now, which only a running turn works out.
    for layer in shown["layers"][1:]:
        assert layer["text"] in sent, layer["name"]
    assert "Atlas plan" in shown["given"] and shown["approx_tokens"] > 0


def _triggers() -> Any:
    from nexusai.modules.agent import module

    return module._triggers


def test_the_brief_can_explain_a_quiet_day_without_history_learning(
    client: TestClient, script: Script
) -> None:
    rows = client.app.state.bus.db.fetch_all(  # type: ignore[attr-defined]
        "SELECT id FROM schedules WHERE kind = 'mail-brief'"
    )
    script.replies = [
        [
            ToolCall(
                "b",
                "update_brief",
                {"text": "There are no open obligations yet. Mail may still be syncing."},
            )
        ],
        [TextChunk("Updated.")],
    ]
    triggers = _triggers()
    triggers.fire_schedule("brief-now", rows[0]["id"])
    wait(
        lambda: client.app.state.bus.db.fetch_all(
            "SELECT 1 FROM trigger_runs WHERE event='brief-now' AND status='done'"
        ),
        "quiet-day brief",
    )  # type: ignore[attr-defined]
    assert len(script.requests) == 2
    assert post(client, "today.view")["prep_text"].startswith("There are no open obligations")


def test_the_brief_can_be_turned_off_and_there_is_no_inbox_review(client: TestClient) -> None:
    current = post(client, "mailAgent.get")
    assert current["morning_brief"] and "inbox_review" not in current
    post(client, "mailAgent.save", "commands", mode="both", morning_brief=False)
    assert not post(client, "mailAgent.get")["morning_brief"]
    # Posty doesn't suggest folders or filing, so the weekly run that did is gone.
    kinds = {
        row["kind"]
        for row in client.app.state.bus.db.fetch_all("SELECT kind FROM schedules")  # type: ignore[attr-defined]
    }
    assert "mail-review" not in kinds


def test_the_model_can_only_use_existing_smart_folders(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.replies.append(triage_reply(category="Atlas launch"))
    fake.state.deliver(make_mail(subject="Name one", message_id="<y1@x>"))
    assert judged(client, "Name one")["category"] is None
    assert not any(
        folder["name"] == "Atlas launch" for folder in post(client, "categories.list")["categories"]
    )
    post(
        client,
        "categories.save",
        "commands",
        name="Atlas",
        mode="smart",
        description="Atlas project",
    )
    script.replies.append(triage_reply(smart_folders=["Atlas", "atlas launch", "Made up"]))
    fake.state.deliver(make_mail(subject="Name two", message_id="<y2@x>"))
    assert judged(client, "Name two")["category"] == "Atlas"
    script.replies.append(triage_reply(category="Brand new"))
    fake.state.deliver(make_mail(subject="Name three", message_id="<y3@x>"))
    assert judged(client, "Name three")["category"] is None


def crowd(count: int) -> str:
    domains = ["big.example"] * (count - 2) + ["other.example"] * 2
    return ", ".join(f"person{n}@{domain}" for n, domain in enumerate(domains))


def test_mail_for_them_alone_or_naming_them_is_pointed_out(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Hi", sender=f"Tess Ter <{USER}>", to="a@x.example", message_id="<n0@x>"),
        box="Sent",
    )
    fake.state.deliver(make_mail(subject="Just you", message_id="<n1@x>"))
    judged(client, "Just you")
    sent = told(script.requests[-1])
    assert "addressed to the person alone" in sent and "names the person" not in sent

    fake.state.deliver(
        make_mail(
            subject="Team update",
            to=f"{crowd(30)}, {USER}",
            body="Thanks all. Tess, can you confirm the dates by Friday?",
            message_id="<n2@x>",
        )
    )
    judged(client, "Team update")
    sent = told(script.requests[-1])
    assert "names the person (“Tess”)" in sent and "addressed to the person alone" not in sent


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


def test_a_conversation_kept_from_the_ai_stays_kept_when_people_write_in_it(
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
    assert first["category"] == "Automated"
    post(client, "categories.save", "commands", name="Job search", mode="smart")
    script.default = triage_reply(smart_folders=["Job search"], status="waiting_on_others")
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
    fake.state.deliver(
        make_mail(
            subject="Re: Interview",
            sender="no-reply@ats.example",
            message_id="<ab3@x>",
            in_reply_to="<ab2@x>",
        )
    )
    # The folder is the gate for the whole conversation: neither the reply nor the answer is
    # shown to the AI, so it stays where it was filed.
    fake.state.deliver(make_mail(subject="Lunch on Friday?", message_id="<ab4@x>"))
    judged(client, "Lunch on Friday")
    kept = row(client, first["id"])
    assert kept["category"] == "Automated"
    assert all("Re: Interview" not in told(request) for request in script.requests)


def test_a_conversation_a_rule_filed_gets_no_ai_folders_and_is_not_learned(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    post(client, "categories.save", "commands", name="Briefing", subject="[Briefing]")
    post(client, "categories.save", "commands", name="Job search", mode="smart")
    fake.state.deliver(make_mail(subject="[Briefing] Week 46", sender=USER, message_id="<b1@x>"))
    first = thread_named(client, "[Briefing] Week 46")
    assert first["category"] == "Briefing"
    # A reply the rule doesn't match still belongs to the conversation the rule filed.
    script.default = triage_reply(smart_folders=["Job search"], status="waiting_on_you")
    fake.state.deliver(
        make_mail(
            subject="Re: [Briefing] Week 46",
            sender="colleague@x.com",
            message_id="<b2@x>",
            in_reply_to="<b1@x>",
        )
    )
    wait(lambda: row(client, first["id"])["status"] == "waiting_on_you", "the reply judged")
    after = row(client, first["id"])
    assert after["category"] == "Briefing"
    assert json.loads(after["extra_categories"]) == []
    assert not client.app.state.bus.db.fetch_all(  # type: ignore[attr-defined]
        "SELECT 1 FROM mail_learning_members WHERE thread=?", (first["id"],)
    )
    bulk_learning.queue(mail_context(client))
    assert not client.app.state.bus.db.fetch_all(  # type: ignore[attr-defined]
        "SELECT 1 FROM mail_learning_members WHERE thread=?", (first["id"],)
    )


def test_read_more_groups_incoming_and_sent_conversations(
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
    # Inbox and Sent sync separately, so wait for both rather than the first to arrive.
    wait(
        lambda: mail_agent.conversations_not_read(mail_context(client)) == 2,
        "both conversations",
    )
    assert mail_agent.queue_learning(mail_context(client), 5) == 2


def plan_thread(fake: FakeMail, emails: int) -> None:
    """One conversation, a day per email, so its order is plain."""
    for day in range(1, emails + 1):
        fake.state.deliver(
            make_mail(
                subject="Plan",
                body=f"Step {day} of the plan.",
                message_id=f"<plan{day}@x>",
                in_reply_to=f"<plan{day - 1}@x>" if day > 1 else None,
                references="<plan1@x>" if day > 1 else None,
                date=f"Mon, {day:02d} Jun 2026 09:00:00 +0000",
            )
        )


def test_a_long_conversation_is_read_newest_first_and_says_what_it_left_out(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    plan_thread(fake, 12)
    sent = wait(
        lambda: next((told(r) for r in script.requests if "Step 12 " in told(r)), None),
        "newest read",
    )
    assert "Emails, newest first" in sent
    assert sent.index("Step 12 ") < sent.index("Step 11 ")
    assert "Step 2 " not in sent
    assert "2 older emails not shown. read_thread with skip_newest=10 reads them." in sent


def test_each_email_is_judged_from_a_clean_context(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="First one", body="Alpha words.", message_id="<c1@x>"))
    judged(client, "First one")
    fake.state.deliver(
        make_mail(subject="Second one", sender="Ravi <ravi@other.com>", message_id="<c2@x>")
    )
    judged(client, "Second one")
    sent = told(script.requests[-1])
    # Nothing of the earlier run: not its email, not what the model said or did with it.
    assert "Second one" in sent and "Alpha words" not in sent
    assert not [m for m in script.requests[-1].messages if m.role in {"assistant", "tool"}]
    # The chat still shows both.
    view = post(client, "session.get", id=mail_agent.SESSION_ID)
    shown = json.dumps(view["messages"])
    assert "First one" in shown and "Second one" in shown


def test_a_run_that_runs_out_of_room_is_tried_once_more_smaller(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.replies = [[providers.ModelContextExceeded(providers.CONTEXT_HELP)]]
    fake.state.deliver(make_mail(subject="Huge", message_id="<h1@x>"))
    judged(client, "Huge")
    assert "ran out of room" in told(script.requests[-1])
    assert "ran out of room" not in told(script.requests[0])


def test_a_run_out_of_room_twice_is_left_unjudged_and_says_why(
    client: TestClient, fake: FakeMail, script: Script
) -> None:
    connect(client, fake)
    script.replies = [[providers.ModelContextExceeded(providers.CONTEXT_HELP)]] * 2
    fake.state.deliver(make_mail(subject="Huge", message_id="<h2@x>"))
    thread = thread_named(client, "Huge")
    wait(lambda: "Not triaged" in str(row(client, thread["id"])["why"] or "") or None, "failed")
    assert len(script.requests) == 2


def test_the_names_they_gave_tell_the_agent_who_they_are(
    client: TestClient, fake: FakeMail, script: Script, app_config: Config
) -> None:
    connect(client, fake)
    mentions.save(
        app_config.home,
        MailMe(names=["Mahi", "PLM Team"], ids=["myadav01"], not_you=["Mahesh Kumar"]),
    )
    fake.state.deliver(
        make_mail(
            subject="BOM", body="Hi all,\n\nMahi, can you check the BOM today?", to="list@x.com"
        )
    )
    judged(client, "BOM")
    sent = told(script.requests[-1])
    assert "names the person or their team: “Mahi, can you check the BOM today?”" in sent
    assert "Names that mean them or their teams: Mahi, PLM Team" in sent
    assert "How tools and colleagues tag them: myadav01" in sent
    assert "not them, though the names look alike: Mahesh Kumar" in sent
