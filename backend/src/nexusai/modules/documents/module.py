"""One library across uploaded files and mail attachments. Signature images never appear."""

import json
import mimetypes
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from nexusai.contracts.documents import (
    DocumentDone,
    DocumentLibrary,
    DocumentPreview,
    DocumentRow,
    GetDocument,
    ListDocuments,
    RemoveDocument,
    SaveFolders,
    UpdateDocument,
)
from nexusai.contracts.events import AppEvent
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail import store
from nexusai.modules.mail.extract import extract_text
from nexusai.modules.mail.parse import part_bytes
from nexusai.modules.mail.pst import PST_PART_OFFSET
from nexusai.modules.mail.pst_worker import read_attachment

log = structlog.get_logger()
documents_module = Module(
    name="documents",
    migrations=[
        Migration(
            "documents_001",
            """
CREATE TABLE documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, stored_name TEXT NOT NULL,
  content_type TEXT NOT NULL, size INTEGER NOT NULL, added TEXT NOT NULL, text TEXT);
CREATE TABLE document_meta (key TEXT PRIMARY KEY, folder TEXT, tags TEXT NOT NULL DEFAULT '[]');
CREATE TABLE document_folders (name TEXT PRIMARY KEY, position INTEGER NOT NULL);
CREATE VIRTUAL TABLE document_search USING fts5(name, text, tokenize = 'unicode61');
""",
        )
    ],
)
EMAIL_KINDS = ("attachment", "calendar", "inline", "risky")


def _file_folder(ctx: Context) -> Path:
    return ctx.config.home / "documents"


def _meta(ctx: Context) -> dict[str, tuple[str | None, list[str]]]:
    rows = ctx.bus.db.fetch_all("SELECT key, folder, tags FROM document_meta")
    return {row["key"]: (row["folder"], json.loads(row["tags"])) for row in rows}


def _email_parts(
    ctx: Context, where: str = "", params: tuple[object, ...] = ()
) -> list[DocumentRow]:
    meta = _meta(ctx)
    marks = ",".join("?" * len(EMAIL_KINDS))
    rows = ctx.bus.db.fetch_all(
        "SELECT p.message, p.part_index, p.filename, p.content_type, p.size, p.kind, m.date, m.thread_id"
        f" FROM message_parts p JOIN messages m ON m.id = p.message WHERE p.kind IN ({marks}) {where}"  # noqa: S608
        " ORDER BY m.date DESC LIMIT 5000",
        (*EMAIL_KINDS, *params),
    )
    documents = []
    for row in rows:
        key = f"m:{row['message']}:{row['part_index']}"
        folder, tags = meta.get(key, (None, []))
        documents.append(
            DocumentRow(
                key=key,
                name=row["filename"],
                content_type=row["content_type"],
                size=row["size"],
                date=row["date"],
                source="email",
                folder=folder,
                tags=tags,
                thread_id=row["thread_id"],
                risky=row["kind"] == "risky",
            )
        )
    return documents


def _uploads(ctx: Context) -> list[DocumentRow]:
    meta = _meta(ctx)
    documents = []
    for row in ctx.bus.db.fetch_all("SELECT * FROM documents ORDER BY added DESC"):
        key = f"u:{row['id']}"
        folder, tags = meta.get(key, (None, []))
        documents.append(
            DocumentRow(
                key=key,
                name=row["name"],
                content_type=row["content_type"],
                size=row["size"],
                date=row["added"],
                source="upload",
                folder=folder,
                tags=tags,
            )
        )
    return documents


def _search_keys(ctx: Context, query: str) -> set[str]:
    words = re.findall(r"[\w@.+-]+", query, flags=re.UNICODE)
    if not words:
        return set()
    match = " ".join(f'"{word}"*' for word in words)
    found = {
        f"u:{row['rowid']}"
        for row in ctx.bus.db.fetch_all(
            "SELECT rowid FROM document_search WHERE document_search MATCH ?", (match,)
        )
    }
    needle = f"%{query}%"
    for row in ctx.bus.db.fetch_all(
        "SELECT message, part_index FROM message_parts WHERE filename LIKE ? OR text LIKE ?",
        (needle, needle),
    ):
        found.add(f"m:{row['message']}:{row['part_index']}")
    return found


@documents_module.query("documents.list")
def list_documents(query: ListDocuments, ctx: Context) -> DocumentLibrary:
    documents: list[DocumentRow] = []
    if query.source != "email":
        documents += _uploads(ctx)
    if query.source != "upload":
        documents += _email_parts(ctx)
    tags = sorted({tag for document in documents for tag in document.tags})
    if query.folder:
        documents = [d for d in documents if d.folder == query.folder]
    if query.tag:
        documents = [d for d in documents if query.tag in d.tags]
    if query.query.strip():
        keys = _search_keys(ctx, query.query)
        documents = [d for d in documents if d.key in keys]
    documents.sort(key=lambda d: d.date, reverse=True)
    folders = ctx.bus.db.fetch_all("SELECT name FROM document_folders ORDER BY position")
    return DocumentLibrary(
        documents=documents[: query.limit], folders=[row["name"] for row in folders], tags=tags
    )


def _part_data(ctx: Context, message: int, index: int) -> bytes | None:
    if index >= PST_PART_OFFSET:
        rows = ctx.bus.db.fetch_all(
            "SELECT i.path, m.folder, m.item FROM pst_messages m JOIN pst_imports i ON i.id = m.import_id"
            " WHERE m.message = ?",
            (message,),
        )
        if not rows:
            return None
        try:
            return read_attachment(
                rows[0]["path"], rows[0]["folder"], rows[0]["item"], index - PST_PART_OFFSET
            )
        except (OSError, FileNotFoundError):
            return None
    raw = store.raw_of(ctx.bus.db, message)
    found = part_bytes(raw, index) if raw else None
    return found[0] if found else None


def part_text(ctx: Context, message: int, index: int) -> str:
    """The attachment's text, read once and kept. Mail search then finds it too."""
    rows = ctx.bus.db.fetch_all(
        "SELECT filename, kind, text FROM message_parts WHERE message = ? AND part_index = ?",
        (message, index),
    )
    if not rows or rows[0]["kind"] == "risky":
        return ""
    if rows[0]["text"] is not None:
        return str(rows[0]["text"])
    data = _part_data(ctx, message, index)
    text = extract_text(rows[0]["filename"], data) if data else ""
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "UPDATE message_parts SET text = ? WHERE message = ? AND part_index = ?",
            (text, message, index),
        )
        combined = tx.execute(
            "SELECT group_concat(text, ' ') FROM message_parts WHERE message = ? AND text != ''",
            (message,),
        ).fetchone()[0]
        tx.execute(
            "UPDATE mail_search SET attachments = ? WHERE rowid = ?", (combined or "", message)
        )
    return text


def extract_message(ctx: Context, message: int) -> None:
    parts = ctx.bus.db.fetch_all(
        "SELECT part_index FROM message_parts WHERE message = ? AND kind = 'attachment' AND text IS NULL",
        (message,),
    )
    for part in parts:
        part_text(ctx, message, part["part_index"])
    if parts:
        with ctx.bus.unit_of_work() as work:
            work.emit(
                "document.indexed", {"message": message}, source="documents", trace_id=ctx.trace_id
            )


@documents_module.on("mail.received", "documents.extract_new_mail")
def extract_new_mail(event: AppEvent, ctx: Context) -> None:
    """New mail is read now. History waits until someone opens it."""
    extract_message(ctx, int(event.payload["message_id"]))


@documents_module.on("thread.opened", "documents.extract_opened")
def extract_opened(event: AppEvent, ctx: Context) -> None:
    for row in ctx.bus.db.fetch_all(
        "SELECT id FROM messages WHERE thread_id = ?", (event.payload["thread_id"],)
    ):
        extract_message(ctx, row["id"])


def _find(ctx: Context, key: str) -> DocumentRow:
    if key.startswith("u:"):
        found = [d for d in _uploads(ctx) if d.key == key]
    else:
        parts = key.split(":")
        if len(parts) != 3:
            raise CommandError("document.not_found", "That document no longer exists.", 404)
        found = _email_parts(
            ctx, "AND p.message = ? AND p.part_index = ?", (int(parts[1]), int(parts[2]))
        )
    if not found:
        raise CommandError("document.not_found", "That document no longer exists.", 404)
    return found[0]


@documents_module.query("documents.get")
def get_document(query: GetDocument, ctx: Context) -> DocumentPreview:
    document = _find(ctx, query.key)
    if query.key.startswith("u:"):
        rows = ctx.bus.db.fetch_all(
            "SELECT text FROM documents WHERE id = ?", (int(query.key[2:]),)
        )
        text = rows[0]["text"] or "" if rows else ""
    else:
        _, message, index = query.key.split(":")
        text = part_text(ctx, int(message), int(index))
    return DocumentPreview(document=document, text=text)


@documents_module.command("documents.update")
def update_document(command: UpdateDocument, ctx: Context) -> DocumentDone:
    _find(ctx, command.key)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO document_meta (key, folder, tags) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET folder = excluded.folder, tags = excluded.tags",
            (command.key, command.folder, json.dumps(command.tags)),
        )
        work.emit(
            "documents.changed", {"key": command.key}, source="documents", trace_id=ctx.trace_id
        )
    return DocumentDone()


@documents_module.command("documents.saveFolders")
def save_folders(command: SaveFolders, ctx: Context) -> DocumentDone:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM document_folders")
        for position, name in enumerate(dict.fromkeys(command.folders)):
            work.tx.execute(
                "INSERT INTO document_folders (name, position) VALUES (?, ?)", (name, position)
            )
        work.emit("documents.changed", {"key": None}, source="documents", trace_id=ctx.trace_id)
    return DocumentDone()


@documents_module.command("documents.remove")
def remove_document(command: RemoveDocument, ctx: Context) -> DocumentDone:
    if not command.key.startswith("u:"):
        raise CommandError(
            "document.not_removable", "Mail attachments stay with their message.", 422
        )
    identifier = int(command.key[2:])
    rows = ctx.bus.db.fetch_all("SELECT stored_name FROM documents WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("document.not_found", "That document no longer exists.", 404)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM documents WHERE id = ?", (identifier,))
        work.tx.execute("DELETE FROM document_search WHERE rowid = ?", (identifier,))
        work.tx.execute("DELETE FROM document_meta WHERE key = ?", (command.key,))
        work.emit(
            "documents.changed", {"key": command.key}, source="documents", trace_id=ctx.trace_id
        )
    (_file_folder(ctx) / rows[0]["stored_name"]).unlink(missing_ok=True)
    return DocumentDone()


_extract_lock = threading.Lock()


def save_upload(ctx: Context, name: str, data: bytes) -> DocumentRow:
    """Copies the file into Home under a generated name, so a filename can't choose where it lands."""
    clean = Path(name.replace("\\", "/")).name.strip() or "document"
    suffix = Path(clean).suffix[:16]
    stored = f"{uuid.uuid4().hex}{suffix}"
    folder = _file_folder(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored).write_bytes(data)
    with _extract_lock:
        text = extract_text(clean, data)
    content_type = mimetypes.guess_type(clean)[0] or "application/octet-stream"
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO documents (name, stored_name, content_type, size, added, text) VALUES (?, ?, ?, ?, ?, ?)",
            (clean, stored, content_type, len(data), datetime.now(UTC).isoformat(), text),
        )
        identifier = int(cursor.lastrowid or 0)
        work.tx.execute(
            "INSERT INTO document_search (rowid, name, text) VALUES (?, ?, ?)",
            (identifier, clean, text),
        )
        work.emit(
            "documents.changed",
            {"key": f"u:{identifier}"},
            source="documents",
            trace_id=ctx.trace_id,
        )
    log.info("document_added", size=len(data))
    return _find(ctx, f"u:{identifier}")


def document_file(ctx: Context, key: str) -> tuple[str, bytes] | None:
    if key.startswith("u:"):
        rows = ctx.bus.db.fetch_all(
            "SELECT name, stored_name FROM documents WHERE id = ?", (int(key[2:]),)
        )
        if not rows:
            return None
        path = _file_folder(ctx) / rows[0]["stored_name"]
        return (rows[0]["name"], path.read_bytes()) if path.exists() else None
    parts = key.split(":")
    if len(parts) != 3:
        return None
    message, index = int(parts[1]), int(parts[2])
    rows = ctx.bus.db.fetch_all(
        "SELECT filename, kind FROM message_parts WHERE message = ? AND part_index = ?",
        (message, index),
    )
    if not rows or rows[0]["kind"] == "risky":
        return None
    data = _part_data(ctx, message, index)
    return (rows[0]["filename"], data) if data is not None else None
