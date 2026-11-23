"""The grouping engine against a made-up mailbox whose emails say what they really are."""

import json
import re
from collections import Counter
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import pytest

import corp_mail
from nexusai.modules.mail import grouping

ENGINE = Path(grouping.__file__)


# Several seeds, because one arrangement of the same mail can hide a rule that only works by
# luck: seeds 1 and 99 once caught a person's dated notes pulling all their mail into Automated.
# Plain is a server without Outlook's marks, where most tools were once missed.
@pytest.fixture(
    scope="module",
    params=[(7, True), (1, True), (99, True), (7, False), (99, False)],
    ids=["marks-7", "marks-1", "marks-99", "plain-7", "plain-99"],
)
def mailbox(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[list[dict[str, Any]], grouping.Report]:
    folder = tmp_path_factory.mktemp("corp")
    seed, marks = request.param
    corp_mail.build(folder, seed=seed, marks=marks)
    labels = json.loads((folder / "labels.json").read_text())
    return labels, grouping.group_mailbox(grouping.read_folder(folder))


def score(labels: list[dict[str, Any]], report: grouping.Report) -> dict[str, Any]:
    decided = report.decisions
    tool = [x for x in labels if x["machine"] and not x["calendar"]]
    people = [x for x in labels if not x["machine"] and not x["calendar"]]
    calendar = [x for x in labels if x["calendar"]]
    important = [x for x in labels if x["important"]]
    missed = [x for x in important if not decided[x["file"]].reaches_ai]
    noise = [
        x for x in labels
        if not x["important"] and not decided[x["file"]].smart and decided[x["file"]].reaches_ai
    ]  # fmt: skip
    return {
        "important_reaching_ai": f"{len(important) - len(missed)}/{len(important)}",
        "missed": Counter(x["truth"] for x in missed),
        "people_in_automated": Counter(
            x["truth"] for x in people if decided[x["file"]].section == "automated"
        ),
        "tool_caught": sum(decided[x["file"]].section == "automated" for x in tool) / len(tool),
        "tool_not_caught": Counter(
            x["truth"] for x in tool if decided[x["file"]].section != "automated"
        ),
        "calendar_caught": sum(decided[x["file"]].section == "calendar" for x in calendar)
        / len(calendar),
        "noise_let_through": Counter(x["truth"] for x in noise),
        "kept_from_ai": sum(not d.reaches_ai for d in decided.values()),
    }


def test_every_important_email_still_reaches_the_ai(mailbox: Any) -> None:
    result = score(*mailbox)
    print(json.dumps(result, indent=1, default=str))
    assert not result["missed"]


def test_mail_people_write_is_never_filed_as_automated(mailbox: Any) -> None:
    assert not score(*mailbox)["people_in_automated"]


def test_most_tool_and_calendar_mail_is_caught(
    mailbox: Any, request: pytest.FixtureRequest
) -> None:
    result = score(*mailbox)
    # Without Outlook's marks a wiki whose subjects never repeat looks like a person: a known
    # miss, kept rather than risk hiding announcements that look the same.
    plain = "plain" in request.node.callspec.id
    assert result["tool_caught"] >= (0.9 if plain else 0.95), result["tool_not_caught"]
    assert result["calendar_caught"] >= 0.95


def test_a_report_naming_the_whole_team_does_not_reach_the_ai(mailbox: Any) -> None:
    labels, report = mailbox
    reports = [x for x in labels if x["truth"] == "effort-report"]
    assert not any(report.decisions[x["file"]].reaches_ai for x in reports)


def test_the_mailbox_owner_comes_from_the_mail(mailbox: Any) -> None:
    _, report = mailbox
    assert report.owner == corp_mail.OWNER[1]


def test_the_engine_knows_nothing_about_the_test_mailbox() -> None:
    """Every sender, tag, name and domain in the made-up mailbox is absent from the engine."""
    source = ENGINE.read_text().lower()
    words = {corp_mail.COMPANY, *corp_mail.OWNER[0].lower().split(), *corp_mail.PROJECTS}
    words |= {name.split()[0] for name, _ in corp_mail.PEOPLE}
    words |= set(re.findall(r"(?:[\w.-]+)@", Path(corp_mail.__file__).read_text()))
    words |= {"plm", "swarm", "qc", "jenkins", "wiki", "tracker", "effort", "invitation", "hr"}
    found = {
        word
        for word in words
        if re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", source)
    }
    assert not found


# The rules on their own, including where they must not fire.

OWNER = "sam.lee@firm.example"


def _mail(sender: str, subject: str, body: str, to: str = OWNER, **headers: str) -> bytes:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message["Message-ID"] = make_msgid()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    message.set_content(body)
    return bytes(message)


def _box(*groups: list[bytes]) -> grouping.Report:
    return grouping.group_mailbox(
        (str(index), raw) for index, raw in enumerate(raw for group in groups for raw in group)
    )


def _section(report: grouping.Report, prefix: str) -> set[str]:
    return {d.section for key, d in report.decisions.items() if key.startswith(prefix)}


def test_a_sender_nobody_answers_and_you_never_wrote_to_is_a_tool() -> None:
    shop = [_mail("orders@shop.example", f"Your parcel for {item} is on its way", "Track it.")
            for item in ("a lamp", "a mug", "socks", "a kettle") * 6]  # fmt: skip
    friend = [_mail("kim@else.example", f"About {topic}", "What do you think?")
              for topic in ("the trip", "dinner", "the book", "work") * 6]  # fmt: skip
    mine = [_mail(OWNER, f"Note {n}", "Hi", to="kim@else.example") for n in range(25)]
    report = _box(shop, friend, mine)
    sections = {d.group: d.section for d in report.decisions.values()}
    assert sections.get("auto:orders@shop.example") == "automated"
    assert not any(gid and "kim@" in gid for gid in sections)
    assert not any(gid and OWNER in gid for gid in sections)


def test_without_sent_mail_or_outlook_marks_nobody_is_called_a_tool_for_being_unanswered() -> None:
    notices = [_mail("people-team@firm.example", f"Update on {topic}", "Dear all, details below.",
                     to="everyone@firm.example") for topic in [f"topic {chr(97 + n)}" for n in range(24)]]  # fmt: skip
    # Distinct subjects, so only the unanswered rule could fire. A person repeating the same
    # subjects 20+ times with no marks and no sent mail does look like a tool: a known limit.
    direct = [_mail("ari@firm.example", f"Question {chr(97 + n)}{chr(97 + n // 3)}", "Can you look?") for n in range(30)]  # fmt: skip
    report = _box(notices, direct)
    assert "automated" not in {d.section for d in report.decisions.values()}


def test_only_what_the_mail_says_to_the_person_counts_as_naming_them() -> None:
    names = grouping._mention(OWNER, "Sam Lee")
    said = [
        ("Case 12 assigned to Sam Lee", ""),
        ("Case 12", "Assignee: Sam Lee\nDue: Friday\n\nDo not reply.\nFooter\nFooter"),
        ("Review", "Pat added Sam Lee (sam.lee) as a reviewer."),
    ]
    not_said = [
        ("Sam Lee, a deal for you", ""),
        ("Deals", "Hi Sam Lee!\nNew offers inside."),
        ("Deals", "SAM LEE\nAccount 1234\nNew offers inside."),
        ("Deals", f"Offers\nhttps://shop.example/?e={OWNER}\nMore"),
        ("Deals", f"Offers\nMore offers\nUnsubscribe\nSent to: {OWNER}\nShop Ltd"),
    ]
    assert all(grouping._addressed(names, subject, body) for subject, body in said)
    assert not any(grouping._addressed(names, subject, body) for subject, body in not_said)


def test_domain_endings_are_learned_from_the_mailbox() -> None:
    endings = grouping._endings(
        {"alerts.one.bank.example", "two.bank.example", "mail.vendor.example"}
    )
    assert endings == {"bank.example"}
    assert grouping._site("alerts.one.bank.example", endings) == "one"
    assert grouping._site("mail.vendor.example", endings) == "vendor"


def test_mail_from_the_person_to_themselves_is_grouped_but_what_they_write_to_others_is_not() -> (
    None
):
    forwarded = [_mail(OWNER, f"[3GPP] RAN1 #{n} meeting report", "Forwarded by rule.") for n in range(30)]  # fmt: skip
    written = [_mail(OWNER, f"[3GPP] RAN1 #{n} our comments", "My view.", to="kim@else.example") for n in range(30)]  # fmt: skip
    others = [_mail("ari@firm.example", f"Lunch {n}?", "Free?") for n in range(10)]
    report = _box(forwarded, written, others)
    sections = [d.section for key, d in report.decisions.items() if int(key) < 30]
    assert set(sections) == {"automated"}
    assert all(report.decisions[str(n)].group is None for n in range(30, 60))


def test_five_repeating_unanswered_emails_are_enough_only_from_an_address_nobody_writes_to() -> (
    None
):
    tool = [_mail("alerts@firm.example", f"Job {n} finished", "Done.\nAlerts") for n in range(6)]
    colleague = [_mail("ari@firm.example", f"Status week {n}", "All fine.\nAri") for n in range(6)]
    mentions = [_mail("kim@firm.example", "Plans", "Talk soon", to=f"{OWNER}, ari@firm.example")]
    report = _box(tool, colleague, mentions)
    assert {report.decisions[str(n)].section for n in range(6)} == {"automated"}
    assert "automated" not in {report.decisions[str(n)].section for n in range(6, 12)}


def test_notes_to_yourself_are_never_grouped_and_a_blank_subject_is_no_pattern() -> None:
    notes = [
        _mail(OWNER, "" if n % 2 else f"note {chr(97 + n)}", "See attached.") for n in range(40)
    ]
    blank = [_mail("kim@else.example", "", f"Thought {n}") for n in range(8)]
    report = _box(notes, blank)
    assert all(d.group is None for d in report.decisions.values())


def test_two_alike_emails_from_an_address_nobody_writes_to_are_enough_but_a_conversation_is_not() -> (
    None
):
    tool = [_mail("orders@shop.example", f"Order {n} confirmed", "Thanks.\nShop") for n in (11, 12)]
    asked = _mail("ari@firm.example", "Lunch?", "Free at 1?")
    again = _mail("ari@firm.example", "Re: Lunch?", "Still on?")
    report = _box(tool, [asked, again])
    assert {report.decisions[str(n)].section for n in (0, 1)} == {"automated"}
    assert report.decisions["2"].group is None and report.decisions["3"].group is None


def test_two_emails_are_enough_only_when_just_a_number_changes() -> None:
    numbered = [_mail("jobs@firm.example", f"Build {n} passed", "Done.\nCI") for n in (7, 8)]
    same = [
        _mail("ari@firm.example", "Need your sign-off", "Please approve.\nAri") for _ in range(2)
    ]
    report = _box(numbered, same)
    assert {report.decisions[str(n)].section for n in (0, 1)} == {"automated"}
    # The same words twice could be a person repeating themselves: too few to be sure.
    assert all(report.decisions[str(n)].section == "too_few" for n in (2, 3))
    assert all(report.decisions[str(n)].reaches_ai for n in (2, 3))


def test_company_mail_that_greets_the_person_by_name_is_never_grouped() -> None:
    names = _mail("kim@firm.example", "Hello", "Hi", to=f"Sam Lee <{OWNER}>")
    asks = [_mail("boss@firm.example", f"Decision {n} needed", "Hi Sam,\nPlease decide.") for n in range(30)]  # fmt: skip
    offers = [_mail("deals@shop.example", f"Deal {n}", "Hi Sam,\nOffers.", List_Unsubscribe="<https://x>") for n in range(30)]  # fmt: skip
    report = _box([names], asks, offers)
    assert all(report.decisions[str(n)].group is None for n in range(1, 31))
    assert {report.decisions[str(n)].section for n in range(31, 61)} == {"automated"}


def test_unsubscribing_by_email_is_not_writing_to_a_sender() -> None:
    letters = [_mail("news@paper.example", f"Issue {n}: the week", "Read more", List_Unsubscribe="<mailto:news@paper.example?subject=unsubscribe>") for n in range(25)]  # fmt: skip
    mine = [_mail(OWNER, "unsubscribe 1fb8", "", to="news@paper.example")]
    mine += [_mail(OWNER, f"Note {n}", "Hi", to="kim@else.example") for n in range(25)]
    report = _box(letters, mine)
    assert {report.decisions[str(n)].section for n in range(25)} == {"automated"}


# One list, one number per sender


def enumerate_mail(raws: list[bytes]) -> list[tuple[str, bytes]]:
    return [(str(index), raw) for index, raw in enumerate(raws)]


def test_each_sender_gets_one_score_and_a_side() -> None:
    tool = [_mail("ci@tools.example", f"Build {n} passed", "Done.") for n in range(6)]
    news = [_mail("news@paper.example", f"Story {chr(97 + n)}", "Read more", List_Unsubscribe="<https://x>") for n in range(6)]  # fmt: skip
    person = [_mail("kim@else.example", f"About {topic}", "Thoughts?") for topic in ("a", "b", "c")]
    once = [_mail("new@shop.example", "Welcome", "Hi")]
    report = grouping.score_senders(enumerate_mail(tool + news + person + once))
    sides = {row.sender: row.side for row in report.senders}
    assert sides["ci@tools.example"] == "ignores"
    assert sides["news@paper.example"] == "ignores"
    assert sides["kim@else.example"] == "reads"
    assert (
        next(row for row in report.senders if row.sender == "new@shop.example").kept
        == "A new sender"
    )
    assert [row.count for row in report.senders] == sorted(
        (row.count for row in report.senders), reverse=True
    )


def test_an_ignored_sender_keeps_all_its_mail_from_the_ai_even_what_names_the_person() -> None:
    builds = [
        _mail("ci@tools.example", f"Build {n} passed", "Done.\nLogs\nMore\nCI") for n in range(6)
    ]
    named = _mail("ci@tools.example", "Build 9 failed", f"Assigned to {OWNER}\nLogs\nMore\nCI")
    report = grouping.score_senders(enumerate_mail([*builds, named]))
    tool = next(row for row in report.senders if row.sender == "ci@tools.example")
    assert tool.side == "ignores"
    # The folder is the gate: the one that names them stays away from the AI too.
    assert report.quiet == {str(n) for n in range(len(builds) + 1)}


def test_only_mail_sent_to_one_person_gets_rules_by_how_its_subjects_start() -> None:
    bank = [_mail("alerts@bank.example", f"Your OTP for login is {n}", "Use it.") for n in range(5)]
    sale = [_mail("deals@shop.example", f"Mahesh take off {n}0%", "Shop now", List_Unsubscribe="<https://x>") for n in range(5)]  # fmt: skip
    report = grouping.score_senders(enumerate_mail(bank + sale))
    starts = {row.sender: row.starts for row in report.senders}
    assert starts["alerts@bank.example"] == ["your otp for"]
    # A newsletter is all one thing: one rule takes all of it, so the next sale stays hidden.
    assert starts["deals@shop.example"] == []
