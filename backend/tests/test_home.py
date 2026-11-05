import json
import os
import stat
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.errors import NoKeyringError

from nexusai.api.app import create_app
from nexusai.kernel import home as homes
from nexusai.kernel.config import Config
from nexusai.kernel.secrets import SECRETS_FILE, LocalStore
from nexusai.modules.agent import prompts_builder, tools


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "app-data"
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(path))
    return path


@pytest.fixture
def unset_client(config: Config, data_dir: Path) -> Iterator[TestClient]:
    app = create_app(replace(config, home_dir=None))
    with TestClient(app, base_url="http://127.0.0.1:4100") as client:
        yield client


def status(client: TestClient) -> dict[str, str]:
    return client.post("/api/home/status").json()


def test_first_run_has_no_home_and_nothing_else_works(unset_client: TestClient) -> None:
    assert status(unset_client)["state"] == "unset"
    assert unset_client.get("/api/health").json()["home"] == "unset"
    refused = unset_client.post("/api/queries/settings.get")
    assert refused.status_code == 409
    assert refused.json()["code"] == "home.not_ready"


def test_choosing_creates_the_layout_and_opens_the_app(
    unset_client: TestClient, tmp_path: Path, data_dir: Path
) -> None:
    target = tmp_path / "MyHome"
    chosen = unset_client.post("/api/home/choose", json={"path": str(target)})
    assert chosen.json()["state"] == "ready"
    assert {p.name for p in target.iterdir()} >= {"home.json", *homes.SUBFOLDERS}
    assert (target / "system" / "nexusai.db").exists()
    assert json.loads((data_dir / "home-pointer.json").read_text())["path"] == str(target.resolve())
    assert unset_client.post("/api/queries/settings.get").status_code == 200


def test_restart_reopens_the_chosen_home(config: Config, tmp_path: Path, data_dir: Path) -> None:
    target = tmp_path / "MyHome"
    app_config = replace(config, home_dir=None)
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:4100") as first:
        first.post("/api/home/choose", json={"path": str(target)})
        first.post("/api/commands/settings.update", json={"theme": "nexus-dark"})
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:4100") as second:
        assert status(second)["state"] == "ready"
        assert second.post("/api/queries/settings.get").json()["theme"] == "nexus-dark"


def test_missing_home_is_reported_and_never_recreated(
    config: Config, tmp_path: Path, data_dir: Path
) -> None:
    gone = tmp_path / "Gone"
    homes.write_pointer(data_dir, gone)
    with TestClient(
        create_app(replace(config, home_dir=None)), base_url="http://127.0.0.1:4100"
    ) as client:
        current = status(client)
        assert current["state"] == "missing"
        assert current["path"] == str(gone)
        assert not gone.exists()


def test_locating_requires_a_real_home(config: Config, tmp_path: Path, data_dir: Path) -> None:
    homes.write_pointer(data_dir, tmp_path / "Gone")
    plain = tmp_path / "plain"
    plain.mkdir()
    moved = tmp_path / "Moved"
    homes.create_home(moved)
    with TestClient(
        create_app(replace(config, home_dir=None)), base_url="http://127.0.0.1:4100"
    ) as client:
        refused = client.post("/api/home/choose", json={"path": str(plain), "must_exist": True})
        assert refused.status_code == 422
        assert refused.json()["code"] == "home.not_found"
        assert not (plain / "home.json").exists()
        located = client.post("/api/home/choose", json={"path": str(moved), "must_exist": True})
        assert located.json()["state"] == "ready"


def test_a_home_from_a_newer_app_is_refused(tmp_path: Path) -> None:
    newer = tmp_path / "Newer"
    newer.mkdir()
    (newer / "home.json").write_text(json.dumps({"format_version": 999, "id": "x"}))
    check = homes.check_folder(str(newer), 0)
    assert not check.ok
    assert "newer" in check.problems[0]


@pytest.mark.skipif(sys.platform == "win32", reason="Needs symlinks or POSIX file modes")
def test_check_blocks_files_and_unwritable_folders(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("x")
    assert not homes.check_folder(str(file), 0).ok
    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        assert not homes.check_folder(str(locked / "child"), 0).ok
    finally:
        os.chmod(locked, 0o700)


def test_check_blocks_network_drives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(homes, "_is_network_path", lambda _: True)
    assert "network drive" in homes.check_folder(str(tmp_path), 0).problems[0]


@pytest.mark.parametrize(
    "path",
    ["Library/Mobile Documents/com~apple~CloudDocs/N", "OneDrive/N", "Desktop/N", "Documents/N"],
)
def test_check_warns_on_cloud_synced_folders(
    path: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    check = homes.check_folder(str(tmp_path / path), 0)
    assert check.ok
    assert any("cloud" in warning for warning in check.warnings)


def test_default_location_has_no_cloud_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert homes.check_folder(str(tmp_path / "NexusAI"), 0).warnings == []


def test_check_warns_on_low_space(tmp_path: Path) -> None:
    assert any("free" in w for w in homes.check_folder(str(tmp_path), 10**18).warnings)


def test_browse_lists_folders_without_hidden_ones(tmp_path: Path) -> None:
    (tmp_path / "Beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    listing = homes.browse(str(tmp_path))
    assert listing.folders == ["alpha", "Beta"]
    assert listing.parent == str(tmp_path.resolve().parent)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "Home"
    homes.create_home(path)
    return path


@pytest.mark.parametrize("path", ["scratch/a.txt", "memory/m.md", "documents/d", "artifacts/x"])
def test_agent_may_write_to_its_folders(home: Path, path: str) -> None:
    assert homes.agent_path(home, path, write=True) == (home / path).resolve()


def test_agent_may_read_but_not_change_prompts(home: Path) -> None:
    assert homes.agent_path(home, "prompts/p.md", write=False)
    with pytest.raises(homes.PathNotAllowed):
        homes.agent_path(home, "prompts/p.md", write=True)


@pytest.mark.parametrize(
    "path",
    ["system/nexusai.db", "home.json", "scratch/../system/nexusai.db", "../outside", "/etc/passwd"],
)
@pytest.mark.parametrize("write", [True, False])
def test_agent_is_kept_out_of_everything_else(home: Path, path: str, write: bool) -> None:
    with pytest.raises(homes.PathNotAllowed):
        homes.agent_path(home, path, write=write)


@pytest.mark.skipif(sys.platform == "win32", reason="Needs symlinks or POSIX file modes")
def test_symlinks_cant_lead_out(home: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.mkdir()
    (home / "scratch" / "link").symlink_to(secret)
    (home / "scratch" / "to-system").symlink_to(home / "system")
    for path in ("scratch/link/key", "scratch/to-system/nexusai.db"):
        with pytest.raises(homes.PathNotAllowed):
            homes.agent_path(home, path, write=False)


def test_each_task_gets_its_own_scratch_folder(home: Path) -> None:
    assert homes.scratch_folder(home, "task-1") == home / "scratch" / "task-1"
    assert (home / "scratch" / "task-1").is_dir()
    with pytest.raises(homes.PathNotAllowed):
        homes.scratch_folder(home, "../escape")


@pytest.mark.skipif(sys.platform == "win32", reason="Permissions work differently")
def test_a_locked_folder_gets_a_reason_and_a_way_back_out(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        listing = homes.browse(str(locked))
        assert listing.problem and listing.folders == [] and listing.parent == str(tmp_path)
        assert homes.browse(str(locked / "inside")).path in {str(locked), str(tmp_path)}
        assert not homes.check_folder(str(locked), 0).ok
        assert not homes.check_folder(str(locked / "inside"), 0).ok
    finally:
        locked.chmod(0o755)


def test_a_name_that_isnt_text_doesnt_stop_the_rest_of_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fine").mkdir()
    real = homes.os.scandir

    class Odd:
        name = "bad\udcff"

        def is_dir(self) -> bool:
            return True

    class Listing:
        def __init__(self, path: Path) -> None:
            self.entries = [*real(path), Odd()]

        def __enter__(self) -> list[object]:
            return self.entries

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(homes.os, "scandir", Listing)
    listing = homes.browse(str(tmp_path))
    assert listing.folders == ["fine"]
    listing.model_dump_json()


def test_a_folder_can_be_made_here_and_only_here(tmp_path: Path) -> None:
    made = homes.create_folder(str(tmp_path), " NexusAI ")
    assert made.path == str((tmp_path / "NexusAI").resolve())
    assert (tmp_path / "NexusAI").is_dir()
    assert homes.create_folder(str(tmp_path), "NexusAI").path == made.path
    for bad in ("..", ".", "a/b", "../out", "a\\b", "x\0y"):
        with pytest.raises(homes.HomeError):
            homes.create_folder(str(tmp_path), bad)
    assert not (tmp_path.parent / "out").exists()
    (tmp_path / "taken").write_text("x")
    with pytest.raises(homes.HomeError):
        homes.create_folder(str(tmp_path), "taken")


def test_the_current_folder_and_home_can_be_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert homes.browse(".").path == str(tmp_path.resolve())
    assert homes.browse("~").path == str(Path.home())


def test_a_home_opens_with_no_keyring_on_the_computer(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_: object, **__: object) -> None:
        raise NoKeyringError("none")

    monkeypatch.setattr(keyring, "get_password", missing)
    monkeypatch.setattr(keyring, "set_password", missing)
    monkeypatch.setattr(keyring, "delete_password", missing)
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(tmp_path / "app-data"))
    plain = replace(config, home_dir=None, secrets_test_file=None)
    with TestClient(create_app(plain), base_url="http://127.0.0.1:4100") as client:
        answer = client.post("/api/home/choose", json={"path": str(tmp_path / "Home")})
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "ready"
    saved = tmp_path / "app-data" / SECRETS_FILE
    assert saved.exists()
    if sys.platform != "win32":
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_secrets_kept_in_the_keyring_before_are_still_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = {("NexusAI", "old-key"): "from-the-keychain"}
    removed: list[str] = []
    monkeypatch.setattr(keyring, "get_password", lambda service, name: earlier.get((service, name)))
    monkeypatch.setattr(keyring, "delete_password", lambda _, name: removed.append(name))
    store = LocalStore(tmp_path / SECRETS_FILE)
    assert store.get("old-key") == "from-the-keychain"
    store.set("new-key", "here")
    assert store.get("new-key") == "here"
    store.delete("old-key")
    assert removed == ["old-key"]


def test_commands_run_in_the_shell_the_model_is_told_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise POSIX selection independently of the host (Windows may return bash.EXE).
    monkeypatch.setattr(
        prompts_builder.shutil,
        "which",
        lambda shell: shell if shell in {"/bin/sh", "bash"} else None,
    )
    monkeypatch.setenv("SHELL", "/bin/sh")
    assert tools.shell_command("ls", windows=False)[0][0] == prompts_builder.posix_shell()
    assert prompts_builder.posix_shell().endswith("sh")
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    assert Path(prompts_builder.posix_shell()).name in prompts_builder.SH_LIKE
