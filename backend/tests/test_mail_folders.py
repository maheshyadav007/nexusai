"""Folders as one tree: the promises made for it, each checked on made-up mail."""

from typing import Any

import pytest

from nexusai.contracts.mail import (
    CategoryName,
    FolderSplit,
    MailRule,
    MarkFolderRead,
    RuleActions,
    RuleCondition,
    SaveCategory,
    SplitFolders,
    UpdateCategory,
)
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import folders, rules, sorting, store
from nexusai.modules.mail import module as mail
from test_mail_organization import ctx  # noqa: F401
from test_mail_sorting import stored as stored_by


def stored(ctx: Context, subject: str, sender: str, body: str = "Done.\nCI") -> store.Stored:  # noqa: F811
    """Stored the way new mail is, through every rule, the folders' own included."""
    engine = mail.rule_engine(ctx, None)
    original = rules.Engine
    rules.Engine = lambda *_: engine  # type: ignore[assignment,misc]
    try:
        return stored_by(ctx, subject, sender, body)
    finally:
        rules.Engine = original  # type: ignore[misc]


def thread_of(ctx: Context, result: store.Stored) -> Any:  # noqa: F811
    return ctx.bus.db.fetch_all("SELECT * FROM threads WHERE id = ?", (result.thread,))[0]


def listed(ctx: Context, name: str) -> set[int]:  # noqa: F811
    found = store.list_threads(ctx.bus.db, "test", "all", name, None, 100)
    return {row.id for row in found.threads}


def in_view(ctx: Context, view: str) -> set[int]:  # noqa: F811
    found = store.list_threads(ctx.bus.db, "test", view, None, None, 100)
    return {row.id for row in found.threads}


def folder(ctx: Context, name: str) -> Any:  # noqa: F811
    row = folders.find(ctx.bus.db, name)
    assert row is not None
    return row


def by_sender(name: str, sender: str, reads: bool = True) -> SaveCategory:
    return SaveCategory(
        name=name,
        mode="exact",
        conditions=[RuleCondition(field="sender_exact", value=sender)],
        ai_reads=reads,
        in_priority=False,
    )


def test_a_parent_shows_its_own_mail_and_everything_under_it(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Projects", "lead@work.example"), ctx)
    mail.save_category(
        by_sender("Alpha", "alpha@work.example").model_copy(update={"parent": "Projects"}), ctx
    )
    mail.save_category(
        by_sender("Deep", "deep@work.example").model_copy(update={"parent": "Alpha"}), ctx
    )
    own = stored(ctx, "Plan", "lead@work.example", "Here.")
    child = stored(ctx, "Alpha", "alpha@work.example", "Here.")
    grandchild = stored(ctx, "Deep", "deep@work.example", "Here.")
    assert listed(ctx, "Projects") == {own.thread, child.thread, grandchild.thread}
    assert listed(ctx, "Alpha") == {child.thread, grandchild.thread}
    assert listed(ctx, "Deep") == {grandchild.thread}
    # Counted the same as what opens, and marked read the same way.
    assert store.list_threads(ctx.bus.db, "test", "all", "Projects", None, 100).total == 3
    mail.mark_folder_read(MarkFolderRead(folder="all", category="Alpha"), ctx)
    unread = {
        row["id"] for row in ctx.bus.db.fetch_all("SELECT id FROM threads WHERE unread_count > 0")
    }
    assert unread == {own.thread}
    # Each email still says which folder it's in.
    assert thread_of(ctx, grandchild)["category"] == "Deep"


def test_the_two_homes_hold_each_side_and_nothing_archived(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Friends", "kim@else.example"), ctx)
    mail.save_category(by_sender("Tools", "ci@tools.example", reads=False), ctx)
    read = stored(ctx, "Dinner", "kim@else.example", "Come over?")
    kept = stored(ctx, "Build passed", "ci@tools.example")
    loose = stored(ctx, "Hello", "ann@new.example", "Are you free?")
    assert thread_of(ctx, kept)["category"] == "Tools" and kept.skip_agent
    assert not read.skip_agent
    assert in_view(ctx, "reads") == {read.thread, loose.thread}
    assert in_view(ctx, "kept") == {kept.thread}
    # The catch-all of Kept from the AI is there too, though it's never listed.
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET category = 'Automated' WHERE id = ?", (loose.thread,))
    assert in_view(ctx, "kept") == {kept.thread, loose.thread}
    with ctx.bus.db.transaction() as tx:
        tx.execute("UPDATE threads SET in_inbox = 0, in_archive = 1 WHERE id = ?", (kept.thread,))
    assert in_view(ctx, "kept") == {loose.thread}
    counts = store.unread_counts(ctx.bus.db, "test")
    assert counts["reads"] == 1 and counts["kept"] == 1


def test_names_are_unique_anywhere_whatever_their_case(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Invoices", "bills@shop.example"), ctx)
    mail.save_category(by_sender("Projects", "lead@work.example"), ctx)
    mail.save_category(
        by_sender("Alpha", "alpha@work.example").model_copy(update={"parent": "Projects"}), ctx
    )
    with pytest.raises(CommandError, match="already a folder called Alpha, under Projects"):
        mail.save_category(by_sender("alpha", "other@work.example"), ctx)
    with pytest.raises(CommandError, match="already a folder called Invoices, in Inbox"):
        mail.update_category(UpdateCategory(name="Alpha", new_name="INVOICES"), ctx)
    with pytest.raises(CommandError, match="already a part of your mail"):
        mail.save_category(by_sender("Kept from the AI", "x@y.example"), ctx)
    with pytest.raises(CommandError):
        mail.save_category(by_sender("A/B", "x@y.example"), ctx)
    # Sorting a sender into a new folder on the Sort page goes through the same check.
    sorting.move_sender(ctx, "z@tools.example", reads=True, folder="Bills")
    with pytest.raises(CommandError, match="already a folder called Bills"):
        mail.save_category(by_sender("BILLS", "q@y.example"), ctx)
    # A sender put in a folder by another spelling joins that folder.
    sorting.move_sender(ctx, "w@tools.example", reads=True, folder="bills")
    assert mail.sender_sides(ctx)["Bills"] == {"z@tools.example": False, "w@tools.example": False}
    # Its own name in another case is a rename, not a clash.
    mail.update_category(UpdateCategory(name="Invoices", new_name="invoices"), ctx)
    assert folder(ctx, "INVOICES")["name"] == "invoices"


def test_renaming_changes_only_the_name(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Projects", "lead@work.example"), ctx)
    mail.save_category(
        by_sender("Alpha", "alpha@work.example").model_copy(update={"parent": "Projects"}), ctx
    )
    filed = stored(ctx, "Alpha", "alpha@work.example", "Here.")
    mail.update_category(UpdateCategory(name="Projects", new_name="Work"), ctx)
    assert folder(ctx, "Alpha")["parent"] == "Work"
    assert listed(ctx, "Work") == {filed.thread}
    assert thread_of(ctx, filed)["category"] == "Alpha"
    mail.update_category(UpdateCategory(name="Alpha", new_name="Bosch"), ctx)
    assert thread_of(ctx, filed)["category"] == "Bosch"
    (rule,) = [r for r in rules.load_rules(ctx.config.home) if r.actions.category == "Bosch"]
    assert rule.name == mail.CATEGORY_RULE_PREFIX + "Bosch"
    # What the rule marked on each email follows it, so nothing reads as filed by a lost rule.
    assert thread_of(ctx, filed)["latest_rule"] == rule.name
    later = stored(ctx, "Alpha again", "alpha@work.example", "Here.")
    assert thread_of(ctx, later)["category"] == "Bosch"


def test_moving_changes_only_the_parent_and_takes_its_new_side(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Projects", "lead@work.example"), ctx)
    mail.save_category(
        by_sender("Alpha", "alpha@work.example").model_copy(update={"parent": "Projects"}), ctx
    )
    mail.save_category(by_sender("Noise", "bot@tools.example", reads=False), ctx)
    sorting.move_sender(ctx, "ping@tools.example", reads=True, folder="Alpha")
    filed = stored(ctx, "Alpha", "alpha@work.example", "Here.")
    # Into a folder kept from the AI: the folder, everything in it and its senders go with it.
    mail.update_category(UpdateCategory(name="Projects", parent="Noise"), ctx)
    assert (folder(ctx, "Projects")["parent"], folder(ctx, "Projects")["ai_reads"]) == ("Noise", 0)
    assert folder(ctx, "Alpha")["ai_reads"] == 0
    assert thread_of(ctx, filed)["category"] == "Alpha"
    sides = mail.sender_sides(ctx)
    assert sides["Alpha"] == {"alpha@work.example": True, "ping@tools.example": True}
    assert stored(ctx, "Alpha later", "alpha@work.example", "Here.").skip_agent
    # Back to the top of the Inbox.
    mail.update_category(UpdateCategory(name="Projects", parent="", ai_reads=True), ctx)
    assert (folder(ctx, "Projects")["parent"], folder(ctx, "Alpha")["ai_reads"]) == (None, 1)
    assert not stored(ctx, "Alpha last", "alpha@work.example", "Here.").skip_agent
    # A folder can't go inside itself or one of its own.
    with pytest.raises(CommandError, match="inside itself"):
        mail.update_category(UpdateCategory(name="Projects", parent="Alpha"), ctx)
    # Inside another, a folder can't take a side of its own: it goes to the top of the other home.
    mail.update_category(UpdateCategory(name="Alpha", ai_reads=False), ctx)
    assert (folder(ctx, "Alpha")["parent"], folder(ctx, "Alpha")["ai_reads"]) == (None, 0)


def test_a_folder_kept_from_the_ai_is_filled_by_rules_only(ctx: Context) -> None:  # noqa: F811
    with pytest.raises(CommandError, match="filled by a rule"):
        mail.save_category(
            SaveCategory(name="Hidden", mode="smart", description="x", ai_reads=False), ctx
        )
    mail.save_category(SaveCategory(name="Trips", mode="smart", description="Travel plans"), ctx)
    mail.save_category(by_sender("Noise", "bot@tools.example", reads=False), ctx)
    with pytest.raises(CommandError, match="filled by a rule"):
        mail.save_category(
            SaveCategory(name="Inner", mode="smart", description="x", parent="Noise"), ctx
        )
    # The mail agent is offered only the smart folders on the AI's side.
    mail.update_category(UpdateCategory(name="Trips", ai_reads=False), ctx)
    offered = ctx.bus.db.fetch_all(
        "SELECT name FROM mail_categories WHERE proposed = 0 AND mode = 'smart' AND ai_reads = 1"
    )
    assert "Trips" not in {row["name"] for row in offered}


def test_a_rule_of_any_shape_files_what_matches_and_counts_it_first(ctx: Context) -> None:  # noqa: F811
    personal = stored(ctx, "Weekend", "kim@else.example", "This is personal, keep it.")
    stored(ctx, "Work", "kim@else.example", "About the project.")
    stored(ctx, "Other", "ann@new.example", "Something personal too.")
    conditions = [
        RuleCondition(field="body", value="personal"),
        RuleCondition(field="sender", value="kim@"),
    ]
    assert mail.preview_rule(ctx, conditions) == 1
    saved = mail.save_category(
        SaveCategory(name="Personal", mode="exact", conditions=conditions, in_priority=True), ctx
    )
    assert saved.filed == 1
    assert listed(ctx, "Personal") == {personal.thread}
    # In the Inbox, a rule files it and the AI still reads it; Show in Priority puts it there.
    later = stored(ctx, "Again", "kim@else.example", "Personal again.")
    assert not later.skip_agent and thread_of(ctx, later)["category"] == "Personal"
    assert later.thread in in_view(ctx, "priority")
    # Saved without filing what's here, only new mail follows it.
    mail.save_category(
        SaveCategory(
            name="Projects",
            mode="exact",
            conditions=[RuleCondition(field="body", value="project")],
            file_existing=False,
        ),
        ctx,
    )
    assert listed(ctx, "Projects") == set()


def test_filing_keeps_mail_from_the_ai_first_and_one_folder_per_email(ctx: Context) -> None:  # noqa: F811
    rules.change_rules(
        ctx.config.home,
        lambda _: [
            MailRule(
                name="Read it",
                conditions=[RuleCondition(field="subject", value="report")],
                actions=RuleActions(category="Reports"),
            ),
            MailRule(
                name="Keep it",
                conditions=[RuleCondition(field="sender_exact", value="ci@tools.example")],
                actions=RuleActions(category="Tools", skip_agent=True),
            ),
        ],
    )
    result = stored(ctx, "Weekly report", "ci@tools.example")
    row = thread_of(ctx, result)
    assert result.skip_agent and row["category"] == "Tools"
    assert row["extra_categories"] == "[]"


def test_a_mixed_folder_splits_with_its_mail_and_rules_and_can_be_put_back(ctx: Context) -> None:  # noqa: F811
    sorting.move_sender(ctx, "orders@shop.example", reads=True, folder="Shopping")
    sorting.move_sender(ctx, "deals@shop.example", reads=False, folder="Shopping", strict=False)
    order = stored(ctx, "Your order", "orders@shop.example", "Shipped.")
    deal = stored(ctx, "50% off", "deals@shop.example", "Sale.")
    assert {thread_of(ctx, order)["category"], thread_of(ctx, deal)["category"]} == {"Shopping"}
    (mixed,) = mail.mixed_folders(None, ctx).folders  # type: ignore[arg-type]
    assert mixed.name == "Shopping" and [s.sender for s in mixed.kept_senders] == [
        "deals@shop.example"
    ]
    assert mixed.suggested == "Shopping offers"
    # The name it's given for the kept half has to be free.
    with pytest.raises(CommandError, match="already a folder"):
        mail.split_folders(
            SplitFolders(splits=[FolderSplit(name="Shopping", kept_name="shopping")]), ctx
        )
    mail.split_folders(
        SplitFolders(splits=[FolderSplit(name="Shopping", kept_name=mixed.suggested)]), ctx
    )
    assert thread_of(ctx, deal)["category"] == "Shopping offers"
    assert thread_of(ctx, order)["category"] == "Shopping"
    assert folder(ctx, "Shopping offers")["ai_reads"] == 0
    assert not mail.mixed_folders(None, ctx).folders  # type: ignore[arg-type]
    assert stored(ctx, "70% off", "deals@shop.example", "Sale.").skip_agent
    # Undo puts the kept half back.
    mail.split_folders(
        SplitFolders(splits=[FolderSplit(name="Shopping", kept_name="Shopping offers")], undo=True),
        ctx,
    )
    assert folders.find(ctx.bus.db, "Shopping offers") is None
    assert thread_of(ctx, deal)["category"] == "Shopping"
    assert len(mail.mixed_folders(None, ctx).folders) == 1  # type: ignore[arg-type]


def test_removing_a_folder_leaves_its_mail_and_folders_where_it_was(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Noise", "bot@tools.example", reads=False), ctx)
    mail.save_category(
        by_sender("Builds", "ci@tools.example", reads=False).model_copy(update={"parent": "Noise"}),
        ctx,
    )
    mail.save_category(
        by_sender("Nightly", "night@tools.example", reads=False).model_copy(
            update={"parent": "Builds"}
        ),
        ctx,
    )
    build = stored(ctx, "Build passed", "ci@tools.example")
    mail.remove_category(CategoryName(name="Builds"), ctx)
    assert folder(ctx, "Nightly")["parent"] == "Noise"
    assert thread_of(ctx, build)["category"] == "Noise"
    assert stored(ctx, "Build again", "ci@tools.example").skip_agent
    # At the top of Kept from the AI, its mail stays kept, in the catch-all.
    mail.remove_category(CategoryName(name="Noise"), ctx)
    assert thread_of(ctx, build)["category"] == "Automated"
    assert build.thread in in_view(ctx, "kept")
    with pytest.raises(CommandError):
        mail.remove_category(CategoryName(name="Automated"), ctx)


def test_folders_named_like_paths_become_a_tree_once(ctx: Context) -> None:  # noqa: F811
    with ctx.bus.db.transaction() as tx:
        for name, reads in [
            ("Automated", 0),
            ("Automated/linkedin", 0),
            ("Automated/beehiiv", 0),
            ("Projects", 1),
            ("Projects/Alpha", 1),
            ("linkedin", 1),
            ("AI & Tech", 1),
        ]:
            tx.execute(
                "INSERT INTO mail_categories (name, source, mode, description, ai_reads, created)"
                " VALUES (?, 'user', 'exact', ?, ?, '2026-11-01')",
                (name, name, reads),
            )
        tx.execute("DELETE FROM migrations WHERE id = ?", (mail.FOLDER_TREE_UPGRADE,))
    sorting.move_sender(ctx, "news@linkedin.example", reads=False, folder="Automated/linkedin")
    sorting.move_sender(ctx, "ai@tech.example", reads=False, folder="Automated", strict=False)
    rules.change_rules(
        ctx.config.home,
        lambda existing: [
            *existing,
            MailRule(
                name="Sorted: AI & Tech: ai@tech.example",
                conditions=[RuleCondition(field="sender_exact", value="ai2@tech.example")],
                actions=RuleActions(category="AI & Tech", skip_agent=True),
            ),
        ],
    )
    post = stored(ctx, "New connection", "news@linkedin.example")
    assert thread_of(ctx, post)["category"] == "Automated/linkedin"
    mail._folder_tree_upgrade(ctx)
    names = {row["name"] for row in ctx.bus.db.fetch_all("SELECT name FROM mail_categories")}
    assert not any("/" in name for name in names)
    # linkedin was taken on the other side, so the kept one gets the next free name.
    assert folder(ctx, "linkedin 2")["ai_reads"] == 0 and not folder(ctx, "linkedin 2")["parent"]
    assert thread_of(ctx, post)["category"] == "linkedin 2"
    assert folder(ctx, "beehiiv")["ai_reads"] == 0
    assert folder(ctx, "Alpha")["parent"] == "Projects"
    # Every rule of AI & Tech kept its mail from the AI, so it moves to Kept from the AI.
    assert folder(ctx, "AI & Tech")["ai_reads"] == 0
    assert stored(ctx, "Another", "news@linkedin.example").skip_agent
    # Only once.
    mail.update_category(UpdateCategory(name="AI & Tech", ai_reads=True), ctx)
    mail._folder_tree_upgrade(ctx)
    assert folder(ctx, "AI & Tech")["ai_reads"] == 1


def test_sorting_makes_plain_folders_on_one_side(ctx: Context) -> None:  # noqa: F811
    mail.save_category(by_sender("Builds", "lead@work.example"), ctx)
    for n in range(8):
        stored(ctx, f"Build {n} passed", "ci@tools.example")
    sorting.prepare(ctx)
    for _ in range(200):
        status = sorting.status(ctx)
        if status.state == "ready":
            break
        import time

        time.sleep(0.02)
    from nexusai.contracts.mail import ApplyMailSort, SortSenderChoice

    sorting.apply(
        ctx,
        ApplyMailSort(
            senders=[
                SortSenderChoice(sender="ci@tools.example", side="ignores", own=True, name="Builds")
            ]
        ),
    )
    # The AI's side already has Builds, so the kept folder gets a name of its own.
    kept = [
        row["name"]
        for row in ctx.bus.db.fetch_all(
            "SELECT name FROM mail_categories WHERE ai_reads = 0 AND name != 'Automated'"
        )
    ]
    assert kept == ["Builds updates"]
    assert folder(ctx, "Builds")["ai_reads"] == 1


def test_a_mailbox_sorted_before_sorting_was_saved_counts_as_sorted(ctx: Context) -> None:  # noqa: F811
    # Older tools wrote "the sender has" rather than "it's from".
    rules.change_rules(
        ctx.config.home,
        lambda _: [
            MailRule(
                name="linkedin: news@linkedin.example",
                conditions=[RuleCondition(field="sender", value="news@linkedin.example")],
                actions=RuleActions(category="linkedin", skip_agent=True),
            )
        ],
    )
    # Learning hasn't started: recording it now could start it, so it waits.
    assert not sorting.record_past_sorting(ctx)
    with ctx.bus.db.transaction() as tx:
        tx.execute("INSERT INTO agent_defaults (key, value) VALUES ('mail_learning', 'asking')")
    assert sorting.record_past_sorting(ctx)
    assert sorting.decided(ctx) == "done"
    assert not sorting.record_past_sorting(ctx)
