"""Writes JSON Schema for every contract, which the frontend turns into TypeScript types."""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nexusai.contracts.errors import ApiError
from nexusai.contracts.events import AppEvent, EventLog, EventLogQuery, FailedEvent
from nexusai.contracts.models import (
    AvailableModel,
    AvailableModels,
    CancelModelLogin,
    DisconnectModel,
    GetModelStatus,
    ListModels,
    ModelLogin,
    ModelReply,
    ModelsChanged,
    ModelStatus,
    SelectModel,
    StartModelLogin,
    TestModel,
)
from nexusai.contracts.settings import GetSettings, Settings, SettingsChanged, UpdateSettings

MODELS: list[type[BaseModel]] = [
    ApiError,
    AppEvent,
    EventLog,
    EventLogQuery,
    FailedEvent,
    GetSettings,
    Settings,
    SettingsChanged,
    UpdateSettings,
    AvailableModel,
    AvailableModels,
    CancelModelLogin,
    DisconnectModel,
    GetModelStatus,
    ListModels,
    ModelLogin,
    ModelReply,
    ModelsChanged,
    ModelStatus,
    SelectModel,
    StartModelLogin,
    TestModel,
]


def main() -> None:
    schema: dict[str, Any] = {"title": "Contracts", "type": "object", "properties": {}, "$defs": {}}
    for model in MODELS:
        model_schema = model.model_json_schema(ref_template="#/$defs/{model}")
        schema["$defs"].update(model_schema.pop("$defs", {}))
        schema["$defs"][model.__name__] = model_schema
        schema["properties"][model.__name__] = {"$ref": f"#/$defs/{model.__name__}"}
    Path(sys.argv[1]).write_text(json.dumps(schema, indent=2) + "\n")


if __name__ == "__main__":
    main()
