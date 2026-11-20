"""The sort lab from sign-in to a finished experiment, against a made-up mailbox."""

import json
import subprocess
import sys
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


def test_an_experiment_scores_senders_saves_choices_and_deletes_the_mail(lab: Any) -> None:
    state, server, client = lab
    assert client.post("/api/start", json=SIGN_IN).status_code == 200
    assert _ready(client)["state"] == "ready"
    # Trash is skipped, and nothing on the server was changed.
    assert len(list(state.folder.glob("*.eml"))) == 1000
    assert not server.changes
    report = client.get("/api/report").json()
    assert report["owner"] == corp_mail.OWNER[1] and report["total"] == 1000
    rows = report["senders"]
    assert [row["count"] for row in rows] == sorted((row["count"] for row in rows), reverse=True)
    ignored = [row for row in rows if row["side"] == "ignores"]
    # The five biggest the AI ignores start as their own categories.
    assert [row["own"] for row in ignored[:6]] == [True] * 5 + [False]
    tool, person = ignored[0], next(row for row in rows if row["side"] == "reads")
    finish = {
        "senders": [
            {"sender": tool["sender"], "side": "ignores", "own": True, "name": "Code reviews"},
            {"sender": person["sender"], "side": "ignores"},
        ],
        "details": False,
    }
    done = client.post("/api/finish", json=finish).json()
    assert done["deleted"] == 1000
    assert not state.folder.exists()
    saved = json.loads(Path(done["saved"]).read_text())
    assert saved["senders"] == len(rows) and saved["moved_by_person"] == 1
    first = saved["rows"][0]
    assert (first["name"], first["own_category"], first["side"]) == (
        "Code reviews",
        True,
        "ignores",
    )
    moved = next(
        row for row in saved["rows"] if row["engine_side"] == "reads" and row["side"] == "ignores"
    )
    assert moved["count"] == person["count"]
    assert "Code reviews" in saved["categories"]
    # Without details, no sender or subject leaves the computer in the file.
    assert "@" not in json.dumps(saved) and "examples" not in first


def test_details_keep_senders_and_score_signs_for_improving_the_engine(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    first = client.get("/api/report").json()["senders"][0]
    body = {"senders": [], "details": True}
    saved = json.loads(Path(client.post("/api/finish", json=body).json()["saved"]).read_text())
    row = saved["rows"][0]
    assert row["id"] == first["sender"] and row["examples"] == first["examples"]
    assert {"repeats", "bulk", "one_way"} <= row.keys()
    # Nothing changed by the person: every sender stays where the engine put it.
    assert saved["moved_by_person"] == 0


def test_each_email_shown_says_when_it_came_and_whether_it_still_reaches_the_ai(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    report = client.get("/api/report").json()
    emails = [email for row in report["senders"] for email in row["emails"]]
    assert all(email["when"] and "snippet" in email for email in emails)
    ignored = [row for row in report["senders"] if row["side"] == "ignores" and row["reach"]]
    assert any(email["names_you"] for row in ignored for email in row["emails"])


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


def test_a_sender_that_names_everyone_lets_none_of_it_through(lab: Any) -> None:
    _, _, client = lab
    client.post("/api/start", json=SIGN_IN)
    _ready(client)
    report = client.get("/api/report").json()
    team = next(row for row in report["senders"] if row["examples"][0].startswith("weekly effort"))
    assert team["side"] == "ignores" and team["reach"] == 0


def test_the_lab_needs_no_database_or_keychain_library() -> None:
    """The exe leaves them out, so importing either would stop it from starting."""
    code = (
        "import sys, nexusai.sortlab.lab, nexusai.sortlab.__main__\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & {'sqlcipher3', 'keyring'}))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert loaded.stdout.strip() == "[]"
