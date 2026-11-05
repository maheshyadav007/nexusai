"""Desktop restarts must not interrupt an active request, agent or import."""

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from nexusai.api.desktop import DesktopControl
from nexusai.kernel.config import load_config
from nexusai.kernel.database import Database, DatabaseTooNew, Migration


def test_scheduling_without_system_timezone_database() -> None:
    """Windows has no system IANA database; installed runtime data must suffice."""
    script = """
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, TZPATH
from nexusai.contracts.agent import Schedule
from nexusai.modules.agent.scheduler import next_scheduled_run, system_timezone

assert not TZPATH
for name in ("UTC", "Asia/Kolkata", "America/New_York"):
    schedule = Schedule(title="Test", prompt="Test", every="day", time="09:00", timezone=name)
    assert next_scheduled_run(schedule, datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
assert datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata")).utcoffset() == timedelta(hours=5.5)
new_york = ZoneInfo("America/New_York")
assert datetime(2026, 1, 1, tzinfo=new_york).utcoffset() == timedelta(hours=-5)
assert datetime(2026, 7, 1, tzinfo=new_york).utcoffset() == timedelta(hours=-4)
if expected := os.environ.get("NEXUSAI_TEST_WINDOWS_ZONE"):
    assert "TZ" not in os.environ
    detected = ZoneInfo(system_timezone())
    for month in (1, 7):
        local = datetime(2026, month, 1)
        assert detected.utcoffset(local) == ZoneInfo(expected).utcoffset(local)
"""
    env = {**os.environ, "PYTHONTZPATH": ""}
    env.pop("TZ", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_deployment_defaults_then_local_credentials_then_process_environment(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    defaults = tmp_path / "deployment.env"
    local = tmp_path / "company.env"
    defaults.write_text(
        "NEXUSAI_MODEL_URL=https://model.example.test\nNEXUSAI_MODEL_NAMES=example\n",
        encoding="utf-8",
    )
    local.write_text("NEXUSAI_MODEL_API_KEY=local-key\n", encoding="utf-8")
    monkeypatch.setenv("NEXUSAI_ENV_DEFAULTS_FILE", str(defaults))
    monkeypatch.setenv("NEXUSAI_ENV_FILE", str(local))
    configured = load_config()
    assert configured.system_model is not None
    assert configured.system_model.base_url == "https://model.example.test"
    assert configured.system_model.api_key == "local-key"
    monkeypatch.setenv("NEXUSAI_MODEL_API_KEY", "process-key")
    overridden = load_config()
    assert overridden.system_model is not None
    assert overridden.system_model.api_key == "process-key"


def controller(rows: list[dict[str, Any]] | None = None) -> DesktopControl:
    app = FastAPI()
    if rows is not None:
        app.state.bus = SimpleNamespace(db=SimpleNamespace(fetch_all=lambda _: rows))
    controlled = DesktopControl(app, "test-desktop-token")
    controlled.server = SimpleNamespace(should_exit=False)  # type: ignore[assignment]
    return controlled


@pytest.mark.asyncio
async def test_control_endpoint_requires_its_own_token_and_post() -> None:
    controlled = controller()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=controlled), base_url="http://test"
    ) as client:
        for method, headers in [
            ("GET", {}),
            ("POST", {}),
            ("POST", {"x-nexusai-desktop": "wrong"}),
        ]:
            response = await client.request(method, "/__desktop__/prepare-exit", headers=headers)
            assert response.status_code == 404
    assert not controlled.draining
    assert controlled.server is not None and not controlled.server.should_exit


@pytest.mark.asyncio
async def test_active_background_work_refuses_exit_and_reopens_admission() -> None:
    controlled = controller([{"id": 1}])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=controlled), base_url="http://test"
    ) as client:
        response = await client.post(
            "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
        )
    assert response.status_code == 409
    assert not controlled.draining
    assert controlled.server is not None and not controlled.server.should_exit


@pytest.mark.asyncio
async def test_idle_exit_drains_and_refuses_new_api_work() -> None:
    controlled = controller([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=controlled), base_url="http://test"
    ) as client:
        response = await client.post(
            "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
        )
        assert response.status_code == 200
        assert (await client.post("/api/mail/send")).status_code == 503
    assert controlled.server is not None and controlled.server.should_exit


@pytest.mark.asyncio
async def test_failed_exit_check_reopens_requests_and_can_be_retried() -> None:
    controlled = controller()

    def broken(_: str) -> list[Any]:
        raise RuntimeError("database unavailable")

    controlled.app.state.bus = SimpleNamespace(db=SimpleNamespace(fetch_all=broken))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=controlled, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        failed = await client.post(
            "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
        )
        assert failed.status_code == 500
        assert not controlled.draining
        assert (await client.post("/ordinary-request")).status_code == 404
        controlled.app.state.bus.db.fetch_all = lambda _: []
        assert (
            await client.post(
                "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
            )
        ).status_code == 200
    assert controlled.server is not None and controlled.server.should_exit


@pytest.mark.asyncio
async def test_disconnected_exit_response_does_not_leave_admission_closed() -> None:
    controlled = controller([])

    async def disconnected(_: Any) -> None:
        raise ConnectionError("control client disconnected")

    scope = {
        "type": "http",
        "path": "/__desktop__/prepare-exit",
        "method": "POST",
        "headers": [(b"x-nexusai-desktop", b"test-desktop-token")],
    }
    with pytest.raises(ConnectionError):
        await controlled(scope, None, disconnected)
    assert not controlled.draining
    assert controlled.server is not None and not controlled.server.should_exit


def test_newer_database_is_rejected_without_modifying_its_migrations(tmp_path: Any) -> None:
    db = Database(tmp_path / "newer.db")
    try:
        old = Migration("known", "CREATE TABLE preserved (value TEXT)")
        future = Migration("future", "ALTER TABLE preserved ADD COLUMN extra TEXT")
        db.migrate([old, future])
        with pytest.raises(DatabaseTooNew, match="newer NexusAI"):
            db.require_compatible([old])
        assert {row["id"] for row in db.fetch_all("SELECT id FROM migrations")} == {
            "known",
            "future",
        }
        db.require_compatible([old, future])
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_send_in_flight_blocks_exit_until_it_finishes() -> None:
    controlled = controller()
    entered, finish = asyncio.Event(), asyncio.Event()

    @controlled.app.post("/send")
    async def sending() -> dict[str, bool]:
        entered.set()
        await finish.wait()
        return {"sent": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=controlled), base_url="http://test"
    ) as client:
        task = asyncio.create_task(client.post("/send"))
        await entered.wait()
        assert controlled.active == 1
        refused = await client.post(
            "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
        )
        assert refused.status_code == 409
        finish.set()
        assert (await task).status_code == 200
        assert controlled.active == 0
        assert (
            await client.post(
                "/__desktop__/prepare-exit", headers={"x-nexusai-desktop": "test-desktop-token"}
            )
        ).status_code == 200
