import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from sqlcipher3 import dbapi2 as sqlcipher

# What a database that isn't encrypted starts with.
PLAIN_HEADER = b"SQLite format 3\0"
RAW_KEY = re.compile(r"^[0-9a-f]{64}$")


class DatabaseDamaged(Exception):
    """The file isn't a readable database, so it needs restoring from a backup."""


class DatabaseTooNew(Exception):
    """An older application must not open a database migrated by a newer one."""


def key_pragma(key: str) -> str:
    """SQL can't take a pragma's value as a parameter, so only an exact key shape gets through."""
    if not RAW_KEY.match(key):
        raise ValueError("Not a database key")
    return f"\"x'{key}'\""


def connect_raw(path: Path, key: str | None, **options: Any) -> sqlite3.Connection:
    """SQLCipher speaks the same API as sqlite3, so its connection is typed as one."""
    connection = sqlcipher.connect(str(path), check_same_thread=False, **options)
    if key:
        connection.execute(f"PRAGMA key = {key_pragma(key)}")
    return cast(sqlite3.Connection, connection)


class StandardErrorsConnection(sqlcipher.Connection):
    """For libraries that catch sqlite3's errors by class, which SQLCipher's aren't."""

    def execute(self, *args: Any) -> Any:
        try:
            return super().execute(*args)
        except sqlcipher.OperationalError as error:
            raise sqlite3.OperationalError(str(error)) from error


class Migration:
    def __init__(self, id: str, sql: str) -> None:
        self.id = id
        self.sql = sql


class Database:
    """The app's only connection, and so its only writer. Calls are serialized by a lock."""

    def __init__(self, path: Path, key: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = connect_raw(path, key, isolation_level=None)
        self._conn.row_factory = cast(Any, sqlcipher.Row)
        self._lock = threading.RLock()
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS migrations ("
                "id TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))"
            )
        except sqlcipher.OperationalError:
            self._conn.close()
            raise
        except sqlcipher.DatabaseError as error:
            self._conn.close()
            raise DatabaseDamaged(str(error)) from error

    def check(self) -> None:
        """Slow on a large database, so it's for after an unclean exit."""
        try:
            result = self.fetch_all("PRAGMA quick_check(1)")[0][0]
        except sqlcipher.OperationalError:
            raise
        except sqlcipher.DatabaseError as error:
            raise DatabaseDamaged(str(error)) from error
        if result != "ok":
            raise DatabaseDamaged(str(result))

    def pending(self, migrations: Sequence[Migration]) -> bool:
        """Whether this database has data that an upgrade is about to change."""
        applied = {row["id"] for row in self.fetch_all("SELECT id FROM migrations")}
        return bool(applied) and any(migration.id not in applied for migration in migrations)

    def require_compatible(
        self, migrations: Sequence[Migration], markers: Sequence[str] = ()
    ) -> None:
        known = {migration.id for migration in migrations} | set(markers)
        applied = {row["id"] for row in self.fetch_all("SELECT id FROM migrations")}
        if applied - known:
            raise DatabaseTooNew(
                "This workspace was updated by a newer NexusAI. Install that version or newer "
                "to open it. Your data has not been migrated or reset."
            )

    def migrate(self, migrations: Sequence[Migration]) -> None:
        with self._lock:
            applied = {row["id"] for row in self._conn.execute("SELECT id FROM migrations")}
            for migration in migrations:
                if migration.id not in applied:
                    with self.transaction() as tx:
                        statement = ""
                        for fragment in migration.sql.split(";"):
                            statement += fragment + ";"
                            if sqlite3.complete_statement(statement):
                                if statement.strip("; \n\t"):
                                    tx.execute(statement)
                                statement = ""
                        if statement.strip("; \n\t"):
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

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Keep a read/validate/write sequence together across existing transactions."""
        with self._lock:
            yield

    def fetch_all(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
