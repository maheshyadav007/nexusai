import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import RUNNING_FILE, create_app
from nexusai.kernel import backups, vault
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database, DatabaseDamaged, key_pragma
from nexusai.kernel.secrets import secret_store

KEY = "ab" * 32


@contextmanager
def running(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:8765") as client:
        yield client


def status(client: TestClient) -> dict[str, str]:
    result: dict[str, str] = client.post("/api/home/status").json()
    return result


def save_theme(client: TestClient) -> None:
    done = client.post("/api/commands/settings.update", json={"theme": "nexus-dark"})
    assert done.status_code == 200


def theme(client: TestClient) -> str:
    result: str = client.post("/api/queries/settings.get").json()["theme"]
    return result


def forget_key(config: Config) -> None:
    """What a new computer looks like: the Home is there, and the secure store is empty."""
    assert config.secrets_test_file
    config.secrets_test_file.unlink()


def recovery_key(client: TestClient) -> str:
    pending: str = client.post("/api/home/recovery-key").json()["pending"]
    return pending


def test_data_on_disk_is_encrypted_and_opens_again(config: Config) -> None:
    with running(config) as client:
        save_theme(client)
        client.post("/api/commands/session.create", json={})
    system = config.home / "system"
    for name in ["nexusai.db", "checkpoints.db"]:
        assert not (system / name).read_bytes().startswith(b"SQLite format 3")
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(system / "nexusai.db").execute("SELECT * FROM sqlite_master").fetchall()
    with running(config) as client:
        assert theme(client) == "nexus-dark"


def test_a_new_computer_needs_the_recovery_key(config: Config) -> None:
    with running(config) as client:
        save_theme(client)
        key = recovery_key(client)
    # The Home folder alone gives no way in: nothing in it holds the key in the clear.
    data_key = json.loads(Path(str(config.secrets_test_file)).read_text())
    forget_key(config)
    contents = (config.home / "system" / "vault.json").read_text()
    assert key not in contents
    assert all(value not in contents for value in data_key.values())

    with running(config) as client:
        assert status(client)["state"] == "locked"
        assert client.post("/api/queries/settings.get").status_code == 409
        wrong = client.post("/api/home/unlock", json={"recovery_key": "AAAA-BBBB"})
        assert (wrong.status_code, wrong.json()["code"]) == (422, "home.wrong_key")
        assert status(client)["state"] == "locked"
        # People retype these, so case, spaces and misread letters don't matter.
        typed = key.lower().replace("-", " ")
        assert (
            client.post("/api/home/unlock", json={"recovery_key": typed}).json()["state"] == "ready"
        )
        assert theme(client) == "nexus-dark"
    with running(config) as client:
        assert status(client)["state"] == "ready"


def test_the_recovery_key_shows_until_saved_and_a_new_one_replaces_it(config: Config) -> None:
    with running(config) as client:
        first = recovery_key(client)
        assert len(first.replace("-", "")) == vault.RECOVERY_CHARS
        assert recovery_key(client) == first
        client.post("/api/home/recovery-key/confirm")
        assert client.post("/api/home/recovery-key").json()["pending"] is None

        second = client.post("/api/home/recovery-key/new").json()["pending"]
        assert second != first
    forget_key(config)
    with running(config) as client:
        old = client.post("/api/home/unlock", json={"recovery_key": first})
        assert old.status_code == 422
        new = client.post("/api/home/unlock", json={"recovery_key": second})
        assert new.json()["state"] == "ready"


def test_a_home_from_before_encryption_is_converted_with_its_data(config: Config) -> None:
    system = config.home / "system"
    system.mkdir(parents=True)
    (config.home / "home.json").write_text(json.dumps({"version": 1}))
    plain = Database(system / "nexusai.db")
    with plain.transaction() as tx:
        tx.execute("CREATE TABLE old_data (text TEXT)")
        tx.execute("INSERT INTO old_data VALUES ('kept')")
        tx.execute("CREATE VIRTUAL TABLE old_search USING fts5(body)")
        tx.execute("INSERT INTO old_search VALUES ('needle in the mail')")
    plain.close()
    assert (system / "nexusai.db").read_bytes().startswith(b"SQLite format 3")

    with running(config) as client:
        assert status(client)["state"] == "ready"
        items = client.post("/api/queries/notifications.list", json={}).json()["items"]
        assert any(item["kind"] == "recovery-key" for item in items)
        assert recovery_key(client)
    assert not (system / "nexusai.db").read_bytes().startswith(b"SQLite format 3")
    assert not list(system.glob("*.encrypting"))

    store = secret_store(config.secrets_test_file)
    converted = Database(system / "nexusai.db", vault.open_key(config.home, store))
    assert converted.fetch_all("SELECT text FROM old_data")[0][0] == "kept"
    assert len(converted.fetch_all("SELECT 1 FROM old_search WHERE old_search MATCH 'needle'")) == 1
    converted.close()


def test_a_damaged_database_can_be_restored_and_the_bad_file_is_kept(config: Config) -> None:
    with running(config) as client:
        save_theme(client)
    home = config.home
    assert backups.create(home, "daily", 3)
    database = home / "system" / "nexusai.db"
    database.write_bytes(b"\0" * 8192)
    (home / "system" / "nexusai.db-wal").unlink(missing_ok=True)
    (home / "system" / "nexusai.db-shm").unlink(missing_ok=True)

    with running(config) as client:
        assert status(client)["state"] == "damaged"
        assert client.post("/api/queries/settings.get").status_code == 409
        names = [row["name"] for row in client.post("/api/home/backups").json()["backups"]]
        assert names
        missing = client.post("/api/home/restore", json={"name": "../../evil"})
        assert missing.status_code == 404
        restored = client.post("/api/home/restore", json={"name": names[0]})
        assert restored.json()["state"] == "ready"
        assert theme(client) == "nexus-dark"
    aside = list((home / "system").glob("damaged-*/nexusai.db"))
    assert len(aside) == 1
    assert aside[0].read_bytes() == b"\0" * 8192


def test_restore_is_refused_while_the_home_is_fine(config: Config) -> None:
    with running(config) as client:
        response = client.post("/api/home/restore", json={"name": "20300101-000000-000000-daily"})
        assert response.status_code == 409


def test_an_unclean_exit_checks_the_database_and_a_clean_one_does_not(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[int] = []
    original = Database.check
    monkeypatch.setattr(Database, "check", lambda self: (checks.append(1), original(self))[1])
    with running(config):
        assert (config.home / "system" / RUNNING_FILE).exists()
    assert not (config.home / "system" / RUNNING_FILE).exists()
    with running(config):
        pass
    assert checks == []
    (config.home / "system" / RUNNING_FILE).touch()
    with running(config) as client:
        assert status(client)["state"] == "ready"
    assert checks == [1]


def test_backups_are_taken_before_an_upgrade_and_old_ones_go(config: Config) -> None:
    with running(config):
        pass
    home = config.home
    assert all(b.reason == "daily" for b in backups.listing(home))
    key = vault.open_key(home, secret_store(config.secrets_test_file))
    with_key = Database(home / "system" / "nexusai.db", key)
    with with_key.transaction() as tx:
        # An older version hadn't run this one yet.
        tx.execute("DELETE FROM migrations WHERE id = 'agent_gateway_run_limits_001'")
        tx.execute("DROP TABLE model_run_limits")
    with_key.close()
    with running(config) as client:
        assert status(client)["state"] == "ready"
    assert backups.listing(home)[0].reason == "upgrade"

    for _ in range(5):
        backups.create(home, "daily", config.backups_kept)
    assert len(backups.listing(home)) == config.backups_kept


def test_a_backup_is_skipped_when_the_drive_is_nearly_full(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running(config):
        pass
    usage = type("Usage", (), {"free": 0})
    monkeypatch.setattr(backups.shutil, "disk_usage", lambda _: usage)
    assert backups.create(config.home, "daily", 3) is None


def test_a_wrong_or_unsafe_key_never_reaches_sql(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Not a database key"):
        key_pragma("x'; DROP TABLE y; --")
    Database(tmp_path / "a.db", KEY).close()
    with pytest.raises(DatabaseDamaged):
        Database(tmp_path / "a.db", "cd" * 32)


def test_config_never_prints_the_key(config: Config) -> None:
    assert KEY not in repr(replace(config, database_key=KEY))
