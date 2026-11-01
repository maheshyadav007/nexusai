"""Search by meaning. Local models, optional, and everything else works without them."""

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from nexusai.contracts.events import AppEvent
from nexusai.contracts.semantic import (
    DownloadModel,
    GetSemanticStatus,
    ImportModel,
    LocalModel,
    ModelName,
    SaveSemanticSettings,
    SemanticHit,
    SemanticStatus,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.semantic import catalog, downloader
from nexusai.modules.semantic.catalog import BY_ID, MODELS, CatalogModel
from nexusai.modules.semantic.embedder import Embedder, OnnxEmbedder
from nexusai.modules.semantic.index import VectorIndex, to_bytes

log = structlog.get_logger()

semantic_module = Module(
    name="semantic",
    migrations=[
        Migration(
            "semantic_001",
            """
CREATE TABLE semantic_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
  chunk INTEGER NOT NULL, vector BLOB NOT NULL);
CREATE INDEX semantic_chunks_ref ON semantic_chunks (model, kind, ref);
CREATE TABLE semantic_done (model TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY (model, kind, ref));
CREATE TABLE semantic_settings (id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL);
""",
        )
    ],
)

BATCH = 8
PAUSE_SECONDS = 0.05
# Unloading frees several hundred megabytes when there's nothing to do.
IDLE_UNLOAD_SECONDS = 600.0
NOTICE_SECONDS = 1.5
MAIL_CHUNKS = 3
DOCUMENT_CHUNKS = 64
CHUNK_CHARS = 900
OVERLAP_CHARS = 100
EXCERPT_CHARS = 240


def chunks_of(text: str, most: int) -> list[str]:
    """Pieces a person could read on their own, breaking at a sentence or line where it can."""
    clean = re.sub(r"[ \t]+", " ", text).strip()
    pieces: list[str] = []
    start = 0
    while start < len(clean) and len(pieces) < most:
        end = min(start + CHUNK_CHARS, len(clean))
        if end < len(clean):
            cut = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end))
            if cut > start + CHUNK_CHARS // 2:
                end = cut + 1
        piece = clean[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(clean):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return pieces


class Engine:
    """One per open Home: the download, the model in memory, and the indexing thread."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.db = ctx.bus.db
        self.home: Path = ctx.config.home
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.downloads: dict[str, threading.Event] = {}
        self.download_threads: list[threading.Thread] = []
        self.errors: dict[str, str] = {}
        self.embedder: Embedder | None = None
        self.embedder_model: str | None = None
        self.index_of: dict[str, VectorIndex] = {}
        self.indexing = False
        self.last_notice = 0.0
        self.thread = threading.Thread(target=self._loop, daemon=True, name="semantic-index")

    # Settings

    def settings(self) -> dict[str, Any]:
        rows = self.db.fetch_all("SELECT value FROM semantic_settings")
        saved = json.loads(rows[0]["value"]) if rows else {}
        return {"active": catalog.DEFAULT, "auto_download": True, "mirror": None, **saved}

    def save_settings(self, **changes: Any) -> None:
        value = json.dumps({**self.settings(), **changes})
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO semantic_settings (id, value) VALUES (1, ?)"
                " ON CONFLICT (id) DO UPDATE SET value = excluded.value",
                (value,),
            )

    def active(self) -> CatalogModel:
        return BY_ID.get(self.settings()["active"], MODELS[0])

    def is_ready(self) -> bool:
        return downloader.is_complete(self.home, self.active())

    # What's true right now

    def status(self) -> SemanticStatus:
        settings = self.settings()
        active = self.active()
        models = []
        for model in MODELS:
            complete = downloader.is_complete(self.home, model)
            downloading = model.id in self.downloads
            error = self.errors.get(model.id)
            state = (
                "downloading"
                if downloading
                else "ready"
                if complete
                else "failed"
                if error
                else "missing"
            )
            models.append(
                LocalModel(
                    id=model.id,
                    label=model.label,
                    description=model.description,
                    size_bytes=model.size,
                    state=state,
                    downloaded_bytes=downloader.bytes_present(self.home, model),
                    error=error,
                    active=model.id == active.id,
                )
            )
        indexed, total = self._counts(active.id)
        return SemanticStatus(
            models=models,
            active=active.id,
            ready=self.is_ready(),
            auto_download=settings["auto_download"],
            mirror=settings["mirror"],
            indexed=indexed,
            total=total,
            indexing=self.indexing,
        )

    def _counts(self, model: str) -> tuple[int, int]:
        rows = self.db.fetch_all(
            "SELECT (SELECT COUNT(*) FROM semantic_done WHERE model = ?) AS done,"
            " (SELECT COUNT(*) FROM messages)"
            " + (SELECT COUNT(*) FROM documents)"
            " + (SELECT COUNT(*) FROM message_parts WHERE kind = 'attachment' AND text IS NOT NULL AND text != '')"
            " AS total",
            (model,),
        )
        return int(rows[0]["done"]), int(rows[0]["total"])

    def announce(self, *, force: bool = False) -> None:
        """The event carries the whole status, so nothing has to ask for it."""
        now = time.monotonic()
        if self.stopping.is_set() or (not force and now - self.last_notice < NOTICE_SECONDS):
            return
        self.last_notice = now
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "semantic.changed",
                self.status().model_dump(mode="json"),
                source="semantic",
                trace_id=self.ctx.trace_id,
            )

    # Downloading

    def download(self, model_id: str | None = None) -> None:
        model = BY_ID.get(model_id or self.active().id)
        if model is None:
            raise CommandError("model.unknown", "That model isn't available.", 404)
        with self.lock:
            if model.id in self.downloads or downloader.is_complete(self.home, model):
                return
            stop = threading.Event()
            self.downloads[model.id] = stop
            self.errors.pop(model.id, None)
        self.announce(force=True)
        self.download_threads = [t for t in self.download_threads if t.is_alive()]
        thread = threading.Thread(
            target=self._download, args=(model, stop), daemon=True, name="model-download"
        )
        self.download_threads.append(thread)
        thread.start()

    def _download(self, model: CatalogModel, stop: threading.Event) -> None:
        try:
            source = self.settings()["mirror"] or self.ctx.config.model_hub
            downloader.download(self.home, model, source, stop, self.announce)
            self.ctx_notify(model)
        except downloader.Cancelled:
            log.info("model_download_cancelled", model=model.id)
        except downloader.DownloadFailed as error:
            self.errors[model.id] = str(error)
            log.warning("model_download_failed", model=model.id, error=str(error))
        except OSError as error:
            self.errors[model.id] = "Couldn't save the model to this drive."
            log.warning("model_download_failed", model=model.id, error=type(error).__name__)
        finally:
            with self.lock:
                self.downloads.pop(model.id, None)
            self.announce(force=True)
            self.wake.set()

    def ctx_notify(self, model: CatalogModel) -> None:
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "notification.requested",
                {
                    "kind": "local-model",
                    "title": "Search by meaning is ready",
                    "detail": "Your mail and documents are being prepared in the background.",
                    "link": "/search",
                },
                source="semantic",
                trace_id=self.ctx.trace_id,
            )

    def cancel(self, model_id: str) -> None:
        with self.lock:
            stop = self.downloads.get(model_id)
        if stop:
            stop.set()

    def ensure(self) -> bool:
        """For anyone about to search: ready now, or fetching it if that's allowed."""
        if self.is_ready():
            return True
        if self.settings()["auto_download"] and self.active().id not in self.errors:
            self.download()
        return False

    # The model

    def _load(self, model: CatalogModel) -> Embedder:
        with self.lock:
            if self.embedder is None or self.embedder_model != model.id:
                self.embedder = make_embedder(self.home, model)
                self.embedder_model = model.id
            return self.embedder

    def _unload(self) -> None:
        with self.lock:
            self.embedder = None
            self.embedder_model = None

    def index(self, model: CatalogModel) -> VectorIndex:
        with self.lock:
            found = self.index_of.get(model.id)
            if found is None:
                found = VectorIndex(self.db, model.id)
                self.index_of[model.id] = found
            return found

    # Indexing, newest first

    def _next_items(self, model: str) -> list[tuple[str, str, str, int]]:
        """Up to one batch of things with no vectors yet: mail, then uploads, then attachments."""
        rows = self.db.fetch_all(
            "SELECT m.id, m.subject, m.from_name, m.own_text FROM messages m"
            " LEFT JOIN semantic_done d ON d.model = ? AND d.kind = 'mail' AND d.ref = CAST(m.id AS TEXT)"
            " WHERE d.ref IS NULL ORDER BY m.id DESC LIMIT ?",
            (model, BATCH),
        )
        if rows:
            return [
                (
                    "mail",
                    str(r["id"]),
                    f"{r['subject']}\n{r['from_name']}\n{r['own_text']}",
                    MAIL_CHUNKS,
                )
                for r in rows
            ]
        rows = self.db.fetch_all(
            "SELECT doc.id, doc.name, doc.text FROM documents doc"
            " LEFT JOIN semantic_done d ON d.model = ? AND d.kind = 'document' AND d.ref = 'u:' || doc.id"
            " WHERE d.ref IS NULL AND doc.status != 'pending' ORDER BY doc.id DESC LIMIT ?",
            (model, BATCH),
        )
        if rows:
            return [
                ("document", f"u:{r['id']}", f"{r['name']}\n{r['text'] or ''}", DOCUMENT_CHUNKS)
                for r in rows
            ]
        rows = self.db.fetch_all(
            "SELECT p.message, p.part_index, p.filename, p.text FROM message_parts p"
            " LEFT JOIN semantic_done d ON d.model = ? AND d.kind = 'document'"
            " AND d.ref = 'm:' || p.message || ':' || p.part_index"
            " WHERE d.ref IS NULL AND p.kind = 'attachment' AND p.text IS NOT NULL AND p.text != ''"
            " ORDER BY p.message DESC LIMIT ?",
            (model, BATCH),
        )
        return [
            (
                "document",
                f"m:{r['message']}:{r['part_index']}",
                f"{r['filename']}\n{r['text']}",
                DOCUMENT_CHUNKS,
            )
            for r in rows
        ]

    def run_once(self) -> bool:
        """One batch. False when there was nothing left to do."""
        model = self.active()
        items = self._next_items(model.id)
        if not items:
            return False
        embedder = self._load(model)
        pieces = [
            (kind, ref, n, piece)
            for kind, ref, text, most in items
            for n, piece in enumerate(chunks_of(text, most))
        ]
        written: list[tuple[str, str, int, bytes]] = []
        for start in range(0, len(pieces), BATCH):
            group = pieces[start : start + BATCH]
            vectors = embedder.embed([p[3] for p in group], query=False)
            written += [
                (p[0], p[1], p[2], to_bytes(v)) for p, v in zip(group, vectors, strict=True)
            ]
        with self.db.transaction() as tx:
            for kind, ref, chunk, vector in written:
                tx.execute(
                    "INSERT INTO semantic_chunks (model, kind, ref, chunk, vector) VALUES (?, ?, ?, ?, ?)",
                    (model.id, kind, ref, chunk, vector),
                )
            for kind, ref, _, _ in items:
                tx.execute(
                    "INSERT OR IGNORE INTO semantic_done (model, kind, ref) VALUES (?, ?, ?)",
                    (model.id, kind, ref),
                )
        index = self.index(model)
        for kind, ref, chunk, vector in written:
            index.added(kind, ref, chunk, vector)
        return True

    def _loop(self) -> None:
        while not self.stopping.is_set():
            worked = False
            if self.is_ready():
                try:
                    worked = self.run_once()
                except Exception:
                    log.exception("semantic_indexing_failed")
            if worked:
                self.indexing = True
                self.announce()
                self.stopping.wait(PAUSE_SECONDS)
                continue
            if self.indexing:
                self.indexing = False
                self.announce(force=True)
                self._tidy()
            if not self.wake.wait(IDLE_UNLOAD_SECONDS):
                self._unload()
            self.wake.clear()

    def _tidy(self) -> None:
        """Mail moved or removed since leaves vectors behind, which only take up space."""
        with self.db.transaction() as tx:
            gone = tx.execute(
                "DELETE FROM semantic_chunks WHERE kind = 'mail'"
                " AND CAST(ref AS INTEGER) NOT IN (SELECT id FROM messages)"
            ).rowcount
            tx.execute(
                "DELETE FROM semantic_done WHERE kind = 'mail'"
                " AND CAST(ref AS INTEGER) NOT IN (SELECT id FROM messages)"
            )
        if gone:
            for index in self.index_of.values():
                index.forget()

    def start(self) -> None:
        self.thread.start()
        if self.is_ready():
            self.wake.set()

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        for stop in list(self.downloads.values()):
            stop.set()
        self.thread.join(timeout=10)
        # They write when they finish, and the database closes after this returns.
        for thread in self.download_threads:
            thread.join(timeout=10)

    # Searching

    def search(self, text: str, kinds: set[str], limit: int) -> list[SemanticHit]:
        model = self.active()
        if not self.is_ready():
            return []
        vector = np.asarray(self._load(model).embed([text], query=True)[0], dtype=np.float32)
        found = self.index(model).search(vector, kinds, limit)
        hits = []
        for item in found:
            if item.score < model.min_score:
                break
            excerpt = self._excerpt(item.kind, item.ref, item.chunk)
            if excerpt is not None:
                hits.append(
                    SemanticHit(kind=item.kind, ref=item.ref, score=item.score, excerpt=excerpt)
                )
        return hits

    def _excerpt(self, kind: str, ref: str, chunk: int) -> str | None:
        """None if the thing has gone since, so it's never shown."""
        if kind == "mail":
            rows = self.db.fetch_all(
                "SELECT subject, from_name, own_text FROM messages WHERE id = ?", (int(ref),)
            )
            text = (
                f"{rows[0]['subject']}\n{rows[0]['from_name']}\n{rows[0]['own_text']}"
                if rows
                else None
            )
            most = MAIL_CHUNKS
        elif ref.startswith("u:"):
            rows = self.db.fetch_all(
                "SELECT name, text FROM documents WHERE id = ?", (int(ref[2:]),)
            )
            text = f"{rows[0]['name']}\n{rows[0]['text'] or ''}" if rows else None
            most = DOCUMENT_CHUNKS
        else:
            _, message, part = ref.split(":")
            rows = self.db.fetch_all(
                "SELECT filename, text FROM message_parts WHERE message = ? AND part_index = ?",
                (int(message), int(part)),
            )
            text = f"{rows[0]['filename']}\n{rows[0]['text'] or ''}" if rows else None
            most = DOCUMENT_CHUNKS
        if text is None:
            return None
        pieces = chunks_of(text, most)
        return (pieces[chunk] if chunk < len(pieces) else text)[:EXCERPT_CHARS]

    def forget(self, kind: str, ref: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM semantic_chunks WHERE kind = ? AND ref = ?", (kind, ref))
            tx.execute("DELETE FROM semantic_done WHERE kind = ? AND ref = ?", (kind, ref))
        for index in self.index_of.values():
            index.forget()


def make_embedder(home: Path, model: CatalogModel) -> Embedder:
    return OnnxEmbedder(home, model)


_engine: Engine | None = None


def engine() -> Engine | None:
    return _engine


def _started() -> Engine:
    if _engine is None:
        raise CommandError("home.not_ready", "Choose a NexusAI Home first.", 409)
    return _engine


def _start(ctx: Context) -> None:
    global _engine
    _engine = Engine(ctx)
    _engine.start()


def _stop() -> None:
    global _engine
    if _engine is not None:
        _engine.stop()
    _engine = None


semantic_module.on_start.append(_start)
semantic_module.on_stop.append(_stop)


@semantic_module.query("semantic.status")
def get_status(query: GetSemanticStatus, ctx: Context) -> SemanticStatus:
    return _started().status()


@semantic_module.command("semantic.download")
def start_download(command: DownloadModel, ctx: Context) -> SemanticStatus:
    current = _started()
    current.download(command.id)
    return current.status()


@semantic_module.command("semantic.cancel")
def cancel_download(command: ModelName, ctx: Context) -> SemanticStatus:
    current = _started()
    current.cancel(command.id)
    return current.status()


@semantic_module.command("semantic.remove")
def remove_model(command: ModelName, ctx: Context) -> SemanticStatus:
    current = _started()
    model = BY_ID.get(command.id)
    if model is None:
        raise CommandError("model.unknown", "That model isn't available.", 404)
    current.cancel(command.id)
    current._unload()
    downloader.remove(ctx.config.home, model)
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM semantic_chunks WHERE model = ?", (model.id,))
        tx.execute("DELETE FROM semantic_done WHERE model = ?", (model.id,))
    current.index_of.pop(model.id, None)
    current.errors.pop(model.id, None)
    current.announce(force=True)
    return current.status()


@semantic_module.command("semantic.setActive")
def set_active(command: ModelName, ctx: Context) -> SemanticStatus:
    current = _started()
    if command.id not in BY_ID:
        raise CommandError("model.unknown", "That model isn't available.", 404)
    current.save_settings(active=command.id)
    current.ensure()
    current.wake.set()
    current.announce(force=True)
    return current.status()


@semantic_module.command("semantic.saveSettings")
def save_settings(command: SaveSemanticSettings, ctx: Context) -> SemanticStatus:
    current = _started()
    changes = command.model_dump(exclude_unset=True)
    if changes.get("mirror") == "":
        changes["mirror"] = None
    current.save_settings(**changes)
    current.errors.clear()
    current.announce(force=True)
    return current.status()


@semantic_module.command("semantic.importFiles")
def import_files(command: ImportModel, ctx: Context) -> SemanticStatus:
    current = _started()
    model = BY_ID.get(command.id)
    if model is None:
        raise CommandError("model.unknown", "That model isn't available.", 404)
    try:
        downloader.import_files(ctx.config.home, model, Path(command.folder).expanduser())
    except downloader.DownloadFailed as error:
        raise CommandError("model.import_failed", str(error), 422) from error
    current.errors.pop(model.id, None)
    current.wake.set()
    current.announce(force=True)
    return current.status()


@semantic_module.on("mail.received", "semantic.new_mail")
@semantic_module.on("mail.changed", "semantic.changed_mail")
@semantic_module.on("document.indexed", "semantic.new_document")
@semantic_module.on("documents.changed", "semantic.changed_document")
def something_new(event: AppEvent, ctx: Context) -> None:
    if _engine is not None:
        _engine.wake.set()
