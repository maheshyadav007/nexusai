from dataclasses import replace
from pathlib import Path

import pytest

from nexusai.kernel.config import Config, load_config
from nexusai.modules.semantic import downloader


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never read the real pointer file or saved mail accounts."""
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(tmp_path / "app-data"))
    # A developer's own .env must not point tests at a real server.
    monkeypatch.setenv("NEXUSAI_ENV_FILE", str(tmp_path / "no.env"))
    # Reading past mail is tested on its own. Elsewhere it would add runs tests don't expect.
    monkeypatch.setenv("NEXUSAI_LEARN_EMAILS", "0")


@pytest.fixture(autouse=True)
def no_model_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Searching fetches the model on demand, and tests must never reach the internet."""

    def blocked(*_: object, **__: object) -> None:
        raise downloader.DownloadFailed("Downloads are off in tests.")

    monkeypatch.setattr(downloader, "download", blocked)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    # The test file keeps tests away from the real Keychain.
    return replace(
        load_config(tmp_path),
        handler_retry_delay_seconds=0,
        secrets_test_file=tmp_path / "secrets.json",
        require_install_token=False,
    )
