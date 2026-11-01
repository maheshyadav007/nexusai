import stat
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.api.security import TOKEN_FILE, TOKEN_HEADER
from nexusai.kernel.config import Config

GOOD = {"host": "127.0.0.1:8765"}


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:8765") as test_client:
        yield test_client


def test_settings_defaults_come_from_config(client: TestClient, config: Config) -> None:
    assert client.post("/api/queries/settings.get").json() == config.default_settings


def test_update_saves_and_emits_one_event_with_the_trace_id(client: TestClient) -> None:
    response = client.post(
        "/api/commands/settings.update", json={"theme": "nexus-dark"}, headers={"x-trace-id": "t1"}
    )
    assert response.json()["theme"] == "nexus-dark"
    assert client.post("/api/queries/settings.get").json()["theme"] == "nexus-dark"
    events = client.post("/api/events/log", json={}).json()["events"]
    assert [(e["type"], e["trace_id"], e["payload"]) for e in events] == [
        ("settings.changed", "t1", {"changed": {"theme": "nexus-dark"}})
    ]


def test_update_with_no_change_emits_nothing(client: TestClient) -> None:
    client.post("/api/commands/settings.update", json={})
    assert client.post("/api/events/log", json={}).json()["events"] == []


@pytest.mark.parametrize("body", [{"density": "huge"}, {"unknown": 1}, {"theme": "../../evil"}])
def test_invalid_update_is_rejected_with_a_code(
    client: TestClient, body: dict[str, object]
) -> None:
    response = client.post("/api/commands/settings.update", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "request.invalid"


def test_unknown_command_is_a_coded_error(client: TestClient) -> None:
    response = client.post("/api/commands/nothing.here")
    assert response.status_code == 404
    assert response.json()["code"] == "contract.unknown"


def test_other_website_origin_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/commands/settings.update",
        json={"theme": "nexus-dark"},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert client.post("/api/queries/settings.get").json()["theme"] != "nexus-dark"


def test_dns_rebinding_host_is_refused(client: TestClient) -> None:
    assert client.get("/api/health", headers={"host": "evil.example:8765"}).status_code == 403


def test_app_origin_is_allowed(client: TestClient) -> None:
    response = client.get("/api/health", headers={"origin": "http://localhost:3000"})
    assert response.status_code == 200


def test_requests_need_this_install_s_token(config: Config, tmp_path: Path) -> None:
    secured = replace(config, require_install_token=True)
    with TestClient(create_app(secured), base_url="http://127.0.0.1:8765") as client:
        token_file = tmp_path / "app-data" / TOKEN_FILE
        token = token_file.read_text()
        assert len(token) >= 40
        if sys.platform != "win32":
            assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

        # Whatever starts the app needs to know it's up, and learns nothing else.
        assert client.get("/api/health").status_code == 200
        for path in [
            "/api/queries/settings.get",
            "/api/home/status",
            "/api/commands/settings.update",
        ]:
            assert client.post(path, json={}).status_code == 401
        wrong = client.post("/api/queries/settings.get", headers={TOKEN_HEADER: "wrong"})
        assert (wrong.status_code, wrong.json()["code"]) == (401, "request.unauthorized")
        # A header that isn't plain text is refused, not a crash.
        odd = client.post(
            "/api/queries/settings.get", headers={TOKEN_HEADER: "caf\u00e9".encode("latin-1")}
        )
        assert odd.status_code == 401
        right = client.post("/api/home/status", headers={TOKEN_HEADER: token})
        assert right.status_code == 200

    # It stays the same across restarts, so the app doesn't have to be told again.
    with TestClient(create_app(secured), base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/home/status", headers={TOKEN_HEADER: token}).status_code == 200
        assert token_file.read_text() == token
