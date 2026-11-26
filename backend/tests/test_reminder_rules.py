# ruff: noqa: F811
"""Reminders that repeat every so many minutes, on chosen days, between two times, until a date.

The case that started it: "remind me to drink water every hour from 10 to 8 on weekdays" made a
schedule that woke an agent every hour, or nothing. Now it's one reminder that fires 11 times a
weekday, never at weekends, with no model run per firing (To do 13)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from nexusai.kernel.module import CommandError
from nexusai.modules.agent.providers import ToolCall
from nexusai.modules.planner import module as planner
from test_agent_work import (
    Script,
    app_config,  # noqa: F401
    client,  # noqa: F401
    fake,  # noqa: F401
    script,  # noqa: F401
)
from test_chat_engine_tools import use_tool

WATER = planner.Rule(
    every_minutes=60, days=(0, 1, 2, 3, 4), window_start="10:00", window_end="20:00"
)
# A Monday.
MONDAY = datetime(2031, 6, 2, 10, 0)


def test_interval_words_and_rules_are_read_or_refused_with_how_to_fix_it() -> None:
    assert planner.interval_of("hourly") == 60
    assert planner.interval_of("every hour") == 60
    assert planner.interval_of("every 2 hours") == 120
    assert planner.interval_of("every 30 minutes") == 30
    assert planner.interval_of("daily") is None
    assert planner.repeat_of("every 2 hours") == "interval"
    kind, rule = planner.rule_of(
        "hourly", days=["weekdays"], window_start="10:00", window_end="20:00"
    )
    assert (kind, rule) == ("interval", WATER)
    assert planner.rule_of("none", every_minutes=90)[0] == "interval"
    for bad, words in (
        ({"repeat": "interval"}, "every_minutes"),
        ({"repeat": "interval", "every_minutes": 2}, "every 5 to 1440"),
        ({"repeat": "day", "window_start": "10:00"}, "both ends"),
        (
            {"repeat": "day", "window_start": "20:00", "window_end": "10:00"},
            "start must come first",
        ),
        ({"repeat": "day", "days": ["funday"]}, "isn't a day"),
        ({"repeat": "none", "days": ["monday"]}, "Set repeat"),
        ({"repeat": "day", "window_start": "25:00", "window_end": "26:00"}, "HH:MM"),
    ):
        with pytest.raises(CommandError, match=words):
            planner.rule_of(**bad)  # type: ignore[arg-type]
    # Every day is the same as no days at all.
    assert planner.rule_of("day", days=["weekdays", "weekends"])[1].days is None


def test_hourly_on_weekdays_between_ten_and_eight_fires_eleven_times_a_day() -> None:
    times = []
    due: datetime | None = MONDAY
    while due is not None and due < datetime(2031, 6, 9):
        times.append(due)
        due = planner.next_due(due, "interval", None, WATER)
    by_day: dict[str, int] = {}
    for at in times:
        by_day[at.strftime("%a")] = by_day.get(at.strftime("%a"), 0) + 1
    assert by_day == {"Mon": 11, "Tue": 11, "Wed": 11, "Thu": 11, "Fri": 11}
    assert times[10] == datetime(2031, 6, 2, 20, 0) and times[11] == datetime(2031, 6, 3, 10, 0)
    # Friday 20:00 is followed by Monday 10:00, never the weekend.
    friday_last = datetime(2031, 6, 6, 20, 0)
    assert planner.next_due(friday_last, "interval", None, WATER) == datetime(2031, 6, 9, 10, 0)


def test_a_rule_ends_on_its_date_and_daily_reminders_keep_their_days() -> None:
    until = planner.Rule(every_minutes=60, until="2031-06-02")
    assert planner.next_due(datetime(2031, 6, 2, 23, 30), "interval", None, until) is None
    weekdays = planner.Rule(days=(0, 1, 2, 3, 4))
    # A daily 09:00 on weekdays skips from Friday to Monday at the same time.
    assert planner.next_due(datetime(2031, 6, 6, 9, 0), "day", None, weekdays) == datetime(
        2031, 6, 9, 9, 0
    )
    # Without a rule, nothing changes from before.
    assert planner.next_due(datetime(2031, 1, 31, 9, 0), "month", 31) == datetime(2031, 2, 28, 9, 0)
    assert (
        planner.describe_repeat("interval", WATER) == "every 60 minutes, 10:00 to 20:00, Mon to Fri"
    )


def test_the_drink_water_reminder_is_one_reminder_set_by_the_tool(
    client: TestClient, script: Script
) -> None:
    water = {
        "reminders": [
            {
                "title": "Drink water",
                # Asked on a Sunday evening: it starts on Monday at 10:00.
                "when": "2031-06-01T19:00",
                "repeat": "hourly",
                "between": "10:00-20:00",
                "days": ["weekdays"],
            }
        ]
    }
    said = use_tool(client, script, ToolCall("a", "create_reminders", water))
    assert said.startswith("Reminders set") and "2031-06-02T10:00" in said
    assert "every 60 minutes, 10:00 to 20:00, Mon to Fri" in said
    rows = client.post("/api/queries/reminders.list").json()["reminders"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["repeat"], row["every_minutes"], row["days"]) == ("interval", 60, [0, 1, 2, 3, 4])
    assert (row["window_start"], row["window_end"], row["when"]) == (
        "10:00",
        "20:00",
        "2031-06-02T10:00",
    )
    # Changing only the hours keeps the rest of the rule.
    change = {"changes": [{"reminder_id": row["id"], "between": "09:00-17:00"}]}
    said = use_tool(client, script, ToolCall("b", "update_reminders", change))
    assert said.startswith("Updated")
    row = client.post("/api/queries/reminders.list").json()["reminders"][0]
    assert (row["window_start"], row["window_end"], row["every_minutes"], row["days"]) == (
        "09:00",
        "17:00",
        60,
        [0, 1, 2, 3, 4],
    )


def test_a_firing_tells_the_person_once_and_moves_to_the_next_allowed_time(
    client: TestClient,
) -> None:
    from nexusai.modules.agent import module as agent

    client.post(
        "/api/commands/reminders.save",
        json={
            "title": "Drink water",
            "when": "2031-06-02T10:00",
            "repeat": "interval",
            "every_minutes": 60,
            "days": [0, 1, 2, 3, 4],
            "window_start": "10:00",
            "window_end": "20:00",
        },
    )
    ctx = agent.current().ctx
    # The laptop slept from Monday 10:00 to 23:00: one notice, not thirteen, and the next is
    # Tuesday 10:00.
    assert planner.fire_due_reminders(ctx, datetime(2031, 6, 2, 23, 0)) == 1
    row = client.post("/api/queries/reminders.list").json()["reminders"][0]
    assert row["when"] == "2031-06-03T10:00" and not row["fired"]


def test_a_schedule_that_only_reminds_is_turned_toward_the_reminder_tool(
    client: TestClient, script: Script
) -> None:
    ask = {"name": "Water", "instructions": "Remind me to drink water", "every": "hour"}
    said = use_tool(client, script, ToolCall("a", "create_schedule", ask))
    assert said.startswith("Not created") and "create_reminders" in said
    assert client.post("/api/queries/schedules.list", json={}).json()["schedules"] == [] or all(
        s["title"] != "Water"
        for s in client.post("/api/queries/schedules.list", json={}).json()["schedules"]
    )
    # Real work that also reminds is still a schedule.
    assert not planner_only("Remind me what's due this week and draft the replies")


def planner_only(text: str) -> bool:
    from nexusai.modules.agent import work_tools

    return work_tools._only_a_reminder(text)


def test_renaming_on_the_reminders_page_keeps_the_rule(client: TestClient) -> None:
    rule = {
        "repeat": "interval",
        "every_minutes": 60,
        "days": [0, 1, 2, 3, 4],
        "window_start": "10:00",
        "window_end": "20:00",
        "until": None,
    }
    client.post(
        "/api/commands/reminders.save", json={"title": "Water", "when": "2031-06-02T10:00", **rule}
    )
    row = client.post("/api/queries/reminders.list").json()["reminders"][0]
    # What the page sends: the reminder as it is, its rule included, with the new title.
    page = {k: row[k] for k in ("id", "when", "thread", "task", "proposed")}
    saved = client.post(
        "/api/commands/reminders.save", json={**page, "title": "Drink water", **rule}
    )
    assert saved.status_code == 200
    row = client.post("/api/queries/reminders.list").json()["reminders"][0]
    assert (row["title"], row["every_minutes"], row["window_start"], row["days"]) == (
        "Drink water",
        60,
        "10:00",
        [0, 1, 2, 3, 4],
    )
    # An interval with no minutes is refused with what to give, not saved as something else.
    refused = client.post(
        "/api/commands/reminders.save",
        json={"title": "Odd", "when": "2031-06-02T10:00", "repeat": "interval"},
    )
    assert refused.status_code == 422 and "every_minutes" in refused.text
