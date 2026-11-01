"""Agents can create, change and remove everything the person keeps here, and do many at once."""
# ruff: noqa: F811

import json
import threading
import time
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.modules.agent import module as agent_module
from nexusai.modules.agent import tools
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import (
    Script,
    app_config,  # noqa: F401
    client,  # noqa: F401
    connect,
    fake,  # noqa: F401
    script,  # noqa: F401
    triage_reply,
    triaged,
    wait,
)


def new_session(client: TestClient) -> str:
    identifier: str = client.post("/api/commands/session.create", json={}).json()["id"]
    return identifier


def chat(client: TestClient, session: str, text: str) -> None:
    with client.stream(
        "POST", "/api/sessions/chat", json={"id": session, "text": text}
    ) as response:
        list(response.iter_lines())


def chat_in_background(client: TestClient, session: str, text: str) -> list[bool]:
    done: list[bool] = []

    def run() -> None:
        chat(client, session, text)
        done.append(True)

    threading.Thread(target=run, daemon=True).start()
    return done


def last_result(script: Script) -> str:
    text: str = script.requests[-1].messages[-1].text
    return text


def use_tool(client: TestClient, script: Script, call: ToolCall) -> str:
    session = new_session(client)
    script.replies = [[call], [TextChunk("Done.")]]
    chat(client, session, "Do it")
    return last_result(script)


def pending(client: TestClient, count: int) -> list[dict[str, Any]]:
    def enough() -> list[dict[str, Any]] | None:
        found: list[dict[str, Any]] = client.post("/api/queries/approvals.list").json()["approvals"]
        return found if len(found) == count else None

    result: list[dict[str, Any]] = wait(enough, f"{count} approvals")
    return result


def approve_one(client: TestClient) -> dict[str, Any]:
    approval = pending(client, 1)[0]
    client.post("/api/commands/approvals.decide", json={"id": approval["id"], "choice": "once"})
    return approval


def subjects(client: TestClient, **query: Any) -> list[str]:
    threads = client.post("/api/queries/threads.list", json=query).json()["threads"]
    return [t["subject"] for t in threads]


def category_named(client: TestClient, name: str) -> dict[str, Any] | None:
    rows = client.post("/api/queries/categories.list").json()["categories"]
    found: dict[str, Any] | None = next((c for c in rows if c["name"] == name), None)
    return found


def rules_of(client: TestClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.post("/api/queries/rules.get").json()["rules"]
    return found


def tasks_of(client: TestClient, **query: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.post("/api/queries/tasks.list", json=query).json()["tasks"]
    return found


def two_filed_threads(client: TestClient, script: Script, fake: FakeMail) -> list[int]:
    connect(client, fake)
    script.replies = [triage_reply(category="Reports"), triage_reply(category="Reports")]
    fake.state.deliver(make_mail(subject="Report one"))
    first = triaged(client, "Report one")["id"]
    fake.state.deliver(make_mail(subject="Report two"))
    return [first, triaged(client, "Report two")["id"]]


# Categories


def test_a_category_can_be_renamed_with_its_mail_and_rule(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    two_filed_threads(client, script, fake)
    client.post(
        "/api/commands/categories.save",
        json={"name": "Reports", "subject": "report", "in_priority": True},
    )
    result = use_tool(
        client, script, ToolCall("c", "update_category", {"name": "Reports", "new_name": "Updates"})
    )
    assert result == "Updated Updates."
    assert category_named(client, "Reports") is None
    renamed = category_named(client, "Updates")
    assert renamed
    assert (renamed["count"], renamed["in_priority"], renamed["subject"]) == (2, True, "report")
    assert set(subjects(client, folder="all", category="Updates")) == {"Report one", "Report two"}
    assert [r["name"] for r in rules_of(client)] == ["Category: Updates"]
    # New mail follows the renamed rule.
    fake.state.deliver(make_mail(subject="Report three"))
    wait(lambda: "Report three" in subjects(client, folder="all", category="Updates"), "new mail")


def test_renaming_onto_a_name_in_use_is_refused(client: TestClient, script: Script) -> None:
    client.post("/api/commands/categories.save", json={"name": "One"})
    client.post("/api/commands/categories.save", json={"name": "Two"})
    result = use_tool(
        client, script, ToolCall("c", "update_category", {"name": "One", "new_name": "Two"})
    )
    assert "already a category" in result
    assert category_named(client, "One")


def test_a_rule_can_be_set_changed_and_cleared_on_a_category(
    client: TestClient, script: Script
) -> None:
    client.post("/api/commands/categories.save", json={"name": "Bills"})
    use_tool(client, script, ToolCall("a", "update_category", {"name": "Bills", "sender": "acme"}))
    assert rules_of(client)[0]["conditions"][0]["value"] == "acme"
    use_tool(
        client, script, ToolCall("b", "update_category", {"name": "Bills", "sender": "globex"})
    )
    assert [r["conditions"][0]["value"] for r in rules_of(client)] == ["globex"]
    use_tool(
        client, script, ToolCall("c", "update_category", {"name": "Bills", "clear_rule": True})
    )
    assert rules_of(client) == []
    assert (category_named(client, "Bills") or {})["sender"] is None


def test_categories_merge_and_keep_their_mail(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    two_filed_threads(client, script, fake)
    client.post("/api/commands/categories.save", json={"name": "Old", "sender": "nobody"})
    use_tool(
        client,
        script,
        ToolCall("c", "merge_categories", {"names": ["Reports", "Old"], "into": "Everything"}),
    )
    assert category_named(client, "Reports") is None
    assert category_named(client, "Old") is None
    assert (category_named(client, "Everything") or {})["count"] == 2


def test_categories_keep_their_order_and_can_be_removed_in_bulk(
    client: TestClient, script: Script
) -> None:
    for name in ("Apples", "Bananas", "Cherries"):
        client.post("/api/commands/categories.save", json={"name": name})
    order = {"names": ["Cherries", "Apples", "Bananas"]}
    use_tool(client, script, ToolCall("c", "reorder_categories", order))
    rows = client.post("/api/queries/categories.list").json()["categories"]
    assert [c["name"] for c in rows] == order["names"]
    use_tool(client, script, ToolCall("d", "delete_categories", {"names": ["Cherries", "Apples"]}))
    rows = client.post("/api/queries/categories.list").json()["categories"]
    assert [c["name"] for c in rows] == ["Bananas"]


def test_categories_saved_side_by_side_all_keep_their_rules(
    client: TestClient, script: Script
) -> None:
    """This used to fail with "No such file" and could lose a rule."""
    session = new_session(client)
    items = [{"categories": [{"name": f"C{n}", "sender": f"s{n}"}]} for n in range(6)]
    script.replies = [
        [ToolCall(f"c{n}", "create_categories", item) for n, item in enumerate(items)],
        [TextChunk("Ok.")],
    ]
    chat(client, session, "Make them")
    assert {r["name"] for r in rules_of(client)} == {f"Category: C{n}" for n in range(6)}


# Mail


def test_many_conversations_change_in_one_call_with_one_approval(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    threads = two_filed_threads(client, script, fake)
    session = new_session(client)
    change = {"thread_ids": threads, "category": "Finance", "flagged": True, "status": "resolved"}
    script.replies = [
        [ToolCall("r", "read_thread", {"thread_id": threads[0]})],
        [ToolCall("u", "update_mail", change)],
        [TextChunk("Done.")],
    ]
    done = chat_in_background(client, session, "Sort them")
    approval = approve_one(client)
    assert "“Report one”" in approval["summary"]
    assert "“Report two”" in approval["detail"]
    wait(lambda: done, "finish")
    rows = client.post("/api/queries/threads.list", json={"folder": "all"}).json()["threads"]
    assert {(t["category"], t["flagged"], t["status"]) for t in rows} == {
        ("Finance", True, "resolved")
    }


def test_mail_can_be_trashed_but_only_after_asking(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    threads = two_filed_threads(client, script, fake)
    session = new_session(client)
    script.replies = [
        [ToolCall("t", "trash_mail", {"thread_ids": threads[:1]})],
        [TextChunk("Ok.")],
    ]
    done = chat_in_background(client, session, "Delete it")
    approve_one(client)
    wait(lambda: done, "finish")
    wait(lambda: subjects(client, folder="all") == ["Report two"], "gone from all mail")


def test_rules_can_be_saved_changed_and_removed(client: TestClient, script: Script) -> None:
    first = {"name": "Bills", "sender": "acme", "category": "Bills"}
    use_tool(client, script, ToolCall("a", "save_rule", first))
    second = {"name": "Bills", "subject": "invoice", "skip_agent": True}
    use_tool(client, script, ToolCall("b", "save_rule", second))
    rules = rules_of(client)
    assert len(rules) == 1
    assert rules[0]["conditions"][0]["value"] == "invoice"
    assert rules[0]["actions"]["skip_agent"] is True
    assert "needs" in use_tool(client, script, ToolCall("c", "save_rule", {"name": "Empty"}))
    use_tool(client, script, ToolCall("d", "delete_rules", {"names": ["Bills"]}))
    assert rules_of(client) == []


# Tasks and reminders


def test_tasks_change_and_go_in_bulk_and_record_their_times(
    client: TestClient, script: Script
) -> None:
    made = {"tasks": [{"title": "One"}, {"title": "Two", "due": "2031-01-02"}, {"title": "Three"}]}
    use_tool(client, script, ToolCall("a", "create_tasks", made))
    rows = tasks_of(client)
    assert all(t["created"] and t["updated"] for t in rows)
    ids = {t["title"]: t["id"] for t in rows}
    changes = [
        {"task_id": ids["One"], "title": "First", "status": "done"},
        {"task_id": ids["Two"], "clear_due": True, "notes": "Soon"},
    ]
    use_tool(client, script, ToolCall("b", "update_tasks", {"changes": changes}))
    changed = {t["id"]: t for t in tasks_of(client, include_done=True)}
    first = changed[ids["One"]]
    assert (first["title"], first["status"]) == ("First", "done")
    assert first["completed"]
    assert first["updated"] >= first["created"]
    assert (changed[ids["Two"]]["due"], changed[ids["Two"]]["notes"]) == (None, "Soon")
    use_tool(
        client, script, ToolCall("c", "delete_tasks", {"task_ids": [ids["Two"], ids["Three"]]})
    )
    assert [t["title"] for t in tasks_of(client, include_done=True)] == ["First"]


def test_changing_a_task_records_when_and_reopening_clears_completed(client: TestClient) -> None:
    client.post("/api/commands/tasks.save", json={"title": "Mine"})
    task = tasks_of(client)[0]
    time.sleep(0.01)
    fields = {k: task[k] for k in ("id", "title", "notes", "due", "thread", "proposed")}
    client.post("/api/commands/tasks.save", json={**fields, "status": "done"})
    done = tasks_of(client, include_done=True)[0]
    assert done["completed"]
    assert done["updated"] > task["updated"]
    client.post("/api/commands/tasks.save", json={**fields, "status": "todo"})
    assert tasks_of(client)[0]["completed"] is None


def test_reminders_change_snooze_and_go_in_bulk_and_record_their_times(
    client: TestClient, script: Script
) -> None:
    made = {
        "reminders": [
            {"title": "One", "when": "2031-05-01T09:00"},
            {"title": "Two", "when": "2031-05-02T09:00"},
        ]
    }
    use_tool(client, script, ToolCall("a", "create_reminders", made))
    rows = client.post("/api/queries/reminders.list").json()["reminders"]
    assert all(r["created"] and r["updated"] for r in rows)
    one, two = sorted(rows, key=lambda r: r["title"])
    changes = [
        {"reminder_id": one["id"], "when": "2032-01-01T08:00", "repeat": "week"},
        {"reminder_id": two["id"], "snooze_minutes": 30},
    ]
    use_tool(client, script, ToolCall("b", "update_reminders", {"changes": changes}))
    rows = {r["id"]: r for r in client.post("/api/queries/reminders.list").json()["reminders"]}
    assert (rows[one["id"]]["when"], rows[one["id"]]["repeat"]) == ("2032-01-01T08:00", "week")
    assert rows[two["id"]]["when"] != two["when"]
    ids = {"reminder_ids": [one["id"], two["id"]]}
    use_tool(client, script, ToolCall("c", "delete_reminders", ids))
    assert client.post("/api/queries/reminders.list").json()["reminders"] == []


# Agents, memory, files and panels


def test_an_agent_can_be_changed_paused_and_removed(client: TestClient, script: Script) -> None:
    client.post("/api/commands/schedules.save", json={"title": "Note", "prompt": "Say hi"})
    row = client.post("/api/queries/schedules.list").json()["schedules"][0]
    assert row["created"]
    assert row["updated"]
    session = new_session(client)
    change = {"agent_id": row["id"], "enabled": False, "instructions": "Say bye"}
    script.replies = [[ToolCall("u", "update_agent", change)], [TextChunk("Paused.")]]
    done = chat_in_background(client, session, "Pause it")
    approve_one(client)
    wait(lambda: done, "finish")
    changed = client.post("/api/queries/schedules.list").json()["schedules"][0]
    assert (changed["enabled"], changed["prompt"], changed["title"]) == (False, "Say bye", "Note")
    gone = {"agent_ids": [row["id"]]}
    script.replies = [[ToolCall("r", "remove_agents", gone)], [TextChunk("Gone.")]]
    done = chat_in_background(client, session, "Remove it")
    approve_one(client)
    wait(lambda: done, "removed")
    assert client.post("/api/queries/schedules.list").json()["schedules"] == []


def test_memory_can_be_changed_and_forgotten(client: TestClient, script: Script) -> None:
    client.post("/api/commands/memory.save", json={"name": "note", "content": "Likes tea"})
    path = client.post("/api/queries/memory.list", json={"query": ""}).json()["files"][0]["path"]
    change = {"path": path, "content": "Likes coffee"}
    use_tool(client, script, ToolCall("a", "update_memory", change))
    files = client.post("/api/queries/memory.list", json={"query": ""}).json()["files"]
    assert "Likes coffee" in files[0]["content"]
    use_tool(client, script, ToolCall("b", "forget_memory", {"paths": [path]}))
    assert client.post("/api/queries/memory.list", json={"query": ""}).json()["files"] == []


def test_files_can_be_listed_moved_and_deleted_in_the_scratch_folder(
    client: TestClient, script: Script
) -> None:
    session = new_session(client)
    script.replies = [
        [ToolCall("w", "write_file", {"path": "a.txt", "content": "hello"})],
        [ToolCall("m", "move_file", {"source": "a.txt", "destination": "b.txt"})],
        [ToolCall("l", "list_folder", {"path": "."})],
        [TextChunk("Listed.")],
    ]
    chat(client, session, "Do it")
    assert "b.txt" in last_result(script)
    script.replies = [[ToolCall("d", "delete_file", {"path": "b.txt"})], [TextChunk("Gone.")]]
    done = chat_in_background(client, session, "Delete it")
    approve_one(client)
    wait(lambda: done, "deleted")
    assert last_result(script).startswith("Deleted")


def test_panels_can_be_saved_and_removed(client: TestClient, script: Script) -> None:
    use_tool(client, script, ToolCall("a", "save_panel", {"title": "From Sam", "sender": "sam"}))
    panels = client.post("/api/queries/panels.board").json()["panels"]
    assert any(p["id"] == "from-sam" for p in panels)
    use_tool(client, script, ToolCall("b", "remove_panels", {"panel_ids": ["from-sam"]}))
    panels = client.post("/api/queries/panels.board").json()["panels"]
    assert not any(p["id"] == "from-sam" for p in panels)


def test_every_powerful_tool_has_a_row_in_settings(client: TestClient) -> None:
    """A new tool that forgets its row would otherwise be impossible to turn off."""
    catalog = {t["name"] for t in client.post("/api/queries/tools.catalog").json()["tools"]}
    context = agent_module.current().ctx
    built = {t.name for t in tools.build_tools(context, "s", tools.RunControl())}
    # These only talk to the person or other agents, or only suggest.
    talking = {
        "ask_user",
        "suggest",
        "tell",
        "notify_person",
        "read_work_board",
        "write_work_board",
        "post_to_agents",
        "read_agent_messages",
        "propose_memory",
        "propose_task",
        "propose_reminder",
        "draft_reply",
        "save_personal_prompt",
    }
    assert built - catalog == talking
    assert catalog <= built


# Counts follow events


def category_events(client: TestClient) -> list[dict[str, Any]]:
    events = client.post("/api/events/log", json={}).json()["events"]
    return [e for e in events if e["type"] == "categories.changed"]


def test_moving_mail_announces_the_new_counts_without_being_asked(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    threads = two_filed_threads(client, script, fake)
    client.post("/api/commands/categories.save", json={"name": "Elsewhere"})
    client.post(
        "/api/commands/thread.setCategory", json={"id": threads[0], "category": "Elsewhere"}
    )

    def counts() -> dict[str, int] | None:
        found = category_events(client)
        if not found:
            return None
        latest = {c["name"]: c["count"] for c in found[-1]["payload"]["categories"]}
        return latest if latest.get("Elsewhere") == 1 else None

    assert wait(counts, "an event with the new counts")["Reports"] == 1


def test_nothing_is_announced_when_no_count_changed(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    threads = two_filed_threads(client, script, fake)
    client.post(
        "/api/commands/thread.setCategory", json={"id": threads[0], "category": "Elsewhere"}
    )
    wait(lambda: category_events(client), "first announcement")
    time.sleep(0.5)
    before = len(category_events(client))
    client.post("/api/commands/thread.setFlag", json={"id": threads[0], "flagged": True})
    time.sleep(0.5)
    assert len(category_events(client)) == before
    assert json.dumps(category_events(client)[-1]["payload"])
