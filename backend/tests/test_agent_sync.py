"""Posty sees what the app shows: every object has one address, used to open and to cite it, and
no internal key reaches the screen (docs/AGENT_SYNC_PLAN.md)."""

# ruff: noqa: F811

import re
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail
from nexusai.modules.agent import mail_agent, matters
from nexusai.modules.agent.citations import Citations
from nexusai.modules.agent.providers import TextChunk, ToolCall
from nexusai.modules.agent.ui_stream import UiTranslator
from test_agent_work import (  # noqa: F401  (fixtures)
    Script,
    app_config,
    client,
    fake,
    script,
    wait,
)
from test_chat_engine import chat, new_session, status, view
from test_matter_objects import one_matter_two_tasks, open_tasks, save_task
from test_matters import query


class Read(Citations):
    """What a turn read, without a database, to test the stream on its own."""

    def __init__(self, read: set[tuple[str, str]]) -> None:
        self.read = read
        self.numbers = {}
        self.pages = {}
        self.messages = {}

    def _was_read(self, kind: str, ref: str) -> bool:
        return (kind, ref) in self.read


def stream(chunks: list[str], read: set[tuple[str, str]]) -> str:
    translator = UiTranslator(started=True, citations=Read(read))
    block: dict[str, Any] = {"kind": "text", "id": "t"}
    parts: list[dict[str, Any]] = []
    for chunk in chunks:
        parts += translator._visible_text(block, chunk)
    parts += translator._end_text(block)
    return "".join(part.get("delta", "") for part in parts)


def test_a_matter_a_task_and_a_reminder_are_cited_like_mail() -> None:
    read = {("matter", "12"), ("task", "88"), ("reminder", "5")}
    assert stream(["RCA [matter:1", "2] is done [task:88]; chase [rem", "inder:5]."], read) == (
        "RCA [1](#cite-1) is done [2](#cite-2); chase [3](#cite-3)."
    )


def test_a_bare_key_becomes_a_citation_when_read_and_goes_when_not() -> None:
    read = {("task", "88"), ("doc", "m:12:2"), ("mail", "7")}
    assert stream(["Ticked task:", "88, see m:12", ":2 and thread:7 and task:99."], read) == (
        "Ticked [1](#cite-1), see [2](#cite-2) and [3](#cite-3) and ."
    )


def test_a_bare_key_at_the_very_end_is_still_rewritten() -> None:
    assert stream(["Done: task:9"], set()) == "Done: "


def test_times_links_and_words_are_left_alone() -> None:
    text = "At 21:45 I'm done with the task, see https://x.example/m:12 and ratio 3:2."
    assert stream([text[:9], text[9:30], text[30:]], set()) == text


def ctx_of(client: TestClient) -> Any:
    from nexusai.modules.agent.module import current

    return current().ctx


def ticked_one(
    client: TestClient, script: Script, fake: FakeMail
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A matter with two tasks, one of them ticked."""
    matter = one_matter_two_tasks(client, script, fake)
    task = next(t for t in open_tasks(client) if t["title"] == "Get CL 88213 merged")
    save_task(client, task, status="done")
    return matter, task


def test_a_ticked_task_shows_as_done_on_the_plate_not_open(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter, task = ticked_one(client, script, fake)
    plate = matters.plate(ctx_of(client))
    going_on, done = plate.split("What's going on")[1].split("Done since yesterday:")
    assert f"[matter:{matter['id']}]" in going_on
    assert f"[task:{task['id']}]" not in going_on
    assert f"[task:{task['id']}] Get CL 88213 merged, done" in done


def test_the_plate_counts_and_lists_the_same_matters_as_today(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    ticked_one(client, script, fake)
    today = query(client, "matters.brief")
    plate = matters.plate(ctx_of(client))
    assert (
        f"Matters waiting on them: {len(today['needs_you'])} · waiting on others:"
        f" {len(today['waiting'])} · worth knowing: {len(today['fyi'])}"
    ) in plate
    for row in [*today["needs_you"], *today["waiting"], *today["fyi"]]:
        assert f"[matter:{row['id']}]" in plate


def test_posty_is_shown_your_day_and_can_cite_a_matter_and_a_task_from_it(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter, _ = ticked_one(client, script, fake)
    other = next(t for t in open_tasks(client) if t["title"] == "Sign the 88213 cost sheet")
    script.replies = [
        [TextChunk(f"Sign the cost sheet [task:{other['id']}] for [matter:{matter['id']}].")]
    ]
    session = new_session(client)
    chat(client, session, "What needs me today?")
    wait(lambda: status(client, session) == "done", "the answer")
    told = script.requests[-1].instructions
    assert "Your day" in told
    assert f"[matter:{matter['id']}]" in told
    answer = view(client, session)["messages"][-1]
    words = "".join(p["text"] for p in answer["parts"] if p["type"] == "text")
    assert words == "Sign the cost sheet [1](#cite-1) for [2](#cite-2)."
    sources = next(p for p in answer["parts"] if p["type"] == "data-sources")["data"]["sources"]
    assert [(s["kind"], s["title"], s["matter"]) for s in sources] == [
        ("task", "Sign the 88213 cost sheet", matter["id"]),
        ("matter", matter["title"], matter["id"]),
    ]


def test_decisions_name_work_by_its_address(client: TestClient) -> None:
    ctx = ctx_of(client)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO tasks (title, notes, status, source, proposed, created)"
            " VALUES ('Book the venue', '', 'todo', 'agent', 1, 'now')"
        )
    waiting = mail_agent.decisions(ctx)
    assert "Suggested tasks: 1 pending" in waiting
    assert "- [task:1] Book the venue" in waiting


def tool_said(client: TestClient, script: Script, call: str, args: dict[str, Any]) -> str:
    """What a tool showed Posty, called once in a chat."""
    script.replies = [[ToolCall("c1", call, args)], [TextChunk("ok")]]
    session = new_session(client)
    chat(client, session, "Look")
    wait(lambda: status(client, session) == "done", call)
    said: str = script.requests[-1].messages[-1].text
    return said


def test_tasks_are_listed_by_address_with_the_ones_just_ticked(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    _, task = ticked_one(client, script, fake)
    other = next(t for t in open_tasks(client) if t["title"] == "Sign the 88213 cost sheet")
    said = tool_said(client, script, "list_tasks", {})
    assert f"[task:{task['id']}] Get CL 88213 merged (done " in said
    assert f"[task:{other['id']}] Sign the 88213 cost sheet (todo" in said
    assert not re.search(r"(?m)^\d+:", said)


def test_a_conversation_says_where_its_matter_stands(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter, task = ticked_one(client, script, fake)
    thread = query(client, "matters.get", id=matter["id"])["threads"][0]["id"]
    said = tool_said(client, script, "read_thread", {"thread_ids": [thread]})
    stands = next(line for line in said.splitlines() if line.startswith("Where it stands:"))
    assert stands.startswith(f"Where it stands: [matter:{matter['id']}] waiting_on_you")
    assert f"done [task:{task['id']}] Get CL 88213 merged" in stands
    found = tool_said(client, script, "search_mail", {"query": "88213"})
    assert f"[matter:{matter['id']}] waiting_on_you" in found


def test_a_document_is_read_by_its_marker_or_its_bare_key() -> None:
    from nexusai.modules.agent.kinds import key_of

    assert key_of("[doc:m:12:2]") == key_of("m:12:2") == key_of("doc:m:12:2#p3") == "m:12:2"


def test_every_agent_is_taught_the_object_model_as_the_code_has_it() -> None:
    from typing import get_args

    from nexusai.contracts.agent import MatterState
    from nexusai.modules.agent import citations, links
    from nexusai.modules.agent.prompts_builder import for_tools, packaged

    # The shared prompt, as an agent with no tools at all gets it.
    taught = for_tools(packaged("system.md"), []).split("## How NexusAI organizes their work")[1]
    taught = taught.split("\n## ")[0]
    states = re.search(r"state is one of (.+?)\. ", taught)
    assert states is not None
    assert set(re.findall(r"[a-z_]+", states.group(1))) - {"or"} == set(get_args(MatterState))
    linked = next(line for line in taught.splitlines() if line.startswith("- Links"))
    assert set(re.findall(r"\b([a-z]+) \(", linked)) == set(links.KINDS_OF_LINK)
    assert set(re.findall(r"\[([a-z]+):", taught)) == set(citations.CITED)
    assert len(taught.split()) < 200


def test_a_matter_and_its_work_open_by_address_and_name_what_to_open_next(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter, task = ticked_one(client, script, fake)
    other = next(t for t in open_tasks(client) if t["title"] == "Sign the 88213 cost sheet")
    whole = tool_said(client, script, "open_item", {"address": f"[matter:{matter['id']}]"})
    assert whole.splitlines()[1].startswith(f"[matter:{matter['id']}]")
    assert "[mail:" in whole
    assert f"- suggested, not kept yet [task:{other['id']}] Sign the 88213 cost sheet" in whole
    assert f"- done [task:{task['id']}] Get CL 88213 merged" in whole
    one = tool_said(client, script, "open_item", {"address": f"task:{other['id']}"})
    assert f"In [matter:{matter['id']}]" in one and "Asked in [mail:" in one
    found = tool_said(client, script, "find_matters", {"words": "88213"})
    assert f"[matter:{matter['id']}]" in found
    assert "isn't an address" in tool_said(client, script, "open_item", {"address": "matter 12"})


RETIRED = {"read_matter", "read_work_board", "write_work_board", "work board"}


def test_no_prompt_names_a_retired_tool() -> None:
    from importlib import resources

    folder = resources.files("nexusai.modules.agent").joinpath("prompts")
    for prompt in folder.iterdir():
        if prompt.name.endswith(".md"):
            text = prompt.read_text("utf-8")
            assert not [name for name in RETIRED if name in text], prompt.name


def test_the_work_board_moves_onto_tasks_and_a_finished_deadline_just_goes(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    matter, ticked = ticked_one(client, script, fake)
    ctx = ctx_of(client)
    db = ctx.bus.db
    with db.transaction() as tx:
        for title, due, thread in (
            # The RCA: its task was ticked, so the deadline is stale, not overdue.
            ("RCA due", "2020-01-01", ticked["thread"]),
            ("Book flights", "2099-03-01", None),
            ("Old thing", "2020-01-01", None),
            ("Status: waiting on legal", None, None),
        ):
            tx.execute(
                "INSERT INTO work_board (kind, title, thread, due, by, updated)"
                " VALUES (?, ?, ?, ?, 'x', 'x')",
                ("status" if title.startswith("Status") else "deadline", title, thread, due),
            )
    last = db.fetch_all("SELECT MAX(id) AS n FROM tasks")[0]["n"]
    matters.adopt_all(ctx)
    assert db.fetch_all("SELECT 1 FROM work_board WHERE done = 0") == []
    added = db.fetch_all("SELECT title, due, proposed FROM tasks WHERE id > ?", (last,))
    assert [(r["title"], r["due"], r["proposed"]) for r in added] == [
        ("Book flights", "2099-03-01", 1)
    ]
    assert "RCA due" not in matters.plate(ctx)
    assert query(client, "matters.get", id=matter["id"])["matter"]["due"] is None


def test_no_tool_reads_or_writes_the_work_board(client: TestClient) -> None:
    from nexusai.modules.agent import tools

    built = {t.name for t in tools.build_tools(ctx_of(client), "s", tools.RunControl())}
    assert not built & RETIRED
