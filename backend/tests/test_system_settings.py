"""A company install: servers set once in .env, POP3 mail, plain SMTP and a plain http model."""

import json
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import PASSWORD, USER, FakeMail, make_mail, start_fake_mail
from fake_pop3 import FakePop3, start_fake_pop3
from nexusai.api.app import create_app
from nexusai.kernel.config import Config, SystemMail, SystemModel, load_config
from nexusai.modules.mail import store
from nexusai.modules.mail.parse import parse_message
from test_mail_sync import status, threads, wait


@pytest.fixture
def pop3() -> Iterator[FakePop3]:
    server = start_fake_pop3()
    yield server
    server.stop()


@pytest.fixture
def smtp() -> Iterator[FakeMail]:
    server = start_fake_mail()
    yield server
    server.stop()


def with_servers(config: Config, pop3: FakePop3, smtp: FakeMail) -> Config:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
    )
    system = SystemMail(
        label="Company mail",
        protocol="pop3",
        host="127.0.0.1",
        port=pop3.port,
        secure=False,
        verify_cert=True,
        smtp_host="127.0.0.1",
        smtp_port=smtp.smtp_port,
        smtp_secure=False,
        domain="corp.example",
    )
    return replace(config, mail=mail, system_mail=system)


@pytest.fixture
def client(config: Config, pop3: FakePop3, smtp: FakeMail) -> Iterator[TestClient]:
    app = create_app(with_servers(config, pop3, smtp))
    with TestClient(app, base_url="http://127.0.0.1:4100") as test:
        yield test


def login_only_profile() -> dict[str, Any]:
    """What the form sends: the servers in it don't matter, since the system settings win."""
    placeholder = {"host": "ignored.example", "port": 1, "secure": False}
    return {
        "label": "Company mail",
        "system": True,
        "imap": placeholder,
        "smtp": placeholder,
        "auth": {"type": "password", "user": USER},
    }


def connect(client: TestClient) -> None:
    saved = client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "work", "profile": login_only_profile(), "password": PASSWORD},
    )
    assert saved.status_code == 200, saved.text
    wait(lambda: status(client)["state"] == "live", "sync to go live")


def subjects(client: TestClient, **body: Any) -> set[str]:
    return {row["subject"] for row in threads(client, **body)}


def test_env_file_sets_the_system_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "company.env"
    env.write_text(
        "# Company servers\n"
        "NEXUSAI_MODEL_URL=http://10.1.2.3:8000/v1/\n"
        'NEXUSAI_MODEL_API_KEY="secret-key"\n'
        "NEXUSAI_MODEL_NAMES=fast, slow\n"
        "NEXUSAI_MAIL_HOST=10.1.2.4\n"
        "NEXUSAI_MAIL_DOMAIN=corp.example\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXUSAI_ENV_FILE", str(env))
    loaded = load_config(tmp_path)
    assert loaded.system_model is not None and loaded.system_mail is not None
    assert loaded.system_model.base_url == "http://10.1.2.3:8000/v1"
    assert loaded.system_model.names == ("fast", "slow")
    assert "secret-key" not in repr(loaded)
    mail = loaded.system_mail
    assert (mail.protocol, mail.port, mail.secure) == ("pop3", 995, True)
    assert (mail.smtp_host, mail.smtp_port, mail.smtp_secure) == ("10.1.2.4", 25, False)
    # Something really set wins over the file, and the key stays out of what commands inherit.
    monkeypatch.setenv("NEXUSAI_MAIL_PORT", "1995")
    again = load_config(tmp_path).system_mail
    assert again is not None and again.port == 1995
    assert "NEXUSAI_MODEL_API_KEY" not in os.environ


def test_without_settings_nothing_changes(config: Config) -> None:
    assert config.system_mail is None and config.system_model is None
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as test:
        presets = test.post("/api/queries/mail.presets", json={}).json()["presets"]
        model = test.post("/api/queries/models.status", json={}).json()
    assert [row["domain"] for row in presets] == ["gmail.com"]
    assert presets[0]["protocol"] == "imap" and not presets[0]["system"]
    assert not model["managed"] and not model["connected"]


def test_system_server_is_offered_beside_gmail(client: TestClient) -> None:
    presets = client.post("/api/queries/mail.presets", json={}).json()["presets"]
    by_domain = {row["domain"]: row for row in presets}
    assert by_domain["gmail.com"]["protocol"] == "imap"
    assert by_domain["*"]["system"] and by_domain["*"]["protocol"] == "pop3"
    assert by_domain["*"]["address_domain"] == "corp.example"


def test_connection_test_counts_the_pop3_mailbox(client: TestClient, pop3: FakePop3) -> None:
    pop3.state.deliver(make_mail("First"))
    pop3.state.deliver(make_mail("Second"))
    result = client.post(
        "/api/commands/mail.accounts.test",
        json={"profile": login_only_profile(), "password": PASSWORD},
    ).json()
    assert result["ok"], result
    assert result["total"] == 2
    assert [row["role"] for row in result["counts"]] == ["inbox"]
    # A test only looks. It must not download anything.
    assert pop3.state.retrieved == []


def test_wrong_pop3_password_says_so(client: TestClient) -> None:
    result = client.post(
        "/api/commands/mail.accounts.test",
        json={"profile": login_only_profile(), "password": "wrong"},
    ).json()
    incoming = next(row for row in result["results"] if row["service"] == "imap")
    assert not incoming["ok"]
    assert "refused" in incoming["message"]


def test_mail_arrives_and_new_mail_needs_a_new_connection(
    client: TestClient, pop3: FakePop3
) -> None:
    pop3.state.deliver(make_mail("Old report"))
    connect(client)
    wait(lambda: "Old report" in subjects(client), "history")
    seen = pop3.state.connections
    pop3.state.deliver(make_mail("Fresh news"))
    wait(lambda: "Fresh news" in subjects(client), "new mail")
    assert pop3.state.connections > seen
    assert pop3.state.retrieved.count("id-0001") == 1


def test_read_marks_stay_here_and_mail_the_server_dropped_stays_too(
    client: TestClient, pop3: FakePop3
) -> None:
    name = pop3.state.deliver(make_mail("Keep me"))
    connect(client)
    thread = wait(lambda: next((t for t in threads(client) if t["subject"] == "Keep me"), None))
    done = client.post("/api/commands/thread.setRead", json={"id": thread["id"], "read": True})
    assert done.status_code == 200
    pop3.state.drop(name)
    seen = pop3.state.connections
    wait(lambda: pop3.state.connections > seen + 1, "another couple of checks")
    row = next(t for t in threads(client) if t["subject"] == "Keep me")
    assert row["unread_count"] == 0


def test_restart_downloads_nothing_again(config: Config, pop3: FakePop3, smtp: FakeMail) -> None:
    pop3.state.deliver(make_mail("Only once"))
    made = with_servers(config, pop3, smtp)
    with TestClient(create_app(made), base_url="http://127.0.0.1:4100") as test:
        connect(test)
        wait(lambda: "Only once" in subjects(test))
    pop3.state.deliver(make_mail("After restart"))
    with TestClient(create_app(made), base_url="http://127.0.0.1:4100") as test:
        wait(lambda: "After restart" in subjects(test))
        assert "Only once" in subjects(test)
    assert pop3.state.retrieved.count("id-0001") == 1


def test_long_lines_and_one_refused_mail_dont_stop_the_rest(
    client: TestClient, pop3: FakePop3
) -> None:
    pop3.state.deliver(make_mail("Long line", body="x" * 5000))
    bad = pop3.state.deliver(make_mail("Refused"))
    pop3.state.refuse.add(bad)
    pop3.state.deliver(make_mail("After it"))
    connect(client)
    wait(lambda: {"Long line", "After it"} <= subjects(client), "the other mail")


def test_a_locked_mailbox_retries_instead_of_blaming_the_password(
    client: TestClient, pop3: FakePop3
) -> None:
    pop3.state.busy = True
    saved = client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "work", "profile": login_only_profile(), "password": PASSWORD},
    )
    assert saved.status_code == 200
    wait(lambda: status(client)["state"] == "offline", "it to wait")
    pop3.state.busy = False
    wait(lambda: status(client)["state"] == "live", "it to carry on")


def _send(client: TestClient, subject: str, **extra: Any) -> None:
    draft = {
        "to": [{"name": "Priya", "address": "priya@corp.example"}],
        "cc": [],
        "bcc": [],
        "subject": subject,
        "body": "Hello",
        **extra,
    }
    sent = client.post("/api/commands/mail.send", json={"draft": draft})
    assert sent.status_code == 200, sent.text


def test_sent_mail_goes_by_plain_smtp_and_is_kept_here(
    client: TestClient, pop3: FakePop3, smtp: FakeMail
) -> None:
    connect(client)
    _send(client, "Status update")
    assert len(smtp.sent) == 1
    wait(lambda: "Status update" in subjects(client, folder="sent"), "the sent copy")


def test_a_relay_that_wants_no_sign_in_still_sends(
    client: TestClient, pop3: FakePop3, smtp: FakeMail
) -> None:
    smtp.servers[1].offers_auth = False  # type: ignore[attr-defined]
    connect(client)
    _send(client, "Through the relay")
    assert len(smtp.sent) == 1


def test_mail_to_yourself_is_one_email(client: TestClient, pop3: FakePop3, smtp: FakeMail) -> None:
    connect(client)
    _send(client, "Note to self")
    assert len(smtp.sent) == 1
    raw = smtp.sent[0]["raw"].replace(b"\r\n..", b"\r\n.")
    pop3.state.deliver(raw)
    wait(lambda: pop3.state.retrieved, "it to come back")
    wait(lambda: "Note to self" in subjects(client), "it in the inbox")
    assert sum(t["subject"] == "Note to self" for t in threads(client, folder="all")) == 1


def test_delete_stays_on_the_server_unless_allowed(client: TestClient, pop3: FakePop3) -> None:
    pop3.state.deliver(make_mail("Stay on server"))
    connect(client)
    thread = wait(
        lambda: next((t for t in threads(client) if t["subject"] == "Stay on server"), None)
    )
    moved = client.post("/api/commands/thread.move", json={"id": thread["id"], "to": "trash"})
    assert moved.status_code == 200
    seen = pop3.state.connections
    wait(lambda: pop3.state.connections > seen, "another check")
    assert pop3.state.deleted == []
    assert "Stay on server" not in subjects(client)
    assert "Stay on server" in subjects(client, folder="trash")


def test_pst_folders_survive_a_pop3_mailbox(client: TestClient, pop3: FakePop3) -> None:
    """POP3 has one mailbox, but mail brought in from a PST keeps the folders it came with."""
    connect(client)
    raw = make_mail("From the archive")
    database = client.app.state.bus.db  # type: ignore[attr-defined]
    with database.transaction() as tx:
        stored = store.store_message(
            tx,
            account="work",
            folder="pst:1:Projects/2024",
            role="other",
            uid=1,
            raw=raw,
            read=True,
            flagged=False,
            parsed=parse_message(raw),
            match=None,
            config=load_config().mail,
        )
    assert stored is not None
    seen = pop3.state.connections
    wait(lambda: pop3.state.connections > seen + 1, "more checks")
    places = database.fetch_all(
        "SELECT folder FROM message_locations WHERE message = ?", (stored.message,)
    )
    assert [row["folder"] for row in places] == ["pst:1:Projects/2024"]


class _ModelServer(BaseHTTPRequestHandler):
    seen_keys: list[str] = []
    prompts: list[Any] = []

    def _answer(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.seen_keys.append(self.headers.get("authorization", ""))
        self._answer({"data": [{"id": "model-b"}, {"id": "model-a"}]})

    def do_POST(self) -> None:
        self.seen_keys.append(self.headers.get("authorization", ""))
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self.prompts.append(body)
        self._answer({"choices": [{"message": {"content": f"hello from {body['model']}"}}]})

    def log_message(self, *_: Any) -> None:
        pass


@pytest.fixture
def model_url() -> Iterator[str]:
    _ModelServer.seen_keys, _ModelServer.prompts = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


def model_client(config: Config, url: str, names: tuple[str, ...] = ()) -> Callable[[], TestClient]:
    system = SystemModel(url, "company-key", names, True)
    return lambda: TestClient(
        create_app(replace(config, system_model=system)), base_url="http://127.0.0.1:4100"
    )


def test_model_from_system_settings_only_shows_names(config: Config, model_url: str) -> None:
    with model_client(config, model_url)() as test:
        status_now = test.post("/api/queries/models.status", json={})
        assert status_now.json()["managed"] and status_now.json()["connected"]
        names = test.post("/api/queries/models.list", json={}).json()["models"]
        assert [row["id"] for row in names] == ["model-a", "model-b"]
        assert test.post("/api/commands/models.select", json={"model": "nope"}).status_code == 422
        chosen = test.post("/api/commands/models.select", json={"model": "model-b"}).json()
        assert chosen["selected_model"] == "model-b"
        reply = test.post("/api/commands/models.test", json={"prompt": "hi"}).json()
        assert reply["text"] == "hello from model-b"
        for query in ("models.status", "models.provider", "models.list"):
            answer = test.post(f"/api/queries/{query}", json={}).text
            assert "company-key" not in answer and model_url not in answer
    assert set(_ModelServer.seen_keys) == {"Bearer company-key"}


def test_listed_model_names_need_no_server_and_the_first_is_the_default(
    config: Config, model_url: str
) -> None:
    with model_client(config, "http://127.0.0.1:9/v1", ("fast", "slow"))() as test:
        assert test.post("/api/queries/models.status", json={}).json()["selected_model"] == "fast"
        names = test.post("/api/queries/models.list", json={}).json()["models"]
        assert [row["id"] for row in names] == ["fast", "slow"]


def test_hand_entered_model_server_can_be_plain_http(config: Config, model_url: str) -> None:
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as test:
        body = {"provider": "litellm", "base_url": "http://10.1.2.3:8000/v1", "model": "m"}
        assert test.post("/api/commands/models.provider.save", json=body).status_code == 200
        body["base_url"] = "https://llm.example/v1"
        assert test.post("/api/commands/models.provider.save", json=body).status_code == 200
        body["base_url"] = "ftp://llm.example/v1"
        assert test.post("/api/commands/models.provider.save", json=body).status_code == 422
