"""Sorting a new mailbox before the AI reads it: what's kept from the AI is filed, gets rules,
and leaves meaning search, while mail that names the person still reaches the AI."""

import json
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from fake_mail import make_mail
from nexusai.contracts.mail import (
    ApplyMailSort,
    MailRule,
    MailSort,
    RuleActions,
    RuleCondition,
    SortSenderChoice,
)
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
    # Listed where its rule files it, and left as it is unless it's moved across.
    tool = build_bot(status)
    assert (tool.side, tool.folder) == ("ignores", "Builds")
    sorting.apply(ctx, named("Builds"))
    assert [r.name for r in rules.load_rules(ctx.config.home)] == ["Builds"]


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
    assert len(automated) == 7 and sum(row.own for row in automated) == 3
    sorting.apply(ctx, ApplyMailSort())
    names = {row["name"] for row in ctx.bus.db.fetch_all("SELECT name FROM mail_categories")}
    assert len([name for name in names if name.startswith("Automated/")]) == 3
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


def test_move_to_inbox_brings_a_sorted_conversation_back_to_the_ai(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    from nexusai.contracts.mail import ThreadToInbox
    from nexusai.modules.mail.module import READS_PREFIX, to_inbox
    from nexusai.modules.mail.store import FOLDER_FILTERS

    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    thread = mailbox["builds"][0].thread
    assert to_inbox(ThreadToInbox(id=thread), ctx).sender == "ci@tools.example"
    row = ctx.bus.db.fetch_all("SELECT * FROM threads WHERE id = ?", (thread,))[0]
    assert (
        row["category"] is None and row["latest_rule"] is None and row["category_source"] == "user"
    )
    inbox = ctx.bus.db.fetch_all(
        f"SELECT id FROM threads WHERE {FOLDER_FILTERS['priority']} AND id = ?", (thread,)
    )  # noqa: S608
    asked = ctx.bus.db.fetch_all("SELECT payload FROM events WHERE type = 'mail.needsTriage'")
    assert inbox and [json.loads(event["payload"])["thread_id"] for event in asked] == [thread]
    # Only this one: the sender's rule still files what comes next, until they say always.
    assert any(r.name.startswith("Sorted: ") for r in rules.load_rules(ctx.config.home))
    assert stored(ctx, "Build 200 passed", "ci@tools.example").skip_agent

    to_inbox(ThreadToInbox(id=thread, always=True), ctx)
    saved = rules.load_rules(ctx.config.home)
    sender_rules = [r for r in saved if any(c.field == "sender_exact" for c in r.conditions)]
    assert [r.name for r in sender_rules] == [f"{READS_PREFIX}ci@tools.example"]
    assert saved[0].name == f"{READS_PREFIX}ci@tools.example"
    assert not stored(ctx, "Build 201 passed", "ci@tools.example").skip_agent


def test_gmails_own_starred_and_important_are_left_to_the_apps_views(ctx: Context) -> None:  # noqa: F811
    from nexusai.contracts.mail import ListMailFolders
    from nexusai.modules.mail.module import mail_folders

    with ctx.bus.db.transaction() as tx:
        for name, role in [("[Gmail]/Starred", "other"), ("[Gmail]/Important", "other"),
                           ("[Gmail]/All Mail", "all"), ("Projects/Aurora", "other")]:  # fmt: skip
            tx.execute(
                "INSERT INTO mail_folders (account, name, role) VALUES ('test', ?, ?)", (name, role)
            )
    found = {row.name: row.shown_elsewhere for row in mail_folders(ListMailFolders(), ctx).folders}
    assert found == {
        "[Gmail]/Starred": True,
        "[Gmail]/Important": True,
        "[Gmail]/All Mail": False,
        "Projects/Aurora": False,
    }


def reviewed(ctx: Context) -> MailSort:  # noqa: F811
    """The page opened again after sorting, once its fresh look at the mail is done."""
    sorting.prepare(ctx, again=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = sorting.status(ctx)
        if status.review in {"ready", "failed"}:
            return status
        time.sleep(0.05)
    raise AssertionError("The mail was never looked at again")


def test_the_page_opens_again_with_each_sender_where_its_rule_puts_it(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    again = reviewed(ctx)
    # Still sorted, so Today doesn't ask again; the page lists every sender as things are now.
    assert again.state == "done" and again.review == "ready"
    tool = build_bot(again)
    kim = next(row for row in again.senders if row.sender == "kim@else.example")
    assert (tool.side, tool.folder) == ("ignores", "Automated/Builds")
    assert (kim.side, kim.folder) == ("reads", "")
    # Moved across from a folder the AI skips as a whole, its sorting rule goes and one lets it
    # in, as Move to Inbox does.
    sorting.apply(ctx, named("Builds", side="reads"))
    found = [r for r in rules.load_rules(ctx.config.home) if "ci@tools.example" in r.name]
    assert [r.name for r in found] == ["AI reads: ci@tools.example"]
    assert build_bot(reviewed(ctx)).side == "reads"


def test_a_rule_changed_elsewhere_shows_when_the_page_opens_again(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    kim = "kim@else.example"
    assert next(r for r in reviewed(ctx).senders if r.sender == kim).side == "reads"
    # A rule made on the Rules page, after sorting.
    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            *existing,
            MailRule(
                name=f"Friends: {kim}",
                conditions=[RuleCondition(field="sender", value=kim)],
                actions=RuleActions(category="Friends", skip_agent=True),
            ),
        ],
    )
    row = next(r for r in reviewed(ctx).senders if r.sender == kim)
    assert (row.side, row.folder) == ("ignores", "Friends")


def test_what_keeps_mail_from_the_ai_is_checked_first_and_the_rest_reaches_it(
    ctx: Context,  # noqa: F811
) -> None:
    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            # Saved first, yet checked after the rule that keeps the same mail away.
            MailRule(
                name="Builds read",
                conditions=[RuleCondition(field="sender_exact", value="ci@tools.example")],
                actions=RuleActions(category="Builds"),
            ),
            MailRule(
                name="Tool tag kept",
                conditions=[RuleCondition(field="subject", value="[CI]")],
                actions=RuleActions(category="Tools", skip_agent=True),
            ),
        ],
    )
    tagged = stored(ctx, "[CI] Build 7 passed", "ci@tools.example")
    plain = stored(ctx, "Build 8 passed", "ci@tools.example")
    stranger = stored(ctx, "Hello", "Ann <ann@new.example>", "Are you free?")
    assert tagged.skip_agent and tagged.rule == "Tool tag kept"
    assert not plain.skip_agent and plain.rule == "Builds read"
    # No rule claims it, so the AI reads it.
    assert not stranger.skip_agent and stranger.rule is None


def test_a_sender_always_has_one_rule_whichever_side_it_is_moved_to(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    sender = "ci@tools.example"

    def mine() -> list[MailRule]:
        return [
            r
            for r in rules.load_rules(ctx.config.home)
            if any(c.value == sender for c in r.conditions)
        ]

    for reads, folder in [(True, None), (False, "Tools"), (True, None), (False, None)]:
        sorting.move_sender(ctx, sender, reads=reads, folder=folder)
        assert len(mine()) == 1
        assert mine()[0].actions.skip_agent is not reads
    # Kept from the AI the last time, in the folder it had.
    assert mine()[0].actions.category == "Tools"
    # Moved to the AI out of a folder it reads, it stays filed there.
    sorting.move_sender(ctx, sender, reads=True)
    assert (mine()[0].actions.category, mine()[0].actions.skip_agent) == ("Tools", False)
    assert build_bot(reviewed(ctx)).side == "reads"


def test_a_sender_put_in_a_folder_on_the_page_goes_there_mail_and_all(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    reviewed(ctx)
    kim = "kim@else.example"

    def folders(sender: str) -> set[str | None]:
        return {
            row["category"]
            for row in ctx.bus.db.fetch_all(
                "SELECT DISTINCT t.category FROM threads t JOIN messages m ON m.thread_id = t.id"
                " WHERE LOWER(m.from_addr) = ?",
                (sender,),
            )
        }

    def rule_of(sender: str) -> MailRule:
        (rule,) = [
            r
            for r in rules.load_rules(ctx.config.home)
            if any(c.value == sender for c in r.conditions)
        ]
        return rule

    # Kim, read by the AI from the Inbox, gets a new folder the AI reads.
    sorting.apply(
        ctx,
        ApplyMailSort(senders=[SortSenderChoice(sender=kim, side="reads", folder="Friends")]),
    )
    friends = ctx.bus.db.fetch_all("SELECT ai_reads FROM mail_categories WHERE name = 'Friends'")
    assert [row["ai_reads"] for row in friends] == [1]
    assert folders(kim) == {"Friends"}
    assert (rule_of(kim).actions.category, rule_of(kim).actions.skip_agent) == ("Friends", False)
    # The build bot is dragged into it from Automated/Builds: its mail follows, the AI reads it.
    bot = "ci@tools.example"
    reviewed(ctx)
    sorting.apply(
        ctx,
        ApplyMailSort(senders=[SortSenderChoice(sender=bot, side="reads", folder="Friends")]),
    )
    assert folders(bot) == {"Friends"}
    assert not rule_of(bot).actions.skip_agent
    # And back to the Inbox: no folder, still read, one rule.
    reviewed(ctx)
    sorting.apply(
        ctx, ApplyMailSort(senders=[SortSenderChoice(sender=kim, side="reads", folder="")])
    )
    assert folders(kim) == {None}
    assert rule_of(kim).actions.category is None
    row = next(r for r in reviewed(ctx).senders if r.sender == bot)
    assert (row.side, row.folder) == ("reads", "Friends")


def test_a_whole_folder_moves_to_one_side_with_every_sender_in_it(
    ctx: Context,  # noqa: F811
    mailbox: Any,
) -> None:
    from nexusai.contracts.mail import UpdateCategory
    from nexusai.kernel.module import CommandError
    from nexusai.modules.mail.module import update_category

    ready(ctx)
    sorting.apply(ctx, named("Builds"))
    # Both senders filed in Shopping by their rules, one read and one kept.
    sorting.move_sender(ctx, "kim@else.example", reads=True, folder="Shopping")
    sorting.move_sender(ctx, "ci@tools.example", reads=False, folder="Shopping")

    def sides() -> dict[str, bool]:
        return {
            c.value: r.actions.skip_agent
            for r in rules.load_rules(ctx.config.home)
            for c in r.conditions
            if r.actions.category == "Shopping"
        }

    assert sides() == {"kim@else.example": False, "ci@tools.example": True}
    update_category(UpdateCategory(name="Shopping", ai_reads=False), ctx)
    assert sides() == {"kim@else.example": True, "ci@tools.example": True}
    update_category(UpdateCategory(name="Shopping", ai_reads=True), ctx)
    assert sides() == {"kim@else.example": False, "ci@tools.example": False}
    reads = ctx.bus.db.fetch_all("SELECT ai_reads FROM mail_categories WHERE name = 'Shopping'")
    assert reads[0]["ai_reads"] == 1
    # What's under Automated stays kept.
    with pytest.raises(CommandError):
        update_category(UpdateCategory(name="Automated/Builds", ai_reads=True), ctx)
