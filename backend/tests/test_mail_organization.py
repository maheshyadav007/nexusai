"""Stateful mail organization regressions, independent of a live mailbox or model."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from fake_mail import make_mail
from nexusai.api.app import MODULES
from nexusai.contracts.mail import (
    ListThreads,
    MailRule,
    MarkFolderRead,
    MoveThread,
    RuleActions,
    RuleCondition,
    SaveCategory,
    SetThreadCategory,
    SetThreadFlag,
    SortCategory,
    UpdateCategory,
)
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import MIGRATIONS, EventBus
from nexusai.kernel.home import create_home
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import bulk_learning, mail_agent, signals
from nexusai.modules.mail import accounts, rules, store
from nexusai.modules.mail import module as mail
from nexusai.modules.mail.parse import parse_message


@pytest.fixture
def ctx(config: Config, monkeypatch: pytest.MonkeyPatch) -> Iterator[Context]:
    create_home(config.home)
    db = Database(config.database_path)
    db.migrate([*MIGRATIONS, *(migration for module in MODULES for migration in module.migrations)])
    bus = EventBus(db, config)
    monkeypatch.setattr(accounts, "current_account", lambda _: "test")
    monkeypatch.setattr(signals, "own_addresses", lambda _: {"me@example.com"})
    yield Context(bus=bus, config=config, trace_id="organization-test")
    db.close()


def add(
    ctx: Context,
    subject: str,
    *,
    sender: str = "priya@example.com",
    days: int = 0,
    to: str = "me@example.com",
    match: Any = None,
    reply_to: str | None = None,
) -> store.Stored:
    count = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM messages")[0]["n"] + 1
    raw = make_mail(
        subject=subject,
        sender=sender,
        to=to,
        date=format_datetime(datetime.now(UTC) - timedelta(days=days)),
        message_id=f"<organization-{count}@test>",
        in_reply_to=reply_to,
    )
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
            parsed=parse_message(raw),
            match=match,
            config=ctx.config.mail,
        )
    assert result is not None
    return result


def thread(ctx: Context, identifier: int) -> Any:
    return ctx.bus.db.fetch_all("SELECT * FROM threads WHERE id=?", (identifier,))[0]


def visible(ctx: Context, identifier: int, view: str = "priority") -> bool:
    return bool(
        ctx.bus.db.fetch_all(
            f"SELECT 1 FROM threads WHERE id=? AND {store.FOLDER_FILTERS[view]}", (identifier,)
        )
    )


def test_literal_prefix_and_exact_address_and_multiple_folder_order(ctx: Context) -> None:
    for name in ["PLM", "Builds"]:
        mail.save_category(
            SaveCategory(name=name, mode="exact", subject="[PLM]", in_priority=False), ctx
        )
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE mail_categories SET position=1 WHERE name='Builds'")
        tx.execute("UPDATE mail_categories SET position=2 WHERE name='PLM'")
    parsed = parse_message(make_mail(subject="[PLM] Build 12"))
    match = rules.evaluate(parsed, mail.ordered_rules(ctx))
    assert match and match.actions.category == "Builds" and match.extra_categories == ("PLM",)
    assert match.actions.skip_agent
    assert (
        rules.evaluate(
            parse_message(make_mail(subject="Re: [PLM] Build 12")), mail.ordered_rules(ctx)
        )
        is None
    )
    rule = MailRule(
        name="sender",
        conditions=[RuleCondition(field="sender_exact", value="boss@example.com")],
        actions=RuleActions(category="Boss"),
    )
    assert rules.evaluate(parse_message(make_mail(sender="notboss@example.com")), [rule]) is None


def test_priority_tracks_latest_message_rule_even_with_old_backfill(ctx: Context) -> None:
    mail.save_category(
        SaveCategory(name="PLM", mode="exact", subject="[PLM]", in_priority=False), ctx
    )
    match = rules.evaluate(
        parse_message(make_mail(subject="[PLM] Build 12")), mail.ordered_rules(ctx)
    )
    first = add(ctx, "[PLM] Build 12", days=2, match=match)
    assert not visible(ctx, first.thread)
    reply = add(ctx, "Re: [PLM] Build 12", days=1, reply_to="<organization-1@test>")
    assert reply.thread == first.thread
    assert visible(ctx, first.thread)
    add(ctx, "[PLM] Build 12", match=match, reply_to="<organization-1@test>")
    assert not visible(ctx, first.thread)
    add(ctx, "Re: [PLM] Build 12", days=5, reply_to="<organization-1@test>")
    assert not visible(ctx, first.thread)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET importance='high' WHERE id=?", (first.thread,))
    assert visible(ctx, first.thread) and visible(ctx, first.thread, "important")


def test_priority_includes_extra_folder_and_unfiled_old_low_mail(ctx: Context) -> None:
    first = add(ctx, "Old one", days=100)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET importance='low' WHERE id=?", (first.thread,))
    assert visible(ctx, first.thread)
    mail.save_category(SaveCategory(name="Project", in_priority=True), ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET category='Broadcast',extra_categories='[\"Project\"]',latest_rule='rule' WHERE id=?",
            (first.thread,),
        )
    assert visible(ctx, first.thread)


@pytest.mark.parametrize("target", ["archive", "trash"])
def test_restore_keeps_every_decision_and_survives_refresh(ctx: Context, target: str) -> None:
    first = add(ctx, "Keep my state")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET category='Project',category_source='user',extra_categories='[\"HR\"]',importance='high',status='waiting_on_others',next_action='reply',follow_up_on='2027-01-01',followup_notified='yesterday',importance_user_message=?,status_user_message=?,why='chosen' WHERE id=?",
            (first.message, first.message, first.thread),
        )
    before = dict(thread(ctx, first.thread))
    mail.move_thread(MoveThread(id=first.thread, to=target), ctx)
    assert not thread(ctx, first.thread)["in_inbox"]
    with ctx.bus.db.transaction() as tx:
        store.refresh_thread(tx, first.thread)
    assert not thread(ctx, first.thread)["in_inbox"]
    mail.move_thread(MoveThread(id=first.thread, to="inbox"), ctx)
    after = dict(thread(ctx, first.thread))
    assert before == after
    if target == "trash":
        # never-delete refuses on the server, but local restore needs no network.
        assert (
            ctx.bus.db.fetch_all(
                "SELECT 1 FROM mail_outbox WHERE json_extract(payload,'$.role')='trash'"
            )
            == []
        )


def test_switching_mode_preserves_history_and_prefills_settings(ctx: Context) -> None:
    mail.save_category(SaveCategory(name="PLM", subject="[PLM]", mode="exact"), ctx)
    first = add(ctx, "[PLM] Release")
    mail.set_category(SetThreadCategory(id=first.thread, category="PLM"), ctx)
    mail.update_category(UpdateCategory(name="PLM", mode="smart"), ctx)
    folder = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name='PLM'")[0]
    assert folder["mode"] == "smart" and "[PLM]" in folder["description"]
    assert not mail.ordered_rules(ctx)
    assert thread(ctx, first.thread)["category"] == "PLM"
    mail.update_category(UpdateCategory(name="PLM", mode="exact"), ctx)
    assert mail.ordered_rules(ctx)
    with pytest.raises(CommandError):
        mail.save_category(SaveCategory(name="Empty", mode="exact"), ctx)
    assert ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name='Empty'") == []


def learn_all(ctx: Context, uncertain: bool = False) -> list[str]:
    batches = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches WHERE status!='done'")
    keys = []
    for batch in batches:
        ids = json.loads(batch["groups_json"])
        keys.extend(ids)
        result = bulk_learning.record(
            ctx,
            batch["id"],
            {
                "groups": [
                    {"id": key, "importance": "low", "note": "A sender", "uncertain": uncertain}
                    for key in ids
                ]
            },
            1,
        )
        assert result.startswith("Learned")
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE trigger_runs SET status='done' WHERE event=?",
                (f"{bulk_learning.PREFIX}{batch['id']}",),
            )
    return keys


def test_cached_groups_use_no_further_learning_calls(ctx: Context) -> None:
    add(ctx, "Payslip for October 2026", days=20)
    add(ctx, "Payslip for November 2026", days=10)
    assert bulk_learning.queue(ctx) == 1
    keys = learn_all(ctx)
    bulk_learning.finish_or_ask(ctx)
    add(ctx, "Re: Payslip for December 2026", days=5)
    assert bulk_learning.queue(ctx) == 0
    assert len(ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")) == 1
    assert (
        len(
            ctx.bus.db.fetch_all("SELECT * FROM mail_learning_members WHERE group_id=?", (keys[0],))
        )
        == 3
    )
    add(ctx, "Performance review", sender="hr@example.com", days=10)
    assert bulk_learning.queue(ctx) == 1


def test_learning_is_batched_and_invalid_coverage_is_atomic(ctx: Context) -> None:
    for index in range(65):
        add(ctx, "Monthly report", sender=f"person{index}@example.com", days=10)
    assert bulk_learning.queue(ctx) == 65
    batches = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")
    assert [len(json.loads(batch["groups_json"])) for batch in batches] == [30, 30, 5]
    assert bulk_learning.record(ctx, batches[0]["id"], {"groups": []}, 1).startswith("Incomplete")
    assert not ctx.bus.db.fetch_all("SELECT 1 FROM mail_learning_groups WHERE learned=1")
    run = ctx.bus.db.fetch_all("SELECT * FROM trigger_runs ORDER BY id LIMIT 1")[0]
    for _ in range(3):
        bulk_learning.after_turn(ctx, run, 1, "temporary model failure")
    assert (
        ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (run["id"],))[0][
            "status"
        ]
        == "failed"
    )
    assert bulk_learning.queue(ctx, retry_failed=True) > 0
    assert (
        ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE id=?", (run["id"],))[0][
            "status"
        ]
        == "pending"
    )


def test_interview_precedes_marks_and_only_recent_mail_can_create_work(ctx: Context) -> None:
    old = add(ctx, "Old obligation", days=20)
    recent = add(ctx, "New obligation", days=1)
    bulk_learning.queue(ctx)
    keys = learn_all(ctx, uncertain=True)
    bulk_learning.finish_or_ask(ctx)
    assert bulk_learning.overview(ctx)["state"] == "asking"
    assert thread(ctx, old.thread)["importance"] == "normal"
    assert thread(ctx, recent.thread)["importance"] == "normal"
    bulk_learning.finalize(ctx, {key: "low" for key in keys})
    assert thread(ctx, old.thread)["importance"] == "high"
    live = ctx.bus.db.fetch_all("SELECT * FROM trigger_runs WHERE event LIKE 'bulk-recent-%'")
    assert [row["message"] for row in live] == [recent.message]
    assert ctx.bus.db.fetch_all("SELECT * FROM tasks") == []
    assert ctx.bus.db.fetch_all("SELECT * FROM reminders") == []
    assert bulk_learning.overview(ctx)["missed"] == [
        {"id": old.thread, "subject": "Old obligation"}
    ]


def test_bulk_marks_preserve_person_choices_and_smart_folders_require_acceptance(
    ctx: Context,
) -> None:
    item = add(ctx, "Old project", days=20)
    mail.set_category(SetThreadCategory(id=item.thread, category="Personal"), ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET importance='low',importance_user_message=? WHERE id=?",
            (item.message, item.thread),
        )
    bulk_learning.queue(ctx)
    learn_all(ctx)
    bulk_learning.finish_or_ask(ctx)
    assert thread(ctx, item.thread)["importance"] == "low"
    assert thread(ctx, item.thread)["category"] == "Personal"


def test_triage_only_files_into_existing_smart_folders_and_preserves_exact(ctx: Context) -> None:
    mail.save_category(SaveCategory(name="Project", mode="smart", description="My project"), ctx)
    mail.save_category(
        SaveCategory(name="PLM", mode="exact", subject="[PLM]", in_priority=False), ctx
    )
    matched = rules.evaluate(
        parse_message(make_mail(subject="[PLM] Release")), mail.ordered_rules(ctx)
    )
    item = add(ctx, "[PLM] Release", match=matched)
    mail_agent.Triage(ctx)._apply(
        item.thread,
        [{"message": item.message, "answer": None}],
        "Release",
        {"smart_folders": ["Project", "Made up", "PLM"], "importance": "high"},
        1,
    )
    current = thread(ctx, item.thread)
    assert current["category"] == "PLM"
    assert json.loads(current["extra_categories"]) == ["Project"]
    assert ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name='Made up'") == []
    assert visible(ctx, item.thread)


def test_proposed_folders_and_counts_are_not_created_or_filed_until_accepted(ctx: Context) -> None:
    item = add(ctx, "Project report", days=20)
    bulk_learning.queue(ctx)
    batch = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")[0]
    key = json.loads(batch["groups_json"])[0]
    assert bulk_learning.record(
        ctx,
        batch["id"],
        {
            "groups": [
                {
                    "id": key,
                    "importance": "normal",
                    "uncertain": True,
                    "folder": {"name": "Project", "mode": "smart", "description": "My project"},
                }
            ]
        },
        1,
    ).startswith("Learned")
    folder = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name='Project'")[0]
    assert folder["proposed"] == 1 and folder["in_priority"] == 1
    assert thread(ctx, item.thread)["category"] is None
    assert bulk_learning.overview(ctx)["suggestions"] == [
        {"name": "Project", "senders": 1, "emails": 1}
    ]


def test_account_scoped_group_identity_and_security_header_exception(ctx: Context) -> None:
    assert bulk_learning.group_id(
        "one", "A@EXAMPLE.COM", "Re: Payslip October 2026"
    ) == bulk_learning.group_id("one", "a@example.com", "Payslip November 2026")
    assert bulk_learning.group_id("one", "a@example.com", "Report") != bulk_learning.group_id(
        "two", "a@example.com", "Report"
    )
    raw = make_mail(subject="Suspicious sign-in", sender="no-reply@example.com")
    matched = rules.evaluate(parse_message(raw), [])
    assert matched and matched.look_closer and matched.actions.category == "Updates"
    result = add(ctx, "Suspicious sign-in", sender="no-reply@example.com", match=matched)
    assert result.worth_a_look
    bulk_learning.finalize(ctx)
    assert thread(ctx, result.thread)["importance"] == "high"
    assert ctx.bus.db.fetch_all(
        "SELECT 1 FROM trigger_runs WHERE message=? AND event LIKE 'bulk-recent-%'",
        (result.message,),
    )


def test_broadcast_priority_exception_and_waiting_override(ctx: Context) -> None:
    mail.save_category(SaveCategory(name="Broadcast", mode="smart", in_priority=False), ctx)
    item = add(ctx, "Company news")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET category='Broadcast',category_source='agent',importance='normal',status='fyi' WHERE id=?",
            (item.thread,),
        )
    assert not visible(ctx, item.thread)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET status='waiting_on_you' WHERE id=?", (item.thread,))
    assert visible(ctx, item.thread) and visible(ctx, item.thread, "important")


def test_changing_header_folder_to_smart_or_removing_it_stops_exact_filing(ctx: Context) -> None:
    parsed = parse_message(make_mail(sender="no-reply@example.com"))
    assert rules.evaluate(parsed, [], folder_modes={"Updates": "exact"})
    assert rules.evaluate(parsed, [], folder_modes={"Updates": "smart"}) is None
    assert rules.evaluate(parsed, [], folder_modes={}) is None


def test_mark_recent_cap_and_older_mail_never_adds_work(ctx: Context) -> None:
    for index in range(205):
        add(ctx, f"Review report {index}", days=1)
    bulk_learning.queue(ctx)
    learn_all(ctx)
    bulk_learning.finalize(ctx)
    assert (
        len(ctx.bus.db.fetch_all("SELECT * FROM trigger_runs WHERE event LIKE 'bulk-recent-%'"))
        == 200
    )
    assert ctx.bus.db.fetch_all("SELECT * FROM tasks") == []


def test_manual_unfile_and_unmark_survive_future_judgement(ctx: Context) -> None:
    item = add(ctx, "Manual choice")
    mail.set_category(SetThreadCategory(id=item.thread, category=None), ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET importance='low',importance_user_message=? WHERE id=?",
            (item.message, item.thread),
        )
    mail.save_category(SaveCategory(name="Project", mode="smart"), ctx)
    mail_agent.Triage(ctx)._apply(
        item.thread,
        [{"message": item.message, "answer": None}],
        "Manual choice",
        {"smart_folders": ["Project"], "importance": "high"},
        1,
    )
    assert thread(ctx, item.thread)["category"] is None
    assert thread(ctx, item.thread)["importance"] == "low"


def test_group_answers_reach_judgement_for_later_messages_in_the_same_group(ctx: Context) -> None:
    add(ctx, "Report October 2026", days=20)
    bulk_learning.queue(ctx)
    keys = learn_all(ctx)
    bulk_learning.save_answers(ctx, "test", {keys[0]: "high"})
    later = add(ctx, "Report November 2026", days=1)
    _, _, task = mail_agent.task_for(ctx, later.thread)
    assert "usual importance is high (confirmed by the person)" in task
    assert "Notes from this group remain guesses" in task


def test_older_reply_card_excludes_automatic_rule_filed_mail(ctx: Context) -> None:
    parsed = parse_message(make_mail(subject="Notification", sender="no-reply@example.com"))
    match = rules.evaluate(parsed, [])
    add(ctx, "Notification", sender="no-reply@example.com", days=20, match=match)
    human = add(ctx, "Can you review this?", days=20)
    assert bulk_learning.overview(ctx)["missed"] == [
        {"id": human.thread, "subject": "Can you review this?"}
    ]


def test_legacy_compound_and_disabled_rules_are_never_broadened(ctx: Context) -> None:
    from nexusai.contracts.mail import RuleSet

    mail.save_category(
        SaveCategory(name="Restricted", mode="exact", sender="boss@example.com"), ctx
    )
    for name in ["Special personal rule", "Category: Restricted"]:
        compound = MailRule(
            name=name,
            conditions=[
                RuleCondition(field="sender_exact", value="boss@example.com"),
                RuleCondition(field="body", value="secret"),
            ],
            actions=RuleActions(category="Restricted", skip_agent=True),
        )
        rules.save_rules(ctx.config.home, RuleSet(rules=[compound]))
        ordinary = parse_message(make_mail(sender="boss@example.com", body="An ordinary note"))
        secret = parse_message(make_mail(sender="boss@example.com", body="A secret note"))
        assert rules.evaluate(ordinary, mail.ordered_rules(ctx)) is None
        assert rules.evaluate(secret, mail.ordered_rules(ctx)) is not None
        rules.save_rules(
            ctx.config.home, RuleSet(rules=[compound.model_copy(update={"enabled": False})])
        )
        assert rules.evaluate(secret, mail.ordered_rules(ctx)) is None


def test_starred_survives_archive_and_excludes_trash(ctx: Context) -> None:
    first = add(ctx, "Keep handy")
    assert not visible(ctx, first.thread, "starred")
    mail.set_flag(SetThreadFlag(id=first.thread, flagged=True), ctx)
    assert visible(ctx, first.thread, "starred")
    assert mail.list_threads(ListThreads(folder="starred"), ctx).threads[0].id == first.thread
    mail.move_thread(MoveThread(id=first.thread, to="archive"), ctx)
    assert visible(ctx, first.thread, "starred")
    mail.move_thread(MoveThread(id=first.thread, to="trash"), ctx)
    assert not visible(ctx, first.thread, "starred")
    mail.move_thread(MoveThread(id=first.thread, to="inbox"), ctx)
    assert visible(ctx, first.thread, "starred")
    mail.set_flag(SetThreadFlag(id=first.thread, flagged=False), ctx)
    assert not visible(ctx, first.thread, "starred")


def test_personalized_folder_settings_reach_mail_context(ctx: Context) -> None:
    mail.save_category(
        SaveCategory(
            name="Standards",
            mode="exact",
            subject="[STD]",
            description="Standards discussions I follow",
            in_priority=False,
        ),
        ctx,
    )
    mail.save_category(
        SaveCategory(
            name="Research", mode="smart", description="Only original research on wireless networks"
        ),
        ctx,
    )
    first = add(ctx, "A research question")
    _, _, task = mail_agent.task_for(ctx, first.thread)
    assert "Standards discussions I follow" in task and "[STD]" in task
    assert "Only original research on wireless networks" in task
    assert "do not assign these as Smart folders" in task


def test_default_plm_swarm_are_exact_and_out_of_priority(ctx: Context) -> None:
    from dataclasses import replace

    from nexusai.kernel.config import load_config

    defaults = load_config(ctx.config.home).mail.starter_categories
    seeded = Context(
        bus=ctx.bus,
        config=replace(ctx.config, mail=replace(ctx.config.mail, starter_categories=defaults)),
        trace_id=ctx.trace_id,
    )
    mail._add_starter_categories(seeded)
    mail._organization_defaults(seeded)
    for name, prefix in [("PLM", "[PLM]"), ("Swarm", "[Swarm]")]:
        row = ctx.bus.db.fetch_all("SELECT * FROM mail_categories WHERE name=?", (name,))[0]
        assert row["mode"] == "exact" and not row["in_priority"]
        assert row["subject"] == prefix
        home_rules = mail.ordered_rules(seeded)
        assert rules.evaluate(parse_message(make_mail(subject=prefix + " agenda")), home_rules)
        assert not rules.evaluate(
            parse_message(make_mail(subject="Re: " + prefix + " agenda")), home_rules
        )


def test_mark_folder_read_scopes_extra_categories_and_is_retry_safe(ctx: Context) -> None:
    first = add(ctx, "Matching")
    other = add(ctx, "Leave unread")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET extra_categories='[\"Project\"]' WHERE id=?", (first.thread,)
        )
    mail.mark_folder_read(MarkFolderRead(category="Project"), ctx)
    assert (
        not thread(ctx, first.thread)["unread_count"] and thread(ctx, other.thread)["unread_count"]
    )
    queued = len(ctx.bus.db.fetch_all("SELECT * FROM mail_outbox"))
    mail.mark_folder_read(MarkFolderRead(category="Project"), ctx)
    assert len(ctx.bus.db.fetch_all("SELECT * FROM mail_outbox")) == queued
    mail.mark_folder_read(MarkFolderRead(location="Missing"), ctx)
    assert thread(ctx, other.thread)["unread_count"]
    mail.mark_folder_read(MarkFolderRead(location="INBOX"), ctx)
    assert not thread(ctx, other.thread)["unread_count"]


def test_mark_folder_read_handles_more_than_one_page_and_respects_view(ctx: Context) -> None:
    for i in range(105):
        add(ctx, f"Inbox {i}")
    archived = add(ctx, "Archived unread")
    mail.move_thread(MoveThread(id=archived.thread, to="archive"), ctx)
    mail.mark_folder_read(MarkFolderRead(folder="priority"), ctx)
    assert (
        ctx.bus.db.fetch_all(
            "SELECT COUNT(*) AS n FROM threads WHERE in_inbox=1 AND unread_count>0"
        )[0]["n"]
        == 0
    )
    assert thread(ctx, archived.thread)["unread_count"]


def test_mark_folder_read_can_resume_after_partial_failure(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = add(ctx, "First")
    second = add(ctx, "Second")
    original = mail.set_read

    def interrupted(command: Any, context: Context) -> Any:
        if command.id == second.thread:
            raise RuntimeError("Interrupted")
        return original(command, context)

    monkeypatch.setattr(mail, "set_read", interrupted)
    with pytest.raises(RuntimeError, match="Interrupted"):
        mail.mark_folder_read(MarkFolderRead(folder="all"), ctx)
    assert not thread(ctx, first.thread)["unread_count"]
    assert thread(ctx, second.thread)["unread_count"]
    monkeypatch.setattr(mail, "set_read", original)
    mail.mark_folder_read(MarkFolderRead(folder="all"), ctx)
    assert not thread(ctx, second.thread)["unread_count"]


def test_exact_historical_sort_requires_confirmation_and_preserves_user_filing(
    ctx: Context,
) -> None:
    mail.save_category(SaveCategory(name="History", subject="[HIST]", mode="exact"), ctx)
    first = add(ctx, "[HIST] Old discussion")
    chosen = add(ctx, "[HIST] Personal choice")
    mail.set_category(SetThreadCategory(id=chosen.thread, category=None), ctx)
    estimate = mail.sort_category(SortCategory(name="History", confirm=False), ctx)
    assert estimate.estimated_tokens == 0
    assert thread(ctx, first.thread)["category"] is None
    result = mail.sort_category(SortCategory(name="History", confirm=True), ctx)
    assert result.queued == 1
    assert thread(ctx, first.thread)["category"] == "History"
    assert thread(ctx, chosen.thread)["category"] is None
