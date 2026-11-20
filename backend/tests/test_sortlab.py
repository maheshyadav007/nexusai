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
SIGN_IN = {"username": corp_mail.OWNER[1], "password": "secret"}


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
    monkeypatch.setattr(sortlab, "open_session", lambda sign_in, settings: server)
    (tmp_path / "sortlab.env").write_text(
        "NEXUSAI_MAIL_HOST=mail.korvia.example\nNEXUSAI_MAIL_DOMAIN=korvia.example\n"
    )
    monkeypatch.setattr(sortlab, "settings_files", lambda: [tmp_path / "sortlab.env"])
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
    second = report["groups"][1]
    missed = report["missed"][0]
    finish = {
        "groups": [
            {"id": first["id"], "name": "Parts system", "folder": "inbox"},
            {"id": second["id"], "merged_into": first["id"]},
        ],
        "misses": [{"sender": missed["sender"], "name": "Reviews", "folder": "automated"}],
        "details": False,
    }
    done = client.post("/api/finish", json=finish).json()
    assert done["deleted"] == 1000
    assert not state.folder.exists()
    saved = json.loads(Path(done["saved"]).read_text())
    category, merged = saved["categories"]
    assert (category["name"], category["engine_name"]) == ("Parts system", first["label"])
    # The person's choice is kept beside the engine's, so the difference shows what to fix.
    assert (category["folder"], category["engine_folder"], category["ai_reads"]) == (
        "inbox",
        "automated",
        True,
    )
    # A merge points at the other category by the same neutral number, not its address.
    assert merged["merged_into"] == category["id"] == "group-1"
    assert saved["added_from_ungrouped"] == [
        {
            "name": "Reviews",
            "folder": "automated",
            "ai_reads": False,
            "count": missed["count"],
            "merged_into": "",
        }
    ]
    # Without details, no sender or subject leaves the computer in the file.
    assert "@" not in json.dumps(saved) and "senders" not in category


def test_details_keep_senders_and_patterns_for_improving_the_engine(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    report = client.get("/api/report").json()
    first, missed = report["groups"][0], report["missed"][0]
    body = {
        "groups": [{"id": first["id"]}],
        "misses": [
            {"sender": missed["sender"], "folder": "automated"},
            {"sender": "untouched@x.example"},
        ],
        "details": True,
    }
    saved = json.loads(Path(client.post("/api/finish", json=body).json()["saved"]).read_text())
    category = saved["categories"][0]
    assert category["senders"] == first["senders"] and category["patterns"]
    assert (category["name"], category["folder"]) == (first["label"], first["folder"])
    # Only senders the person changed are kept.
    assert [row["sender"] for row in saved["added_from_ungrouped"]] == [missed["sender"]]


def test_each_email_shown_says_when_it_came_and_whether_it_names_the_person(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    report = client.get("/api/report").json()
    emails = [email for group in report["groups"] for email in group["emails"]]
    assert all(email["when"] and "from" in email and "snippet" in email for email in emails)
    assert any(email["names_you"] for email in emails)
    assert {group["folder"] for group in report["groups"]} == {"automated", "calendar", "inbox"}


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


def test_the_page_asks_only_for_a_username_and_password(lab: Any) -> None:
    _, _, client = lab
    page = client.get("/").text
    assert 'id="username"' in page and 'id="password"' in page
    assert not any(field in page for field in ('id="host"', 'id="port"', 'id="protocol"'))
    assert client.get("/api/setup").json() == {
        "ready": True,
        "domain": "korvia.example",
        "settings_file": client.get("/api/setup").json()["settings_file"],
    }
    assert "host" not in client.get("/api/setup").json()


def test_without_a_server_in_the_settings_nothing_starts(
    lab: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, client = lab
    monkeypatch.setattr(sortlab, "settings_files", lambda: [tmp_path / "missing.env"])
    assert client.get("/api/setup").json()["ready"] is False
    refused = client.post("/api/start", json=SIGN_IN)
    assert refused.status_code == 422 and "sortlab.env" in refused.text


def test_settings_come_from_the_file_and_a_plain_login_gets_the_company_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = tmp_path / "sortlab.env"
    settings.write_text(
        "# company server\nNEXUSAI_MAIL_HOST=pop.firm.example\nNEXUSAI_MAIL_PROTOCOL=pop3\n"
        "NEXUSAI_MAIL_VERIFY_CERT=false\nNEXUSAI_MAIL_DOMAIN=@firm.example\nNEXUSAI_SORTLAB_LIMIT=500\n"
    )
    monkeypatch.setattr(sortlab, "settings_files", lambda: [tmp_path / "missing.env", settings])
    server = sortlab.server_settings()
    assert server is not None
    assert (server.host, server.protocol, server.port, server.verify_cert, server.limit) == (
        "pop.firm.example", "pop3", 995, False, 500
    )  # fmt: skip
    assert sortlab.address_for("sam.lee", server.domain) == "sam.lee@firm.example"
    assert sortlab.address_for("sam@else.example", server.domain) == "sam@else.example"
