"""Where the agent's outside tools come from: Email, always, and any MCP server the person adds."""

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import structlog

from nexusai.contracts.connectors import (
    AddConnector,
    Connector,
    ConnectorAction,
    Connectors,
    ConnectorState,
    ConnectorTest,
    ConnectorTool,
    GetConnectors,
    SetConnectorEnabled,
    TestConnector,
)
from nexusai.contracts.mail import GetMailStatus, MailStatus
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.kernel.secrets import secret_store
from nexusai.modules.connectors import client
from nexusai.modules.connectors.client import ConnectorUnavailable
from nexusai.modules.mail import module as mail

log = structlog.get_logger()
connectors_module = Module(
    name="connectors",
    migrations=[
        Migration(
            "connectors_001",
            """
CREATE TABLE connectors (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, audience TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL, detail TEXT, tools TEXT NOT NULL DEFAULT '[]', tools_hash TEXT NOT NULL, new_tools TEXT, created TEXT NOT NULL);
""",
        )
    ],
)
EMAIL = "email"
PREFIX = "mcp_"
# The model API only takes this much of a name, in these characters.
NAME_LIMIT = 64
NOT_NAME = re.compile(r"[^a-zA-Z0-9_-]+")
DESCRIPTION_LIMIT = 1000
LIST_SECONDS = 10.0
CALL_SECONDS = 60.0
EMAIL_STATES: dict[str, tuple[ConnectorState, str]] = {
    "live": ("ok", "Up to date"),
    "off": ("off", "Not connected"),
    "failed": ("failed", "It couldn't sign in"),
    "offline": ("failed", "It can't reach the server"),
}


@dataclass(frozen=True)
class AgentTool:
    id: str
    name: str
    description: str
    parameters: dict[str, Any]
    connector: str
    connector_name: str
    url: str
    audience: str


def _token_key(identifier: str) -> str:
    return f"connector:{identifier}"


def _slug(name: str) -> str:
    return NOT_NAME.sub("-", name.lower()).strip("-")[:30] or "server"


def _tool_id(connector: str, name: str) -> str:
    return f"{PREFIX}{connector}_{NOT_NAME.sub('_', name)}"[:NAME_LIMIT]


def _tools_from(identifier: str, listed: list[client.Listed]) -> list[dict[str, Any]]:
    return [
        {
            "id": _tool_id(identifier, tool.name),
            "name": tool.name,
            "description": tool.description[:DESCRIPTION_LIMIT],
            "parameters": tool.parameters,
        }
        for tool in listed
    ]


def _hash(tools: list[dict[str, Any]]) -> str:
    """Covers descriptions too, because the model reads them and they could carry instructions."""
    return hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()


def _token(ctx: Context, identifier: str) -> str | None:
    return secret_store(ctx.config.secrets_test_file).get(_token_key(identifier))


def _announce(ctx: Context, identifier: str, state: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "connectors.changed",
            {"id": identifier, "state": state},
            source="connectors",
            trace_id=ctx.trace_id,
        )


def _email(ctx: Context) -> Connector:
    status = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    state, detail = EMAIL_STATES.get(status.state, ("ok", "Downloading"))
    return Connector(
        id=EMAIL,
        name="Email",
        kind=EMAIL,
        state=state,
        detail=status.message or detail,
        enabled=status.account is not None,
    )


def _row(ctx: Context, row: Any) -> Connector:
    # While changed tools wait for a yes, what's listed is the new set, so it can be read first.
    tools = json.loads(row["new_tools"] or row["tools"])
    return Connector(
        id=row["id"],
        name=row["name"],
        kind="mcp",
        url=row["url"],
        audience=row["audience"],
        enabled=bool(row["enabled"]),
        state=row["state"] if row["enabled"] else "off",
        detail=row["detail"],
        tools=[ConnectorTool(**tool) for tool in tools],
        has_token=_token(ctx, row["id"]) is not None,
    )


def _everything(ctx: Context) -> Connectors:
    rows = ctx.bus.db.fetch_all("SELECT * FROM connectors ORDER BY created")
    return Connectors(connectors=[_email(ctx), *[_row(ctx, row) for row in rows]])


@connectors_module.query("connectors.list")
def list_connectors(query: GetConnectors, ctx: Context) -> Connectors:
    return _everything(ctx)


@connectors_module.command("connectors.test")
def test_connector(command: TestConnector, ctx: Context) -> ConnectorTest:
    try:
        client.check_url(command.url)
        listed = client.list_tools(command.url, command.token, LIST_SECONDS)
    except ConnectorUnavailable as error:
        return ConnectorTest(ok=False, error=str(error))
    tools = _tools_from("new", listed)
    return ConnectorTest(ok=True, tools=[ConnectorTool(**tool) for tool in tools])


def _free_id(ctx: Context, name: str) -> str:
    slug = _slug(name)
    taken = {row["id"] for row in ctx.bus.db.fetch_all("SELECT id FROM connectors")}
    if slug not in taken and slug != EMAIL:
        return slug
    number = 2
    while f"{slug}-{number}" in taken:
        number += 1
    return f"{slug}-{number}"


@connectors_module.command("connectors.add")
def add_connector(command: AddConnector, ctx: Context) -> Connectors:
    identifier = _free_id(ctx, command.name)
    try:
        client.check_url(command.url)
        listed = client.list_tools(command.url, command.token, LIST_SECONDS)
    except ConnectorUnavailable as error:
        raise CommandError("connector.unreachable", str(error), 422) from error
    tools = _tools_from(identifier, listed)
    if command.token:
        secret_store(ctx.config.secrets_test_file).set(_token_key(identifier), command.token)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO connectors (id, name, url, audience, state, tools, tools_hash, created)"
            " VALUES (?, ?, ?, ?, 'ok', ?, ?, ?)",
            (
                identifier,
                command.name,
                command.url,
                command.audience,
                json.dumps(tools),
                _hash(tools),
                datetime.now(UTC).isoformat(),
            ),
        )
    _announce(ctx, identifier, "ok")
    return _everything(ctx)


def _found(ctx: Context, identifier: str) -> Any:
    rows = ctx.bus.db.fetch_all("SELECT * FROM connectors WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("connector.not_found", "That connector no longer exists.", 404)
    return rows[0]


def _refresh(ctx: Context, row: Any) -> str:
    identifier = row["id"]
    detail: str | None
    try:
        listed = client.list_tools(row["url"], _token(ctx, identifier), LIST_SECONDS)
    except ConnectorUnavailable as error:
        state, detail, new_tools = "failed", str(error), row["new_tools"]
    else:
        tools = _tools_from(identifier, listed)
        changed = _hash(tools) != row["tools_hash"]
        state = "changed" if changed else "ok"
        detail = (
            "Its tools have changed, so they're stopped until you check them." if changed else None
        )
        new_tools = json.dumps(tools) if changed else None
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE connectors SET state = ?, detail = ?, new_tools = ? WHERE id = ?",
            (state, detail, new_tools, identifier),
        )
    if state != row["state"]:
        _announce(ctx, identifier, state)
    return state


@connectors_module.command("connectors.refresh")
def refresh_connector(command: ConnectorAction, ctx: Context) -> Connectors:
    _refresh(ctx, _found(ctx, command.id))
    _announce(ctx, command.id, "refreshed")
    return _everything(ctx)


@connectors_module.command("connectors.approve")
def approve_connector(command: ConnectorAction, ctx: Context) -> Connectors:
    """The person has read the changed tools, so they become the ones in use."""
    row = _found(ctx, command.id)
    if row["new_tools"]:
        tools = json.loads(row["new_tools"])
        with ctx.bus.db.transaction() as tx:
            tx.execute(
                "UPDATE connectors SET state = 'ok', detail = NULL, tools = ?, tools_hash = ?, new_tools = NULL WHERE id = ?",
                (row["new_tools"], _hash(tools), command.id),
            )
    _announce(ctx, command.id, "ok")
    return _everything(ctx)


@connectors_module.command("connectors.setEnabled")
def set_enabled(command: SetConnectorEnabled, ctx: Context) -> Connectors:
    _found(ctx, command.id)
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE connectors SET enabled = ? WHERE id = ?", (int(command.enabled), command.id)
        )
    _announce(ctx, command.id, "enabled" if command.enabled else "off")
    return _everything(ctx)


@connectors_module.command("connectors.remove")
def remove_connector(command: ConnectorAction, ctx: Context) -> Connectors:
    _found(ctx, command.id)
    secret_store(ctx.config.secrets_test_file).delete(_token_key(command.id))
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM connectors WHERE id = ?", (command.id,))
    _announce(ctx, command.id, "removed")
    return _everything(ctx)


def list_mcp(ctx: Context) -> list[Any]:
    return ctx.bus.db.fetch_all("SELECT id, state FROM connectors WHERE enabled = 1")


def agent_tools(ctx: Context) -> list[AgentTool]:
    """Read from what's saved, so starting an agent never waits on the network."""
    rows = ctx.bus.db.fetch_all(
        "SELECT * FROM connectors WHERE enabled = 1 AND state != 'changed' ORDER BY created"
    )
    return [
        AgentTool(
            id=tool["id"],
            name=tool["name"],
            description=tool["description"],
            parameters=tool["parameters"],
            connector=row["id"],
            connector_name=row["name"],
            url=row["url"],
            audience=row["audience"],
        )
        for row in rows
        for tool in json.loads(row["tools"])
    ]


def call(ctx: Context, tool: AgentTool, arguments: dict[str, Any]) -> str:
    """Words for the agent, whatever happens. A server being down shouldn't stop the run."""
    try:
        text, failed = client.call_tool(
            tool.url, _token(ctx, tool.connector), tool.name, arguments, CALL_SECONDS
        )
    except ConnectorUnavailable as error:
        return f"That didn't work: {error}"
    return f"The server reported an error: {text}" if failed else text or "It returned nothing."


def _check_all(ctx: Context) -> None:
    for row in ctx.bus.db.fetch_all("SELECT * FROM connectors WHERE enabled = 1"):
        try:
            _refresh(ctx, row)
        except Exception:
            log.exception("connector_check_failed", connector=row["id"])


def _start(ctx: Context) -> None:
    # In the background, because a slow server shouldn't hold up the app opening.
    threading.Thread(target=_check_all, args=(ctx,), daemon=True, name="connectors").start()


connectors_module.on_start.append(_start)


def _forget(ctx: Context) -> None:
    store = secret_store(ctx.config.secrets_test_file)
    for row in ctx.bus.db.fetch_all("SELECT id FROM connectors"):
        store.delete(_token_key(row["id"]))


connectors_module.on_reset.append(_forget)
