import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.kernel.logging import REMOVED, clean_fields, sink


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:8765") as test_client:
        yield test_client


@pytest.mark.parametrize(
    "fields",
    [
        {"password": "hunter2"},
        {"access_token": "abc"},
        {"Authorization": "Bearer abc"},
        {"api_key": "abc"},
        {"nested": {"refresh_token": "abc"}},
        {"note": "called with Bearer abc.def-ghi"},
        {"note": "token eyJhbGciOiJI.eyJzdWIiOiIx.c2ln here"},
        {"note": "key sk-abcdefghijklmnopqrstuv"},
        {"items": [{"secret": "abc"}]},
    ],
)
def test_secrets_are_always_removed(fields: dict[str, Any]) -> None:
    for debug in (False, True):
        text = json.dumps(clean_fields(fields, debug))
        assert "hunter2" not in text and "abc" not in text.replace(REMOVED, "")
        assert "eyJhbG" not in text and "sk-abc" not in text


def test_mail_content_stays_out_unless_debugging() -> None:
    assert clean_fields({"body": "dear asha"})["body"] == REMOVED
    assert clean_fields({"body": "dear asha"}, debug=True)["body"] == "dear asha"
    assert clean_fields({"event": "ok", "seq": 3}) == {"event": "ok", "seq": 3}


def test_logs_are_written_to_home_searchable_and_clean(client: TestClient, config: Config) -> None:
    structlog.get_logger().info("sync_done", account="a1", password="hunter2")
    structlog.get_logger().warning("sync_slow", account="a1")
    files = list((config.home / "system" / "logs").glob("*.jsonl"))
    assert files and "hunter2" not in files[0].read_text()

    lines = client.post("/api/queries/logs.search", json={}).json()["lines"]
    assert [line["event"] for line in lines[:2]] == ["sync_slow", "sync_done"]
    only = client.post("/api/queries/logs.search", json={"level": "warning"}).json()["lines"]
    assert {line["level"] for line in only} == {"warning"}
    text = client.post("/api/queries/logs.search", json={"text": "SYNC_DONE"}).json()["lines"]
    assert [line["event"] for line in text] == ["sync_done"]


def test_old_log_files_are_removed(config: Config, tmp_path: Any) -> None:
    folder = tmp_path / "logs"
    folder.mkdir()
    (folder / "nexusai-2001-01-01.jsonl").write_text("{}\n")
    (folder / "nexusai-2999-01-01.jsonl").write_text("{}\n")
    sink.attach(folder, 30)
    sink.detach()
    assert [p.name for p in folder.iterdir()] == ["nexusai-2999-01-01.jsonl"]


def test_a_trace_shows_its_events_and_logs(client: TestClient) -> None:
    client.post(
        "/api/commands/settings.update", json={"theme": "nexus-dark"}, headers={"x-trace-id": "t9"}
    )
    client.post(
        "/api/commands/settings.update", json={"density": "compact"}, headers={"x-trace-id": "t8"}
    )
    trace = client.post("/api/queries/trace.get", json={"trace_id": "t9"}).json()
    assert [event["trace_id"] for event in trace["events"]] == ["t9"]
    assert any(line.get("trace_id") == "t9" for line in trace["lines"])
    empty = client.post("/api/queries/trace.get", json={"trace_id": "none"}).json()
    assert empty == {"events": [], "lines": []}


def test_notifications_arrive_through_events_and_can_be_read(client: TestClient) -> None:
    def request(title: str, kind: str = "mail") -> None:
        with client.app.state.bus.unit_of_work() as work:  # type: ignore[attr-defined]
            work.emit(
                "notification.requested",
                {"kind": kind, "title": title, "detail": "", "link": None},
                source="test",
                trace_id="t",
            )

    def listing(**body: str) -> dict[str, Any]:
        for _ in range(200):
            result = client.post("/api/queries/notifications.list", json=body).json()
            if result["items"]:
                return result
            time.sleep(0.01)
        raise AssertionError("no notification arrived")

    request("First")
    first = listing()
    assert first["unread"] == 1 and first["kinds"] == ["mail"]
    request("Second", kind="agent")
    for _ in range(200):
        if listing()["unread"] == 2:
            break
        time.sleep(0.01)
    both = listing()
    assert [item["title"] for item in both["items"]] == ["Second", "First"]
    assert [item["title"] for item in listing(kind="agent")["items"]] == ["Second"]

    newest = both["items"][0]["id"]
    assert (
        client.post("/api/commands/notifications.markRead", json={"id": newest}).json()["unread"]
        == 1
    )
    assert client.post("/api/commands/notifications.markRead", json={}).json()["unread"] == 0


def test_sidebar_layout_saves_and_resets(client: TestClient) -> None:
    layout = {
        "sections": ["agent", "mail"],
        "items": {"mail": ["sent", "inbox"]},
        "hidden": ["drafts"],
    }
    assert client.post("/api/commands/sidebar.update", json=layout).json() == layout
    assert client.post("/api/queries/sidebar.get").json() == layout
    empty = {"sections": [], "items": {}, "hidden": []}
    assert client.post("/api/commands/sidebar.reset").json() == empty
    assert client.post("/api/queries/sidebar.get").json() == empty


def test_settings_validate_the_new_preferences(client: TestClient) -> None:
    saved = client.post(
        "/api/commands/settings.update",
        json={"accent": "moss", "theme": "system", "time_format": "24"},
    ).json()
    assert (saved["accent"], saved["theme"], saved["time_format"]) == ("moss", "system", "24")
    assert client.post("/api/commands/settings.update", json={"accent": "neon"}).status_code == 422


def test_support_report_has_no_personal_details(
    client: TestClient, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://user:hunter2@proxy.corp.example:8080")
    result = client.post("/api/queries/diagnostics.get").json()
    assert result["proxy"] == "proxy.corp.example"
    assert "hunter2" not in json.dumps(result)
    assert str(config.home) not in result["report"]
    assert "proxy.corp" not in result["report"]
    assert result["report"].startswith("NexusAI ")
