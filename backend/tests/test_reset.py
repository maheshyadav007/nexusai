"""Reset removes everything NexusAI made, and nothing else, and setup can start again."""
# ruff: noqa: F811

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import psutil
import pytest
from fastapi.testclient import TestClient

from fake_mail import PASSWORD, FakeMail, make_mail
from nexusai.api.app import create_app
from nexusai.kernel import home as homes
from nexusai.kernel.config import Config
from nexusai.modules.agent.providers import TextChunk
from nexusai.modules.semantic import downloader
from nexusai.modules.semantic.catalog import DEFAULT
from test_agent_work import Script, connect, fake, script, thread_named, wait  # noqa: F401
from test_chat_engine import chat, new_session


@pytest.fixture
def setup(tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch, script: Script) -> Any:
    secrets = tmp_path / "secrets.json"
    data = tmp_path / "app-data"
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(data))
    home = tmp_path / "MyHome"
    fresh = replace(
        config,
        home_dir=None,
        secrets_test_file=secrets,
        database_key=None,
        mail=replace(
            config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
        ),
    )
    with TestClient(create_app(fresh), base_url="http://127.0.0.1:4100") as client:
        assert client.post("/api/home/choose", json={"path": str(home)}).is_success
        yield client, home, secrets, data


def reset(client: TestClient, **fields: Any) -> Any:
    return client.post("/api/home/reset", json={"confirm": "RESET", **fields})


def fill_everything(client: TestClient, script: Script, fake: FakeMail, home: Path) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Keep me out"))
    thread_named(client, "Keep me out")
    client.post("/api/documents/upload", params={"name": "secret.txt"}, content=b"private words")
    client.post("/api/commands/tasks.save", json={"title": "A task"})
    client.post("/api/commands/schedules.save", json={"title": "Weekly", "prompt": "Go"})
    session = new_session(client)
    script.replies = [[TextChunk("Hello.")]]
    chat(client, session, "Hi")
    (home / "artifacts" / "report.md").write_text("Made by an agent")
    (home / "memory" / "fact.md").write_text("A fact")
    (home / "system" / "models" / DEFAULT).mkdir(parents=True)
    (home / "system" / "models" / DEFAULT / "model.onnx").write_bytes(b"weights")


def test_it_needs_the_word_typed(setup: Any) -> None:
    client, home, _, _ = setup
    refused = client.post("/api/home/reset", json={"confirm": "reset"})
    assert refused.status_code == 422
    assert client.post("/api/home/reset", json={"confirm": ""}).status_code == 422
    assert homes.is_home(home)


def test_everything_goes_and_setup_starts_again(setup: Any, script: Script, fake: FakeMail) -> None:
    client, home, secrets, data = setup
    fill_everything(client, script, fake, home)
    assert (home / "system" / "mail-accounts.enc").exists()
    assert any(name.startswith("home-key:") for name in json.loads(secrets.read_text()))

    assert reset(client, keep_models=False).is_success
    assert client.post("/api/home/status").json()["state"] == "unset"
    assert sorted(path.name for path in home.iterdir()) == []
    # Nothing is left in the credential store, and the pointer is gone.
    assert json.loads(secrets.read_text()) == {}
    assert homes.read_pointer(data) is None
    # Nothing answers until a Home is chosen again.
    assert client.post("/api/queries/threads.list", json={}).status_code == 409


def test_a_fresh_home_works_again_in_the_same_process(
    setup: Any, script: Script, fake: FakeMail
) -> None:
    client, home, _, _ = setup
    fill_everything(client, script, fake, home)
    assert reset(client).is_success
    assert client.post("/api/home/choose", json={"path": str(home)}).is_success
    assert client.post("/api/queries/threads.list", json={}).json()["threads"] == []
    assert client.post("/api/queries/tasks.list", json={}).json()["tasks"] == []
    assert client.post("/api/queries/schedules.list").json()["schedules"] == []
    assert client.post("/api/queries/onboarding.state").json()["completed"] is False
    assert client.post("/api/queries/mail.status").json()["state"] == "off"
    # Everything that was stopped is running again.
    session = new_session(client)
    script.replies = [[TextChunk("Back again.")]]
    assert "Back again." in "".join(p.get("delta", "") for p in chat(client, session, "Hi"))
    client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "t", "profile": fake.profile(), "password": PASSWORD},
    )
    wait(lambda: client.post("/api/queries/mail.status").json()["state"] == "live", "mail")
    fake.state.deliver(make_mail(subject="After the reset"))
    thread_named(client, "After the reset")
    uploaded = client.post(
        "/api/documents/upload", params={"name": "new.txt"}, content=b"new words"
    ).json()
    wait(
        lambda: (
            client.post("/api/queries/documents.get", json={"key": uploaded["key"]}).json()[
                "document"
            ]["status"]
            == "ready"
        ),
        "the reader to run again",
    )


@pytest.mark.parametrize("keep", [True, False])
def test_downloaded_models_stay_only_if_asked(
    setup: Any, script: Script, fake: FakeMail, keep: bool
) -> None:
    client, home, _, _ = setup
    fill_everything(client, script, fake, home)
    assert reset(client, keep_models=keep).is_success
    assert (home / "system" / "models" / DEFAULT / "model.onnx").exists() is keep
    assert sorted(path.name for path in home.iterdir()) == (["system"] if keep else [])
    if keep:
        assert [path.name for path in (home / "system").iterdir()] == ["models"]
    assert downloader is not None


@pytest.mark.skipif(sys.platform == "win32", reason="Needs symlinks or POSIX file modes")
def test_only_what_nexusai_made_is_removed(
    setup: Any, tmp_path: Path, script: Script, fake: FakeMail
) -> None:
    client, home, _, _ = setup
    fill_everything(client, script, fake, home)
    (home / "my-own-notes.txt").write_text("mine")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important.txt").write_text("not yours")
    (home / "scratch" / "link").symlink_to(outside)
    archive = tmp_path / "archive.pst"
    archive.write_bytes(b"read in place")
    client.post("/api/commands/pst.add", json={"path": str(archive)})
    assert reset(client, keep_models=False).is_success
    assert (home / "my-own-notes.txt").read_text() == "mine"
    assert (outside / "important.txt").read_text() == "not yours"
    assert archive.read_bytes() == b"read in place"


def test_old_account_details_arent_picked_up_again(setup: Any, script: Script) -> None:
    client, home, _, data = setup
    earlier = data / "mail-accounts.json"
    earlier.parent.mkdir(parents=True, exist_ok=True)
    earlier.write_text(json.dumps({"activeProfile": None, "profiles": {}}))
    assert reset(client).is_success
    assert not earlier.exists()


def test_running_work_is_stopped_first(setup: Any, script: Script) -> None:
    import threading

    client, _, _, _ = setup
    session = new_session(client)
    script.gate = threading.Event()
    script.replies = [[TextChunk("Slow.")]]
    threading.Thread(target=lambda: chat(client, session, "Hi"), daemon=True).start()
    wait(lambda: script.requests, "the run to start")
    script.gate.set()
    assert reset(client).is_success


def test_no_file_stays_open_when_a_home_closes(setup: Any, script: Script, fake: FakeMail) -> None:
    """Windows refuses to remove an open file, so a handle left behind would break Reset there."""
    client, home, _, _ = setup
    fill_everything(client, script, fake, home)
    assert reset(client, keep_models=False).is_success
    left = [item.path for item in psutil.Process().open_files() if str(home) in item.path]
    assert left == []


def test_a_file_held_by_another_program_is_named_and_the_app_can_carry_on(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, home, _, _ = setup

    def refused(*_: Any, **__: Any) -> None:
        raise PermissionError(13, "in use", str(home / "documents" / "held.docx"))

    monkeypatch.setattr(homes, "wipe", refused)
    answer = reset(client, keep_models=False)
    assert answer.status_code == 409
    assert "held.docx" in answer.json()["message"]
    assert client.post("/api/home/status").json()["state"] == "unset"
