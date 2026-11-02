"""Reads text out of each kind of file, keeping its shape: headings, tables, pages and sheets.

Only used inside the extraction worker, so a bad file can't take anything else down with it.
"""

import csv
import io
import json
import re
import struct
import tarfile
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from typing import Any
from xml.etree import ElementTree

import olefile

PAGE_MARK = "[Page {}]"
SLIDE_MARK = "[Slide {}]"
SHEET_MARK = "[Sheet: {}]"
CELL_MARK = "[Cell {}]"
LISTING_LIMIT = 2000
# Old Word and PowerPoint keep text as UTF-16 or as single bytes in this code page.
OLD_ENCODING = "cp1252"
PPT_TEXT_UNICODE = 0x0FA0
PPT_TEXT_BYTES = 0x0FA8
PPT_CONTAINER = 0xF
HWP_PARAGRAPH_TEXT = 67
HWP_CONTROL_CODES = set(range(0, 32)) - {9, 10, 13}
HEADING_STYLE = re.compile(r"heading\s*(\d)", re.IGNORECASE)
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODF_PRESENTATION = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"


def _table(rows: Iterable[Iterable[str]]) -> str:
    """As a markdown table, which reads well as plain text and shows as one too."""
    lines = [[cell.replace("\n", " ").replace("|", "\\|").strip() for cell in row] for row in rows]
    lines = [line for line in lines if any(line)]
    if not lines:
        return ""
    width = max(len(line) for line in lines)
    filled = [line + [""] * (width - len(line)) for line in lines]
    head = "| " + " | ".join(filled[0]) + " |"
    rule = "|" + " --- |" * width
    return "\n".join([head, rule, *("| " + " | ".join(line) + " |" for line in filled[1:])])


def _sheet(name: str, rows: Iterable[Iterable[Any]]) -> str:
    lines = []
    for row in rows:
        cells = ["" if cell is None else str(cell) for cell in row]
        if any(cells):
            lines.append("\t".join(cells))
    return "\n".join([SHEET_MARK.format(name), *lines]) if lines else ""


def _joined(blocks: Iterable[str]) -> str:
    return "\n\n".join(block for block in blocks if block.strip())


# Office


def read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt("")
    pages = ((n, page.extract_text() or "") for n, page in enumerate(reader.pages, 1))
    return _joined(f"{PAGE_MARK.format(n)}\n{text}" for n, text in pages if text.strip())


def read_docx(data: bytes) -> str:
    from docx import Document
    from docx.table import Table

    document = Document(io.BytesIO(data))
    blocks = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            blocks.append(_table([cell.text for cell in row.cells] for row in item.rows))
            continue
        heading = HEADING_STYLE.match(item.style.name or "") if item.style else None
        blocks.append(f"{'#' * int(heading.group(1))} {item.text}" if heading else item.text)
    return _joined(blocks)


def read_docm(data: bytes) -> str:
    """Laid out like .docx, which its library refuses because of the macros. They aren't run."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    blocks = []
    for paragraph in root.iter(f"{WORD}p"):
        style = paragraph.find(f"{WORD}pPr/{WORD}pStyle")
        heading = HEADING_STYLE.match(style.get(f"{WORD}val", "")) if style is not None else None
        text = "".join(node.text or "" for node in paragraph.iter(f"{WORD}t"))
        blocks.append(f"{'#' * int(heading.group(1))} {text}" if heading and text else text)
    return _joined(blocks)


def read_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    return _joined(
        _sheet(sheet.title, sheet.iter_rows(values_only=True)) for sheet in book.worksheets
    )


def read_xls(data: bytes) -> str:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    return _joined(
        _sheet(sheet.name, (sheet.row_values(n) for n in range(sheet.nrows)))
        for sheet in book.sheets()
    )


def read_pptx(data: bytes) -> str:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    slides = []
    for number, slide in enumerate(deck.slides, 1):
        words = [s.text_frame.text for s in slide.shapes if s.has_text_frame and s.text_frame.text]
        if words:
            slides.append("\n".join([SLIDE_MARK.format(number), *words]))
    return _joined(slides)


def read_pptm(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda name: int(re.findall(r"\d+", name)[-1]))
        slides = []
        for number, name in enumerate(names, 1):
            root = ElementTree.fromstring(archive.read(name))
            words = [node.text for node in root.iter(f"{DRAWING}t") if node.text]
            if words:
                slides.append("\n".join([SLIDE_MARK.format(number), *words]))
    return _joined(slides)


def read_doc(data: bytes) -> str:
    """Old Word, using its table of text pieces. Without Office, layouts may come out plain."""
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        main = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", main, 0x0A)[0]
        table_name = "1Table" if flags & 0x0200 else "0Table"
        table = ole.openstream(table_name).read()
    clx_offset, clx_size = struct.unpack_from("<II", main, 0x01A2)
    clx = table[clx_offset : clx_offset + clx_size]
    position = 0
    pieces = b""
    while position < len(clx):
        kind = clx[position]
        if kind == 2:
            size = struct.unpack_from("<I", clx, position + 1)[0]
            pieces = clx[position + 5 : position + 5 + size]
            break
        if kind != 1:
            break
        position += 3 + struct.unpack_from("<H", clx, position + 1)[0]
    count = (len(pieces) - 4) // 12
    words = []
    for n in range(count):
        start, end = struct.unpack_from("<II", pieces, n * 4)
        offset = struct.unpack_from("<I", pieces, (count + 1) * 4 + n * 8 + 2)[0]
        length = end - start
        if offset & 0x40000000:
            raw = main[(offset & ~0x40000000) // 2 :][:length]
            words.append(raw.decode(OLD_ENCODING, "replace"))
        else:
            words.append(main[offset : offset + length * 2].decode("utf-16-le", "replace"))
    text = "".join(words).replace("\r", "\n").replace("\x07", "\t")
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)


def _ppt_records(data: bytes, start: int, end: int) -> Iterator[str]:
    position = start
    while position + 8 <= end:
        version, kind, size = struct.unpack_from("<HHI", data, position)
        body = position + 8
        if version & 0xF == PPT_CONTAINER:
            yield from _ppt_records(data, body, min(body + size, end))
        elif kind == PPT_TEXT_UNICODE:
            yield data[body : body + size].decode("utf-16-le", "replace")
        elif kind == PPT_TEXT_BYTES:
            yield data[body : body + size].decode(OLD_ENCODING, "replace")
        position = body + size


def read_ppt(data: bytes) -> str:
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        stream = ole.openstream("PowerPoint Document").read()
    return "\n".join(part.replace("\r", "\n") for part in _ppt_records(stream, 0, len(stream)))


# Korean office files


def read_hwpx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(
            n for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)
        )
        blocks = []
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            for paragraph in root.iter():
                if paragraph.tag.endswith("}p"):
                    words = [n.text for n in paragraph.iter() if n.tag.endswith("}t") and n.text]
                    blocks.append("".join(words))
    return _joined(blocks)


def _hwp_section(raw: bytes, compressed: bool) -> str:
    # Through an object, because the stream can have padding after the compressed part.
    data = zlib.decompressobj(-15).decompress(raw) if compressed else raw
    position = 0
    paragraphs = []
    while position + 4 <= len(data):
        header = struct.unpack_from("<I", data, position)[0]
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        position += 4
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, position)[0]
            position += 4
        if tag == HWP_PARAGRAPH_TEXT:
            text = data[position : position + size].decode("utf-16-le", "replace")
            paragraphs.append("".join(c for c in text if ord(c) not in HWP_CONTROL_CODES))
        position += size
    return "\n".join(paragraphs)


def read_hwp(data: bytes) -> str:
    """Older Korean word processor files. Controls embedded in the text are dropped."""
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 1)
        if header[36] & 2:
            raise ValueError("encrypted")
        sections = sorted(
            (entry for entry in ole.listdir() if entry[0] == "BodyText"),
            key=lambda entry: int(re.findall(r"\d+", entry[1])[0]),
        )
        bodies = [_hwp_section(ole.openstream(entry).read(), compressed) for entry in sections]
        if not any(body.strip() for body in bodies) and ole.exists("PrvText"):
            return str(ole.openstream("PrvText").read().decode("utf-16-le", "replace"))
    return _joined(bodies)


# Mail files


def read_msg(data: bytes) -> str:
    """Outlook's own format. Each field is a stream with a fixed name, in UTF-16 or single bytes."""
    with olefile.OleFileIO(io.BytesIO(data)) as ole:

        def field(code: str) -> str:
            for suffix, encoding in (("001F", "utf-16-le"), ("001E", OLD_ENCODING)):
                name = f"__substg1.0_{code}{suffix}"
                if ole.exists(name):
                    return str(ole.openstream(name).read().decode(encoding, "replace")).strip("\0 ")
            return ""

        heads = (
            ("From", field("0C1A")),
            ("To", field("0E04")),
            ("Cc", field("0E03")),
            ("Date", field("0039")),
            ("Subject", field("0037")),
        )
        body = field("1000")
    return _joined(["\n".join(f"{k}: {v}" for k, v in heads if v), body])


def read_eml(data: bytes) -> str:
    from nexusai.modules.mail.parse import parse_message

    parsed = parse_message(data)
    heads = (
        ("From", parsed.from_addr),
        ("To", ", ".join(parsed.to)),
        ("Date", parsed.date),
        ("Subject", parsed.subject),
    )
    return _joined(["\n".join(f"{k}: {v}" for k, v in heads if v), parsed.clean])


# Open formats


def _odf_text(node: ElementTree.Element) -> str:
    return "".join(node.itertext())


def read_odt(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    blocks = []
    for node in root.iter():
        if node.tag == f"{ODF_TEXT}h":
            level = int(node.get(f"{ODF_TEXT}outline-level", "1"))
            blocks.append(f"{'#' * level} {_odf_text(node)}")
        elif node.tag == f"{ODF_TEXT}p":
            blocks.append(_odf_text(node))
    return _joined(blocks)


def read_ods(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    sheets = []
    for table in root.iter(f"{ODF_TABLE}table"):
        rows = (
            [_odf_text(cell) for cell in row.iter(f"{ODF_TABLE}table-cell")]
            for row in table.iter(f"{ODF_TABLE}table-row")
        )
        sheets.append(_sheet(table.get(f"{ODF_TABLE}name", ""), rows))
    return _joined(sheets)


def read_odp(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    slides = []
    for number, page in enumerate(root.iter(f"{ODF_PRESENTATION}page"), 1):
        words = [_odf_text(p) for p in page.iter(f"{ODF_TEXT}p") if _odf_text(p)]
        if words:
            slides.append("\n".join([SLIDE_MARK.format(number), *words]))
    return _joined(slides)


def read_rtf(data: bytes) -> str:
    from striprtf.striprtf import rtf_to_text

    return str(rtf_to_text(data.decode(OLD_ENCODING, "replace"), errors="ignore"))  # type: ignore[no-untyped-call]


# Tables and engineering files


def read_delimited(data: bytes, delimiter: str) -> str:
    rows = csv.reader(io.StringIO(data.decode("utf-8-sig", "replace")), delimiter=delimiter)
    return "\n".join("\t".join(row) for row in rows)


def read_csv(data: bytes) -> str:
    return read_delimited(data, ",")


def read_tsv(data: bytes) -> str:
    return read_delimited(data, "\t")


def read_ipynb(data: bytes) -> str:
    notebook = json.loads(data)
    cells = []
    for number, cell in enumerate(notebook.get("cells", []), 1):
        source = cell.get("source", "")
        text = "".join(source) if isinstance(source, list) else str(source)
        if text.strip():
            fence = f"```\n{text}\n```" if cell.get("cell_type") == "code" else text
            cells.append(f"{CELL_MARK.format(number)}\n{fence}")
    return _joined(cells)


def read_svg(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    return "\n".join(text.strip() for text in root.itertext() if text.strip())


def read_tar(data: bytes) -> str:
    """Only the names. Nothing is unpacked."""
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    return "\n".join(names[:LISTING_LIMIT])


READERS = {
    "pdf": read_pdf,
    "docx": read_docx,
    "docm": read_docm,
    "xlsx": read_xlsx,
    "xlsm": read_xlsx,
    "xls": read_xls,
    "pptx": read_pptx,
    "pptm": read_pptm,
    "doc": read_doc,
    "ppt": read_ppt,
    "hwp": read_hwp,
    "hwpx": read_hwpx,
    "msg": read_msg,
    "eml": read_eml,
    "odt": read_odt,
    "ods": read_ods,
    "odp": read_odp,
    "rtf": read_rtf,
    "csv": read_csv,
    "tsv": read_tsv,
    "ipynb": read_ipynb,
    "svg": read_svg,
    "tar": read_tar,
    "tgz": read_tar,
}
ZIP_BASED = {"docx", "docm", "xlsx", "xlsm", "pptx", "pptm", "hwpx", "odt", "ods", "odp"}
# These are OLE containers, where a password-protected .docx also looks like one.
OLE_BASED = {"doc", "xls", "ppt", "hwp", "msg"}
