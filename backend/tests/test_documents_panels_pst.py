import io
import os
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import PASSWORD, FakeMail, make_mail, start_fake_mail
from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.mail import pst
from nexusai.modules.mail.extract import extract_text

TESTS = Path(__file__).parent
SAMPLE = os.environ.get("NEXUSAI_TEST_PST")


def wait(check: Callable[[], Any], what: str = "condition", seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture
def app_config(config: Config) -> Config:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, idle_seconds=1
    )
    return replace(config, mail=mail)


@pytest.fixture
def client(app_config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as test:
        yield test


@pytest.fixture
def fake() -> Iterator[FakeMail]:
    server = start_fake_mail()
    yield server
    server.stop()


def connect(client: TestClient, fake: FakeMail) -> None:
    client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "t", "profile": fake.profile(), "password": PASSWORD},
    )
    wait(lambda: client.post("/api/queries/mail.status").json()["state"] == "live", "live")


def docx_bytes(text: str) -> bytes:
    from docx import Document

    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def xlsx_bytes(text: str) -> bytes:
    from openpyxl import Workbook

    buffer = io.BytesIO()
    book = Workbook()
    book.active["A1"] = text
    book.save(buffer)
    return buffer.getvalue()


def pptx_bytes(text: str) -> bytes:
    from pptx import Presentation

    buffer = io.BytesIO()
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[0])
    slide.shapes.title.text = text
    deck.save(buffer)
    return buffer.getvalue()


def pdf_bytes(text: str) -> bytes:
    body = f"BT /F1 12 Tf 10 10 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, item in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + item + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(out)


@pytest.mark.parametrize(
    ("name", "make"),
    [("a.docx", docx_bytes), ("a.xlsx", xlsx_bytes), ("a.pptx", pptx_bytes), ("a.pdf", pdf_bytes)],
)
def test_text_comes_out_of_office_files_and_pdfs(name: str, make: Callable[[str], bytes]) -> None:
    assert "quarterly" in extract_text(name, make("quarterly numbers"))


def test_bad_or_unknown_files_give_no_text_and_no_error() -> None:
    assert extract_text("a.pdf", b"not a pdf") == ""
    assert extract_text("a.docx", b"not a zip") == ""
    assert extract_text("a.bin", b"\x00\x01") == ""
    assert extract_text("a.txt", b"plain words") == "plain words"


def test_zip_bombs_arent_opened() -> None:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * 50_000_000)
    assert extract_text("a.docx", buffer.getvalue()) == ""


def upload(client: TestClient, name: str, data: bytes) -> dict[str, Any]:
    response = client.post("/api/documents/upload", params={"name": name}, content=data)
    assert response.status_code == 200, response.text
    return response.json()


def library(client: TestClient, **body: Any) -> dict[str, Any]:
    return client.post("/api/queries/documents.list", json=body).json()


def test_uploads_are_copied_indexed_and_searchable(client: TestClient, config: Config) -> None:
    document = upload(client, "plan.docx", docx_bytes("zebra launch plan"))
    assert document["source"] == "upload" and document["name"] == "plan.docx"
    assert len(list((config.home / "documents").iterdir())) == 1
    wait(lambda: library(client, query="zebra")["documents"], "the text to be read")
    assert [d["key"] for d in library(client, query="zebra")["documents"]] == [document["key"]]
    assert library(client, query="giraffe")["documents"] == []
    preview = client.post("/api/queries/documents.get", json={"key": document["key"]}).json()
    assert "zebra" in preview["text"]
    file = client.get("/api/documents/file", params={"key": document["key"]})
    assert file.headers["content-disposition"].startswith("attachment")
    assert file.headers["content-type"] == "application/octet-stream"


def test_a_filename_cant_choose_where_the_file_lands(client: TestClient, config: Config) -> None:
    document = upload(client, "../../../evil.txt", b"x")
    assert document["name"] == "evil.txt"
    assert not (config.home.parent / "evil.txt").exists()
    assert all(p.parent == config.home / "documents" for p in (config.home / "documents").iterdir())
    assert upload(client, "..\\..\\win.txt", b"y")["name"] == "win.txt"


def test_too_large_uploads_are_refused(app_config: Config) -> None:
    with TestClient(
        create_app(replace(app_config, max_upload_bytes=10)), base_url="http://127.0.0.1:8765"
    ) as test:
        refused = test.post("/api/documents/upload", params={"name": "big.txt"}, content=b"x" * 11)
        assert refused.status_code == 413


def test_folders_and_tags_organize_and_filter(client: TestClient) -> None:
    first = upload(client, "a.txt", b"x")
    second = upload(client, "b.txt", b"x")
    client.post("/api/commands/documents.saveFolders", json={"folders": ["Legal", "Finance"]})
    client.post(
        "/api/commands/documents.update",
        json={"key": first["key"], "folder": "Legal", "tags": ["urgent"]},
    )
    result = library(client)
    assert result["folders"] == ["Legal", "Finance"]
    assert result["tags"] == ["urgent"]
    assert [d["key"] for d in library(client, folder="Legal")["documents"]] == [first["key"]]
    assert [d["key"] for d in library(client, tag="urgent")["documents"]] == [first["key"]]
    assert {d["key"] for d in library(client, source="upload")["documents"]} == {
        first["key"],
        second["key"],
    }


def test_removing_a_document_deletes_its_file(client: TestClient, config: Config) -> None:
    document = upload(client, "a.txt", b"x")
    client.post("/api/commands/documents.remove", json={"key": document["key"]})
    assert list((config.home / "documents").iterdir()) == []
    assert library(client)["documents"] == []


def test_new_mail_attachments_appear_and_their_text_is_searchable(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Report",
            attachments=[("r.docx", "application/octet-stream", docx_bytes("walrus forecast"))],
        )
    )
    document = wait(lambda: library(client, source="email")["documents"], "attachment")[0]
    assert document["name"] == "r.docx" and document["thread_id"]
    hits = wait(
        lambda: client.post("/api/queries/search.run", json={"query": "walrus"}).json()["hits"],
        "attachment search",
    )
    assert hits[0]["matched_attachment"] is True
    assert (
        "walrus"
        in client.post("/api/queries/documents.get", json={"key": document["key"]}).json()["text"]
    )
    assert (
        client.post("/api/commands/documents.remove", json={"key": document["key"]}).status_code
        == 422
    )


def test_history_attachments_are_only_read_when_opened(client: TestClient, fake: FakeMail) -> None:
    fake.state.deliver(
        make_mail(
            subject="Old report",
            attachments=[("o.docx", "application/octet-stream", docx_bytes("narwhal budget"))],
        )
    )
    connect(client, fake)
    wait(lambda: library(client, source="email")["documents"], "attachment listed")
    assert client.post("/api/queries/search.run", json={"query": "narwhal"}).json()["hits"] == []
    thread = client.post("/api/queries/threads.list", json={}).json()["threads"][0]
    client.post("/api/queries/thread.get", json={"id": thread["id"]})
    wait(
        lambda: client.post("/api/queries/search.run", json={"query": "narwhal"}).json()["hits"],
        "search after opening",
    )


def test_signature_images_stay_out_of_the_library(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    raw = (
        b"From: a@x.com\r\nSubject: Logo\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=b\r\n\r\n"
        b"--b\r\nContent-Type: text/plain\r\n\r\nHi\r\n--b\r\nContent-Type: image/png\r\nContent-ID: <logo>\r\n"
        b"Content-Disposition: inline; filename=logo.png\r\nContent-Transfer-Encoding: base64\r\n\r\nAAAA\r\n--b--\r\n"
    )
    fake.state.deliver(raw)
    wait(lambda: client.post("/api/queries/threads.list", json={}).json()["threads"], "mail")
    assert library(client, source="email")["documents"] == []


def test_risky_attachments_are_listed_but_never_open(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(attachments=[("run.exe", "application/octet-stream", b"MZ")]))
    document = wait(lambda: library(client, source="email")["documents"], "attachment")[0]
    assert document["risky"] is True
    assert client.get("/api/documents/file", params={"key": document["key"]}).status_code == 404
    assert (
        client.post("/api/queries/documents.get", json={"key": document["key"]}).json()["text"]
        == ""
    )


def board(client: TestClient) -> dict[str, Any]:
    return client.post("/api/queries/panels.board").json()


def test_starter_panels_can_be_changed_and_reset(client: TestClient) -> None:
    starters = board(client)
    assert [p["id"] for p in starters["panels"]][:2] == ["waiting-on-you", "unread"]
    changed = {"panels": [{**starters["panels"][1], "size": "large"}]}
    assert (
        client.post("/api/commands/panels.saveBoard", json=changed).json()["panels"][0]["size"]
        == "large"
    )
    assert len(board(client)["panels"]) == 1
    assert client.post("/api/commands/panels.reset").json() == starters


def test_panels_show_live_filtered_results_without_a_model(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="From Priya", sender="priya@x.com"))
    fake.state.deliver(make_mail(subject="From Sam", sender="sam@x.com"))
    wait(lambda: client.post("/api/queries/mail.status").json()["messages"] == 2, "mail")
    panel = {"id": "p", "title": "Priya", "source": "threads", "filters": {"sender": "priya@x.com"}}
    results = client.post("/api/queries/panels.results", json={"panel": panel}).json()
    assert [t["subject"] for t in results["threads"]] == ["From Priya"]
    unread = {**panel, "filters": {"unread_only": True}}
    assert (
        len(client.post("/api/queries/panels.results", json={"panel": unread}).json()["threads"])
        == 2
    )
    upload(client, "a.txt", b"walrus")
    docs = {"id": "d", "title": "D", "source": "documents", "filters": {"query": "walrus"}}
    wait(
        lambda: client.post("/api/queries/panels.results", json={"panel": docs}).json()[
            "documents"
        ],
        "the text to be read",
    )
    assert (
        len(client.post("/api/queries/panels.results", json={"panel": docs}).json()["documents"])
        == 1
    )
    tasks = {"id": "t", "title": "T", "source": "tasks"}
    assert client.post("/api/queries/panels.results", json={"panel": tasks}).json() == {
        "threads": [],
        "documents": [],
    }


@pytest.fixture
def fake_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pst,
        "worker_command",
        lambda path, start: [sys.executable, str(TESTS / "fake_pst_worker.py"), path, str(start)],
    )
    monkeypatch.setenv("PYTHONPATH", str(TESTS))


def imports(client: TestClient) -> list[dict[str, Any]]:
    return client.post("/api/queries/pst.imports").json()["imports"]


def add_pst(client: TestClient, tmp_path: Path, name: str = "old.pst") -> dict[str, Any]:
    file = tmp_path / name
    file.write_bytes(b"x")
    response = client.post("/api/commands/pst.add", json={"path": str(file)})
    assert response.status_code == 200, response.text
    return response.json()["imports"][0]


def status_is(client: TestClient, status: str) -> bool:
    current = imports(client)
    return bool(current) and current[0]["status"] == status


def test_pst_imports_in_the_background_with_no_triage(
    client: TestClient, tmp_path: Path, fake_worker: None
) -> None:
    add_pst(client, tmp_path)
    wait(lambda: status_is(client, "done"), "import")
    job = imports(client)[0]
    assert (job["imported"], job["total"], job["position"]) == (5, 5, 5)
    threads = client.post("/api/queries/threads.list", json={"folder": "archive"}).json()["threads"]
    assert len(threads) == 5
    events = client.post("/api/events/log", json={}).json()["events"]
    assert not [e for e in events if e["type"] in {"mail.received", "mail.needsTriage"}]
    assert client.post("/api/queries/threads.list", json={}).json()["threads"] == []


def test_pst_pause_and_resume_continue_exactly(
    client: TestClient, tmp_path: Path, fake_worker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pst, "BATCH", 2)
    monkeypatch.setenv("FAKE_PST_TOTAL", "30")
    monkeypatch.setenv("FAKE_PST_DELAY", "0.05")
    job = add_pst(client, tmp_path)
    wait(lambda: imports(client)[0]["position"] >= 2, "some progress")
    client.post("/api/commands/pst.pause", json={"id": job["id"]})
    wait(lambda: status_is(client, "paused"), "pause")
    position = imports(client)[0]["position"]
    assert 0 < position < 30
    time.sleep(0.2)
    assert imports(client)[0]["position"] == position
    client.post("/api/commands/pst.resume", json={"id": job["id"]})
    wait(lambda: status_is(client, "done"), "finish")
    assert imports(client)[0]["imported"] == 30
    assert client.post("/api/queries/mail.status").json()["messages"] == 30


def test_pst_resumes_by_itself_after_a_restart(
    app_config: Config, tmp_path: Path, fake_worker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pst, "BATCH", 2)
    monkeypatch.setenv("FAKE_PST_TOTAL", "20")
    monkeypatch.setenv("FAKE_PST_DELAY", "0.05")
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as first:
        job = add_pst(first, tmp_path)
        wait(lambda: imports(first)[0]["position"] >= 2, "some progress")
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as second:
        assert job["id"]
        wait(lambda: status_is(second, "done"), "finish")
        assert imports(second)[0]["imported"] == 20


def test_pst_skips_mail_already_here_and_joins_threads(
    client: TestClient, tmp_path: Path, fake_worker: None, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Archived 0", message_id="<archived-0@x>", sender="old@x.com")
    )
    fake.state.deliver(
        make_mail(
            subject="Re: Archived 1",
            in_reply_to="<archived-1@x>",
            references="<archived-1@x>",
            sender="old@x.com",
        )
    )
    wait(lambda: client.post("/api/queries/mail.status").json()["messages"] == 2, "live mail")
    add_pst(client, tmp_path)
    wait(lambda: status_is(client, "done"), "import")
    job = imports(client)[0]
    assert (job["imported"], job["duplicates"]) == (4, 1)
    joined = [
        t
        for t in client.post("/api/queries/threads.list", json={}).json()["threads"]
        if t["message_count"] == 2
    ]
    assert len(joined) == 1


def test_pst_rules_run_and_bad_files_say_so(
    client: TestClient, tmp_path: Path, fake_worker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PST_FAIL", "1")
    job = add_pst(client, tmp_path)
    wait(lambda: status_is(client, "failed"), "failure")
    assert "PST" in imports(client)[0]["error"]
    monkeypatch.delenv("FAKE_PST_FAIL")
    monkeypatch.setenv("FAKE_PST_HEADERS", '{"List-Id": "<x>"}')
    client.post("/api/commands/pst.resume", json={"id": job["id"]})
    wait(lambda: status_is(client, "done"), "retry")
    thread = client.post("/api/queries/threads.list", json={"folder": "archive"}).json()["threads"][
        0
    ]
    assert thread["category"] == "Newsletters"


def test_pst_input_is_checked(client: TestClient, tmp_path: Path, fake_worker: None) -> None:
    assert (
        client.post("/api/commands/pst.add", json={"path": str(tmp_path / "none.pst")}).status_code
        == 422
    )
    other = tmp_path / "a.txt"
    other.write_text("x")
    assert client.post("/api/commands/pst.add", json={"path": str(other)}).status_code == 422
    add_pst(client, tmp_path)
    wait(lambda: status_is(client, "done"), "import")
    again = client.post("/api/commands/pst.add", json={"path": str(tmp_path / "old.pst")})
    assert again.status_code == 409


@pytest.mark.skipif(not SAMPLE, reason="Set NEXUSAI_TEST_PST to a real PST file")
def test_a_real_pst_imports_with_threads_and_attachments(client: TestClient) -> None:
    response = client.post("/api/commands/pst.add", json={"path": SAMPLE})
    assert response.status_code == 200
    wait(lambda: imports(client)[0]["status"] in {"done", "failed"}, "real import", 120)
    job = imports(client)[0]
    assert job["status"] == "done", job
    assert job["imported"] + job["duplicates"] + job["failed"] == job["total"]
    assert job["failed"] == 0
    hits = client.post("/api/queries/search.run", json={"query": "energy"}).json()["hits"]
    assert hits
    documents = library(client, source="email")["documents"]
    assert documents
    named = [d for d in documents if not d["name"].startswith("attachment-")]
    assert named, "attachments should keep their names"
    file = client.get("/api/documents/file", params={"key": named[0]["key"]})
    assert file.status_code == 200 and len(file.content) == named[0]["size"]
