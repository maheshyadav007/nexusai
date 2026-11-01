"""Writes JSON Schema for every contract, which the frontend turns into TypeScript types."""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nexusai.contracts.errors import ApiError
from nexusai.contracts.events import AppEvent, EventLog, EventLogQuery, FailedEvent
from nexusai.contracts.home import (
    BrowseFolders,
    CheckHome,
    ChooseHome,
    FolderListing,
    HomeCheck,
    HomeStatus,
)
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
from nexusai.contracts.notifications import (
    ListNotifications,
    MarkNotificationsRead,
    Notification,
    NotificationList,
    NotificationRequested,
    NotificationsChanged,
)
from nexusai.contracts.onboarding import (
    FinishOnboarding,
    GetOnboarding,
    OnboardingChanged,
    OnboardingState,
    SetOnboardingStep,
)
from nexusai.contracts.settings import (
    GetProfile,
    GetSettings,
    GetSidebar,
    Profile,
    ProfileChanged,
    ResetSidebar,
    Settings,
    SettingsChanged,
    SidebarChanged,
    SidebarLayout,
    UpdateSettings,
)
from nexusai.contracts.system import (
    CheckNetwork,
    Diagnostics,
    GetDiagnostics,
    GetTrace,
    LogLines,
    NetworkCheck,
    NetworkChecks,
    SearchLogs,
    TraceView,
)

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
    BrowseFolders,
    CheckHome,
    ChooseHome,
    FolderListing,
    HomeCheck,
    HomeStatus,
    FinishOnboarding,
    GetOnboarding,
    OnboardingChanged,
    OnboardingState,
    SetOnboardingStep,
    GetProfile,
    Profile,
    ProfileChanged,
    ListNotifications,
    MarkNotificationsRead,
    Notification,
    NotificationList,
    NotificationRequested,
    NotificationsChanged,
    GetSidebar,
    ResetSidebar,
    SidebarChanged,
    SidebarLayout,
    CheckNetwork,
    Diagnostics,
    GetDiagnostics,
    GetTrace,
    LogLines,
    NetworkCheck,
    NetworkChecks,
    SearchLogs,
    TraceView,
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
