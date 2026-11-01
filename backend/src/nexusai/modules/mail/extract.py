"""Pulls readable text out of documents. A bad file gives no text, never an error for the caller."""

import csv
import io
import zipfile

import structlog

log = structlog.get_logger()
MAX_INPUT_BYTES = 50_000_000
MAX_TEXT_CHARS = 1_000_000
ZIP_RATIO_LIMIT = 200
TEXT_TYPES = {"txt", "md", "log", "json", "xml", "eml"}


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return ""
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


def extract_text(filename: str, data: bytes) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if len(data) > MAX_INPUT_BYTES:
        return ""
    try:
        if extension in TEXT_TYPES:
            return data.decode("utf-8", "replace")[:MAX_TEXT_CHARS]
        reader = READERS.get(extension)
        if reader is None or (extension in ZIP_BASED and not _safe_zip(data)):
            return ""
        return reader(data)[:MAX_TEXT_CHARS]
    except Exception as error:
        log.info("text_extraction_failed", extension=extension, error=type(error).__name__)
        return ""
