"""What has to hold on Windows, tested here in whatever way each can be away from a Windows machine."""

import ast
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import keyring
import psutil
import pytest
from keyring.backend import KeyringBackend

import nexusai
from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition, RuleSet
from nexusai.kernel import files
from nexusai.kernel import home as homes
from nexusai.kernel.secrets import KeyringStore
from nexusai.modules.agent import approval_view, tools
from nexusai.modules.mail import rules

WINDOWS_LIMIT_BYTES = 2560
LONG_TOKEN = "token-" + "x" * 5000


class CredentialManagerLike(KeyringBackend):
    """Refuses what Windows Credential Manager refuses."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.saved: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.saved.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if len(password.encode("utf-16-le")) > WINDOWS_LIMIT_BYTES:
            raise OSError(1783, "CredWrite", "The stub received bad data.")
        self.saved[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.saved[(service, username)]


@pytest.fixture
def vault() -> Any:
    before = keyring.get_keyring()
    backend = CredentialManagerLike()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(before)


def test_a_long_token_fits_in_the_credential_store(vault: CredentialManagerLike) -> None:
    store = KeyringStore()
    store.set("tokens", LONG_TOKEN)
    assert store.get("tokens") == LONG_TOKEN


def test_short_values_stay_one_entry_as_they_always_were(vault: CredentialManagerLike) -> None:
    store = KeyringStore()
    store.set("key", "abc")
    assert store.get("key") == "abc"
    assert list(vault.saved) == [("NexusAI", "key")]


def test_a_shorter_value_leaves_no_old_pieces_and_delete_removes_them_all(
    vault: CredentialManagerLike,
) -> None:
    store = KeyringStore()
    store.set("tokens", LONG_TOKEN)
    store.set("tokens", "x" * 1500)
    assert store.get("tokens") == "x" * 1500
    assert len(vault.saved) == 3
    store.set("tokens", "short")
    assert list(vault.saved) == [("NexusAI", "tokens")]
    store.set("tokens", LONG_TOKEN)
    store.delete("tokens")
    assert vault.saved == {}
    assert store.get("tokens") is None


def test_a_token_missing_a_piece_counts_as_gone(vault: CredentialManagerLike) -> None:
    store = KeyringStore()
    store.set("tokens", LONG_TOKEN)
    del vault.saved[("NexusAI", "tokens#1")]
    assert store.get("tokens") is None


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _waits_for_child() -> str:
    return (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )


def test_stopping_a_command_stops_what_it_started() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", _waits_for_child()],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    child = int(process.stdout.readline())
    assert _alive(child)
    tools._kill_children_too(process)
    process.wait(5)
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child)


def test_output_held_open_by_something_that_escaped_cant_hang_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "AFTER_STOP_SECONDS", 0.2)
    process = subprocess.Popen(
        [sys.executable, "-c", _waits_for_child()],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    assert process.stdout is not None
    child = process.stdout.readline()
    # Only the parent goes, as happens when one process in the family can't be found.
    process.kill()
    started = time.monotonic()
    expired = subprocess.TimeoutExpired("x", 1, output=b"so far")
    assert tools._after_stopping(process, expired) == "so far"
    assert time.monotonic() - started < 3
    psutil.Process(int(child)).kill()


def test_windows_commands_come_in_on_stdin_so_their_length_doesnt_matter() -> None:
    long_command = "Write-Output " + "x" * 100_000
    argv, script = tools.shell_command(long_command, windows=True)
    assert script == long_command
    assert sum(len(part) for part in argv) < 1000
    assert argv[0] == "powershell"
    assert "UTF8" in argv[-1]


def test_a_command_runs_and_reports_non_ascii_output(tmp_path: Path) -> None:
    control = tools.RunControl()
    done = tools.run_shell("printf '안녕'", tmp_path, 5, control)
    assert "안녕" in done
    assert "[Exit code 0]" in done


def test_nothing_reads_or_writes_text_in_the_systems_own_encoding() -> None:
    """Windows defaults to an older encoding, which garbles or refuses Korean text."""
    root = Path(nexusai.__file__).parent
    careless = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            positional = {"read_text": 0, "write_text": 1}.get(node.func.attr)
            has_encoding = any(word.arg == "encoding" for word in node.keywords)
            if positional is not None and not has_encoding and len(node.args) <= positional:
                careless.append(f"{path.name}:{node.lineno}")
    assert careless == []


def test_rules_in_korean_survive_being_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str | None] = []
    original = Path.write_text

    def noting(self: Path, data: str, encoding: str | None = None, **rest: Any) -> int:
        written.append(encoding)
        return original(self, data, encoding=encoding, **rest)

    monkeypatch.setattr(Path, "write_text", noting)
    rule = MailRule(
        name="회의 메일",
        conditions=[RuleCondition(field="subject", value="회의")],
        actions=RuleActions(category="회의"),
    )
    (tmp_path / "system").mkdir()
    rules.save_rules(tmp_path, RuleSet(rules=[rule]))
    assert written == ["utf-8"]
    assert rules.load_rules(tmp_path)[0].name == "회의 메일"


def test_replacing_a_file_waits_out_a_brief_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "FIRST_WAIT_SECONDS", 0.001)
    source, target = tmp_path / "new", tmp_path / "old"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    real, calls = os.replace, []

    def locked_twice(a: Any, b: Any) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "in use")
        real(a, b)

    monkeypatch.setattr(os, "replace", locked_twice)
    files.replace_file(source, target)
    assert target.read_text(encoding="utf-8") == "new"


def test_replacing_gives_up_on_a_lock_that_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "FIRST_WAIT_SECONDS", 0.001)

    def always(*_: Any) -> None:
        raise PermissionError(13, "in use")

    monkeypatch.setattr(os, "replace", always)
    with pytest.raises(PermissionError):
        files.replace_file(tmp_path / "a", tmp_path / "b")


def test_read_only_files_can_be_removed(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    held = folder / "readonly.txt"
    held.write_text("x", encoding="utf-8")
    held.chmod(stat.S_IREAD)
    files.remove_tree(folder)
    assert not folder.exists()


def test_other_drives_are_offered_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    class Part:
        def __init__(self, mountpoint: str, opts: str = "rw,fixed") -> None:
            self.mountpoint, self.opts = mountpoint, opts

    monkeypatch.setattr(homes.sys, "platform", "win32")
    monkeypatch.setattr(
        homes.psutil,
        "disk_partitions",
        lambda all=False: [Part("C:\\"), Part("D:\\"), Part("E:\\", "cdrom")],
    )
    assert homes._other_drives(Path("/anywhere")) == ["C:\\", "D:\\"]


def test_a_mapped_network_drive_is_recognized(monkeypatch: pytest.MonkeyPatch) -> None:
    class Part:
        mountpoint, opts, fstype = "Z:\\", "rw,remote", "NTFS"

    monkeypatch.setattr(homes.psutil, "disk_partitions", lambda all=True: [Part()])
    assert homes._is_network_path(Path("Z:\\NexusAI")) is True


def test_powershell_file_write_reads_as_one_only_when_it_is_exactly_that() -> None:
    plain = "@'\n<p>Hi</p>\n'@ | Set-Content -Path C:\\out\\a.html -Encoding utf8"
    preview = approval_view.describe("run_command", "Make a page", plain)
    assert (preview.kind, preview.language, preview.content) == ("file", "html", "<p>Hi</p>")
    assert preview.summary.startswith("Create file a.html")
    for sneaky in (
        "@'\nhi\n'@ | Set-Content a.txt; Remove-Item C:\\x -Recurse",
        "Remove-Item x; @'\nhi\n'@ | Set-Content a.txt",
        '@"\n$(evil)\n"@ | Set-Content a.txt',
        "@'\nhi\n'@\nRemove-Item x\n@'\nbye\n'@ | Set-Content a.txt",
        "@'\nhi\n'@ | Set-Content $(evil)",
    ):
        assert approval_view.describe("run_command", "x", sneaky).kind == "command", sneaky
