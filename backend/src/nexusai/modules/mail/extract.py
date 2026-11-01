"""Pulls readable text out of documents. A bad file gives no text, never an error for the caller."""

import csv
import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass

import structlog

log = structlog.get_logger()
MAX_INPUT_BYTES = 50_000_000
MAX_TEXT_CHARS = 1_000_000
ZIP_RATIO_LIMIT = 200
TEXT_TYPES = {
    "txt",
    "md",
    "log",
    "json",
    "xml",
    "eml",
    "yaml",
    "yml",
    "ini",
    "cfg",
    "toml",
    "py",
    "sql",
}
HTML_TYPES = {"html", "htm"}
IMAGE_TYPES = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic"}
OLD_OFFICE = {"doc", "xls", "ppt"}
# Password-protected Office files aren't zips at all, they're this older container.
OLE_HEADER = bytes.fromhex("d0cf11e0a1b11ae1")
WORKER_SECONDS = 120.0


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt("")
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx(data: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(data))
    cells = (cell.text for table in document.tables for row in table.rows for cell in row.cells)
    return "\n".join([*(p.text for p in document.paragraphs), *cells])


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(cell) for cell in row if cell is not None]
            if cells:
                lines.append(" ".join(cells))
    return "\n".join(lines)


def _pptx(data: bytes) -> str:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    return "\n".join(
        shape.text_frame.text
        for slide in deck.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )


def _csv(data: bytes) -> str:
    rows = csv.reader(io.StringIO(data.decode("utf-8", "replace")))
    return "\n".join(" ".join(row) for row in rows)


READERS = {"pdf": _pdf, "docx": _docx, "xlsx": _xlsx, "pptx": _pptx, "csv": _csv}
ZIP_BASED = {"docx", "xlsx", "pptx"}


def _safe_zip(data: bytes) -> bool:
    """Office files are zips. A zip that would grow enormously isn't opened."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expanded = sum(item.file_size for item in archive.infolist())
    return expanded <= max(len(data), 1) * ZIP_RATIO_LIMIT


@dataclass(frozen=True)
class Extraction:
    """The text, and if there isn't any, why, in words for the person."""

    text: str
    status: str
    reason: str | None = None
    truncated: bool = False


def _decode(data: bytes) -> str:
    """Mail and files here are often not UTF-8. Korean Windows files are usually CP949."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", "replace")
    for encoding in ("utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _html(data: bytes) -> str:
    import html
    import re

    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", _decode(data))
    text = re.sub(r"(?i)<(br|/p|/div|/tr|/li|/h[1-6])\s*/?>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _zip_listing(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(item.filename for item in archive.infolist() if not item.is_dir())


def _pdf_is_locked(data: bytes) -> bool:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    # Many are only marked encrypted, with an empty password that opens them.
    return bool(reader.is_encrypted and reader.decrypt("") == 0)


def extract_detail(filename: str, data: bytes) -> Extraction:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not data:
        return Extraction("", "empty", "This file is empty.")
    if len(data) > MAX_INPUT_BYTES:
        return Extraction("", "too_large", "This file is too large to read, but it's kept here.")
    if extension in IMAGE_TYPES:
        return Extraction("", "image", "Text in images can't be read yet.")
    if extension in OLD_OFFICE:
        return Extraction(
            "",
            "unsupported",
            f"Old .{extension} files can't be read. Saving it as .{extension}x would fix that.",
        )
    try:
        if extension in ZIP_BASED and data.startswith(OLE_HEADER):
            return Extraction(
                "", "encrypted", "This file has a password, so its text can't be read."
            )
        if extension in ZIP_BASED and not _safe_zip(data):
            return Extraction(
                "", "failed", "This file would expand far too much, so it wasn't opened."
            )
        if extension == "pdf" and _pdf_is_locked(data):
            return Extraction(
                "", "encrypted", "This PDF has a password, so its text can't be read."
            )
        if extension in TEXT_TYPES:
            text = _decode(data)
        elif extension in HTML_TYPES:
            text = _html(data)
        elif extension == "zip":
            if not _safe_zip(data):
                return Extraction(
                    "", "failed", "This archive would expand far too much, so it wasn't opened."
                )
            text = _zip_listing(data)
        elif extension in READERS:
            text = READERS[extension](data)
        else:
            return Extraction(
                "", "unsupported", "This kind of file is kept, but its text can't be read."
            )
    except Exception as error:
        log.info("text_extraction_failed", extension=extension, error=type(error).__name__)
        return Extraction("", "failed", "This file looks damaged, so its text couldn't be read.")
    if not text.strip():
        if extension == "pdf":
            return Extraction("", "no_text", "This looks like a scan, and scans can't be read yet.")
        return Extraction("", "no_text", "No text was found in this file.")
    if len(text) > MAX_TEXT_CHARS:
        return Extraction(
            text[:MAX_TEXT_CHARS],
            "ready",
            "Only the start of this file was read, because it's very long.",
            True,
        )
    return Extraction(text, "ready")


def extract_text(filename: str, data: bytes) -> str:
    return extract_detail(filename, data).text


def extract_safely(filename: str, data: bytes, seconds: float = WORKER_SECONDS) -> Extraction:
    """In a separate process with a time limit, so one bad file costs only itself."""
    command = [sys.executable, "-m", "nexusai.modules.mail.extract_worker"]
    # A newline in a name would split the header. The name is only used for its ending.
    header = filename.replace("\n", " ").encode("utf-8") + b"\n"
    try:
        done = subprocess.run(
            command, input=header + data, capture_output=True, timeout=seconds, check=True
        )
        return Extraction(**json.loads(done.stdout))
    except subprocess.TimeoutExpired:
        return Extraction("", "failed", "This file took too long to read, so it was skipped.")
    except (subprocess.CalledProcessError, ValueError, OSError):
        return Extraction("", "failed", "This file couldn't be read.")
