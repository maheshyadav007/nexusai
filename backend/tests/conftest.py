from dataclasses import replace
from pathlib import Path

import pytest

from nexusai.kernel.config import Config, load_config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return replace(load_config(tmp_path), handler_retry_delay_seconds=0)
