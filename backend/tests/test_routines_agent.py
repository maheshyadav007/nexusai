# ruff: noqa: F811
"""Setting up routines is the Routines agent's job (To do 1 and 10). The lead hands it over,
and the Routines agent makes them, with only what it needs to write them well."""

from fastapi.testclient import TestClient

from nexusai.modules.agent import cards, tools
from nexusai.modules.agent import module as agent_module
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import (
    Script,
    app_config,  # noqa: F401
    client,  # noqa: F401
    fake,  # noqa: F401
    script,  # noqa: F401
    wait,
)
from test_chat_engine_tools import chat, chat_in_background, last_result, new_session

FRIDAY = {
    "name": "Friday status",
    "instructions": "Write my team status from this week's sent mail.",
    "every": "week",
    "weekday": "Friday",
    "time": "17:00",
}


def test_the_lead_is_pointed_to_the_routines_agent(client: TestClient, script: Script) -> None:
    script.replies = [[ToolCall("a", "create_schedule", FRIDAY)], [TextChunk("Handing it on.")]]
    chat(client, new_session(client), "Every Friday at 5, write my team status")
    said = last_result(script)
    routines = cards.card(agent_module.current().db, "routines")
    assert routines is not None and said.startswith("Not run") and routines.at in said
    assert client.post("/api/queries/schedules.list").json()["schedules"] == [] or all(
        row["title"] != "Friday status"
        for row in client.post("/api/queries/schedules.list").json()["schedules"]
    )


def test_the_routines_agent_sets_one_up(client: TestClient, script: Script) -> None:
    script.replies = [
        [ToolCall("l", "list_schedules", {})],
        [ToolCall("c", "create_schedule", FRIDAY)],
        [TextChunk("Set up.")],
    ]
    done = chat_in_background(
        client, new_session(client), "@routines Every Friday at 5, write my team status"
    )
    approval = wait(
        lambda: client.post("/api/queries/approvals.list").json()["approvals"], "approval"
    )[0]
    assert approval["tool"] == "create_schedule"
    client.post("/api/commands/approvals.decide", json={"id": approval["id"], "choice": "once"})
    wait(lambda: done, "finish")
    titles = [
        row["title"] for row in client.post("/api/queries/schedules.list").json()["schedules"]
    ]
    assert "Friday status" in titles
    offered = {tool.name for tool in script.requests[0].tools}
    assert {"create_schedule", "update_schedule", "remove_schedules", "run_schedule"} <= offered
    # It reads to write routines well, but changes nothing else.
    assert not {"update_mail", "send_mail", "create_tasks", "run_command"} & offered


def test_only_the_routines_agent_has_the_routine_tools() -> None:
    owned = {"create_schedule", "update_schedule", "remove_schedules", "run_schedule"}
    assert owned <= tools.withheld_for("session") and owned <= tools.withheld_for("scheduled")
    assert not owned & tools.withheld_for("routines")
    assert owned <= (tools.allowed_for("routines", "person", False) or set())
    assert "ask_user" in (tools.allowed_for("routines", "person", False) or set())
    assert "ask_user" not in (tools.allowed_for("routines", "task", False) or set())


def test_the_morning_brief_is_listed_and_switched_with_the_built_in_routines(
    client: TestClient,
) -> None:
    listed = client.post("/api/queries/schedules.list").json()
    assert listed["morning_brief_enabled"] is True and listed["morning_brief_time"] == "08:30"
    off = client.post(
        "/api/commands/schedules.setDefaults", json={"morning_brief_enabled": False}
    ).json()
    assert off["morning_brief_enabled"] is False and off["morning_brief_next"] is None
    # The same switch the Mail agent's settings show.
    settings = client.post("/api/queries/mailAgent.get").json()
    assert settings["morning_brief"] is False
    on = client.post(
        "/api/commands/schedules.setDefaults", json={"morning_brief_enabled": True}
    ).json()
    assert on["morning_brief_enabled"] is True and on["morning_brief_next"]


def test_the_agents_page_says_what_each_agent_does_and_what_starts_it(client: TestClient) -> None:
    listed = {c["id"]: c for c in client.post("/api/queries/agents.cards").json()["cards"]}
    mail = listed["mail"]
    assert mail["plugin"] == "Mail" and mail["reads_untrusted_mail"] is True
    assert mail["jobs"] == [
        "reading each email and recording what it holds",
        "suggesting tasks and reminders from mail for the person to keep",
    ]
    assert {"key": "on-new-mail", "time": None} in mail["starts"]
    assert "drafting-replies" in mail["skills"]
    brief = listed["daily-prep"]
    assert brief["starts"] == [{"key": "every-morning", "time": "08:30"}]
    assert listed["routines"]["plugin"] == "Routines" and listed["session"]["jobs"] == []
