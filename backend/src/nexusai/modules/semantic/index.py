"""Vectors in their own encrypted file for each kind of thing, searched from memory.

A plain scan is fast at this size. These can always be rebuilt from mail and documents, so they
stay out of backups, and rebuilding one kind leaves the other alone.
"""

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nexusai.kernel.database import Database, Migration
from nexusai.modules.semantic.catalog import DIMENSIONS

BLOCK = 8192
SCALE = 127.0
FOLDER = "index"
MIGRATION = Migration(
    "index_001",
    """
CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL, ref TEXT NOT NULL, chunk INTEGER NOT NULL, vector BLOB NOT NULL);
CREATE INDEX chunks_ref ON chunks (model, ref);
CREATE TABLE done (model TEXT NOT NULL, ref TEXT NOT NULL, fingerprint TEXT NOT NULL, PRIMARY KEY (model, ref));
CREATE INDEX done_fingerprint ON done (model, fingerprint);
CREATE TABLE manifest (fingerprint TEXT PRIMARY KEY, model TEXT NOT NULL, details TEXT NOT NULL, created TEXT NOT NULL);
""",
)


def to_bytes(vector: NDArray[np.float32]) -> bytes:
    """One byte per value: a quarter of the space, and close enough for ranking."""
    return bytes(np.clip(np.round(vector * SCALE), -127, 127).astype(np.int8).tobytes())


@dataclass(frozen=True)
class Found:
    kind: str
    ref: str
    chunk: int
    score: float


class IndexStore:
    """One kind of thing, in one file. It has its own connection, and so its own single writer."""

    def __init__(self, home: Path, kind: str, key: str | None) -> None:
        self.kind = kind
        self.db = Database(home / "system" / FOLDER / f"{kind}.db", key)
        self.db.migrate([MIGRATION])
        self.vectors: dict[str, VectorIndex] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        self.db.close()

    def vector_index(self, model: str) -> "VectorIndex":
        with self.lock:
            found = self.vectors.get(model)
            if found is None:
                found = VectorIndex(self.db, self.kind, model)
                self.vectors[model] = found
            return found

    def done_refs(self, model: str) -> set[str]:
        rows = self.db.fetch_all("SELECT ref FROM done WHERE model = ?", (model,))
        return {row["ref"] for row in rows}

    def record_version(self, fingerprint: str, model: str, details: dict[str, Any]) -> None:
        """What was used to build these vectors, kept for as long as any of them are here."""
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT OR IGNORE INTO manifest (fingerprint, model, details, created) VALUES (?, ?, ?, ?)",
                (fingerprint, model, json.dumps(details), datetime.now(UTC).isoformat()),
            )

    def write(
        self,
        model: str,
        fingerprint: str,
        refs: Iterable[str],
        chunks: list[tuple[str, int, bytes]],
    ) -> None:
        with self.db.transaction() as tx:
            for ref, chunk, vector in chunks:
                tx.execute(
                    "INSERT INTO chunks (model, ref, chunk, vector) VALUES (?, ?, ?, ?)",
                    (model, ref, chunk, vector),
                )
            for ref in refs:
                tx.execute(
                    "INSERT OR REPLACE INTO done (model, ref, fingerprint) VALUES (?, ?, ?)",
                    (model, ref, fingerprint),
                )
        index = self.vector_index(model)
        for ref, chunk, vector in chunks:
            index.added(ref, chunk, vector)

    def counts(self, model: str, fingerprint: str) -> tuple[int, int]:
        rows = self.db.fetch_all(
            "SELECT COUNT(*) AS done, COALESCE(SUM(fingerprint != ?), 0) AS stale FROM done WHERE model = ?",
            (fingerprint, model),
        )
        return int(rows[0]["done"]), int(rows[0]["stale"])

    def version(self, fingerprint: str) -> tuple[dict[str, Any], str] | None:
        rows = self.db.fetch_all(
            "SELECT details, created FROM manifest WHERE fingerprint = ?", (fingerprint,)
        )
        return (json.loads(rows[0]["details"]), rows[0]["created"]) if rows else None

    def forget(self, ref: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM chunks WHERE ref = ?", (ref,))
            tx.execute("DELETE FROM done WHERE ref = ?", (ref,))
        self._read_again()

    def forget_many(self, refs: Iterable[str]) -> int:
        count = 0
        with self.db.transaction() as tx:
            for ref in refs:
                count += tx.execute("DELETE FROM chunks WHERE ref = ?", (ref,)).rowcount
                tx.execute("DELETE FROM done WHERE ref = ?", (ref,))
        if count:
            self._read_again()
        return count

    def drop_model(self, model: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM chunks WHERE model = ?", (model,))
            tx.execute("DELETE FROM done WHERE model = ?", (model,))
            tx.execute("DELETE FROM manifest WHERE model = ?", (model,))
        with self.lock:
            self.vectors.pop(model, None)

    def _read_again(self) -> None:
        with self.lock:
            indexes = list(self.vectors.values())
        for index in indexes:
            index.forget()


class VectorIndex:
    """Loaded on the first search, then kept in step as new vectors are written."""

    def __init__(self, db: Database, kind: str, model: str) -> None:
        self.db = db
        self.kind = kind
        self.model = model
        self.lock = threading.Lock()
        self.vectors: NDArray[np.int8] | None = None
        self.rows: list[tuple[str, int]] = []
        self.pending: list[tuple[str, int, bytes]] = []

    def _load(self) -> None:
        rows = self.db.fetch_all(
            "SELECT ref, chunk, vector FROM chunks WHERE model = ?", (self.model,)
        )
        self.rows = [(r["ref"], r["chunk"]) for r in rows]
        joined = b"".join(r["vector"] for r in rows)
        self.vectors = np.frombuffer(joined, dtype=np.int8).reshape(-1, DIMENSIONS)
        self.pending = []

    def added(self, ref: str, chunk: int, vector: bytes) -> None:
        with self.lock:
            if self.vectors is not None:
                self.pending.append((ref, chunk, vector))

    def forget(self) -> None:
        """Something was removed. The next search reads what's left."""
        with self.lock:
            self.vectors = None

    def _absorb(self) -> None:
        if not self.pending or self.vectors is None:
            return
        extra = np.frombuffer(b"".join(p[2] for p in self.pending), dtype=np.int8)
        self.vectors = np.concatenate([self.vectors, extra.reshape(-1, DIMENSIONS)])
        self.rows.extend((p[0], p[1]) for p in self.pending)
        self.pending = []

    def search(self, query: NDArray[np.float32], limit: int) -> list[Found]:
        with self.lock:
            if self.vectors is None:
                self._load()
            self._absorb()
            vectors, rows = self.vectors, self.rows
        if vectors is None or not len(vectors):
            return []
        scores = np.empty(len(vectors), dtype=np.float32)
        # In blocks, so a large mailbox never needs a full-size copy in memory.
        for start in range(0, len(vectors), BLOCK):
            scores[start : start + BLOCK] = (
                vectors[start : start + BLOCK].astype(np.float32) @ query
            ) / SCALE
        order = np.argsort(-scores)
        best: dict[str, Found] = {}
        for position in order:
            ref, chunk = rows[int(position)]
            if ref not in best:
                best[ref] = Found(self.kind, ref, chunk, float(scores[int(position)]))
                if len(best) >= limit:
                    break
        return list(best.values())
