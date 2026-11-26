"""Posty sets up schedules by asking: a wrong call is fixed before the person sees it, the card
says when it runs in plain words, and the result tells the model what happened and what's next."""
# ruff: noqa: F811

from typing import Any

from fastapi.testclient import TestClient

from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import Script, app_config, client, fake, script, wait  # noqa: F401
from test_chat_engine import (
    approve_when_asked,
    chat,
    chat_in_background,
    last_tool_result,
    new_session,
)


def schedules(client: TestClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = client.post("/api/queries/schedules.list").json()["schedules"]
    return rows


def approvals(client: TestClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.post("/api/queries/approvals.list").json()["approvals"]
    return found


def call(client: TestClient, script: Script, name: str, arguments: dict[str, Any]) -> str:
    """A call that's refused before asking: it returns at once, with no approval."""
    script.replies = [[ToolCall("c1", name, arguments)], [TextChunk("Ok.")]]
    # Routines are the Routines agent's job, so the work goes to it.
    chat(client, new_session(client), "@routines Do it")
    return last_tool_result(script)


def approved(
    client: TestClient, script: Script, name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    script.replies = [[ToolCall("c1", name, arguments)], [TextChunk("Ok.")]]
    done = chat_in_background(client, new_session(client), "@routines Do it")
    card = approve_when_asked(client)
    wait(lambda: done, "finish")
    return card, last_tool_result(script)


FRIDAY = {
    "name": "Friday status",
    "instructions": "Write my team status.",
    "every": "week",
    "weekday": "Friday",
    "time": "17:00",
}


def test_a_wrong_call_is_explained_and_never_reaches_the_person(
    client: TestClient, script: Script
) -> None:
    told = call(
        client,
        script,
        "create_schedule",
        {"name": "Status", "instructions": "Write it.", "every": "week"},
    )
    assert "every='week' needs weekday" in told
    assert "Example: create_schedule(" in told
    told = call(client, script, "create_schedule", {**FRIDAY, "time": "5pm"})
    assert "time" in told and "Not run" in told
    told = call(client, script, "create_schedule", {**FRIDAY, "every": "fortnightly"})
    assert "every" in told and "Not run" in told
    told = call(
        client, script, "create_schedule", {**FRIDAY, "every": "once", "date": "2020-01-01"}
    )
    assert "in the past" in told
    assert approvals(client) == []
    assert schedules(client) == []


def test_the_card_says_when_in_plain_words_and_the_result_says_what_happens_next(
    client: TestClient, script: Script
) -> None:
    card, told = approved(client, script, "create_schedule", FRIDAY)
    assert card["summary"] == "New schedule: Friday status"
    assert "When: every Friday at 17:00" in card["detail"]
    assert "Next run: Fri " in card["detail"]
    assert "Write my team status." in card["detail"]
    [row] = schedules(client)
    assert (row["title"], row["every"], row["weekday"], row["time"]) == (
        "Friday status",
        "week",
        4,
        "17:00",
    )
    assert told.startswith(f"Created schedule {row['id']}: Friday status.")
    assert "first run Fri " in told


def test_the_same_name_points_to_the_one_that_exists(client: TestClient, script: Script) -> None:
    approved(client, script, "create_schedule", FRIDAY)
    told = call(
        client, script, "create_schedule", {**FRIDAY, "name": "friday STATUS", "time": "18:00"}
    )
    assert "is already called Friday status" in told and "update_schedule" in told
    assert len(schedules(client)) == 1


def test_a_change_shows_before_and_after_and_only_what_changed(
    client: TestClient, script: Script
) -> None:
    approved(client, script, "create_schedule", FRIDAY)
    [row] = schedules(client)
    card, told = approved(
        client, script, "update_schedule", {"schedule_id": row["id"], "time": "18:00"}
    )
    assert card["detail"] == "When: every Friday at 17:00 → every Friday at 18:00"
    assert "next run Fri " in told
    told = call(client, script, "update_schedule", {"schedule_id": row["id"], "time": "18:00"})
    assert told.startswith("Nothing to change")
    card, told = approved(
        client, script, "update_schedule", {"schedule_id": row["id"], "enabled": False}
    )
    assert card["detail"] == "Paused"
    assert told.startswith("Paused schedule")
    assert schedules(client)[0]["enabled"] is False


def test_new_cadences_and_an_end_date(client: TestClient, script: Script) -> None:
    card, _ = approved(
        client,
        script,
        "create_schedule",
        {
            "name": "Month end",
            "instructions": "Sum up the month.",
            "every": "month",
            "month_day": 31,
            "time": "16:00",
            "until": "2099-12-31",
        },
    )
    assert "When: on the last day of every month at 16:00, until 2099-12-31" in card["detail"]
    card, _ = approved(
        client,
        script,
        "create_schedule",
        {
            "name": "Standup notes",
            "instructions": "Note blockers.",
            "every": "weekdays",
            "time": "09:30",
        },
    )
    assert "every weekday (Monday to Friday) at 09:30" in card["detail"]


def test_built_in_schedules_and_missing_ones_are_refused_with_the_way_forward(
    client: TestClient, script: Script
) -> None:
    listed = call(client, script, "list_schedules", {})
    assert "Your brief — every day at 08:30 — next " in listed and "comes with the app" in listed
    brief = int(listed.split("\n")[1].split(":")[0])
    told = call(client, script, "update_schedule", {"schedule_id": brief, "time": "09:00"})
    assert "comes with the app" in told and "Settings" in told
    told = call(client, script, "update_schedule", {"schedule_id": 1_000, "time": "09:00"})
    assert "no schedule 1000" in told and "list_schedules" in told
    told = call(client, script, "remove_schedules", {"schedule_ids": [1_000]})
    assert "no schedule 1000" in told
    assert approvals(client) == []
