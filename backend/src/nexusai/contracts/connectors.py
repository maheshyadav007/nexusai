from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectorState = Literal["ok", "failed", "changed", "off"]
Audience = Literal["internal", "public"]


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


class Connectors(BaseModel):
    connectors: list[Connector]


class TestConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    token: str | None = Field(default=None, max_length=8000)


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


class ConnectorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)


class SetConnectorEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    enabled: bool
