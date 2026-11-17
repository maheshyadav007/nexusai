"""Every cadence lands on the right day, never in the past, and stops at its end date."""

import calendar
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nexusai.contracts.agent import Schedule
from nexusai.modules.agent import scheduler

ZONES = ("Asia/Kolkata", "America/New_York", "Europe/London", "Australia/Sydney", "UTC")
EVERY = ("hour", "day", "weekdays", "week", "month", "year")
CASES = 10_000
# DST can push a wall time an hour later, and a month day can wait for the next year's February.
LONGEST_WAIT = {"hour": 2, "day": 2, "weekdays": 4, "week": 8, "month": 32, "year": 367}


def _random_schedule(pick: random.Random) -> Schedule:
    return Schedule(
        title="t",
        every=pick.choice(EVERY),
        time=f"{pick.randrange(24):02d}:{pick.choice((0, 15, 30, 45, 59)):02d}",
        weekday=pick.randrange(7),
        month_day=pick.randrange(1, 32),
        month=pick.randrange(1, 13),
        timezone=pick.choice(ZONES),
    )


def test_ten_thousand_random_schedules_run_after_now_on_the_right_day() -> None:
    pick = random.Random(20261118)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(CASES):
        schedule = _random_schedule(pick)
        after = start + timedelta(minutes=pick.randrange(60 * 24 * 900))
        found = scheduler.next_scheduled_run(schedule, after)
        assert found is not None
        moment = datetime.fromisoformat(found)
        assert after < moment <= after + timedelta(days=LONGEST_WAIT[schedule.every])
        local = moment.astimezone(ZoneInfo(schedule.timezone or "UTC"))
        if schedule.every == "weekdays":
            assert local.weekday() < scheduler.SATURDAY
        if schedule.every == "week":
            assert local.weekday() == schedule.weekday
        if schedule.every in ("month", "year"):
            last = calendar.monthrange(local.year, local.month)[1]
            assert local.day == min(schedule.month_day, last)
        if schedule.every == "year":
            assert local.month == schedule.month


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        # Friday evening waits for Monday; Saturday too.
        ("2026-11-20T18:00", "2026-11-23T09:00"),
        ("2026-11-21T08:00", "2026-11-23T09:00"),
        ("2026-11-23T08:59", "2026-11-23T09:00"),
    ],
)
def test_weekdays_skip_the_weekend(after: str, expected: str) -> None:
    schedule = Schedule(title="t", every="weekdays", time="09:00")
    assert scheduler.next_run_after(schedule, datetime.fromisoformat(after)) == expected


def test_the_31st_runs_on_each_months_last_day() -> None:
    schedule = Schedule(title="t", every="month", month_day=31, time="10:00")
    runs, after = [], datetime(2027, 1, 1)
    for _ in range(4):
        value = scheduler.next_run_after(schedule, after)
        assert value is not None
        runs.append(value[:10])
        after = datetime.fromisoformat(value)
    assert runs == ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30"]


def test_the_29th_of_february_runs_on_the_28th_in_other_years() -> None:
    schedule = Schedule(title="t", every="year", month=2, month_day=29, time="08:00")
    assert scheduler.next_run_after(schedule, datetime(2027, 3, 1)) == "2028-02-29T08:00"
    assert scheduler.next_run_after(schedule, datetime(2028, 3, 1)) == "2029-02-28T08:00"


def test_nothing_runs_after_the_end_date() -> None:
    schedule = Schedule(title="t", every="day", time="09:00", until="2026-11-20", timezone="UTC")
    assert scheduler.next_scheduled_run(schedule, datetime(2026, 11, 20, 8, tzinfo=UTC))
    assert scheduler.next_scheduled_run(schedule, datetime(2026, 11, 20, 10, tzinfo=UTC)) is None


def test_described_in_plain_words() -> None:
    assert scheduler.describe(Schedule(title="t", every="week", weekday=4, time="17:00")) == (
        "every Friday at 17:00"
    )
    assert scheduler.describe(Schedule(title="t", every="month", month_day=31, time="10:00")) == (
        "on the last day of every month at 10:00"
    )
    assert scheduler.describe(
        Schedule(title="t", every="weekdays", time="09:00", until="2026-12-31")
    ) == ("every weekday (Monday to Friday) at 09:00, until 2026-12-31")
