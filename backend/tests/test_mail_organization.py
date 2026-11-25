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
    GetNamedYou,
    ListThreads,
    MailMe,
    MailRule,
    MarkFolderRead,
    MoveThread,
    NotAboutMe,
    PreviewMe,
    RuleActions,
    RuleCondition,
    SaveCategory,
    SetThreadCategory,
    SetThreadFlag,
    SortCategory,
    UpdateCategory,
)
from nexusai.contracts.settings import UpdateSettings
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import MIGRATIONS, EventBus
from nexusai.kernel.home import create_home
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import bulk_learning, mail_agent, signals
from nexusai.modules.mail import accounts, mentions, rules, store
from nexusai.modules.mail import module as mail
from nexusai.modules.mail.parse import parse_message
from nexusai.modules.settings.module import update_settings


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
            decision=rules.decision_for(match, parse_message(raw)),
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
    # One folder per email, the first in order; in the Inbox a rule files it and the AI reads it.
    assert match and match.actions.category == "Builds" and match.extra_categories == ()
    assert not match.actions.skip_agent
    mail.update_category(UpdateCategory(name="Builds", ai_reads=False), ctx)
    kept = rules.evaluate(parsed, mail.ordered_rules(ctx))
    assert kept and kept.actions.category == "Builds" and kept.actions.skip_agent
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


def choose(ctx: Context, *shows: str) -> None:
    update_settings(UpdateSettings.model_validate({"priority_shows": list(shows)}), ctx)


def test_priority_shows_only_what_is_chosen(ctx: Context) -> None:
    first = add(ctx, "Plain")
    # By default: waiting on you or on others, or important. Plain mail stays out.
    assert not visible(ctx, first.thread)
    choose(ctx, "unfiled")
    assert visible(ctx, first.thread)
    choose(ctx, "important")
    assert not visible(ctx, first.thread)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET importance='high' WHERE id=?", (first.thread,))
    assert visible(ctx, first.thread)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET importance='normal', status='waiting_on_others' WHERE id=?",
            (first.thread,),
        )
    assert not visible(ctx, first.thread)
    choose(ctx, "waiting_on_others")
    assert visible(ctx, first.thread)
    # A folder set to Show in Priority counts only when folders are chosen.
    mail.save_category(SaveCategory(name="Project", in_priority=True), ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET status='none', category='Broadcast',"
            " extra_categories='[\"Project\"]' WHERE id=?",
            (first.thread,),
        )
    assert not visible(ctx, first.thread)
    choose(ctx, "folders")
    assert visible(ctx, first.thread)


def test_priority_leaves_out_a_closed_matter_even_when_important(ctx: Context) -> None:
    first = add(ctx, "Decided")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET importance='high', status='resolved' WHERE id=?", (first.thread,)
        )
    assert visible(ctx, first.thread)
    now = datetime.now(UTC).isoformat()
    with ctx.bus.db.transaction() as tx:
        matter = tx.execute(
            "INSERT INTO matters (account, title, created, updated) VALUES ('test', 'Decision', ?, ?)",
            (now, now),
        ).lastrowid
        tx.execute(
            "INSERT INTO matter_threads (thread, matter, how, why, linked) VALUES (?, ?, 'test', '', ?)",
            (first.thread, matter, now),
        )
    # Nothing in it is open, so the matter is closed and its mail leaves Priority.
    assert not visible(ctx, first.thread)
    # A kept task still to do keeps it open.
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO tasks (title, status, source, created, matter) VALUES ('Send it', 'open', 'test', ?, ?)",
            (now, matter),
        )
    assert visible(ctx, first.thread)
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE tasks SET status='done'")
        tx.execute("UPDATE threads SET status='waiting_on_you' WHERE id=?", (first.thread,))
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


def test_learning_is_batched_and_missing_coverage_is_asked_again(ctx: Context) -> None:
    for index in range(65):
        add(ctx, "Monthly report", sender=f"person{index}@example.com", days=10)
    assert bulk_learning.queue(ctx) == 65
    batches = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")
    assert [len(json.loads(batch["groups_json"])) for batch in batches] == [30, 30, 5]
    assert bulk_learning.record(ctx, batches[0]["id"], {"groups": []}, 1).startswith(
        "Saved 0 groups. Still missing: g1, g2,"
    )
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
    bulk_learning.finalize(ctx, {key: "normal" for key in keys})
    assert thread(ctx, old.thread)["importance"] == "high"
    live = ctx.bus.db.fetch_all("SELECT * FROM trigger_runs WHERE event LIKE 'bulk-recent-%'")
    assert [row["message"] for row in live] == [recent.message]
    assert ctx.bus.db.fetch_all("SELECT * FROM tasks") == []
    assert ctx.bus.db.fetch_all("SELECT * FROM reminders") == []
    assert bulk_learning.overview(ctx)["missed"] == [
        {"id": old.thread, "subject": "Old obligation"}
    ]


def test_once_sorted_unsure_groups_keep_their_guesses_without_asking(ctx: Context) -> None:
    """Sorting already chose what the AI reads, so nobody is asked to rate each unsure group."""
    from nexusai.modules.mail import sorting

    add(ctx, "New obligation", days=1)
    sorting._decide(ctx, "done")
    bulk_learning.queue(ctx)
    learn_all(ctx, uncertain=True)
    bulk_learning.finish_or_ask(ctx)
    assert bulk_learning.overview(ctx)["state"] == "done"


def test_promotions_and_confirmed_low_mail_are_not_raised_by_guesses(ctx: Context) -> None:
    """Regression: "valid by 30 Nov" or "expires" used to raise promotions to high."""
    sale = add(
        ctx,
        "Your offer expires tonight",
        sender="deals@shop.example",
        days=3,
        match=rules.RuleMatch(
            "Marketing or bulk mail", rules.RuleActions(category="Promotions", skip_agent=True)
        ),
    )
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE messages SET clean_text='Offer valid by 30 Nov. Hurry!' WHERE id=?",
            (sale.message,),
        )
    vendor = add(ctx, "Weekly digest", sender="news@vendor.example", days=3)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE messages SET clean_text='Register by 30 Nov for the webinar' WHERE id=?",
            (vendor.message,),
        )
    alert = add(ctx, "Security alert: new sign-in", sender="alerts@bank.example", days=3)
    bulk_learning.queue(ctx)
    keys = learn_all(ctx, uncertain=True)
    groups = {
        row["sender"]: row["id"]
        for row in ctx.bus.db.fetch_all("SELECT id,sender FROM mail_learning_groups")
    }
    vendor_group, alert_group = groups["news@vendor.example"], groups["alerts@bank.example"]
    bulk_learning.finalize(ctx, {vendor_group: "low", alert_group: "low"})
    assert vendor_group in keys and alert_group in keys
    assert thread(ctx, sale.thread)["importance"] != "high"
    # The person said low, so a deadline in the body doesn't overrule them...
    assert thread(ctx, vendor.thread)["importance"] == "low"
    # ...but a subject that says act still surfaces.
    assert thread(ctx, alert.thread)["importance"] == "high"


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


def test_triage_adds_no_folders_to_mail_a_visible_rule_filed(ctx: Context) -> None:
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
    # The [PLM] rule decides alone: no smart folder beside it, and nothing made up.
    assert json.loads(current["extra_categories"]) == []
    assert ctx.bus.db.fetch_all("SELECT 1 FROM mail_categories WHERE name='Made up'") == []
    assert visible(ctx, item.thread)


def test_agent_files_missed_promotions_and_broadcast_only_fills_a_gap(ctx: Context) -> None:
    """Regression: marketing without unsubscribe headers could only land in Broadcast."""
    mail.save_category(SaveCategory(name="Broadcast", mode="smart", in_priority=False), ctx)
    with ctx.bus.db.transaction() as tx:
        for name in ("Promotions", "Updates"):
            tx.execute(
                "INSERT OR IGNORE INTO mail_categories(name,source,mode,description,created) VALUES(?,'rule','exact',?,?)",
                (name, name, "2026-01-01"),
            )
    many = ", ".join(f"person{index}@example.com" for index in range(12))
    task = mail_agent.task_for(ctx, add(ctx, "Big sale", to=many).thread)[2]
    assert '"name": "Promotions"' in task and '"name": "Updates"' in task
    for chosen, expected in ((["Promotions"], "Promotions"), ([], "Broadcast")):
        item = add(ctx, f"Mass mail {expected}", to=many)
        mail_agent.Triage(ctx)._apply(
            item.thread,
            [{"message": item.message, "answer": None}],
            "Mass mail",
            {"smart_folders": chosen, "importance": "low"},
            1,
        )
        assert thread(ctx, item.thread)["category"] == expected


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


def test_account_scoped_group_identity_and_no_exception_for_kept_mail(ctx: Context) -> None:
    assert bulk_learning.group_id(
        "one", "A@EXAMPLE.COM", "Re: Payslip October 2026"
    ) == bulk_learning.group_id("one", "a@example.com", "Payslip November 2026")
    assert bulk_learning.group_id("one", "a@example.com", "Report") != bulk_learning.group_id(
        "two", "a@example.com", "Report"
    )
    raw = make_mail(subject="Suspicious sign-in", sender="no-reply@example.com")
    matched = rules.evaluate(parse_message(raw), [])
    assert matched and matched.actions.category == "Automated"
    # Filed where the AI doesn't read, so the AI never sees it, whatever its subject says.
    result = add(ctx, "Suspicious sign-in", sender="no-reply@example.com", match=matched)
    assert result.skip_agent
    bulk_learning.finalize(ctx)
    assert not ctx.bus.db.fetch_all(
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
    assert rules.evaluate(parsed, [], folder_modes={"Automated": "exact"})
    assert rules.evaluate(parsed, [], folder_modes={"Automated": "smart"}) is None
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
    assert "never assign these as Smart folders" in task


def test_no_starter_categories_ship(ctx: Context) -> None:
    from nexusai.kernel.config import load_config

    assert load_config(ctx.config.home).mail.starter_categories == ()


def test_starter_categories_are_exact_and_out_of_priority(ctx: Context) -> None:
    from dataclasses import replace

    defaults = (
        {"name": "PLM", "subject_prefix": "[PLM]"},
        {"name": "Swarm", "subject_prefix": "[Swarm]"},
    )
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
    mail.mark_folder_read(MarkFolderRead(folder="reads"), ctx)
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


def test_only_a_newer_reply_moves_waiting_on_others_back_to_the_person(ctx: Context) -> None:
    """Regression: a late event for an older message undid the person's own status choice."""
    first = add(ctx, "Quote", days=2)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET status='waiting_on_others',status_user_message=? WHERE id=?",
            (first.message, first.thread),
        )
    mail_agent.they_answered(ctx, first.message, first.thread)
    assert thread(ctx, first.thread)["status"] == "waiting_on_others"
    reply = add(ctx, "Re: Quote", days=1, reply_to="<organization-1@test>")
    assert reply.thread == first.thread
    mail_agent.they_answered(ctx, reply.message, reply.thread)
    assert thread(ctx, first.thread)["status"] == "waiting_on_you"


def test_the_folder_is_checked_again_just_before_the_ai_judges(ctx: Context) -> None:
    waiting = add(ctx, "Can you review this?")
    assert not waiting.skip_agent
    mail_agent.enqueue(ctx, waiting.message, waiting.thread)
    # Filed where the AI doesn't read after it was queued: it's never shown to the AI.
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET category='Automated', category_source='user' WHERE id=?",
            (waiting.thread,),
        )
    assert mail_agent.next_turn(ctx, "mail") is None
    run = ctx.bus.db.fetch_all("SELECT status FROM trigger_runs WHERE thread=?", (waiting.thread,))[
        0
    ]
    assert run["status"] == "skipped"


def test_learning_and_counts_leave_out_what_a_folder_keeps_from_the_ai(ctx: Context) -> None:
    read = add(ctx, "Quarterly plan", sender="lee@example.com")
    kept = add(ctx, "Weekly digest", sender="digest@example.com")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET category='Automated', category_source='user' WHERE id=?",
            (kept.thread,),
        )
    assert mail_agent.unjudged_count(ctx) == 1
    bulk_learning.queue(ctx)
    members = {
        row["thread"] for row in ctx.bus.db.fetch_all("SELECT thread FROM mail_learning_members")
    }
    assert read.thread in members and kept.thread not in members
    assert signals.hidden_threads(ctx, [read.thread, kept.thread]) == {kept.thread}


def test_a_reply_that_names_the_person_stays_in_its_folder_and_the_ai_reads_it(
    ctx: Context,
) -> None:
    plm = MailRule(
        name="PLM",
        conditions=[RuleCondition(field="tag", value="PLM")],
        actions=RuleActions(category="Automated", skip_agent=True),
    )
    mentions.save(ctx.config.home, MailMe(names=["Mahesh"], addresses=["me@example.com"]))
    engine = rules.Engine([plm], me=mail.who_am_i(ctx))
    first = add(
        ctx,
        "[PLM] ECO-1112 assigned",
        sender="plm-noreply@corp.example",
        match=rules.RuleMatch(plm.name, plm.actions),
    )
    assert thread(ctx, first.thread)["category"] == "Automated" and first.skip_agent
    count = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM messages")[0]["n"] + 1
    raw = make_mail(
        subject="RE: [PLM] ECO-1112 assigned",
        sender="Rahul Menon <rahul@corp.example>",
        body="@Mahesh please check the BOM.",
        message_id=f"<organization-{count}@test>",
        in_reply_to="<organization-1@test>",
    )
    decision = engine.decide([parse_message(raw)])[0]
    with ctx.bus.db.transaction() as tx:
        named = store.store_message(
            tx, account="test", folder="INBOX", role="inbox", uid=count, raw=raw, read=False,
            flagged=False, parsed=parse_message(raw), decision=decision, config=ctx.config.mail,
        )  # fmt: skip
    assert named is not None and named.thread == first.thread and not named.skip_agent
    row = thread(ctx, first.thread)
    # Still filed where it was, and still listed under Kept from the AI, but the AI may read it.
    assert row["category"] == "Automated" and visible(ctx, first.thread, "kept")
    assert row["named"] == "Rahul Menon: @Mahesh please check the BOM."
    assert signals.hidden_threads(ctx, [first.thread]) == set()
    assert mail.named_you(GetNamedYou(), ctx).items[0].quote == "@Mahesh please check the BOM."
    mail_agent.enqueue(ctx, named.message, named.thread)
    assert mail_agent.next_turn(ctx, "mail") is not None

    # It wasn't about them: hidden again, and that name stops counting.
    me = mail.not_about_me(NotAboutMe(thread=first.thread, stop="Mahesh"), ctx)
    assert me.names == [] and thread(ctx, first.thread)["named"] is None
    assert signals.hidden_threads(ctx, [first.thread]) == {first.thread}


def test_a_team_name_added_after_sorting_lets_its_hidden_replies_reach_the_ai(
    ctx: Context,
) -> None:
    plm = MailRule(
        name="PLM",
        conditions=[RuleCondition(field="tag", value="PLM")],
        actions=RuleActions(category="Automated", skip_agent=True),
    )
    mentions.save(ctx.config.home, MailMe(names=["Mahesh"], addresses=["me@example.com"]))
    engine = rules.Engine([plm], me=mail.who_am_i(ctx))

    def stored(subject: str, sender: str, body: str, reply_to: str | None = None) -> int:
        count = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM messages")[0]["n"] + 1
        raw = make_mail(
            subject=subject, sender=sender, body=body,
            message_id=f"<organization-{count}@test>", in_reply_to=reply_to,
        )  # fmt: skip
        with ctx.bus.db.transaction() as tx:
            done = store.store_message(
                tx, account="test", folder="INBOX", role="inbox", uid=count, raw=raw, read=False,
                flagged=False, parsed=parse_message(raw), decision=engine.decide([parse_message(raw)])[0],
                config=ctx.config.mail,
            )  # fmt: skip
        assert done is not None
        return done.thread

    first = stored("[PLM] ECO-1200 assigned", "plm-noreply@corp.example", "Assigned to PLM team.")
    reply = stored(
        "RE: [PLM] ECO-1200 assigned",
        "Rahul Menon <rahul@corp.example>",
        "Can the PLM team check the BOM?",
        "<organization-1@test>",
    )
    assert reply == first and signals.hidden_threads(ctx, [first]) == {first}

    # Tried before saving: the person's reply counts for the team, the tool's own mail doesn't.
    seen = mail.preview_me(PreviewMe(names=["Mahesh", "PLM team"]), ctx)
    assert seen.counts == {"Mahesh": 0, "PLM team": 1} and seen.total == 1
    assert [(e.sender, e.word) for e in seen.examples] == [("Rahul Menon", "PLM team")]
    assert "PLM team" in seen.examples[0].quote

    # Saved, the reply already there reaches the AI; taken away, it's hidden again.
    mail.save_me(MailMe(names=["Mahesh", "PLM team"], addresses=["me@example.com"]), ctx)
    assert thread(ctx, first)["named"] == "Rahul Menon: Can the PLM team check the BOM?"
    assert signals.hidden_threads(ctx, [first]) == set()
    mail.save_me(MailMe(names=["Mahesh"], addresses=["me@example.com"]), ctx)
    assert thread(ctx, first)["named"] is None
    assert signals.hidden_threads(ctx, [first]) == {first}


def sent(ctx: Context, subject: str, *, days: int = 0, reply_to: str | None = None) -> store.Stored:
    """A copy of mail the person sent, as Sent brings it in."""
    count = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM messages")[0]["n"] + 1
    raw = make_mail(
        subject=subject,
        sender="me@example.com",
        to="priya@example.com",
        date=format_datetime(datetime.now(UTC) - timedelta(days=days)),
        message_id=f"<organization-{count}@test>",
        in_reply_to=reply_to,
    )
    with ctx.bus.db.transaction() as tx:
        result = store.store_message(
            tx,
            account="test",
            folder="Sent",
            role="sent",
            uid=count,
            raw=raw,
            read=True,
            flagged=False,
            parsed=parse_message(raw),
            decision=rules.decision_for(None, parse_message(raw)),
            config=ctx.config.mail,
        )
    assert result is not None
    return result


def ask(ctx: Context, thread_id: int, days: float) -> int:
    with ctx.bus.db.transaction() as tx:
        return int(
            tx.execute(
                "INSERT INTO channel_messages (kind, agent, thread, text, time) VALUES"
                " ('ask', 'mail', ?, 'Reply to Priya?', ?)",
                (thread_id, (datetime.now(UTC) - timedelta(days=days)).isoformat()),
            ).lastrowid
            or 0
        )


def ask_status(ctx: Context, identifier: int) -> str:
    rows = ctx.bus.db.fetch_all("SELECT status FROM channel_messages WHERE id=?", (identifier,))
    return str(rows[0]["status"])


def test_writing_back_waits_on_them_and_answers_the_question(ctx: Context) -> None:
    first = add(ctx, "Quote", days=2)
    question = ask(ctx, first.thread, days=1.5)
    reply = sent(ctx, "Re: Quote", days=1, reply_to="<organization-1@test>")
    assert reply.thread == first.thread
    assert mail_agent.person_replied(ctx, reply.message, reply.thread)
    assert thread(ctx, first.thread)["status"] == "waiting_on_others"
    assert ask_status(ctx, question) == "dismissed"


def test_a_sent_copy_synced_after_the_answer_leaves_the_answer_waiting(ctx: Context) -> None:
    """Sent can come down after Inbox, so the answer to a reply is stored before the reply."""
    first = add(ctx, "Quote", days=3)
    answer = add(ctx, "Re: Quote", days=1, reply_to="<organization-1@test>")
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET status='waiting_on_you' WHERE id=?", (first.thread,))
    question = ask(ctx, first.thread, days=0)
    reply = sent(ctx, "Re: Quote", days=2, reply_to="<organization-1@test>")
    assert reply.thread == answer.thread == first.thread
    assert not mail_agent.person_replied(ctx, reply.message, reply.thread)
    assert thread(ctx, first.thread)["status"] == "waiting_on_you"
    assert ask_status(ctx, question) == "open"


def test_a_status_chosen_after_writing_back_stays(ctx: Context) -> None:
    first = add(ctx, "Quote", days=2)
    reply = sent(ctx, "Re: Quote", days=1, reply_to="<organization-1@test>")
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE threads SET status='waiting_on_you', status_user_message=? WHERE id=?",
            (reply.message, first.thread),
        )
    mail_agent.person_replied(ctx, reply.message, reply.thread)
    assert thread(ctx, first.thread)["status"] == "waiting_on_you"


def failed_send(ctx: Context, thread_id: int | None, *, kept: bool = True, error: str = "") -> int:
    """A send whose handling failed while mail.sent was announced without its message."""
    seq = 0
    if kept:
        with ctx.bus.unit_of_work() as work:
            work.emit("mail.sent", {"thread_id": thread_id}, source="mail")
        seq = ctx.bus.latest_seq()
    with ctx.bus.db.transaction() as tx:
        return int(
            tx.execute(
                "INSERT INTO failed_events (listener, event_seq, event_type, error, time)"
                " VALUES ('agent.person_replied', ?, 'mail.sent', ?, ?)",
                (seq, error or mail_agent.UNANNOUNCED_SEND, datetime.now(UTC).isoformat()),
            ).lastrowid
            or 0
        )


def failed_ids(ctx: Context) -> set[int]:
    return {row["id"] for row in ctx.bus.db.fetch_all("SELECT id FROM failed_events")}


def test_sends_that_failed_before_are_handled_at_start(ctx: Context) -> None:
    reply_to = add(ctx, "Quote", days=1)
    reply = sent(ctx, "Re: Quote", reply_to="<organization-1@test>")
    new = sent(ctx, "Kickoff")
    other = failed_send(ctx, reply.thread, error="'thread_id'")
    failed_send(ctx, reply.thread)
    # A new email had no conversation yet, and this event has since been cleaned up.
    failed_send(ctx, None, kept=False)
    mail_agent.repair_failed_sends(ctx)
    assert thread(ctx, reply_to.thread)["status"] == "waiting_on_others"
    assert thread(ctx, new.thread)["status"] == "waiting_on_others"
    # Only the failure this repairs is cleared.
    assert failed_ids(ctx) == {other}
    observed = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM interaction_events WHERE action='sent'"
    )
    assert observed[0]["n"] == 2
    # Run again, nothing is handled twice.
    failed_send(ctx, reply.thread)
    mail_agent.repair_failed_sends(ctx)
    observed = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM interaction_events WHERE action='sent'"
    )
    assert observed[0]["n"] == 2
    assert failed_ids(ctx) == {other}


def test_a_repair_that_fails_leaves_that_failure_and_carries_on(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = sent(ctx, "First")
    second = sent(ctx, "Second")
    broken = failed_send(ctx, first.thread)
    failed_send(ctx, second.thread)
    original = mail_agent.handle_sent

    def handle(ctx: Context, message: int, thread_id: int, event_id: str | None) -> bool:
        if thread_id == first.thread:
            raise RuntimeError("Disk full")
        return original(ctx, message, thread_id, event_id)

    monkeypatch.setattr(mail_agent, "handle_sent", handle)
    mail_agent.repair_failed_sends(ctx)
    assert failed_ids(ctx) == {broken}
    assert thread(ctx, second.thread)["status"] == "waiting_on_others"


def test_a_repair_that_cannot_read_failures_starts_anyway(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any) -> Any:
        raise RuntimeError("Locked")

    monkeypatch.setattr(ctx.bus.db, "fetch_all", refuse)
    assert mail_agent.repair_failed_sends(ctx) == 0
