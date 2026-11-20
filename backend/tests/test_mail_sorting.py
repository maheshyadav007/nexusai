"""Sorting a new mailbox before the AI reads it: what's kept from the AI is filed, gets rules,
and leaves meaning search, while mail that names the person still reaches the AI."""

import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from fake_mail import make_mail
from nexusai.contracts.mail import ApplyMailSort, MailSort, SortChoice
from nexusai.kernel.module import Context
from nexusai.modules.mail import rules, sorting, store
from nexusai.modules.mail.parse import parse_message
from nexusai.modules.semantic.module import KEPT_MAIL
from test_mail_organization import ctx  # noqa: F401

OWNER = "me@example.com"


def stored(ctx: Context, subject: str, sender: str, body: str = "Done.\nCI") -> store.Stored:  # noqa: F811
    count = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM messages")[0]["n"] + 1
    raw = make_mail(
        subject=subject,
        sender=sender,
        to=OWNER,
        body=body,
        date=format_datetime(datetime.now(UTC) - timedelta(days=count)),
        message_id=f"<sorting-{count}@test>",
    )
    parsed = parse_message(raw)
    with ctx.bus.db.transaction() as tx:
        result = store.store_message(
            tx,
            account="test",
            folder="INBOX",
            role="inbox",
            uid=count,
            raw=raw,
            read=False,
            flagged=False,
            parsed=parsed,
            match=rules.evaluate(parsed, rules.load_rules(ctx.config.home)),
            config=ctx.config.mail,
        )
    assert result is not None
    return result


def ready(ctx: Context) -> MailSort:  # noqa: F811
    sorting.prepare(ctx)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = sorting.status(ctx)
        if status.state in {"ready", "failed"}:
            return status
        time.sleep(0.05)
    raise AssertionError("The mail was never grouped")


@pytest.fixture
def mailbox(ctx: Context) -> dict[str, Any]:  # noqa: F811
    builds = [stored(ctx, f"Build {n} passed", "ci@tools.example") for n in range(8)]
    asked = stored(
        ctx,
        "Build 99 failed",
        "ci@tools.example",
        f"Build 99 failed.\nAssigned to {OWNER}\nLogs: see the job\nRetry with the button\nCI",
    )
    people = [stored(ctx, f"About {topic}", "Kim <kim@else.example>", "What do you think?")
              for topic in ("the trip", "dinner", "a book")]  # fmt: skip
    return {"builds": builds, "asked": asked, "people": people}


def test_sorting_files_what_the_ai_ignores_and_gives_it_a_rule(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    status = ready(ctx)
    assert status.state == "ready" and status.emails == 12
    tool = next(group for group in status.groups if "ci@tools.example" in group.senders)
    assert tool.folder == "automated" and tool.names_you == 1
    moved = sorting.apply(
        ctx, ApplyMailSort(choices=[SortChoice(id=tool.id, name="Builds", folder="automated")])
    )
    assert moved == 8
    category = ctx.bus.db.fetch_all(
        "SELECT * FROM mail_categories WHERE name = 'Automated/Builds'"
    )[0]
    assert (category["mode"], category["ai_reads"]) == ("exact", 0)
    parent = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name = 'Automated'")[0]
    assert parent["ai_reads"] == 0
    filed = {
        row["thread_id"]
        for row in ctx.bus.db.fetch_all(
            "SELECT thread_id FROM messages WHERE rule LIKE 'Sorted: %'"
        )
    }
    assert filed == {build.thread for build in mailbox["builds"]}
    # The email that names them stays where the AI reads it.
    asked = ctx.bus.db.fetch_all(
        "SELECT category FROM threads WHERE id = ?", (mailbox["asked"].thread,)
    )[0]
    assert asked["category"] != "Automated/Builds"
    assert sorting.decided(ctx) == "done"
    # Meaning search leaves the filed mail out; keyword search still has it.
    indexed = ctx.bus.db.fetch_all(f"SELECT COUNT(*) AS n FROM messages WHERE {KEPT_MAIL}")[0]["n"]  # noqa: S608
    assert indexed == 12 - 8


def test_new_mail_follows_the_rule_unless_it_names_the_person(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    status = ready(ctx)
    tool = next(group for group in status.groups if "ci@tools.example" in group.senders)
    sorting.apply(
        ctx, ApplyMailSort(choices=[SortChoice(id=tool.id, name="Builds", folder="automated")])
    )
    rule = next(
        r for r in rules.load_rules(ctx.config.home) if r.actions.category == "Automated/Builds"
    )
    assert rule.actions.skip_agent and OWNER in rule.actions.mentions
    quiet = stored(ctx, "Build 120 passed", "ci@tools.example")
    asked = stored(
        ctx,
        "Build 121 failed",
        "ci@tools.example",
        f"Please look, {OWNER} is on call.\nLogs\nCI\nFooter",
    )
    assert quiet.skip_agent and not quiet.worth_a_look
    assert asked.skip_agent and asked.worth_a_look


def test_a_merged_or_inbox_choice_files_nothing_there(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    status = ready(ctx)
    tool = next(group for group in status.groups if "ci@tools.example" in group.senders)
    moved = sorting.apply(ctx, ApplyMailSort(choices=[SortChoice(id=tool.id, folder="inbox")]))
    assert moved == 0
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name LIKE 'Automated%'")
    assert not [r for r in rules.load_rules(ctx.config.home) if r.name.startswith("Sorted: ")]


def test_skipping_leaves_the_mail_as_it_was(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    ready(ctx)
    sorting.skip(ctx)
    assert sorting.decided(ctx) == "skipped" and sorting.status(ctx).state == "skipped"
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM messages WHERE rule LIKE 'Sorted: %'")
