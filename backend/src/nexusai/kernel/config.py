import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]
    home_dir: Path
    max_chain_depth: int
    handler_max_attempts: int
    handler_retry_delay_seconds: float
    sse_keepalive_seconds: float
    log_page_size: int
    default_settings: dict[str, Any]

    @property
    def database_path(self) -> Path:
        return self.home_dir / "system" / "nexusai.db"


def load_config(home_dir: Path | None = None) -> Config:
    raw = tomllib.loads(resources.files(__package__).joinpath("defaults.toml").read_text("utf-8"))
    server, events = raw["server"], raw["events"]
    return Config(
        host=os.environ.get("NEXUSAI_HOST", server["host"]),
        port=int(os.environ.get("NEXUSAI_PORT", server["port"])),
        allowed_hosts=frozenset(server["allowed_hosts"]),
        allowed_origins=frozenset(server["allowed_origins"]),
        home_dir=home_dir or Path(os.environ.get("NEXUSAI_HOME", raw["home"]["dir"])).resolve(),
        max_chain_depth=events["max_chain_depth"],
        handler_max_attempts=events["handler_max_attempts"],
        handler_retry_delay_seconds=events["handler_retry_delay_seconds"],
        sse_keepalive_seconds=events["sse_keepalive_seconds"],
        log_page_size=events["log_page_size"],
        default_settings=raw["settings"],
    )
