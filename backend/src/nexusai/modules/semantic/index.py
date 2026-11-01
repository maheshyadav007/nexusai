"""Vectors in the encrypted database, searched from memory. A plain scan is fast at this size."""

import threading
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from nexusai.kernel.database import Database
from nexusai.modules.semantic.catalog import DIMENSIONS

BLOCK = 8192
SCALE = 127.0


def to_bytes(vector: NDArray[np.float32]) -> bytes:
    """One byte per value: a quarter of the space, and close enough for ranking."""
    return bytes(np.clip(np.round(vector * SCALE), -127, 127).astype(np.int8).tobytes())


@dataclass(frozen=True)
class Found:
    kind: str
    ref: str
    chunk: int
    score: float


class VectorIndex:
    """Loaded on the first search, then kept in step as new vectors are written."""

    def __init__(self, db: Database, model: str) -> None:
        self.db = db
        self.model = model
        self.lock = threading.Lock()
        self.vectors: NDArray[np.int8] | None = None
        self.rows: list[tuple[str, str, int]] = []
        self.pending: list[tuple[str, str, int, bytes]] = []

    def _load(self) -> None:
        rows = self.db.fetch_all(
            "SELECT kind, ref, chunk, vector FROM semantic_chunks WHERE model = ?", (self.model,)
        )
        self.rows = [(r["kind"], r["ref"], r["chunk"]) for r in rows]
        joined = b"".join(r["vector"] for r in rows)
        self.vectors = np.frombuffer(joined, dtype=np.int8).reshape(-1, DIMENSIONS)
        self.pending = []

    def added(self, kind: str, ref: str, chunk: int, vector: bytes) -> None:
        with self.lock:
            if self.vectors is not None:
                self.pending.append((kind, ref, chunk, vector))

    def forget(self) -> None:
        """Something was removed. The next search reads what's left."""
        with self.lock:
            self.vectors = None

    def _absorb(self) -> None:
        if not self.pending or self.vectors is None:
            return
        extra = np.frombuffer(b"".join(p[3] for p in self.pending), dtype=np.int8)
        self.vectors = np.concatenate([self.vectors, extra.reshape(-1, DIMENSIONS)])
        self.rows.extend((p[0], p[1], p[2]) for p in self.pending)
        self.pending = []

    def search(self, query: NDArray[np.float32], kinds: set[str], limit: int) -> list[Found]:
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
        best: dict[tuple[str, str], Found] = {}
        for position in order:
            kind, ref, chunk = rows[int(position)]
            if kind in kinds and (kind, ref) not in best:
                best[(kind, ref)] = Found(kind, ref, chunk, float(scores[int(position)]))
                if len(best) >= limit:
                    break
        return list(best.values())
