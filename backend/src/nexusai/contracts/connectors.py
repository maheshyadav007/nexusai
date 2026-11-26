from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectorState = Literal["ok", "failed", "changed", "off"]
Audience = Literal["internal", "public"]
Transport = Literal["http", "sse"]


class GetConnectors(BaseModel):
    pass


class ConnectorTool(BaseModel):
    # The name the agent uses, which also carries its permission in Settings.
    id: str
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class Connector(BaseModel):
    """Never carries a token."""

    id: str
    name: str
    kind: Literal["email", "mcp"]
    url: str | None = None
    audience: Audience | None = None
    enabled: bool = True
    state: ConnectorState
    detail: str | None = None
    tools: list[ConnectorTool] = Field(default_factory=list)
    has_token: bool = False
    # The names of the headers it sends, never their values.
    header_names: list[str] = Field(default_factory=list)
    transport: Transport = "http"
    timeout_seconds: int | None = None


class Connectors(BaseModel):
    connectors: list[Connector]


class TestConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    token: str | None = Field(default=None, max_length=8000)
    headers: dict[str, str] = Field(default_factory=dict, max_length=10)
    transport: Transport = "http"


class ConnectorTest(BaseModel):
    ok: bool
    error: str | None = None
    tools: list[ConnectorTool] = Field(default_factory=list)


class AddConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=2000)
    token: str | None = Field(default=None, max_length=8000)
    audience: Audience
    # Headers the server needs, such as an API key or a tenant id. Every value is kept as a
    # secret, never in the database, and never shown again or given to an agent.
    headers: dict[str, str] = Field(default_factory=dict, max_length=10)
    # How it's reached: streamable HTTP (the standard now) or the older server-sent events.
    transport: Transport = "http"
    # How long a tool call may take before it's given up, in seconds. None is the app's default.
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class ConnectorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class SetConnectorEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    enabled: bool
