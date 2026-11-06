import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from fake_chatgpt import ACCOUNT, create_fake, token
from nexusai.api.app import create_app
from nexusai.kernel.config import Config


@pytest.fixture
def fake() -> Iterator[tuple[str, dict[str, Any]]]:
    app = create_fake()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}", app.state.fake
    server.should_exit = True
    thread.join()


@pytest.fixture
def client(config: Config, fake: tuple[str, dict[str, Any]]) -> Iterator[TestClient]:
    url, _ = fake
    chatgpt = replace(config.chatgpt, issuer=url, base_url=f"{url}/codex", min_poll_seconds=0.01)
    with TestClient(
        create_app(replace(config, chatgpt=chatgpt)), base_url="http://127.0.0.1:4100"
    ) as test_client:
        yield test_client


def status(client: TestClient) -> dict[str, Any]:
    return client.post("/api/queries/models.status").json()


def connect(client: TestClient) -> dict[str, Any]:
    started = client.post("/api/commands/models.login.start").json()
    assert started["login"]["state"] == "waiting"
    assert started["login"]["user_code"] == "WXYZ-1234"
    assert started["login"]["verification_url"].endswith("/codex/device")
    for _ in range(500):
        current = status(client)
        if current["connected"]:
            return current
        time.sleep(0.01)
    raise AssertionError("never connected")


def stored(config: Config) -> dict[str, str]:
    return json.loads(json.loads((config.home_dir / "secrets.json").read_text())["chatgpt.tokens"])


def event_changes(client: TestClient) -> list[str]:
    events = client.post("/api/events/log", json={}).json()["events"]
    return [e["payload"]["change"] for e in events if e["type"] == "models.changed"]


def test_starts_disconnected(client: TestClient) -> None:
    assert status(client) == {
        "connected": False,
        "account_email": None,
        "plan": None,
        "selected_model": None,
        "login": {"state": "idle", "user_code": None, "verification_url": None, "error": None},
        "managed": False,
    }


def test_sign_in_connects_and_shows_who(client: TestClient) -> None:
    current = connect(client)
    assert current["account_email"] == "tester@example.com"
    assert current["plan"] == "plus"
    assert event_changes(client) == ["login_started", "connected"]


def test_tokens_never_reach_responses_or_events(
    client: TestClient, fake: tuple[str, dict[str, Any]], config: Config
) -> None:
    connect(client)
    secrets = stored(config)
    seen = json.dumps(status(client)) + client.post("/api/events/log", json={}).text
    assert secrets["access_token"] not in seen
    assert secrets["refresh_token"] not in seen


def test_requests_identify_nexusai_and_the_account(
    client: TestClient, fake: tuple[str, dict[str, Any]]
) -> None:
    connect(client)
    client.post("/api/queries/models.list")
    sent = fake[1]["headers"][-1]
    assert sent["originator"] == "nexusai"
    assert sent["user-agent"].startswith("NexusAI/")
    assert sent["chatgpt-account-id"] == ACCOUNT


def test_lists_only_visible_models_best_first(client: TestClient) -> None:
    connect(client)
    assert client.post("/api/queries/models.list").json() == {
        "models": [{"id": "gpt-best", "name": "GPT Best"}, {"id": "gpt-slow", "name": "GPT Slow"}]
    }


def test_choosing_a_model_is_saved_and_validated(client: TestClient) -> None:
    connect(client)
    chosen = client.post("/api/commands/models.select", json={"model": "gpt-best"})
    assert chosen.json()["selected_model"] == "gpt-best"
    assert status(client)["selected_model"] == "gpt-best"

    for model in ("gpt-secret", "made-up"):
        refused = client.post("/api/commands/models.select", json={"model": model})
        assert refused.status_code == 422
        assert refused.json()["code"] == "models.not_available"
    assert status(client)["selected_model"] == "gpt-best"


def test_test_message_sends_only_the_prompt_and_stores_nothing(
    client: TestClient, fake: tuple[str, dict[str, Any]]
) -> None:
    connect(client)
    client.post("/api/commands/models.select", json={"model": "gpt-best"})
    reply = client.post("/api/commands/models.test", json={"prompt": "Say hello"})
    assert reply.json() == {"model": "gpt-best", "text": "Hello from gpt-best"}
    body = fake[1]["bodies"][-1]
    assert body["store"] is False
    assert body["input"][0]["content"] == [{"type": "input_text", "text": "Say hello"}]


def test_test_message_needs_a_model(client: TestClient) -> None:
    connect(client)
    refused = client.post("/api/commands/models.test", json={"prompt": "Hi"})
    assert refused.status_code == 409
    assert refused.json()["code"] == "models.none_selected"


def test_nothing_works_before_connecting(client: TestClient) -> None:
    refused = client.post("/api/queries/models.list")
    assert refused.status_code == 409
    assert refused.json()["code"] == "models.not_connected"


def test_expiring_token_is_renewed_and_the_new_refresh_token_kept(
    client: TestClient, fake: tuple[str, dict[str, Any]], config: Config
) -> None:
    state = fake[1]
    state["access"] = token("about-to-end", expires_in=10)
    connect(client)
    assert client.post("/api/queries/models.list").status_code == 200
    assert len(state["refresh_tokens"]) == 2
    assert stored(config)["refresh_token"] == state["refresh_tokens"][-1]


def test_rejected_token_is_renewed_once_and_the_call_retried(
    client: TestClient, fake: tuple[str, dict[str, Any]]
) -> None:
    connect(client)
    fake[1]["reject_next_request"] = True
    assert client.post("/api/queries/models.list").status_code == 200
    assert len(fake[1]["refresh_tokens"]) == 2


def test_ended_sign_in_disconnects_with_a_clear_message(
    client: TestClient, fake: tuple[str, dict[str, Any]]
) -> None:
    connect(client)
    fake[1]["reject_next_request"] = True
    fake[1]["revoked"] = True
    refused = client.post("/api/queries/models.list")
    assert refused.status_code == 401
    assert "Connect ChatGPT again" in refused.json()["message"]
    assert status(client)["connected"] is False
    assert event_changes(client)[-1] == "disconnected"
    for _ in range(200):
        notices = client.post("/api/queries/notifications.list", json={}).json()
        if notices["items"]:
            break
        time.sleep(0.01)
    assert notices["unread"] == 1
    assert notices["items"][0]["title"] == "ChatGPT was disconnected"
    assert notices["items"][0]["link"] == "/settings?section=models"


def test_disconnect_forgets_tokens_and_selection(client: TestClient, config: Config) -> None:
    connect(client)
    client.post("/api/commands/models.select", json={"model": "gpt-best"})
    current = client.post("/api/commands/models.disconnect").json()
    assert current["connected"] is False
    assert current["selected_model"] is None
    secrets = json.loads((config.home_dir / "secrets.json").read_text())
    assert "chatgpt.tokens" not in secrets


def test_cancelling_stops_the_sign_in(client: TestClient, fake: tuple[str, dict[str, Any]]) -> None:
    fake[1]["polls_until_done"] = 10_000
    client.post("/api/commands/models.login.start")
    assert client.post("/api/commands/models.login.cancel").json()["login"]["state"] == "idle"
    polls = fake[1]["polls"]
    time.sleep(0.1)
    assert fake[1]["polls"] <= polls + 1
    assert status(client)["connected"] is False


def test_starting_twice_keeps_the_same_sign_in(
    client: TestClient, fake: tuple[str, dict[str, Any]]
) -> None:
    fake[1]["polls_until_done"] = 10_000
    first = client.post("/api/commands/models.login.start").json()
    second = client.post("/api/commands/models.login.start").json()
    assert first["login"] == second["login"]
    assert event_changes(client) == ["login_started"]


def test_a_model_server_set_up_in_settings_counts_as_connected(client: TestClient) -> None:
    assert status(client)["connected"] is False
    saved = client.post(
        "/api/commands/models.provider.save",
        json={
            "provider": "litellm",
            "base_url": "http://llm.example/v1",
            "api_key": "k",
            "model": "company-model",
            "supports_tools": False,
        },
    )
    assert saved.status_code == 200
    current = status(client)
    assert current["connected"] is True
    assert current["selected_model"] == "company-model"
    assert "connected" in event_changes(client)


def test_a_slow_model_gets_minutes_but_an_unreachable_server_fails_fast() -> None:
    from nexusai.kernel.config import load_config
    from nexusai.modules.models.chatgpt import model_timeout

    timeout = model_timeout(load_config().chatgpt)
    assert (timeout.read, timeout.write, timeout.pool) == (500, 500, 500)
    assert timeout.connect == 30
