"""The scheduler must agree with the OS clock on non-UTC Windows machines."""

from datetime import UTC, datetime, timedelta

import pytest

from nexusai.contracts.agent import Schedule
from nexusai.modules.agent import scheduler


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/New_York"])
def test_default_zone_uses_os_detection_without_tz(
    monkeypatch: pytest.MonkeyPatch, zone: str
) -> None:
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(scheduler, "get_localzone_name", lambda: zone, raising=False)
    assert scheduler.system_timezone() == zone


def test_explicit_tz_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    assert scheduler.system_timezone() == "Asia/Kolkata"


def test_scheduler_clock_keeps_the_instant_even_if_zone_detection_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "system_timezone", lambda: "UTC")
    before = datetime.now(UTC) - timedelta(minutes=1)
    now = scheduler._local_now()
    assert now.utcoffset() is not None
    assert before <= now.astimezone(UTC) <= datetime.now(UTC)


def test_non_utc_default_schedule_uses_its_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(scheduler, "get_localzone_name", lambda: "Asia/Kolkata", raising=False)
    schedule = Schedule(title="Brief", every="day", time="08:30")
    assert (
        scheduler.next_scheduled_run(schedule, datetime(2026, 11, 4, 2, 59, tzinfo=UTC))
        == "2026-11-04T03:00:00+00:00"
    )
