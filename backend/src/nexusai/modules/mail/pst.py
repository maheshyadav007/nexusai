"""Brings PST archives in the background, with pause and resume. No model ever reads them."""

import json
import subprocess
import sys
import threading
from dataclasses import dataclass

import structlog

from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context
from nexusai.modules.mail import accounts, store
from nexusai.modules.mail.parse import Part, parse_message
from nexusai.modules.mail.rules import evaluate, load_rules

log = structlog.get_logger()
MIGRATION = Migration(
    "mail_002",
    """
CREATE TABLE pst_imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
  total INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,
  duplicates INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE pst_messages (message INTEGER PRIMARY KEY, import_id INTEGER NOT NULL, folder TEXT NOT NULL, item INTEGER NOT NULL);
""",
)
UID_SPACE = 10_000_000
BATCH = 200
# PST attachments aren't copied: this marks the part numbers that read from the PST on demand.
PST_PART_OFFSET = 100_000
_stderr_limit = 500


def worker_command(path: str, start: int) -> list[str]:
    return [sys.executable, "-m", "nexusai.modules.mail.pst_worker", path, str(start)]


@dataclass
class _Running:
    import_id: int
    process: subprocess.Popen[str]
    pausing: bool = False


class PstRunner:
    """One import at a time, in order, so several large archives don't compete."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: _Running | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False

    def kick(self, ctx: Context) -> None:
        with self._lock:
            self._stopping = False
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._drain, args=(ctx,), daemon=True, name="pst"
            )
            self._thread.start()

    def pause(self, import_id: int) -> bool:
        with self._lock:
            if self._current and self._current.import_id == import_id:
                self._current.pausing = True
                self._current.process.terminate()
                return True
        return False

    def stop(self) -> None:
        """The app is closing. The import stays marked as running, so it continues on next start."""
        with self._lock:
            self._stopping = True
            current, thread = self._current, self._thread
            if current:
                current.process.terminate()
        if thread:
            thread.join(timeout=10)

    def _drain(self, ctx: Context) -> None:
        while not self._stopping:
            rows = ctx.bus.db.fetch_all(
                "SELECT * FROM pst_imports WHERE status IN ('queued', 'running') ORDER BY id LIMIT 1"
            )
            if not rows:
                return
            try:
                self._run_one(ctx, dict(rows[0]))
            except Exception:
                log.exception("pst_import_failed", import_id=rows[0]["id"])
                _set_status(
                    ctx, rows[0]["id"], "failed", "The import hit a problem. You can try again."
                )

    def _run_one(self, ctx: Context, job: dict[str, object]) -> None:
        import_id = int(str(job["id"]))
        _set_status(ctx, import_id, "running", None)
        process = subprocess.Popen(
            worker_command(str(job["path"]), int(str(job["position"]))),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        with self._lock:
            self._current = _Running(import_id, process)
        finished = False
        batch: list[dict[str, object]] = []
        assert process.stdout is not None
        for line in process.stdout:
            record = json.loads(line)
            if "total" in record:
                with ctx.bus.db.transaction() as tx:
                    tx.execute(
                        "UPDATE pst_imports SET total = ? WHERE id = ?",
                        (record["total"], import_id),
                    )
                continue
            if "finished" in record:
                finished = True
                break
            batch.append(record)
            if len(batch) >= BATCH:
                _store_batch(ctx, import_id, batch)
                batch = []
        if batch:
            _store_batch(ctx, import_id, batch)
        process.wait()
        with self._lock:
            pausing = self._current.pausing if self._current else False
            self._current = None
        if self._stopping:
            return
        if pausing:
            _set_status(ctx, import_id, "paused", None)
        elif finished:
            _set_status(ctx, import_id, "done", None)
        else:
            detail = process.stderr.read()[-_stderr_limit:] if process.stderr else ""
            log.warning("pst_worker_stopped", code=process.returncode, detail=detail)
            message = "NexusAI couldn't read this file. Check that it's a PST archive and isn't open in Outlook."
            _set_status(ctx, import_id, "failed", message)


def _set_status(ctx: Context, import_id: int, status: str, error: str | None) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE pst_imports SET status = ?, error = ? WHERE id = ?", (status, error, import_id)
        )
        work.emit(
            "pst.progress",
            {"id": import_id, "status": status},
            source="mail",
            trace_id=ctx.trace_id,
        )


def _store_batch(ctx: Context, import_id: int, batch: list[dict[str, object]]) -> None:
    account = accounts.current_account(ctx.config)
    rules = load_rules(ctx.config.home)
    prepared = []
    failed = 0
    for record in batch:
        if "raw" not in record:
            failed += 1
            continue
        raw = bytes.fromhex(str(record["raw"]))
        try:
            parsed = parse_message(raw)
        except Exception:
            failed += 1
            continue
        for attachment in record.get("attachments") or []:  # type: ignore[attr-defined]
            parsed.parts.append(
                Part(
                    index=PST_PART_OFFSET + int(attachment["index"]),
                    filename=str(attachment["name"]),
                    content_type="application/octet-stream",
                    size=int(attachment["size"]),
                    content_id=None,
                    disposition="attachment",
                    sha256="",
                )
            )
        prepared.append((record, raw, parsed, evaluate(parsed, rules)))
    imported = duplicates = 0
    with ctx.bus.unit_of_work() as work:
        for record, raw, parsed, match in prepared:
            # Mail already here from the server stays as it is. The archive only adds what's missing.
            exists = work.tx.execute(
                "SELECT 1 FROM messages WHERE account = ? AND message_id = ? LIMIT 1",
                (account, parsed.message_id),
            ).fetchone()
            if exists:
                duplicates += 1
                continue
            stored = store.store_message(
                work.tx,
                account=account,
                folder=f"pst:{import_id}:{record['folder']}",
                role="archive",
                uid=import_id * UID_SPACE + int(str(record["seq"])),
                raw=raw,
                read=True,
                flagged=False,
                parsed=parsed,
                match=match,
                config=ctx.config.mail,
            )
            if stored:
                imported += 1
                work.tx.execute(
                    "INSERT INTO pst_messages (message, import_id, folder, item) VALUES (?, ?, ?, ?)",
                    (stored.message, import_id, record["folder"], record["index"]),
                )
        # The position saves with the mail, so a stop at any moment resumes exactly here.
        work.tx.execute(
            "UPDATE pst_imports SET position = ?, imported = imported + ?, duplicates = duplicates + ?,"
            " failed = failed + ? WHERE id = ?",
            (int(str(batch[-1]["seq"])) + 1, imported, duplicates, failed, import_id),
        )
        work.emit(
            "pst.progress",
            {"id": import_id, "status": "running"},
            source="mail",
            trace_id=ctx.trace_id,
        )
        if imported:
            work.emit(
                "mail.changed",
                {"threads": imported, "reason": "archive"},
                source="mail",
                trace_id=ctx.trace_id,
            )


runner = PstRunner()
