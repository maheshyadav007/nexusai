"""Sorting a new mailbox before the AI reads it: what's kept from the AI is filed, gets rules,
and leaves meaning search, while mail that names the person still reaches the AI."""

import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from fake_mail import make_mail
from nexusai.contracts.mail import ApplyMailSort, MailSort, SortSenderChoice
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
            decision=rules.Engine(rules.load_rules(ctx.config.home)).decide([parsed])[0],
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
    raise AssertionError("The mail was never scored")


def build_bot(status: MailSort) -> Any:
    return next(row for row in status.senders if row.sender == "ci@tools.example")


def named(name: str, side: str = "ignores") -> ApplyMailSort:
    return ApplyMailSort(
        senders=[SortSenderChoice(sender="ci@tools.example", side=side, own=True, name=name)]  # type: ignore[arg-type]
    )


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
    tool = build_bot(status)
    assert tool.side == "ignores" and tool.own and tool.reach == 1 and tool.count == 9
    assert tool.score >= 0.5
    kim = next(row for row in status.senders if row.sender == "kim@else.example")
    assert kim.side == "reads"
    moved = sorting.apply(ctx, named("Builds"))
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
    # Kept from the AI, so out of the Inbox too; the one that names them stays in it.
    from nexusai.modules.mail.store import FOLDER_FILTERS

    inbox = {
        row["id"]
        for row in ctx.bus.db.fetch_all(
            f"SELECT id FROM threads WHERE {FOLDER_FILTERS['priority']}"  # noqa: S608
        )
    }
    assert not inbox & filed and mailbox["asked"].thread in inbox
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
    ready(ctx)
    sorting.apply(ctx, named("Builds"))
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
    # Its rule keeps the sender away, but this one names the person, so the AI reads it.
    assert not asked.skip_agent and asked.worth_a_look


def test_a_sender_moved_to_the_ai_is_filed_nowhere(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    ready(ctx)
    moved = sorting.apply(ctx, named("Builds", side="reads"))
    assert moved == 0
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name LIKE 'Automated%'")
    assert not [r for r in rules.load_rules(ctx.config.home) if r.name.startswith("Sorted: ")]


def test_scoring_waits_until_the_mail_is_all_in(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    from nexusai.modules.mail import accounts

    account = accounts.current_account(ctx.config)
    with ctx.bus.db.transaction() as tx:
        tx.execute("INSERT INTO mail_sync_settings (account) VALUES (?)", (account,))
    sorting.prepare(ctx)
    assert sorting.status(ctx).state == "none"
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE mail_sync_settings SET history_finished = 'now' WHERE account = ?", (account,)
        )
    assert ready(ctx).state == "ready"


def test_mail_that_came_after_scoring_is_scored_when_asked_again(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    assert ready(ctx).emails == 12
    stored(ctx, "Release 4 notes", "notes@tools.example")
    assert ready(ctx).emails == 13


def test_skipping_leaves_the_mail_as_it_was(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    ready(ctx)
    sorting.skip(ctx)
    assert sorting.decided(ctx) == "skipped" and sorting.status(ctx).state == "skipped"
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM messages WHERE rule LIKE 'Sorted: %'")


def test_mail_its_own_rules_already_file_is_left_as_it_is(ctx: Context, mailbox: Any) -> None:  # noqa: F811
    # Sorting after an archive comes in builds on the categories and rules already there.
    from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition

    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            *existing,
            MailRule(
                name="Builds",
                conditions=[RuleCondition(field="sender_exact", value="ci@tools.example")],
                actions=RuleActions(category="Builds", skip_agent=True),
            ),
        ],
    )
    status = ready(ctx)
    assert status.already_sorted == 9
    assert not [row for row in status.senders if row.sender == "ci@tools.example"]


def test_senders_given_one_name_share_a_category(ctx: Context) -> None:  # noqa: F811
    for tool in range(2):
        for n in range(6):
            stored(ctx, f"Alert {n} raised", f"alerts{tool}@monitor.example")
    ready(ctx)
    sorting.apply(
        ctx,
        ApplyMailSort(
            senders=[
                SortSenderChoice(
                    sender=f"alerts{tool}@monitor.example", side="ignores", own=True, name=name
                )
                for tool, name in ((0, "Monitoring"), (1, "monitoring"))
            ]
        ),
    )
    names = {row["name"] for row in ctx.bus.db.fetch_all("SELECT name FROM mail_categories")}
    assert names == {"Automated", "Automated/Monitoring"}


def test_only_the_biggest_tools_get_a_folder_and_the_rest_go_into_automated(ctx: Context) -> None:  # noqa: F811
    for tool in range(7):
        for n in range(6 + tool):
            stored(ctx, f"Report {n} ready", f"tool{tool}@tools{tool}.example")
    status = ready(ctx)
    automated = [row for row in status.senders if row.side == "ignores"]
    assert len(automated) == 7 and sum(row.own for row in automated) == 5
    sorting.apply(ctx, ApplyMailSort())
    names = {row["name"] for row in ctx.bus.db.fetch_all("SELECT name FROM mail_categories")}
    assert len([name for name in names if name.startswith("Automated/")]) == 5
    smallest = ctx.bus.db.fetch_all(
        "SELECT DISTINCT t.category FROM threads t JOIN messages m ON m.thread_id = t.id"
        " WHERE m.from_addr = 'tool0@tools0.example'"
    )
    assert [row["category"] for row in smallest] == ["Automated"]
    # New Homes start with only the Automated folder; the header kinds all file into it.
    assert not names & {"Updates", "Promotions", "Forums", "Social", "Broadcast"}


def test_after_sorting_the_ai_suggests_no_folders(ctx: Context) -> None:  # noqa: F811
    from nexusai.modules.agent.mail_agent import Triage

    suggestion = {"name": "Vendor quotes", "reason": "They keep coming", "sender": "q@v.example"}
    sorting.skip(ctx)
    Triage(ctx)._suggest_category(suggestion, 1)
    # Skipped, the person never settled folders, so the AI may still suggest one.
    assert ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name = 'Vendor quotes'")
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM mail_categories")
        tx.execute("UPDATE mail_sorting SET state = 'done'")
    Triage(ctx)._suggest_category(suggestion, 1)
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories")
