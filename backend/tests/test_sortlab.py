"""The sort lab from sign-in to a finished experiment, against a made-up mailbox."""

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import corp_mail
from nexusai.modules.mail.imap import Fetched, Folder
from nexusai.sortlab import lab as sortlab

TOKEN = "test-token"
SIGN_IN = {
    "address": corp_mail.OWNER[1],
    "password": "secret",
    "host": "mail.korvia.example",
    "port": 993,
}


class FakeServer:
    """Two folders and a trash, holding the made-up mailbox. Records anything that would change it."""

    def __init__(self, folder: Path) -> None:
        raws = [path.read_bytes() for path in sorted(folder.glob("*.eml"))]
        self.boxes = {"INBOX": raws[:700], "Archive": raws[700:], "Trash": raws[:5]}
        self.selected = ""
        self.changes: list[str] = []

    def folders(self) -> list[Folder]:
        return [Folder("INBOX", "inbox"), Folder("Archive", "archive"), Folder("Trash", "trash")]

    def select(self, name: str) -> tuple[int, int]:
        self.selected = name
        return 1, len(self.boxes[name])

    def all_uids(self) -> list[int]:
        return list(range(1, len(self.boxes[self.selected]) + 1))

    def fetch(self, uids: list[int]) -> list[Fetched]:
        return [Fetched(uid, self.boxes[self.selected][uid - 1], False, False) for uid in uids]

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        self.changes.append(name)
        raise AssertionError(f"The lab must not call {name}")


@pytest.fixture
def lab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[sortlab.Lab, FakeServer, TestClient]:
    corp_mail.build(tmp_path / "source")
    server = FakeServer(tmp_path / "source")
    monkeypatch.setattr(sortlab, "open_session", lambda sign_in: server)
    state = sortlab.Lab(folder=tmp_path / "mail", results=tmp_path / "results")
    client = TestClient(sortlab.create_app(state, TOKEN), headers={"X-Lab-Token": TOKEN})
    return state, server, client


def _ready(client: TestClient) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = client.get("/api/status").json()
        if status["state"] in {"ready", "failed"}:
            return status
        time.sleep(0.1)
    raise AssertionError("The lab never finished grouping")


def test_an_experiment_groups_saves_feedback_and_deletes_the_mail(lab: Any) -> None:
    state, server, client = lab
    assert client.post("/api/start", json=SIGN_IN).status_code == 200
    assert _ready(client)["state"] == "ready"
    # Trash is skipped, and nothing on the server was changed.
    assert len(list(state.folder.glob("*.eml"))) == 1000
    assert not server.changes
    report = client.get("/api/report").json()
    assert report["owner"] == corp_mail.OWNER[1] and report["total"] == 1000
    first = report["groups"][0]
    assert first["emails"] and first["section"] == "automated"
    finish = {
        "groups": [{"id": first["id"], "name": "Parts system", "verdict": "right"}],
        "misses": [{"sender": report["missed"][0]["sender"], "verdict": "right"}]
        if report["missed"]
        else [],
        "details": False,
    }
    done = client.post("/api/finish", json=finish).json()
    assert done["deleted"] == 1000
    assert not state.folder.exists()
    saved = json.loads(Path(done["saved"]).read_text())
    assert saved["groups"][0]["name"] == "Parts system"
    assert saved["groups"][0]["engine_name"] == first["label"]
    # Without details, no sender or subject leaves the computer in the file.
    text = json.dumps(saved)
    assert "@" not in text and "senders" not in saved["groups"][0]


def test_details_keep_senders_and_patterns_for_improving_the_engine(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    first = client.get("/api/report").json()["groups"][0]
    wrong = first["emails"][0]["key"]
    body = {"groups": [{"id": first["id"], "not_belonging": [wrong]}], "details": True}
    saved = json.loads(Path(client.post("/api/finish", json=body).json()["saved"]).read_text())
    group = saved["groups"][0]
    assert group["senders"] == first["senders"] and group["patterns"]
    assert group["not_belonging_subjects"] == [first["emails"][0]["subject"]]


def test_discarding_deletes_the_mail_and_saves_nothing(lab: Any) -> None:
    state, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    assert client.post("/api/discard").json()["deleted"] == 1000
    assert not state.folder.exists() and not state.results.exists()


def test_only_this_runs_page_can_use_it(lab: Any) -> None:
    _, _, client = lab
    stranger = {"X-Lab-Token": "guess"}
    assert client.get("/api/status", headers=stranger).status_code == 403
    assert client.post("/api/start", json=SIGN_IN, headers=stranger).status_code == 403
    assert client.get("/").status_code == 200
