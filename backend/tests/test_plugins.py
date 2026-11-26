"""Agents, skills and prompts load from the built-in plugins exactly as they did from the old
card, prompt and skill folders (the golden file was written from the old code before the move)."""

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import cards, mail_agent, plugins, prompts_builder, skills


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as test:
        yield test


GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "plugins_golden.json").read_text("utf-8"))
SOURCE = Path(plugins.__file__).parent / "builtin_plugins"


# What changed on purpose since the golden file was written: the Organizer folded into the lead
# (docs/AGENT_OWNERS_PLAN.md), so the lead's card and prompt took over its work.
FOLDED = "organizer"
# Added since: the Routines agent, which owns setting up routines (To do 1).
NEW_AGENT = "routines"
LEAD_CAN_DO = "Adds, changes and clears your tasks and reminders, without duplicates"
LEAD_PROMPT_EDITS = (
    (
        "Before you create a category, rule, schedule, panel, memory note or draft, view what"
        " exists with its list tool (list_categories, list_rules, list_schedules, list_panels,"
        " list_memory, list_drafts).",
        "Before you create a task, reminder, category, rule, panel, memory note or draft, view what"
        " exists with its list tool (list_tasks, list_reminders, list_categories, list_rules,"
        " list_panels, list_memory, list_drafts).",
    ),
    (
        "## Pasted conversations\n",
        "## Tasks and reminders\n\nYou add, change, complete and remove the person's tasks and"
        " reminders yourself.\n- A thing to do gets a task. A moment to be reminded gets a reminder."
        " Never both for the same thing unless asked. Link it to the conversation with its thread id"
        ' when it comes from mail.\n- Use the person\'s local time, from "This run". Write due dates'
        ' as YYYY-MM-DD and reminder times as YYYY-MM-DDTHH:MM. Work out words like "tomorrow",'
        ' "Thursday" or "next week" from today\'s date.\n- If a date or time you need isn\'t given'
        " and can't be found in the mail, ask with ask_user. Don't invent one.\n- \"Remind me\" is"
        ' always a reminder, never a schedule, however often it repeats. "Every hour from 10 to 8'
        ' on weekdays" is one reminder: repeat interval, every_minutes 60, between 10:00-20:00,'
        " days weekdays.\n\n## Pasted"
        " conversations\n",
    ),
    (
        "| Adding, changing, completing or removing tasks and reminders |"
        " {{agent.organizer.handle}} |\n",
        "",
    ),
    (
        "| Anything about the brief on Today | {{agent.daily-prep.handle}} |\n",
        "| Anything about the brief on Today | {{agent.daily-prep.handle}} |\n| Work that should"
        ' run by itself, later or again: "every Friday, write my status" |'
        " {{agent.routines.handle}} |\n",
    ),
    (
        "If what's needed is unclear, such as when a reminder should go off, ask the person first,"
        " then hand over.",
        "If what's needed is unclear, ask the person first, then hand over.",
    ),
)


def _golden_cards() -> dict[str, object]:
    expected = {k: v for k, v in GOLDEN["cards"].items() if k != FOLDED}
    lead = dict(expected["session"])
    can_do = list(lead["can_do"])
    lead["can_do"] = [*can_do[:-1], LEAD_CAN_DO, can_do[-1]]
    lead["may_assign_to"] = [*(a for a in lead["may_assign_to"] if a != FOLDED), NEW_AGENT]
    expected["session"] = lead
    return expected


def test_every_card_is_as_it_was() -> None:
    loaded = {}
    for card in cards._files().values():
        data = dataclasses.asdict(card)
        data.pop("version")
        loaded[card.id] = json.loads(json.dumps(data))
    assert loaded.pop(NEW_AGENT)["default"] is False
    assert loaded == _golden_cards()
    # The team is listed in the same order as before.
    assert [c for c in cards._files() if c != NEW_AGENT] == sorted(_golden_cards())


def test_every_agent_prompt_is_byte_for_byte_the_same() -> None:
    # The prompt text is hashed into decision_context_version: one changed byte re-judges mail.
    for agent, text in GOLDEN["agent_prompts"].items():
        if agent == FOLDED:
            continue
        if agent == "session":
            for old, new in LEAD_PROMPT_EDITS:
                assert text.count(old) == 1, old
                text = text.replace(old, new)
        assert prompts_builder.agent_base(agent) == text, agent


def test_prompts_that_arent_an_agents_still_load_from_prompts() -> None:
    assert prompts_builder.agent_base("summary") == prompts_builder.packaged("summary.md")


def test_every_shipped_skill_is_as_it_was() -> None:
    folders = plugins.skill_folders()
    assert [folder.name for folder in folders] == [s["folder"] for s in GOLDEN["skills"].values()]
    for folder in folders:
        skill = skills.parse(skills._read_folder(folder), "built_in")
        assert json.loads(json.dumps(dataclasses.asdict(skill))) == {
            k: v for k, v in GOLDEN["skills"][skill.name].items() if k != "folder"
        }


def test_every_mail_agent_run_prompt_is_as_it_was() -> None:
    assert plugins.prompt_names() == set(GOLDEN["triggers"])
    for name, text in GOLDEN["triggers"].items():
        assert plugins.prompt(name) == text
        assert mail_agent._template(name) == text.strip()


def test_a_card_version_comes_from_its_agent_file() -> None:
    files = plugins.agent_files()
    for card in cards._files().values():
        assert card.version == files[card.id].hash


def test_built_in_plugins_follow_the_format() -> None:
    names = {plugin.name for plugin in plugins.built_in()}
    assert names == {"nexusai", "mail", "brief", "meetings", "routines"}
    assert {p.name for p in plugins.built_in() if p.required} == {"nexusai", "mail"}
    for folder in SOURCE.iterdir():
        if not folder.is_dir():
            continue
        # A root plugin.json, so packaging never has to carry a hidden folder.
        assert (folder / "plugin.json").is_file(), folder.name
        assert not any(part.startswith(".") for p in folder.rglob("*") for part in p.parts[-1:])
        manifest = json.loads((folder / "plugin.json").read_text("utf-8"))
        assert manifest["name"] == folder.name and manifest["description"]
    for agent in plugins.agent_files().values():
        # Anthropic's two required fields, and only our own fields under nexusai.
        assert agent.front["name"] == agent.name and agent.description
        assert set(agent.front) <= {"name", "description", "nexusai"}


def test_frontmatter_is_split_without_touching_the_body() -> None:
    front, body = plugins.split("---\nname: x\ndescription: y\n---\nline one\n\n---\nnot front\n")
    assert front == {"name": "x", "description": "y"}
    assert body == "line one\n\n---\nnot front\n"
    with pytest.raises(ValueError, match="frontmatter"):
        plugins.split("name: x\n")
    with pytest.raises(ValueError, match="closing"):
        plugins.split("---\nname: x\n")


def test_an_unknown_run_prompt_is_a_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="no-such"):
        plugins.prompt("no-such")


TOOLS_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "tools_golden.json").read_text("utf-8")
)
ROUTINE_TOOLS = {"create_schedule", "update_schedule", "remove_schedules", "run_schedule"}
TASK_TOOLS = {
    "create_tasks", "update_tasks", "delete_tasks",
    "create_reminders", "update_reminders", "delete_reminders",
}  # fmt: skip


def test_every_agents_tools_are_as_they_were_but_for_the_organizer_fold() -> None:
    """Written from the old code before jobs.py. The only changes meant: the Organizer is gone and
    Posty keeps tasks and reminders itself, shown up front; the Mail agent's suggestion tools are
    its own job, so schedules no longer have them either."""
    from nexusai.modules.agent import team, tools

    for key, old in TOOLS_GOLDEN.items():
        agent, origin, has_email = key.split("|")
        if agent == "organizer":
            continue
        allowed = tools.allowed_for(agent, origin, has_email == "True")
        new_allowed = sorted(allowed) if allowed is not None else None
        assert new_allowed == old["allowed"], key
        if allowed is None:
            kept_out = set(
                tools.MAIL_AGENT_ONLY | tools.BRIEF_AGENT_ONLY | tools.withheld_for(agent)
            )
            expected = set(old["kept_out"])
            if agent == "session":
                expected -= TASK_TOOLS
            if agent == "scheduled":
                expected |= {"propose_task", "propose_reminder"}
            # Setting up routines is the Routines agent's job now.
            expected |= ROUTINE_TOOLS
            assert kept_out == expected, key
        shown = tools.shown_for(agent, has_email == "True")
        expected_shown = old["shown"]
        if agent in {"session", "scheduled"} and expected_shown is not None:
            expected_shown = sorted({*expected_shown, "create_tasks", "create_reminders"})
        assert (sorted(shown) if shown is not None else None) == expected_shown, key
    assert team.TASK_ORIGIN in {key.split("|")[1] for key in TOOLS_GOLDEN}


def test_every_owned_job_has_one_owner_that_exists() -> None:
    from nexusai.modules.agent import jobs

    owned = jobs.owned_tools()
    assert set(owned) == {
        "record_triage", "save_what_i_learned", "propose_task", "propose_reminder",
        "read_plate", "update_brief", *ROUTINE_TOOLS,
    }  # fmt: skip
    for job in jobs.OWNED:
        assert job.owner in cards._files(), job.name
    assert "organizer" not in cards._files()


def test_a_tool_of_another_agents_job_names_who_to_hand_it_to() -> None:
    from nexusai.modules.agent import jobs

    assert jobs.handed_over_tools("session") == {
        "record_triage": "mail", "save_what_i_learned": "mail",
        "read_plate": "daily-prep", "update_brief": "daily-prep",
        **{tool: "routines" for tool in ROUTINE_TOOLS},
    }  # fmt: skip
    # Suggestions aren't handed over: the lead makes the task itself.
    assert not TASK_TOOLS & set(jobs.handed_over_tools("session"))
    assert "propose_task" in jobs.withheld_for("session")
    assert jobs.handed_over_tools("mail") == {
        "read_plate": "daily-prep",
        "update_brief": "daily-prep",
        **{tool: "routines" for tool in ROUTINE_TOOLS},
    }


def test_the_organizers_chats_tasks_and_messages_become_the_leads(client: TestClient) -> None:
    """What the Organizer left behind is the lead's after the fold, so nothing has no agent."""
    from nexusai.modules.agent import module as agent

    db = agent.current().db
    now = "2026-11-20T10:00:00+00:00"
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_sessions (id, title, agent, status, created, updated)"
            " VALUES ('org-chat', 'Task 3', 'organizer', 'idle', ?, ?)",
            (now, now),
        )
        tx.execute(
            "INSERT INTO team_tasks (objective, expected_output, done_criteria, assigner, owner,"
            " state, budget_tokens, created, updated)"
            " VALUES ('Add a task', 'Its id', 'It exists', 'session', 'organizer', 'working', 1000, ?, ?)",
            (now, now),
        )
        tx.execute(
            "INSERT INTO agent_channel (sender, recipient, text, time, sender_agent)"
            " VALUES ('organizer', 'session', 'Added task 4.', ?, 'organizer')",
            (now,),
        )
    fold = next(m for m in agent.agent_module.migrations if m.id == "agent_organizer_folded_001")
    with db.transaction() as tx:
        for statement in filter(None, (part.strip() for part in fold.sql.split(";"))):
            tx.execute(statement)
    assert db.fetch_all("SELECT agent FROM agent_sessions WHERE id = 'org-chat'")[0]["agent"] == (
        "session"
    )
    assert {r["owner"] for r in db.fetch_all("SELECT owner FROM team_tasks")} == {"session"}
    row = db.fetch_all("SELECT sender, sender_agent FROM agent_channel")[0]
    assert (row["sender"], row["sender_agent"]) == ("session", "session")
