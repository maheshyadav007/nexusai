"""Dates in invented mail, relative to the day an eval runs, so a deadline is never already past.

{day+2} becomes "Thursday 19 November", {iso+2} becomes "2026-11-19", and {day+0} is today."""

import re
from datetime import date, timedelta
from typing import Any

PLACEHOLDER = re.compile(r"\{(day|iso)([+-]\d+)\}")


def fill(text: str, today: date | None = None) -> str:
    base = today or date.today()

    def one(match: re.Match[str]) -> str:
        when = base + timedelta(days=int(match.group(2)))
        return when.isoformat() if match.group(1) == "iso" else f"{when:%A} {when.day} {when:%B}"

    return PLACEHOLDER.sub(one, text)


def fill_all(value: Any, today: date | None = None) -> Any:
    """Every string in a JSON value, however deep."""
    if isinstance(value, str):
        return fill(value, today)
    if isinstance(value, list):
        return [fill_all(item, today) for item in value]
    if isinstance(value, dict):
        return {key: fill_all(item, today) for key, item in value.items()}
    return value
