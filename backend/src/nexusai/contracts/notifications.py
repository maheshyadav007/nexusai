from pydantic import BaseModel, ConfigDict, Field


class NotificationRequested(BaseModel):
    """Any module asks for a notification by emitting this. Holds short facts, not content."""

    kind: str = Field(pattern=r"^[a-z-]+$", max_length=32)
    title: str = Field(max_length=200)
    detail: str = Field(default="", max_length=500)
    link: str | None = Field(default=None, max_length=500)


class Notification(BaseModel):
    id: int
    time: str
    kind: str
    title: str
    detail: str
    link: str | None
    read: bool


class ListNotifications(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(default=None, max_length=32)


class NotificationList(BaseModel):
    items: list[Notification]
    unread: int
    kinds: list[str]


class MarkNotificationsRead(BaseModel):
    """No id means all of them."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None


class NotificationsChanged(BaseModel):
    unread: int
