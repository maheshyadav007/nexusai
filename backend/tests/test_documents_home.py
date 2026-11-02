"""Reading every common kind of file, and looking around Home."""
# ruff: noqa: F811

import io
import json
import struct
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexusai.kernel.config import Config
from nexusai.modules.mail.extract import extract_detail
from nexusai.modules.semantic.module import chunks_of, place_of
from test_agent_work import Script, app_config, client, script, wait  # noqa: F401


def zipped(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def ole(streams: dict[str, bytes]) -> bytes:
    """The smallest real compound file, with one level of folders, like "BodyText/Section0"."""
    sector = 512
    # Below this a stream would live in a separate mini stream, which this doesn't write.
    streams = {name: data.ljust(4096, b"\0") for name, data in streams.items()}
    body = b""
    starts = {}
    for name, data in streams.items():
        starts[name] = len(body) // sector
        body += data + b"\0" * (-len(data) % sector)
    none = 0xFFFFFFFF

    def entry(name: str, kind: int, start: int, size: int, right: int, child: int) -> bytes:
        encoded = (name + "\0").encode("utf-16-le")
        return (
            encoded.ljust(64, b"\0")
            + struct.pack("<HBB", len(encoded), kind, 1)
            + struct.pack("<III", none, right, child)
            + b"\0" * 36
            + struct.pack("<II", start, size)
            + b"\0" * 4
        )

    top = sorted({name.split("/")[0] for name in streams}, key=lambda n: (len(n), n.upper()))
    records: list[bytes] = [b""]
    next_id = 1

    def chain(names: list[str], prefix: str) -> int:
        """Siblings hang off each other to the right, which is a valid if lopsided tree."""
        nonlocal next_id
        first = next_id if names else none
        ids = list(range(next_id, next_id + len(names)))
        next_id += len(names)
        records.extend([b""] * len(names))
        for position, name in enumerate(names):
            full = f"{prefix}{name}"
            right = ids[position + 1] if position + 1 < len(ids) else none
            if full in streams:
                record = entry(name, 2, starts[full], len(streams[full]), right, none)
            else:
                inside = [n.split("/")[1] for n in streams if n.startswith(f"{full}/")]
                inside.sort(key=lambda n: (len(n), n.upper()))
                record = entry(name, 1, 0, 0, right, chain(inside, f"{full}/"))
            records[ids[position]] = record
        return first

    root_child = chain(top, "")
    records[0] = entry("Root Entry", 5, 0xFFFFFFFE, 0, none, root_child)
    directory = b"".join(records)
    directory += b"\0" * (-len(directory) % sector)
    directory_start = len(body) // sector
    directory_sectors = len(directory) // sector
    fat: list[int] = []
    for name, data in streams.items():
        count = (len(data) + sector - 1) // sector
        fat += [starts[name] + n + 1 for n in range(count - 1)] + [0xFFFFFFFE]
    fat += [directory_start + n + 1 for n in range(directory_sectors - 1)] + [0xFFFFFFFE]
    fat_start = len(fat)
    fat_sectors = 1
    while fat_sectors * (sector // 4) < len(fat) + fat_sectors:
        fat_sectors += 1
    fat += [0xFFFFFFFD] * fat_sectors
    fat += [0xFFFFFFFF] * (fat_sectors * (sector // 4) - len(fat))
    difat = [fat_start + n for n in range(fat_sectors)]
    difat += [0xFFFFFFFF] * (109 - len(difat))
    header = (
        bytes.fromhex("d0cf11e0a1b11ae1")
        + b"\0" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
        + b"\0" * 6
        + struct.pack("<II", 0, fat_sectors)
        + struct.pack("<I", directory_start)
        + b"\0" * 4
        + struct.pack("<I", 4096)
        + struct.pack("<II", 0xFFFFFFFE, 0)
        + struct.pack("<II", 0xFFFFFFFE, 0)
        + struct.pack("<109I", *difat)
    )
    return header + body + directory + struct.pack(f"<{len(fat)}I", *fat)


def word_97(text: str) -> bytes:
    """A Word 97 file holding one run of UTF-16 text."""
    encoded = text.encode("utf-16-le")
    main = bytearray(0x0400)
    struct.pack_into("<H", main, 0x0A, 0x0200)
    offset = len(main)
    main += encoded
    pieces = struct.pack("<II", 0, len(text)) + struct.pack("<HIH", 0, offset, 0)
    clx = b"\x02" + struct.pack("<I", len(pieces)) + pieces
    struct.pack_into("<II", main, 0x01A2, 0, len(clx))
    return ole({"WordDocument": bytes(main), "1Table": clx})


def powerpoint_97(text: str) -> bytes:
    encoded = text.encode("utf-16-le")
    atom = struct.pack("<HHI", 0, 0x0FA0, len(encoded)) + encoded
    container = struct.pack("<HHI", 0x0F, 0x03E8, len(atom)) + atom
    return ole({"PowerPoint Document": container})


def hangul(text: str) -> bytes:
    encoded = text.encode("utf-16-le")
    record = struct.pack("<I", 67 | (len(encoded) << 20)) + encoded
    compress = zlib.compressobj(wbits=-15)
    section = compress.compress(record) + compress.flush()
    header = bytearray(256)
    header[36] = 1
    return ole({"FileHeader": bytes(header), "BodyText/Section0": section})


def outlook_message() -> bytes:
    field = "__substg1.0_{}001F"
    return ole(
        {
            field.format("0037"): "Quarterly numbers".encode("utf-16-le"),
            field.format("0C1A"): "Priya Nair".encode("utf-16-le"),
            field.format("1000"): "Here are the figures.".encode("utf-16-le"),
        }
    )


def excel_97() -> bytes:
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Budget")
    sheet.write(0, 0, "Item")
    sheet.write(0, 1, "Cost")
    sheet.write(1, 0, "Servers")
    sheet.write(1, 1, 1200)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def word_macros() -> bytes:
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        f'<w:document xmlns:w="{word}"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Plan</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Macro words</w:t></w:r></w:p></w:body></w:document>"
    )
    return zipped({"word/document.xml": document})


def slides_macros() -> bytes:
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
    slide = f'<p xmlns:a="{drawing}"><a:t>Slide words</a:t></p>'
    return zipped({"ppt/slides/slide1.xml": slide})


def hwpx() -> bytes:
    section = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        "<hp:p><hp:run><hp:t>예산 회의</hp:t></hp:run></hp:p></hs:sec>"
    )
    return zipped({"Contents/section0.xml": section})


ODF = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)


def odf(inner: str) -> bytes:
    return zipped(
        {"content.xml": f"<office:document-content {ODF}>{inner}</office:document-content>"}
    )


def tar_file() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("logs/run.txt")
        data = b"x"
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


EML = (
    b"From: Priya <priya@example.com>\r\nTo: me@example.com\r\nSubject: Numbers\r\n"
    b"Message-ID: <a@b>\r\nContent-Type: text/plain\r\n\r\nThe figures are in.\r\n"
)
NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown", "source": ["# Results"]},
        {"cell_type": "code", "source": ["print('hello')"]},
    ]
}
CASES: list[tuple[str, bytes, list[str]]] = [
    ("a.doc", word_97("Old word text"), ["Old word text"]),
    ("a.ppt", powerpoint_97("Old slide text"), ["Old slide text"]),
    ("a.xls", excel_97(), ["[Sheet: Budget]", "Servers\t1200"]),
    ("a.hwp", hangul("예산 회의 자료"), ["예산 회의 자료"]),
    ("a.hwpx", hwpx(), ["예산 회의"]),
    (
        "a.msg",
        outlook_message(),
        ["Subject: Quarterly numbers", "Priya Nair", "Here are the figures."],
    ),
    ("a.eml", EML, ["Subject: Numbers", "The figures are in."]),
    ("a.docm", word_macros(), ["# Plan", "Macro words"]),
    ("a.pptm", slides_macros(), ["[Slide 1]", "Slide words"]),
    (
        "a.odt",
        odf('<text:h text:outline-level="2">Title</text:h><text:p>Body words</text:p>'),
        ["## Title", "Body words"],
    ),
    (
        "a.ods",
        odf(
            '<table:table table:name="S1"><table:table-row><table:table-cell><text:p>Cell</text:p></table:table-cell></table:table-row></table:table>'
        ),
        ["[Sheet: S1]", "Cell"],
    ),
    (
        "a.odp",
        odf("<draw:page><text:p>Deck words</text:p></draw:page>"),
        ["[Slide 1]", "Deck words"],
    ),
    ("a.rtf", rb"{\rtf1\ansi Rich words\par}", ["Rich words"]),
    ("a.tsv", b"a\tb\n1\t2\n", ["a\tb"]),
    ("a.csv", b'name,note\nSam,"one, two"\n', ["Sam\tone, two"]),
    ("a.ipynb", json.dumps(NOTEBOOK).encode(), ["[Cell 1]", "# Results", "print('hello')"]),
    ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><text>Label</text></svg>", ["Label"]),
    ("a.tar", tar_file(), ["logs/run.txt"]),
    ("a.c", b"int main(void) { return 0; }", ["int main"]),
    ("a.kt", "val x = 1 // 예산".encode(), ["val x = 1"]),
    ("Dockerfile", b"FROM python:3.12", ["FROM python"]),
    ("a.patch", b"--- a\n+++ b\n", ["+++ b"]),
]


@pytest.mark.parametrize(("name", "data", "expected"), CASES, ids=[case[0] for case in CASES])
def test_every_common_kind_of_file_is_read(name: str, data: bytes, expected: list[str]) -> None:
    found = extract_detail(name, data)
    assert found.status == "ready", found.reason
    for words in expected:
        assert words in found.text


def test_pdfs_and_decks_say_where_things_are() -> None:
    from pptx import Presentation

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[0])
    slide.shapes.title.text = "Launch plan"
    buffer = io.BytesIO()
    deck.save(buffer)
    assert "[Slide 1]\nLaunch plan" in extract_detail("a.pptx", buffer.getvalue()).text


def test_word_keeps_headings_and_tables() -> None:
    from docx import Document

    document = Document()
    document.add_heading("Budget", level=2)
    document.add_paragraph("Some words.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Cost"
    table.cell(1, 0).text = "Servers"
    table.cell(1, 1).text = "1200"
    buffer = io.BytesIO()
    document.save(buffer)
    text = extract_detail("a.docx", buffer.getvalue()).text
    assert "## Budget" in text
    assert "| Item | Cost |" in text and "| Servers | 1200 |" in text
    assert text.index("## Budget") < text.index("Some words.") < text.index("| Item")


@pytest.mark.parametrize("name", ["a.doc", "a.ppt", "a.xls", "a.hwp", "a.msg"])
def test_a_damaged_old_file_says_so_plainly(name: str) -> None:
    found = extract_detail(name, b"not really this kind of file")
    assert found.status == "failed"
    assert "couldn't be read" in (found.reason or "")


@pytest.mark.parametrize("name", ["a.odt", "a.hwpx", "a.docm"])
def test_a_damaged_zip_file_says_so(name: str) -> None:
    assert extract_detail(name, b"not a zip").status == "failed"


def test_binary_with_no_known_kind_isnt_read_as_text() -> None:
    assert extract_detail("a.bin", b"\x00\x01\x02").status == "unsupported"


def test_a_scan_or_picture_says_it_cant_be_read_yet() -> None:
    assert extract_detail("a.png", b"\x89PNG").status == "image"


def test_chunks_stop_at_paragraphs_and_know_their_page() -> None:
    first = "A sentence here. " * 40
    second = "Another one here. " * 40
    text = f"[Page 1]\n{first}\n\n[Page 2]\n{second}"
    pieces = chunks_of(text, 10)
    assert any(piece.endswith(first.strip()) for piece in pieces)
    assert place_of(text, 0, 10) == "Page 1"
    assert place_of(text, len(pieces) - 1, 10) == "Page 2"


# Looking around Home


def folder(client: TestClient, path: str = "") -> dict[str, Any]:
    response = client.post("/api/queries/homeFiles.list", json={"path": path})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_top_shows_only_the_folders_people_may_see(client: TestClient, script: Script) -> None:
    names = {entry["name"] for entry in folder(client)["entries"]}
    assert names == {"documents", "artifacts", "scratch", "memory", "prompts"}


@pytest.mark.parametrize(
    "path", ["system", "system/nexusai.db", "../..", "scratch/../system", "/etc/passwd"]
)
def test_nothing_private_or_outside_can_be_reached(
    client: TestClient, script: Script, path: str
) -> None:
    listed = client.post("/api/queries/homeFiles.list", json={"path": path})
    assert listed.status_code == 403
    read = client.post("/api/queries/documents.read", json={"path": path})
    assert read.status_code == 403
    assert client.get("/api/home/file", params={"path": path}).status_code == 403


@pytest.mark.skipif(sys.platform == "win32", reason="Needs symlinks or POSIX file modes")
def test_a_link_cant_lead_out_of_home(
    client: TestClient, script: Script, app_config: Config, tmp_path: Path
) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("private")
    link = app_config.home / "scratch" / "sneaky.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    assert "sneaky.txt" not in {e["name"] for e in folder(client, "scratch")["entries"]}
    assert client.get("/api/home/file", params={"path": "scratch/sneaky.txt"}).status_code == 403


def test_scratch_shows_the_session_it_belongs_to_and_files_can_be_read(
    client: TestClient, script: Script, app_config: Config
) -> None:
    session = client.post("/api/commands/session.create", json={"title": "Vendor quotes"}).json()
    work = app_config.home / "scratch" / session["id"]
    (work / "notes.py").write_text("print('hi')")
    entry = next(e for e in folder(client, "scratch")["entries"] if e["name"] == session["id"])
    assert entry["label"] == "Vendor quotes"
    assert folder(client, f"scratch/{session['id']}")["entries"][0]["name"] == "notes.py"
    shown = client.post(
        "/api/queries/documents.read", json={"path": f"scratch/{session['id']}/notes.py"}
    ).json()
    assert (shown["kind"], shown["text"]) == ("code", "print('hi')")


def test_uploads_show_their_real_names(client: TestClient, script: Script) -> None:
    client.post("/api/documents/upload", params={"name": "budget.txt"}, content=b"words")
    labels = {entry["label"] for entry in folder(client, "documents")["entries"]}
    assert "budget.txt" in labels


def test_artifacts_join_the_library_and_follow_changes(
    client: TestClient, script: Script, app_config: Config
) -> None:
    def rows() -> list[dict[str, Any]]:
        listed = client.post("/api/queries/documents.list", json={"source": "home"}).json()
        return listed["documents"]

    path = app_config.home / "artifacts" / "report.md"
    path.write_text("# Findings\n\nThe vendor is late.")
    row = wait(lambda: (lambda r: r[0] if r and r[0]["status"] == "ready" else None)(rows()), "it")
    assert (row["name"], row["source"]) == ("report.md", "home")
    found = client.post("/api/queries/documents.list", json={"query": "vendor"}).json()["documents"]
    assert row["key"] in {document["key"] for document in found}
    shown = client.post("/api/queries/documents.read", json={"key": row["key"]}).json()
    assert shown["kind"] == "markdown" and "The vendor is late." in shown["text"]
    path.write_text("# Findings\n\nThe courier is early.")
    wait(
        lambda: (
            "courier"
            in client.post("/api/queries/documents.get", json={"key": row["key"]}).json()["text"]
        ),
        "the change",
    )
    path.unlink()
    wait(lambda: not rows(), "it to go")


def test_only_pictures_and_pdfs_open_in_place(
    client: TestClient, script: Script, app_config: Config
) -> None:
    folder_path = app_config.home / "scratch" / "s"
    folder_path.mkdir(parents=True)
    (folder_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (folder_path / "a.html").write_text("<script>alert(1)</script>")
    (folder_path / "a.svg").write_text("<svg onload='alert(1)'/>")
    pdf = client.get("/api/home/file", params={"path": "scratch/s/a.pdf", "inline": True})
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.headers["x-content-type-options"] == "nosniff"
    for name in ("a.html", "a.svg"):
        risky = client.get("/api/home/file", params={"path": f"scratch/s/{name}", "inline": True})
        assert risky.headers["content-type"] == "application/octet-stream"
        assert risky.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("a.pdf", "pdf"),
        ("a.png", "image"),
        ("a.md", "markdown"),
        ("a.csv", "table"),
        ("a.xlsx", "table"),
        ("a.html", "html"),
        ("a.docx", "document"),
        ("a.hwp", "document"),
        ("a.py", "code"),
        ("a.log", "code"),
    ],
)
def test_each_file_gets_the_right_view(name: str, kind: str) -> None:
    from nexusai.modules.documents.module import reader_kind

    assert reader_kind(name, "ready") == kind
