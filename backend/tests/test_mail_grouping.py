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
@pytest.fixture(scope="module", params=[7, 1, 99])
def mailbox(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[list[dict[str, Any]], grouping.Report]:
    folder = tmp_path_factory.mktemp("corp")
    corp_mail.build(folder, seed=request.param)
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


def test_most_tool_and_calendar_mail_is_caught(mailbox: Any) -> None:
    result = score(*mailbox)
    assert result["tool_caught"] >= 0.95, result["tool_not_caught"]
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
