# ruff: noqa: F811
"""Installing a plugin: its skills as proposals the person reviews, its MCP servers as connectors
with the settings they ask for, the rest listed as not used, and all of it removed as one."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mcp import URL, FakeMcp, running
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
        connector = added.json()["connectors"][0]
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
