import stat
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.api.security import TOKEN_FILE, TOKEN_HEADER
from nexusai.kernel.config import Config, load_config

GOOD = {"host": "127.0.0.1:4100"}


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as test_client:
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


def test_a_refused_page_gets_no_cross_origin_permission_and_a_clear_reason(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/queries/settings.get", json={}, headers={"origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert "NEXUSAI_ALLOWED_ORIGINS" in response.json()["message"]


def test_the_apps_own_origin_can_read_answers_and_errors(client: TestClient) -> None:
    origin = {"origin": "http://localhost:4000"}
    assert client.get("/api/health", headers=origin).headers["access-control-allow-origin"] == (
        "http://localhost:4000"
    )
    missing = client.post("/api/queries/no.such", json={}, headers=origin)
    assert missing.status_code == 404
    assert missing.headers["access-control-allow-origin"] == "http://localhost:4000"


def test_a_browsers_question_first_is_answered_but_only_for_allowed_origins(
    config: Config,
) -> None:
    secured = replace(config, require_install_token=True)
    asking = {"access-control-request-method": "POST"}
    with TestClient(create_app(secured), base_url="http://127.0.0.1:4100") as client:
        allowed = client.options(
            "/api/queries/settings.get", headers={**asking, "origin": "http://127.0.0.1:4000"}
        )
        assert allowed.status_code == 204
        assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:4000"
        assert "x-nexusai-token" in allowed.headers["access-control-allow-headers"]
        refused = client.options(
            "/api/queries/settings.get", headers={**asking, "origin": "https://evil.example"}
        )
        assert refused.status_code == 403
        # Being allowed to ask isn't being let in: the token still decides.
        real = client.post(
            "/api/queries/settings.get", json={}, headers={"origin": "http://127.0.0.1:4000"}
        )
        assert real.status_code == 401


def test_another_address_can_be_named_but_never_opened_to_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUSAI_ALLOWED_ORIGINS", "http://mybox.local:4000/, https://work.example")
    named = load_config()
    assert {"http://mybox.local:4000", "https://work.example"} <= named.allowed_origins
    assert "mybox.local:4000" in named.allowed_hosts
    assert "*" not in named.allowed_origins


def test_dns_rebinding_host_is_refused(client: TestClient) -> None:
    assert client.get("/api/health", headers={"host": "evil.example:4100"}).status_code == 403


def test_app_origin_is_allowed(client: TestClient) -> None:
    response = client.get("/api/health", headers={"origin": "http://localhost:4000"})
    assert response.status_code == 200


def test_requests_need_this_install_s_token(config: Config, tmp_path: Path) -> None:
    secured = replace(config, require_install_token=True)
    with TestClient(create_app(secured), base_url="http://127.0.0.1:4100") as client:
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
    with TestClient(create_app(secured), base_url="http://127.0.0.1:4100") as client:
        assert client.post("/api/home/status", headers={TOKEN_HEADER: token}).status_code == 200
        assert token_file.read_text() == token
