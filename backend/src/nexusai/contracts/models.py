from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LoginState = Literal["idle", "waiting", "failed"]


class GetModelStatus(BaseModel):
    pass


class ModelLogin(BaseModel):
    """A sign-in in progress. The code is shown to the user; it isn't a credential by itself."""

    state: LoginState
    user_code: str | None = None
    verification_url: str | None = None
    error: str | None = None


class ModelStatus(BaseModel):
    """Never carries tokens."""

    connected: bool
    account_email: str | None = None
    plan: str | None = None
    selected_model: str | None = None
    login: ModelLogin


class StartModelLogin(BaseModel):
    pass


class CancelModelLogin(BaseModel):
    pass


class DisconnectModel(BaseModel):
    pass


class ListModels(BaseModel):
    pass


class AvailableModel(BaseModel):
    id: str
    name: str


class AvailableModels(BaseModel):
    models: list[AvailableModel]


class SelectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=128)


class TestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)


class ModelReply(BaseModel):
    model: str
    text: str


class ModelsChanged(BaseModel):
    """Facts only: no codes, tokens or account details."""

    change: Literal[
        "login_started", "login_failed", "login_cancelled", "connected", "disconnected", "selected"
    ]
