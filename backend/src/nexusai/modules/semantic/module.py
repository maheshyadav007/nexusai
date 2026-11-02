"""Search by meaning. Local models, optional, and everything else works without them."""

import json
import os
import re
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import psutil
import structlog

from nexusai.contracts.events import AppEvent
from nexusai.contracts.semantic import (
    DetectModels,
    DownloadModel,
    GetSemanticStatus,
    ImportModel,
    IndexInfo,
    IndexState,
    LocalModel,
    ModelDetection,
    ModelName,
    RebuildIndex,
    SaveSemanticSettings,
    SemanticHit,
    SemanticStatus,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.modules.mail.extract import EXTRACTOR_VERSION
from nexusai.modules.semantic import catalog, downloader
from nexusai.modules.semantic.catalog import BY_ID, MODELS, CatalogModel
from nexusai.modules.semantic.embedder import Embedder, OnnxEmbedder
from nexusai.modules.semantic.index import IndexStore, to_bytes

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
        ),
        # Vectors moved to their own files. They're rebuilt there, from the mail and documents.
        Migration(
            "semantic_separate_indexes_001",
            "DROP TABLE semantic_chunks; DROP TABLE semantic_done;",
        ),
    ],
)

BATCH = 8
PAUSE_SECONDS = 0.05
# While a lot is arriving, the list of what's left is only rebuilt this often.
REFILL_SECONDS = 5.0
# Unloading frees several hundred megabytes when there's nothing to do.
IDLE_UNLOAD_SECONDS = 600.0
NOTICE_SECONDS = 1.5
# About 5 KB of one email, and about 400 KB of one document. A chunk takes about 520 bytes on
# disk, as measured, so a full document costs about 260 KB and a typical email about 1 KB.
MAIL_CHUNKS = 6
DOCUMENT_CHUNKS = 500
CHUNK_CHARS = 900
OVERLAP_CHARS = 100
EXCERPT_CHARS = 240
MAIL = "mail"
DOCUMENT = "document"
KINDS = (MAIL, DOCUMENT)
MOST_CHUNKS = {MAIL: MAIL_CHUNKS, DOCUMENT: DOCUMENT_CHUNKS}
NAMES = {MAIL: "emails", DOCUMENT: "documents"}
HUB_CHECK_SECONDS = 3.0
PLACE_MARK = re.compile(
    r"^\[((?:Page \d+)|(?:Slide \d+)|(?:Cell \d+)|(?:Sheet: [^\]]+))\]$", re.MULTILINE
)
# Below this, the larger model would make the computer feel slow.
SMALL_MODEL_BELOW_BYTES = 8 * 1024**3


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _spans(clean: str, most: int) -> list[tuple[int, int]]:
    """Where each piece starts and ends, breaking at a paragraph, line or sentence where it can."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(clean) and len(spans) < most:
        end = min(start + CHUNK_CHARS, len(clean))
        if end < len(clean):
            # A paragraph or a new page is the best place to stop, then a line, then a sentence.
            halfway = start + CHUNK_CHARS // 2
            for mark in ("\n\n", "\n", ". "):
                cut = clean.rfind(mark, halfway, end)
                if cut > start:
                    end = cut + 1
                    break
        if clean[start:end].strip():
            spans.append((start, end))
        if end >= len(clean):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return spans


def chunks_of(text: str, most: int) -> list[str]:
    """Pieces a person could read on their own."""
    clean = _clean(text)
    return [clean[start:end].strip() for start, end in _spans(clean, most)]


def place_of(text: str, chunk: int, most: int) -> str | None:
    """Which page, slide or sheet a piece came from, from the nearest mark before its end.

    By position, not by searching for its words, since headers repeat from page to page.
    """
    clean = _clean(text)
    spans = _spans(clean, most)
    if chunk >= len(spans):
        return None
    found = PLACE_MARK.findall(clean[: spans[chunk][1]])
    return found[-1] if found else None


# Spam and Trash stay in their own folders, so they're never found by meaning.
KEPT_MAIL = "folder_role NOT IN ('junk', 'trash')"


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
        self.stores = {kind: IndexStore(self.home, kind, ctx.config.database_key) for kind in KINDS}
        self.queue: deque[tuple[str, str]] = deque()
        self.queue_for: str | None = None
        self.stale_queue = True
        self.last_refill = 0.0
        self.indexing = False
        self.last_notice = 0.0
        self.thread = threading.Thread(target=self._loop, daemon=True, name="semantic-index")

    # Settings

    def settings(self) -> dict[str, Any]:
        rows = self.db.fetch_all("SELECT value FROM semantic_settings")
        saved = json.loads(rows[0]["value"]) if rows else {}
        return {"active": catalog.DEFAULT, "mirror": None, **saved}

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
        indexes = [self.index_info(kind, active) for kind in KINDS]
        return SemanticStatus(
            models=models,
            active=active.id,
            ready=self.is_ready(),
            mirror=settings["mirror"],
            indexed=sum(index.indexed for index in indexes),
            total=sum(index.total for index in indexes),
            indexing=self.indexing,
            indexes=indexes,
        )

    def _settings_for(self, kind: str, model: CatalogModel) -> dict[str, Any]:
        chunking: dict[str, int] = {
            "chunk_chars": CHUNK_CHARS,
            "overlap_chars": OVERLAP_CHARS,
            "most_chunks": MOST_CHUNKS[kind],
        }
        if kind == DOCUMENT:
            chunking["extractor"] = EXTRACTOR_VERSION
        return catalog.build_settings(model, **chunking)

    def _fingerprint(self, kind: str, model: CatalogModel) -> str:
        return catalog.fingerprint_of(self._settings_for(kind, model))

    def _total(self, kind: str) -> int:
        if kind == MAIL:
            return int(
                self.db.fetch_all(f"SELECT COUNT(*) AS n FROM messages WHERE {KEPT_MAIL}")[0]["n"]
            )  # noqa: S608
        rows = self.db.fetch_all(
            "SELECT (SELECT COUNT(*) FROM documents)"
            " + (SELECT COUNT(*) FROM home_files)"
            " + (SELECT COUNT(*) FROM message_parts p JOIN messages m ON m.id = p.message WHERE p.kind = 'attachment' AND p.text IS NOT NULL AND p.text != '' AND m.folder_role NOT IN ('junk', 'trash'))"
            " AS n"
        )
        return int(rows[0]["n"])

    def index_info(self, kind: str, model: CatalogModel) -> IndexInfo:
        store = self.stores[kind]
        fingerprint = self._fingerprint(kind, model)
        indexed, stale = store.counts(model.id, fingerprint)
        total = self._total(kind)
        state: IndexState = (
            "off"
            if not self.is_ready()
            else "out_of_date"
            if stale
            else "partial"
            if indexed < total
            else "current"
        )
        version = store.version(fingerprint)
        return IndexInfo(
            kind=kind,
            state=state,
            indexed=indexed,
            total=total,
            stale=stale,
            fingerprint=fingerprint,
            build_settings=self._settings_for(kind, model),
            built=version[1] if version else None,
        )

    def coverage(self, kinds: set[str]) -> str | None:
        """Words for the agent when part of the index isn't ready, or None when all of it is."""
        model = self.active()
        infos = [self.index_info(kind, model) for kind in KINDS if kind in kinds]
        missing = [info for info in infos if info.indexed < info.total]
        if not missing:
            return None
        parts = [f"{info.indexed} of {info.total} {NAMES[info.kind]}" for info in missing]
        return (
            f"Search by meaning so far covers {' and '.join(parts)}, so results may be incomplete."
        )

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

    # Indexing, newest first

    def _refill(self, model: str) -> None:
        """What has no vectors yet: mail, then uploads, then attachments. Nothing is read twice."""
        rows = self.db.fetch_all(f"SELECT id FROM messages WHERE {KEPT_MAIL} ORDER BY id DESC")  # noqa: S608
        done = self.stores[MAIL].done_refs(model)
        items = [(MAIL, str(r["id"])) for r in rows if str(r["id"]) not in done]
        done = self.stores[DOCUMENT].done_refs(model)
        rows = self.db.fetch_all(
            "SELECT id FROM documents WHERE status != 'pending' ORDER BY id DESC"
        )
        items += [(DOCUMENT, f"u:{r['id']}") for r in rows if f"u:{r['id']}" not in done]
        rows = self.db.fetch_all(
            "SELECT id FROM home_files WHERE status != 'pending' ORDER BY id DESC"
        )
        items += [(DOCUMENT, f"h:{r['id']}") for r in rows if f"h:{r['id']}" not in done]
        rows = self.db.fetch_all(
            "SELECT p.message, p.part_index FROM message_parts p JOIN messages m ON m.id = p.message"
            " WHERE p.kind = 'attachment' AND p.text IS NOT NULL AND p.text != ''"
            " AND m.folder_role NOT IN ('junk', 'trash') ORDER BY p.message DESC"
        )
        for row in rows:
            ref = f"m:{row['message']}:{row['part_index']}"
            if ref not in done:
                items.append((DOCUMENT, ref))
        self.queue = deque(items)
        self.queue_for = model
        self.stale_queue = False
        self.last_refill = time.monotonic()

    def _text_of(self, kind: str, ref: str) -> str | None:
        """None if the thing has gone since."""
        if kind == MAIL:
            rows = self.db.fetch_all(
                "SELECT subject, from_name, own_text FROM messages WHERE id = ?", (int(ref),)
            )
            return (
                f"{rows[0]['subject']}\n{rows[0]['from_name']}\n{rows[0]['own_text']}"
                if rows
                else None
            )
        if ref.startswith("u:"):
            rows = self.db.fetch_all(
                "SELECT name, text FROM documents WHERE id = ?", (int(ref[2:]),)
            )
            return f"{rows[0]['name']}\n{rows[0]['text'] or ''}" if rows else None
        if ref.startswith("h:"):
            rows = self.db.fetch_all(
                "SELECT name, text FROM home_files WHERE id = ?", (int(ref[2:]),)
            )
            return f"{rows[0]['name']}\n{rows[0]['text']}" if rows else None
        _, message, part = ref.split(":")
        rows = self.db.fetch_all(
            "SELECT filename, text FROM message_parts WHERE message = ? AND part_index = ?",
            (int(message), int(part)),
        )
        return f"{rows[0]['filename']}\n{rows[0]['text'] or ''}" if rows else None

    def _next_items(self, model: str) -> tuple[str, list[tuple[str, str]]]:
        """Up to one batch of one kind, so each batch writes to one file."""
        due = self.stale_queue and (
            not self.queue or time.monotonic() - self.last_refill > REFILL_SECONDS
        )
        if self.queue_for != model or due:
            self._refill(model)
        items: list[tuple[str, str]] = []
        kind = self.queue[0][0] if self.queue else MAIL
        while self.queue and self.queue[0][0] == kind and len(items) < BATCH:
            _, ref = self.queue.popleft()
            text = self._text_of(kind, ref)
            if text is not None:
                items.append((ref, text))
        return kind, items

    def run_once(self) -> bool:
        """One batch. False when there was nothing left to do."""
        model = self.active()
        kind, items = self._next_items(model.id)
        if not items:
            return bool(self.queue)
        embedder = self._load(model)
        pieces = [
            (ref, n, piece)
            for ref, text in items
            for n, piece in enumerate(chunks_of(text, MOST_CHUNKS[kind]))
        ]
        written: list[tuple[str, int, bytes]] = []
        for start in range(0, len(pieces), BATCH):
            if self.stopping.is_set():
                return False
            group = pieces[start : start + BATCH]
            vectors = embedder.embed([p[2] for p in group], query=False)
            written += [(p[0], p[1], to_bytes(v)) for p, v in zip(group, vectors, strict=True)]
        store = self.stores[kind]
        fingerprint = self._fingerprint(kind, model)
        store.record_version(fingerprint, model.id, self._settings_for(kind, model))
        store.write(model.id, fingerprint, [ref for ref, _ in items], written)
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
                self._announce_finished()
            if not self.wake.wait(IDLE_UNLOAD_SECONDS):
                self._unload()
            self.wake.clear()

    def _announce_finished(self) -> None:
        with self.ctx.bus.unit_of_work() as work:
            work.emit(
                "index.finished",
                {"title": "The search index is up to date"},
                source="semantic",
                trace_id=self.ctx.trace_id,
            )

    def _tidy(self) -> None:
        """Mail moved or removed since leaves vectors behind, which only take up space."""
        store = self.stores[MAIL]
        model = self.active().id
        here = {
            str(r["id"]) for r in self.db.fetch_all(f"SELECT id FROM messages WHERE {KEPT_MAIL}")
        }  # noqa: S608
        store.forget_many(store.done_refs(model) - here)

    def rebuild(self, kind: str) -> None:
        """Only when asked: a large mailbox can take a long time, and the old vectors still work."""
        model = self.active()
        store = self.stores[kind]
        store.forget_many(store.done_refs(model.id))
        self.stale_queue = True
        self.queue_for = None
        self.wake.set()
        self.announce(force=True)

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
        for store in self.stores.values():
            store.close()

    # Searching

    def search(self, text: str, kinds: set[str], limit: int) -> list[SemanticHit]:
        model = self.active()
        if not self.is_ready():
            return []
        vector = np.asarray(self._load(model).embed([text], query=True)[0], dtype=np.float32)
        found = [
            item
            for kind in KINDS
            if kind in kinds
            for item in self.stores[kind].vector_index(model.id).search(vector, limit)
        ]
        found.sort(key=lambda item: item.score, reverse=True)
        hits = []
        for item in found[:limit]:
            if item.score < model.min_score:
                break
            found_text = self._excerpt(item.kind, item.ref, item.chunk)
            if found_text is not None:
                excerpt, place = found_text
                hits.append(
                    SemanticHit(
                        kind=item.kind, ref=item.ref, score=item.score, excerpt=excerpt, place=place
                    )
                )
        return hits

    def _excerpt(self, kind: str, ref: str, chunk: int) -> tuple[str, str | None] | None:
        """None if the thing has gone since, so it's never shown."""
        text = self._text_of(kind, ref)
        if text is None:
            return None
        pieces = chunks_of(text, MOST_CHUNKS[kind])
        piece = pieces[chunk] if chunk < len(pieces) else text
        return piece[:EXCERPT_CHARS], place_of(text, chunk, MOST_CHUNKS[kind])

    def forget(self, kind: str, ref: str) -> None:
        self.stores[kind].forget(ref)


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
    for store in current.stores.values():
        store.drop_model(model.id)
    current.queue_for = None
    current.errors.pop(model.id, None)
    current.announce(force=True)
    return current.status()


@semantic_module.command("semantic.setActive")
def set_active(command: ModelName, ctx: Context) -> SemanticStatus:
    current = _started()
    if command.id not in BY_ID:
        raise CommandError("model.unknown", "That model isn't available.", 404)
    current.save_settings(active=command.id)
    current.queue_for = None
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
        _engine.stale_queue = True
        _engine.wake.set()


@semantic_module.query("semantic.detect")
def detect(query: DetectModels, ctx: Context) -> ModelDetection:
    """What this computer already has and can manage, so the person only has to say yes or no."""
    current = _started()
    source = current.settings()["mirror"] or ctx.config.model_hub
    here = [model.id for model in MODELS if downloader.is_complete(ctx.config.home, model)]
    memory = psutil.virtual_memory().total
    free = shutil.disk_usage(ctx.config.home).free
    biggest = MODELS[0]
    reachable = _hub_answers(source, biggest)
    if here:
        recommended, reason = here[0], "already_here"
    elif memory < SMALL_MODEL_BELOW_BYTES or free < biggest.size + ctx.config.min_free_bytes:
        recommended, reason = MODELS[-1].id, "small_computer"
    else:
        recommended, reason = biggest.id, "best"
    return ModelDetection(
        on_this_computer=here,
        recommended=recommended,
        reason=reason,
        reachable=reachable,
        memory_bytes=memory,
        free_bytes=free,
        cores=os.cpu_count() or 1,
    )


def _hub_answers(source: str, model: CatalogModel) -> bool:
    try:
        response = httpx.head(
            catalog.url(model, model.files[1], source),
            timeout=HUB_CHECK_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return False
    return response.status_code < 500


@semantic_module.command("semantic.rebuild")
def rebuild_index(command: RebuildIndex, ctx: Context) -> SemanticStatus:
    current = _started()
    current.rebuild(command.kind)
    return current.status()
