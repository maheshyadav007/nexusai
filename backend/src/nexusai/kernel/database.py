import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


class Migration:
    def __init__(self, id: str, sql: str) -> None:
        self.id = id
        self.sql = sql


class Database:
    """The app's only connection, and so its only writer. Calls are serialized by a lock."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS migrations ("
            "id TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))"
        )

    def migrate(self, migrations: Sequence[Migration]) -> None:
        with self._lock:
            applied = {row["id"] for row in self._conn.execute("SELECT id FROM migrations")}
            for migration in migrations:
                if migration.id not in applied:
                    with self.transaction() as tx:
                        for statement in migration.sql.split(";"):
                            if statement.strip():
                                tx.execute(statement)
                        tx.execute("INSERT INTO migrations (id) VALUES (?)", (migration.id,))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def fetch_all(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
