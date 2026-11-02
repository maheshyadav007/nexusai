from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Density = Literal["compact", "comfortable", "spacious"]
TextSize = Literal["small", "medium", "large"]
Tone = Literal["formal", "friendly", "brief"]
Accent = Literal["terracotta", "cobalt", "moss", "plum"]
DefaultScreen = Literal["today", "inbox"]
DateFormat = Literal["system", "day-month", "month-day", "iso"]
RemoteImages = Literal["load", "block"]
TimeFormat = Literal["system", "12", "24"]
THEME_ID_PATTERN = r"^[a-z0-9-]+$"


class Settings(BaseModel):
    theme: str = Field(pattern=THEME_ID_PATTERN, max_length=64)
    density: Density
    text_size: TextSize
    accent: Accent
    default_screen: DefaultScreen
    date_format: DateFormat
    time_format: TimeFormat
    remote_images: RemoteImages
    sound_muted: bool
    # Kinds of notification that make no sound.
    sound_off: list[str]


class GetSettings(BaseModel):
    pass


class UpdateSettings(BaseModel):
    """Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    theme: str | None = Field(default=None, pattern=THEME_ID_PATTERN, max_length=64)
    density: Density | None = None
    text_size: TextSize | None = None
    accent: Accent | None = None
    default_screen: DefaultScreen | None = None
    date_format: DateFormat | None = None
    time_format: TimeFormat | None = None
    remote_images: RemoteImages | None = None
    sound_muted: bool | None = None
    sound_off: list[str] | None = None


class Profile(BaseModel):
    name: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    signature: str = Field(default="", max_length=2000)
    tone: Tone = "friendly"
    vips: str = Field(default="", max_length=4000)
    about: str = Field(default="", max_length=8000)


class GetProfile(BaseModel):
    pass


class ProfileChanged(BaseModel):
    """Which fields changed, not what they now say."""

    fields: list[str]


class GetSidebar(BaseModel):
    pass


class ResetSidebar(BaseModel):
    pass


class SidebarLayout(BaseModel):
    """Order and visibility only. Unknown or missing IDs are ignored, so updates add new items."""

    model_config = ConfigDict(extra="forbid")

    sections: list[str] = Field(default_factory=list, max_length=64)
    items: dict[str, list[str]] = Field(default_factory=dict)
    hidden: list[str] = Field(default_factory=list, max_length=256)


class SidebarChanged(BaseModel):
    reset: bool


class SettingsChanged(BaseModel):
    changed: dict[str, str | bool | list[str]]
