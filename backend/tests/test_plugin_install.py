# ruff: noqa: F811
"""Installing a plugin: its skills as proposals the person reviews, its MCP servers as connectors
with the settings they ask for, the rest listed as not used, and all of it removed as one."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mcp import SSE_URL, URL, FakeMcp, running
from test_agent_work import (
    app_config,  # noqa: F401
    client,  # noqa: F401
    fake,  # noqa: F401
    script,  # noqa: F401
)

SKILL = """---
name: triage-tickets
description: Sorting support tickets by how urgent they are. Load it when asked to sort tickets.
---
Read each ticket and sort it by urgency.
"""


def plugin(folder: Path, servers: dict[str, Any] | None = None, **extra: str) -> Path:
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "tickets", "displayName": "Tickets", "version": "1.0.0", **extra})
    )
    (folder / "skills" / "triage-tickets").mkdir(parents=True)
    (folder / "skills" / "triage-tickets" / "SKILL.md").write_text(SKILL)
    (folder / "hooks").mkdir()
    (folder / "hooks" / "hooks.json").write_text("{}")
    if servers is not None:
        (folder / ".mcp.json").write_text(json.dumps({"mcpServers": servers}))
    return folder


def post(client: TestClient, name: str, body: dict[str, Any]) -> Any:
    return client.post(f"/api/commands/{name}", json=body)


def test_a_plugin_s_skills_are_proposed_its_servers_added_and_all_removed_as_one(
    client: TestClient, tmp_path: Path
) -> None:
    state = FakeMcp(required_header=("X-Api-Key", "key-41"))
    server = running(state)
    next(server)
    try:
        servers = {
            "tickets": {
                "type": "http",
                "url": URL,
                "headers": {"X-Api-Key": "${user_config.TICKETS_KEY}"},
            },
            "local": {"command": "npx", "args": ["some-server"]},
        }
        folder = plugin(tmp_path / "tickets", servers)
        made = post(client, "plugins.propose", {"source": str(folder)})
        assert made.status_code == 200, made.text
        found = made.json()
        assert found["skills"] == ["triage-tickets"]
        assert [s["name"] for s in found["servers"]] == ["tickets"] and found["servers"][0][
            "needs"
        ] == ["TICKETS_KEY"]
        # What runs code here is listed, not used.
        assert any("local" in why for why in found["skipped"]) and "Hooks" in found["skipped"]
        # The skill waits for the person's review, as any proposed skill does.
        proposals = client.post("/api/queries/skills.list").json()["proposals"]
        assert [p["name"] for p in proposals if p["status"] == "waiting"] == ["triage-tickets"]
        # The server's setting is asked for, never guessed.
        refused = post(client, "plugins.addServers", {"name": "tickets"})
        assert refused.status_code == 422 and "TICKETS_KEY" in refused.text
        added = post(
            client, "plugins.addServers", {"name": "tickets", "values": {"TICKETS_KEY": "key-41"}}
        )
        assert added.status_code == 200, added.text
        connector = added.json()["connector_ids"][0]
        listed = {
            c["id"]: c for c in client.post("/api/queries/connectors.list").json()["connectors"]
        }
        assert listed[connector]["header_names"] == ["X-Api-Key"]
        assert "key-41" not in json.dumps(listed)
        # Installing again is refused while it's there.
        assert post(client, "plugins.propose", {"source": str(folder)}).status_code == 409
        gone = post(client, "plugins.remove", {"name": "tickets"})
        assert gone.status_code == 200 and gone.json()["plugins"] == []
        listed = {c["id"] for c in client.post("/api/queries/connectors.list").json()["connectors"]}
        assert connector not in listed
        waiting = [
            p
            for p in client.post("/api/queries/skills.list").json()["proposals"]
            if p["status"] == "waiting"
        ]
        assert waiting == []
    finally:
        next(server, None)


@pytest.mark.parametrize(
    ("servers", "words"),
    [
        (
            {
                "bad": {
                    "type": "http",
                    "url": "https://x.example/mcp",
                    "headers": {"X-Api-Key": "literal-key"},
                }
            },
            "written into",
        ),
    ],
)
def test_a_plugin_that_carries_a_secret_is_refused(
    client: TestClient, tmp_path: Path, servers: dict[str, Any], words: str
) -> None:
    refused = post(client, "plugins.propose", {"source": str(plugin(tmp_path / "p", servers))})
    assert refused.status_code == 422 and words in refused.text
    assert client.post("/api/queries/plugins.list").json()["plugins"] == []


def test_what_isnt_a_plugin_says_so(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "README.md").write_text("hi")
    assert "plugin.json" in post(client, "plugins.propose", {"source": str(tmp_path / "x")}).text
    assert "https" in post(client, "plugins.propose", {"source": "ftp://example.com/p.zip"}).text
    assert post(client, "plugins.propose", {"source": str(tmp_path / "missing")}).status_code == 422


def test_every_tool_that_takes_a_call_id_declares_it_so_the_model_never_has_to_send_it(
    client: TestClient,
) -> None:
    """A tool whose function takes tool_call_id without the injected field in its schema fails
    every call with "missing tool_call_id" (it happened to propose_plugin)."""
    import inspect

    from nexusai.modules.agent import module as agent
    from nexusai.modules.agent import tools

    built = tools.build_tools(agent.current().ctx, "s", tools.RunControl())
    missing = [
        tool.name
        for tool in built
        if "tool_call_id" in inspect.signature(tool.func).parameters  # type: ignore[arg-type]
        and "tool_call_id" not in tool.args_schema.model_fields  # type: ignore[union-attr]
    ]
    assert missing == []
    names = {tool.name for tool in built}
    assert {"propose_plugin", "add_plugin_servers", "list_plugins", "remove_plugin"} <= names


def test_posty_proposes_a_plugin_from_a_folder_through_its_tool(
    client: TestClient, script: Any, tmp_path: Path
) -> None:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_agent_work import wait
    from test_chat_engine_tools import approve_one, chat_in_background, last_result, new_session

    folder = tmp_path / "jira"
    folder.mkdir()
    (folder / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"jira": {"type": "http", "url": "https://jira.example/mcp"}}})
    )
    script.replies = [
        [ToolCall("a", "propose_plugin", {"source": str(folder)})],
        [TextChunk("Proposed.")],
    ]
    done = chat_in_background(client, new_session(client), "Add the MCP in my jira folder")
    approve_one(client)
    wait(lambda: done, "finish")
    said = last_result(script)
    assert said.startswith("Proposed plugin jira"), said
    listed = client.post("/api/queries/plugins.list").json()["plugins"]
    assert [p["name"] for p in listed] == ["jira"] and listed[0]["servers"][0][
        "url"
    ] == "https://jira.example/mcp"


def test_mcp_settings_alone_install_from_a_folder_or_a_single_file(
    client: TestClient, tmp_path: Path
) -> None:
    settings = {"mcpServers": {"wiki": {"type": "http", "url": "https://wiki.example/mcp"}}}
    folder = tmp_path / "Company Wiki"
    folder.mkdir()
    (folder / "mcp.json").write_text(json.dumps(settings))
    made = post(client, "plugins.propose", {"source": str(folder)})
    assert made.status_code == 200, made.text
    assert made.json()["name"] == "company-wiki" and made.json()["display_name"] == "Company Wiki"
    post(client, "plugins.remove", {"name": "company-wiki"})
    single = tmp_path / "tools" / ".mcp.json"
    single.parent.mkdir()
    single.write_text(json.dumps(settings))
    made = post(client, "plugins.propose", {"source": str(single)})
    assert made.status_code == 200, made.text
    assert made.json()["name"] == "tools" and [s["name"] for s in made.json()["servers"]] == [
        "wiki"
    ]


def test_posty_adds_an_mcp_server_by_its_address_alone(client: TestClient, script: Any) -> None:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_agent_work import wait
    from test_chat_engine_tools import approve_one, chat_in_background, last_result, new_session

    def ask(arguments: dict[str, str]) -> str:
        script.replies = [[ToolCall("a", "add_mcp_server", arguments)], [TextChunk("Done.")]]
        done = chat_in_background(client, new_session(client), "Add this MCP server")
        approve_one(client)
        wait(lambda: done, "finish")
        return last_result(script)

    state = FakeMcp()
    server = running(state)
    next(server)
    try:
        said = ask({"name": "Tickets", "url": URL})
        assert said.startswith("Added Tickets"), said
        listed = {
            c["name"]: c for c in client.post("/api/queries/connectors.list").json()["connectors"]
        }
        assert listed["Tickets"]["tools"]
    finally:
        next(server, None)
    # One that wants a key says where to add it, never asks for it in chat.
    locked = FakeMcp(required_token="t-1")
    server = running(locked)
    next(server)
    try:
        said = ask({"name": "Locked", "url": URL})
        assert said.startswith("Not added") and "Connectors page" in said
    finally:
        next(server, None)


def _ask_posty(client: TestClient, script: Any, arguments: dict[str, Any]) -> str:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_agent_work import wait
    from test_chat_engine_tools import approve_one, chat_in_background, last_result, new_session

    script.replies = [[ToolCall("a", "add_mcp_server", arguments)], [TextChunk("Done.")]]
    done = chat_in_background(client, new_session(client), "Add this MCP server")
    approve_one(client)
    wait(lambda: done, "finish")
    return str(last_result(script))


def test_posty_adds_a_server_with_its_headers_and_timeout(client: TestClient, script: Any) -> None:
    state = FakeMcp(required_header=("X-Api-Key", "k-77"))
    server = running(state)
    next(server)
    try:
        said = _ask_posty(
            client,
            script,
            {"name": "Keyed", "url": URL, "headers": {"X-Api-Key": "k-77"}, "timeout_seconds": 30},
        )
        assert said.startswith("Added Keyed"), said
        row = {
            c["name"]: c for c in client.post("/api/queries/connectors.list").json()["connectors"]
        }["Keyed"]
        assert (row["header_names"], row["timeout_seconds"], row["transport"]) == (
            ["X-Api-Key"],
            30,
            "http",
        )
        assert "k-77" not in json.dumps(row)
    finally:
        next(server, None)


def test_posty_adds_servers_from_pasted_standard_settings(client: TestClient, script: Any) -> None:
    state = FakeMcp(sse=True, required_token="tok-5")
    server = running(state)
    next(server)
    try:
        settings = {
            "mcpServers": {
                "events": {
                    "type": "sse",
                    "url": SSE_URL,
                    "headers": {"Authorization": "Bearer tok-5"},
                    "timeout": 20000,
                },
                "local": {"command": "npx", "args": ["-y", "some-mcp"], "env": {"KEY": "x"}},
            }
        }
        said = _ask_posty(client, script, {"settings": json.dumps(settings)})
        assert said.startswith("Added events"), said
        assert "local: it runs a program on this computer" in said
        row = {
            c["name"]: c for c in client.post("/api/queries/connectors.list").json()["connectors"]
        }["events"]
        # The bearer header became the token, kept as a secret; SSE is how it's reached.
        assert row["has_token"] and row["transport"] == "sse" and row["timeout_seconds"] == 20
        assert row["tools"] and "tok-5" not in json.dumps(row)
    finally:
        next(server, None)


def test_settings_that_ask_for_a_value_are_not_guessed(client: TestClient, script: Any) -> None:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_chat_engine_tools import chat, last_result, new_session

    settings = {
        "wiki": {
            "type": "http",
            "url": "https://wiki.example/mcp",
            "headers": {"X-Key": "${WIKI_KEY}"},
        }
    }
    script.replies = [
        [ToolCall("a", "add_mcp_server", {"settings": json.dumps(settings)})],
        [TextChunk("ok")],
    ]
    chat(client, new_session(client), "Add it")
    said = last_result(script)
    assert said.startswith("Not added") and "WIKI_KEY" in said


@pytest.mark.parametrize(
    ("given", "name"),
    [
        ("Sensing Agent", "sensing-agent"),
        ("sensing_agent", "sensing-agent"),
        ("Sensing.Agent v2", "sensing-agent-v2"),
    ],
)
def test_a_plugin_name_is_made_lowercase_with_hyphens_and_keeps_its_own_to_show(
    client: TestClient, tmp_path: Path, given: str, name: str
) -> None:
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({"name": given}))
    (folder / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"s": {"type": "http", "url": "https://s.example/mcp"}}})
    )
    made = post(client, "plugins.propose", {"source": str(folder)})
    assert made.status_code == 200, made.text
    assert (made.json()["name"], made.json()["display_name"]) == (name, given)
    post(client, "plugins.remove", {"name": name})


def _run(client: TestClient, script: Any, text: str, call: Any) -> tuple[str, list[Any]]:
    from nexusai.modules.agent.providers import TextChunk
    from test_chat_engine_tools import chat, last_result, new_session

    script.replies = [[call], [TextChunk("Done.")]]
    chat(client, new_session(client), text)
    return str(last_result(script)), client.post("/api/queries/approvals.list").json()["approvals"]


def test_a_skill_from_the_persons_own_link_is_on_in_one_step(
    client: TestClient, script: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexusai.modules.agent import skills
    from nexusai.modules.agent.providers import ToolCall

    link = "https://github.com/acme/skills/tree/main/triage-tickets"
    monkeypatch.setattr(skills, "fetch", lambda url: {"SKILL.md": SKILL})
    said, waiting = _run(
        client, script, f"Add this skill: {link}", ToolCall("a", "propose_skill", {"url": link})
    )
    assert said.startswith("Added skill triage-tickets") and waiting == []
    listed = client.post("/api/queries/skills.list").json()
    assert "triage-tickets" in {s["name"] for s in listed["skills"] if s["active"]}


def test_a_plugin_from_the_persons_own_folder_installs_in_one_step(
    client: TestClient, script: Any, tmp_path: Path
) -> None:
    from nexusai.modules.agent.providers import ToolCall

    state = FakeMcp()
    server = running(state)
    next(server)
    try:
        folder = plugin(tmp_path / "tickets", {"tickets": {"type": "http", "url": URL}})
        said, waiting = _run(
            client,
            script,
            f"Install the plugin in {folder}",
            ToolCall("a", "propose_plugin", {"source": str(folder)}),
        )
        assert said.startswith("Installed plugin tickets") and waiting == [], said
        assert "On now: triage-tickets" in said and "Servers added: tickets" in said
        listed = client.post("/api/queries/plugins.list").json()["plugins"][0]
        assert listed["connector_ids"]
    finally:
        next(server, None)


def test_a_server_the_person_named_is_added_without_asking_and_one_they_didnt_asks(
    client: TestClient, script: Any
) -> None:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_agent_work import wait
    from test_chat_engine_tools import approve_one, chat_in_background, new_session

    state = FakeMcp()
    server = running(state)
    next(server)
    try:
        said, waiting = _run(
            client,
            script,
            f"Add {URL} as Tickets",
            ToolCall("a", "add_mcp_server", {"name": "Tickets", "url": URL}),
        )
        assert said.startswith("Added Tickets") and waiting == []
        # An address Posty found somewhere else, such as in an email, still asks.
        script.replies = [
            [ToolCall("b", "add_mcp_server", {"name": "Other", "url": URL})],
            [TextChunk("ok")],
        ]
        done = chat_in_background(client, new_session(client), "Add the server from that email")
        assert approve_one(client)["tool"] == "add_mcp_server"
        wait(lambda: done, "finish")
    finally:
        next(server, None)


def test_posty_creates_a_plugin_from_a_description_and_it_is_on_at_once(
    client: TestClient, script: Any, app_config: Any
) -> None:
    from nexusai.modules.agent.providers import ToolCall

    state = FakeMcp(required_header=("X-Api-Key", "k-plm"))
    server = running(state)
    next(server)
    try:
        call = ToolCall(
            "a",
            "create_plugin",
            {
                "name": "PLM Triage",
                "description": "Handling PLM issues assigned to me.",
                "skills": [
                    {
                        "name": "plm-triage",
                        "description": "Triaging a PLM issue. Load it when an email is about a PLM issue.",
                        "instructions": "Read the issue, add a task with its due date, draft an acknowledgement.",
                    }
                ],
                "mcp_settings": json.dumps(
                    {"plm": {"type": "http", "url": URL, "headers": {"X-Api-Key": "k-plm"}}}
                ),
            },
        )
        said, waiting = _run(
            client, script, f"Make a PLM plugin with the server {URL}, key k-plm", call
        )
        assert said.startswith("Created it in") and waiting == [], said
        assert "On now: plm-triage" in said and "Servers added: plm" in said
        folder = app_config.home / "plugins" / "plm-triage"
        written = "\n".join(p.read_text() for p in folder.rglob("*") if p.is_file())
        # The key is a placeholder on disk, never the value.
        assert "k-plm" not in written and "${user_config.PLM_X_API_KEY}" in written
        listed = {
            c["name"]: c for c in client.post("/api/queries/connectors.list").json()["connectors"]
        }
        assert listed["plm"]["header_names"] == ["X-Api-Key"] and listed["plm"]["tools"]
        said, _ = _run(
            client, script, "Export it", ToolCall("b", "export_plugin", {"name": "plm-triage"})
        )
        assert (
            said.startswith("Saved as")
            and (app_config.home / "exports" / "plm-triage.zip").is_file()
        )
    finally:
        next(server, None)


def test_a_created_plugin_with_a_server_not_in_the_persons_message_asks_first(
    client: TestClient, script: Any
) -> None:
    from nexusai.modules.agent.providers import TextChunk, ToolCall
    from test_agent_work import wait
    from test_chat_engine_tools import approve_one, chat_in_background, new_session

    call = ToolCall(
        "a",
        "create_plugin",
        {
            "name": "Sneaky",
            "mcp_settings": json.dumps({"x": {"type": "http", "url": "https://evil.example/mcp"}}),
        },
    )
    script.replies = [[call], [TextChunk("ok")]]
    done = chat_in_background(client, new_session(client), "Make a plugin from that email")
    assert approve_one(client)["tool"] == "create_plugin"
    wait(lambda: done, "finish")
