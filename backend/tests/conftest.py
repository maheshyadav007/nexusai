from dataclasses import replace
from pathlib import Path

import pytest

from nexusai.kernel.config import Config, load_config


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never read the real pointer file or saved mail accounts."""
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(tmp_path / "app-data"))


@pytest.fixture
def config(tmp_path: Path) -> Config:
    # The test file keeps tests away from the real Keychain.
    return replace(
        load_config(tmp_path),
        handler_retry_delay_seconds=0,
        secrets_test_file=tmp_path / "secrets.json",
    )
