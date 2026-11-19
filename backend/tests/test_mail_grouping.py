"""The grouping engine against a made-up mailbox whose emails say what they really are."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import corp_mail
from nexusai.modules.mail import grouping

ENGINE = Path(grouping.__file__)


@pytest.fixture(scope="module")
def mailbox(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[list[dict[str, Any]], grouping.Report]:
    folder = tmp_path_factory.mktemp("corp")
    corp_mail.build(folder)
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
