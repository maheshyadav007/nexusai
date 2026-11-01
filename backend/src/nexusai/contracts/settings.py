from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Density = Literal["compact", "comfortable", "spacious"]
TextSize = Literal["small", "medium", "large"]
Tone = Literal["formal", "friendly", "brief"]
THEME_ID_PATTERN = r"^[a-z0-9-]+$"


class Settings(BaseModel):
    theme: str = Field(pattern=THEME_ID_PATTERN, max_length=64)
    density: Density
    text_size: TextSize


class GetSettings(BaseModel):
    pass


class UpdateSettings(BaseModel):
    """Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    theme: str | None = Field(default=None, pattern=THEME_ID_PATTERN, max_length=64)
    density: Density | None = None
    text_size: TextSize | None = None


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


class SettingsChanged(BaseModel):
    changed: dict[str, str]
