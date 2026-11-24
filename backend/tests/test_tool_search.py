"""Agents are shown the tools they use most, and find the rest when they need them."""
# ruff: noqa: F811

from fastapi.testclient import TestClient

from nexusai.modules.agent import module as agent_module
from nexusai.modules.agent import tools
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import Script, app_config, client, fake, script  # noqa: F401


def offered(request: object) -> set[str]:
    return {tool.name for tool in request.tools}  # type: ignore[attr-defined]


def test_the_lead_starts_small_and_a_found_tool_stays_offered(
    client: TestClient, script: Script
) -> None:
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.replies = [
        [ToolCall("a", "find_tools", {"query": "save a mail rule"})],
        [ToolCall("b", "list_rules", {})],
        [TextChunk("Done.")],
    ]
    with client.stream("POST", "/api/sessions/chat", json={"id": session, "text": "Go"}) as r:
        list(r.iter_lines())
    first, second, third = (offered(request) for request in script.requests[-3:])
    assert "find_tools" in first and "remember" in first and "list_memory" in first
    assert "save_rule" not in first and "run_command" not in first
    # What its prompt reaches for first, out of the 80 or so it may use.
    assert "open_item" in first and "find_matters" in first and "list_rules" in first
    assert len(first) < 35
    assert "save_rule" in second and "list_rules" in second
    assert "save_rule" in third


def test_finding_matches_words_and_lists_everything_when_nothing_matches(
    client: TestClient,
) -> None:
    ctx = agent_module.current().ctx
    catalog = tools.build_tools(ctx, "s", tools.RunControl())
    found = tools.find(catalog, "add a reminder")
    assert "- create_reminders:" in found
    nothing = tools.find(catalog, "zzzz")
    assert "No tool matches" in nothing and "save_rule" in nothing


def test_judging_mail_and_the_interview_see_their_whole_small_set() -> None:
    assert tools.shown_for("mail", True) is None
    assert tools.shown_for("interview", False) is None
    assert tools.shown_for("daily-prep", False) is None
    for shown in (tools.LEAD_SHOWN, tools.MAIL_SHOWN):
        assert shown >= tools.ALWAYS_SHOWN


def test_it_can_be_turned_off(client: TestClient, script: Script, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("NEXUSAI_TOOL_SEARCH", "off")
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    script.replies = [[TextChunk("Hi.")]]
    with client.stream("POST", "/api/sessions/chat", json={"id": session, "text": "Go"}) as r:
        list(r.iter_lines())
    shown = offered(script.requests[-1])
    assert "save_rule" in shown and "find_tools" not in shown
