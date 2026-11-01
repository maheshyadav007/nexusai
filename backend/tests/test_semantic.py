"""Search by meaning: the model arrives safely, everything gets indexed, and words still work."""
# ruff: noqa: F811

import hashlib
import threading
from collections.abc import Iterator, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.modules.agent.providers import TextChunk, ToolCall
from nexusai.modules.mail.extract import extract_detail, extract_safely
from nexusai.modules.semantic import downloader
from nexusai.modules.semantic import module as semantic
from nexusai.modules.semantic.catalog import DIMENSIONS, CatalogModel, ModelFile, folder
from nexusai.modules.semantic.downloader import download as real_download
from test_agent_work import (
    Script,
    app_config,  # noqa: F401
    client,  # noqa: F401
    connect,
    fake,  # noqa: F401
    script,  # noqa: F401
    wait,
)
from test_chat_engine_tools import use_tool

# The fake model knows these are about the same thing, as a real one would.
TOPICS = [
    {"budget", "spending", "finance", "예산"},
    {"holiday", "vacation", "leave", "휴가"},
    {"outage", "downtime"},
]


class FakeEmbedder:
    def embed(self, texts: Sequence[str], *, query: bool) -> list[Any]:
        vectors = []
        for text in texts:
            words = set(text.lower().split())
            vector = np.zeros(DIMENSIONS, dtype=np.float32)
            for dimension, topic in enumerate(TOPICS):
                if words & topic:
                    vector[dimension] = 1.0
            if not vector.any():
                vector[DIMENSIONS - 1] = 1.0
            vectors.append(vector / np.linalg.norm(vector))
        return vectors


@pytest.fixture
def model_here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(downloader, "is_complete", lambda *_: True)
    monkeypatch.setattr(semantic, "make_embedder", lambda *_: FakeEmbedder())


def status(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.post("/api/queries/semantic.status").json()
    return result


def search(client: TestClient, text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = client.post(
        "/api/queries/search.run", json={"query": text}
    ).json()["hits"]
    return hits


def all_indexed(client: TestClient) -> bool:
    now = status(client)
    return bool(now["total"]) and now["indexed"] >= now["total"]


def upload(client: TestClient, name: str, data: bytes) -> dict[str, Any]:
    response = client.post("/api/documents/upload", params={"name": name}, content=data)
    assert response.status_code == 200, response.text
    return response.json()


def document(client: TestClient, key: str) -> dict[str, Any]:
    found: dict[str, Any] = client.post("/api/queries/documents.get", json={"key": key}).json()
    return found["document"]


def read(client: TestClient, key: str) -> dict[str, Any]:
    wait(lambda: document(client, key)["status"] != "pending", "the file to be read")
    return document(client, key)


# Search


def test_mail_is_found_by_meaning_and_words_rank_with_it(
    client: TestClient, fake: FakeMail, model_here: None
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="cut the spending"))
    fake.state.deliver(make_mail(subject="Team lunch", body="biryani tuesday"))
    wait(lambda: all_indexed(client) and status(client)["total"] == 2, "indexing")

    # Nothing shares a word with this, so only meaning can find it.
    hits = search(client, "budget")
    assert [h["thread"]["subject"] for h in hits] == ["Finance review"]
    assert hits[0]["matched_by"] == "meaning"

    both = search(client, "spending")
    assert both[0]["thread"]["subject"] == "Finance review"
    assert both[0]["matched_by"] == "both"


def test_a_question_in_another_language_finds_it(
    client: TestClient, fake: FakeMail, model_here: None
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="the budget"))
    wait(lambda: all_indexed(client), "indexing")
    assert [h["thread"]["subject"] for h in search(client, "예산")] == ["Finance review"]


def test_filters_still_apply_to_what_meaning_found(
    client: TestClient, fake: FakeMail, model_here: None
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", sender="priya@x.com", body="budget"))
    wait(lambda: all_indexed(client), "indexing")
    found = client.post(
        "/api/queries/search.run", json={"query": "spending", "sender": "sam@x.com"}
    ).json()
    assert found["hits"] == []


def test_without_the_model_words_still_work_and_asking_fetches_it(
    client: TestClient, fake: FakeMail, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = threading.Event()
    release = threading.Event()

    def slow(*_: object, **__: object) -> None:
        asked.set()
        release.wait(10)
        raise downloader.DownloadFailed("Couldn't reach the download server.")

    monkeypatch.setattr(downloader, "download", slow)
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="the budget"))
    wait(lambda: client.post("/api/queries/mail.status").json()["messages"] == 1, "mail")

    assert status(client)["ready"] is False
    hits = search(client, "budget")
    assert [h["matched_by"] for h in hits] == ["words"]
    assert asked.wait(5), "searching should start the download"
    assert status(client)["models"][0]["state"] == "downloading"
    release.set()
    wait(lambda: status(client)["models"][0]["state"] == "failed", "the failure to show")
    assert "reach" in status(client)["models"][0]["error"]
    # It doesn't keep trying behind the person's back.
    asked.clear()
    search(client, "budget")
    assert not asked.wait(0.2)


def test_turning_off_automatic_download_is_respected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(downloader, "download", lambda *_: asked.append(True))
    client.post("/api/commands/semantic.saveSettings", json={"auto_download": False})
    search(client, "budget")
    client.post("/api/queries/documents.list", json={"query": "budget"})
    assert asked == []
    assert status(client)["auto_download"] is False


def test_jobs_show_the_model_while_it_downloads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    monkeypatch.setattr(downloader, "download", lambda *_: release.wait(10))
    client.post("/api/commands/semantic.download", json={})
    jobs = client.post("/api/queries/jobs.list").json()["jobs"]
    assert any(j["kind"] == "model" for j in jobs)
    release.set()


def test_the_agent_tool_finds_by_meaning(
    client: TestClient, script: Script, fake: FakeMail, model_here: None
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="cut the spending"))
    wait(lambda: all_indexed(client), "indexing")
    result = use_tool(
        client,
        script,
        ToolCall("t1", "semantic_search", {"query": "budget", "scope": "mail"}),
    )
    assert "Finance review" in result


def test_the_agent_hears_when_the_model_isnt_here(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="the budget"))
    wait(lambda: client.post("/api/queries/mail.status").json()["messages"] == 1, "mail")
    result = use_tool(client, script, ToolCall("t1", "semantic_search", {"query": "budget"}))
    assert "isn't available yet" in result and "Finance review" in result


def test_mail_search_tool_uses_meaning_too(
    client: TestClient, script: Script, fake: FakeMail, model_here: None
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Finance review", body="cut the spending"))
    wait(lambda: all_indexed(client), "indexing")
    script.replies = [[ToolCall("t1", "search_mail", {"query": "budget"})], [TextChunk("Done.")]]
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    with client.stream("POST", "/api/sessions/chat", json={"id": session, "text": "Go"}) as reply:
        list(reply.iter_lines())
    assert "Finance review" in script.requests[-1].messages[-1].text


# Documents and search


def test_an_uploaded_file_is_read_then_found_by_meaning(
    client: TestClient, model_here: None
) -> None:
    added = upload(client, "plan.txt", b"the holiday calendar")
    assert added["status"] == "pending"
    assert read(client, added["key"])["status"] == "ready"
    wait(lambda: all_indexed(client), "indexing")
    found = client.post("/api/queries/documents.list", json={"query": "vacation"}).json()
    assert [d["key"] for d in found["documents"]] == [added["key"]]


def test_removing_a_file_removes_it_from_search(client: TestClient, model_here: None) -> None:
    added = upload(client, "plan.txt", b"the holiday calendar")
    read(client, added["key"])
    wait(lambda: all_indexed(client), "indexing")
    client.post("/api/commands/documents.remove", json={"key": added["key"]})
    found = client.post("/api/queries/documents.list", json={"query": "vacation"}).json()
    assert found["documents"] == []
    current = semantic.engine()
    assert current is not None
    assert current.search("vacation", {"document"}, 10) == []


# Reading files


def test_the_same_file_twice_is_one_document(client: TestClient) -> None:
    first = upload(client, "a.txt", b"the same content")
    second = upload(client, "b.txt", b"the same content")
    assert second["key"] == first["key"] and second["duplicate"] is True
    assert first["duplicate"] is False


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [("empty.txt", b"", "document.empty"), ("setup.exe", b"MZ", "document.risky")],
)
def test_files_that_cant_be_kept_are_refused_plainly(
    client: TestClient, name: str, data: bytes, code: str
) -> None:
    refused = client.post("/api/documents/upload", params={"name": name}, content=data)
    assert refused.status_code == 422
    assert refused.json()["code"] == code
    assert name in refused.json()["message"]


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("scan.png", b"\x89PNG\r\n\x1a\n", "image"),
        ("broken.pdf", b"%PDF-1.4 this is not really a pdf", "failed"),
        ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "unsupported"),
        ("mystery.xyz", b"\x00\x01\x02", "unsupported"),
    ],
)
def test_a_file_that_cant_be_read_says_why_and_stays_kept(
    client: TestClient, name: str, data: bytes, expected: str
) -> None:
    added = upload(client, name, data)
    done = read(client, added["key"])
    assert done["status"] == expected
    assert done["status_reason"]
    assert client.get("/api/documents/file", params={"key": added["key"]}).content == data


def test_text_in_other_encodings_is_read() -> None:
    assert extract_detail("a.txt", "예산 회의".encode("cp949")).text.strip() == "예산 회의"
    assert extract_detail("b.txt", "é".encode("utf-8-sig")).text == "é"
    assert extract_detail("c.html", b"<p>hello <b>there</b></p>").text.split() == ["hello", "there"]


def test_reading_runs_apart_so_a_bad_file_cant_take_the_app_down() -> None:
    found = extract_safely("broken.pdf", b"%PDF-1.4 nothing here")
    assert found.status == "failed"
    assert extract_safely("a.txt", b"hello").text == "hello"


def test_a_file_that_failed_can_be_read_again(client: TestClient) -> None:
    added = upload(client, "plan.txt", b"walrus plan")
    read(client, added["key"])
    assert client.post("/api/commands/documents.readAgain", json={"key": added["key"]}).is_success
    assert read(client, added["key"])["status"] == "ready"


# Downloading


class Files(BaseHTTPRequestHandler):
    content: bytes = b""
    drop_after: int | None = None
    status_code = 200
    seen: list[tuple[str, str | None]]

    def do_GET(self) -> None:
        self.seen.append((self.path, self.headers.get("Range")))
        if self.status_code != 200:
            self.send_error(self.status_code)
            return
        start = int(self.headers.get("Range", "bytes=0-")[6:-1])
        body = self.content[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        limit = type(self).drop_after
        if limit is not None:
            # Once, like a dropped connection.
            type(self).drop_after = None
            self.wfile.write(body[:limit])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)

    def log_message(self, *_: Any) -> None:
        pass


CONTENT = b"model bytes " * 100_000


def tiny(content: bytes = CONTENT) -> CatalogModel:
    item = ModelFile(
        "model.onnx", "onnx/model.onnx", len(content), hashlib.sha256(content).hexdigest()
    )
    return CatalogModel("tiny", "Tiny", "For tests.", "org/tiny", "abc", (item,))


@pytest.fixture
def mirror() -> Iterator[tuple[str, type[Files]]]:
    handler = type("Handler", (Files,), {"seen": [], "content": CONTENT})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", handler
    server.shutdown()


def NOTHING() -> None:
    pass


def test_the_model_comes_from_the_mirror_and_is_checked(
    tmp_path: Path, mirror: tuple[str, type[Files]]
) -> None:
    address, handler = mirror
    model = tiny()
    real_download(tmp_path, model, address, threading.Event(), NOTHING)
    assert (folder(tmp_path, model) / "model.onnx").read_bytes() == CONTENT
    assert handler.seen[0][0] == "/org/tiny/resolve/abc/onnx/model.onnx"
    assert downloader.is_complete(tmp_path, model)


def test_a_dropped_connection_carries_on_where_it_stopped(
    tmp_path: Path, mirror: tuple[str, type[Files]]
) -> None:
    address, handler = mirror
    handler.drop_after = 300_000
    model = tiny()
    real_download(tmp_path, model, address, threading.Event(), NOTHING)
    assert (folder(tmp_path, model) / "model.onnx").read_bytes() == CONTENT
    assert handler.seen[-1][1] is not None and handler.seen[-1][1] != "bytes=0-"


def test_a_wrong_file_is_thrown_away(tmp_path: Path, mirror: tuple[str, type[Files]]) -> None:
    address, handler = mirror
    handler.content = b"x" * len(CONTENT)
    model = tiny()
    with pytest.raises(downloader.DownloadFailed, match="didn't match"):
        real_download(tmp_path, model, address, threading.Event(), NOTHING)
    assert list(folder(tmp_path, model).iterdir()) == []


def test_a_blocked_network_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(downloader.DownloadFailed, match="mirror"):
        real_download(tmp_path, tiny(), "http://127.0.0.1:9", threading.Event(), NOTHING)


def test_a_refusal_is_not_retried(tmp_path: Path, mirror: tuple[str, type[Files]]) -> None:
    address, handler = mirror
    handler.status_code = 403
    with pytest.raises(downloader.DownloadFailed, match="403"):
        real_download(tmp_path, tiny(), address, threading.Event(), NOTHING)
    assert len(handler.seen) == 1


def test_cancelling_stops_and_keeps_what_arrived(
    tmp_path: Path, mirror: tuple[str, type[Files]]
) -> None:
    address, _ = mirror
    stop = threading.Event()
    with pytest.raises(downloader.Cancelled):
        real_download(tmp_path, tiny(), address, stop, stop.set)
    assert downloader.bytes_present(tmp_path, tiny()) > 0
    assert not downloader.is_complete(tmp_path, tiny())


def test_imported_files_are_checked_too(tmp_path: Path) -> None:
    source = tmp_path / "usb"
    source.mkdir()
    (source / "model.onnx").write_bytes(CONTENT)
    home = tmp_path / "home"
    downloader.import_files(home, tiny(), source)
    assert downloader.is_complete(home, tiny())
    (source / "model.onnx").write_bytes(b"y" * len(CONTENT))
    other = tmp_path / "other"
    with pytest.raises(downloader.DownloadFailed):
        downloader.import_files(other, tiny(), source)
