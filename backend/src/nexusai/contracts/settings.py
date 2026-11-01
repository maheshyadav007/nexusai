from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Density = Literal["compact", "comfortable", "spacious"]
TextSize = Literal["small", "medium", "large"]
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


class SettingsChanged(BaseModel):
    changed: dict[str, str]
