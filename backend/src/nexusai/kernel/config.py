import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChatGptConfig:
    issuer: str
    base_url: str
    client_id: str
    originator: str
    timeout_seconds: float
    login_timeout_seconds: float
    min_poll_seconds: float
    refresh_skew_seconds: float
    model_list_client_versions: tuple[str, ...]
    test_instructions: str


@dataclass(frozen=True)
class MailConfig:
    connect_timeout_seconds: float
    initial_batch: int
    backfill_batch: int
    flag_window: int
    idle_seconds: float
    reconnect_min_seconds: float
    reconnect_max_seconds: float
    signature_max_bytes: int
    signature_repeat_count: int


@dataclass(frozen=True)
class AgentConfig:
    daily_token_cap: int
    max_running_sessions: int
    triage_batch: int
    triage_retry_seconds: float
    max_recent_thread_messages: int
    max_thread_chars: int
    memory_max_chars: int
    compress_after_chars: int
    command_timeout_seconds: float
    max_tool_output_chars: int
    max_agent_messages_per_run: int
    max_steps: int


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]
    home_dir: Path | None
    max_chain_depth: int
    handler_max_attempts: int
    handler_retry_delay_seconds: float
    sse_keepalive_seconds: float
    log_page_size: int
    default_settings: dict[str, Any]
    min_free_bytes: int
    backups_kept: int
    backup_interval_hours: int
    max_upload_bytes: int
    log_retention_days: int
    network_check_timeout_seconds: float
    chatgpt: ChatGptConfig
    mail: MailConfig
    agent: AgentConfig
    secrets_test_file: Path | None = None
    # Not printed if a config is ever logged.
    database_key: str | None = field(default=None, repr=False)
    require_install_token: bool = True

    @property
    def database_path(self) -> Path:
        return self.home / "system" / "nexusai.db"

    @property
    def home(self) -> Path:
        if self.home_dir is None:
            raise RuntimeError("Home isn't open yet")
        return self.home_dir


def load_config(home_dir: Path | None = None) -> Config:
    raw = tomllib.loads(resources.files(__package__).joinpath("defaults.toml").read_text("utf-8"))
    server, events, chatgpt = raw["server"], raw["events"], raw["chatgpt"]
    secrets_test_file = os.environ.get("NEXUSAI_SECRETS_TEST_FILE")
    return Config(
        host=os.environ.get("NEXUSAI_HOST", server["host"]),
        port=int(os.environ.get("NEXUSAI_PORT", server["port"])),
        allowed_hosts=frozenset(server["allowed_hosts"]),
        allowed_origins=frozenset(server["allowed_origins"]),
        # Normally None: the user's choice is read from the pointer file at startup.
        home_dir=home_dir
        or (Path(fixed).resolve() if (fixed := os.environ.get("NEXUSAI_HOME")) else None),
        min_free_bytes=raw["home"]["min_free_bytes"],
        backups_kept=raw["home"]["backups_kept"],
        backup_interval_hours=raw["home"]["backup_interval_hours"],
        max_upload_bytes=raw["home"]["max_upload_bytes"],
        log_retention_days=raw["logs"]["retention_days"],
        network_check_timeout_seconds=raw["network"]["check_timeout_seconds"],
        max_chain_depth=events["max_chain_depth"],
        handler_max_attempts=events["handler_max_attempts"],
        handler_retry_delay_seconds=events["handler_retry_delay_seconds"],
        sse_keepalive_seconds=events["sse_keepalive_seconds"],
        log_page_size=events["log_page_size"],
        default_settings=raw["settings"],
        mail=MailConfig(**raw["mail"]),
        agent=AgentConfig(**raw["agent"]),
        chatgpt=ChatGptConfig(
            issuer=os.environ.get("NEXUSAI_CHATGPT_ISSUER", chatgpt["issuer"]),
            base_url=os.environ.get("NEXUSAI_CHATGPT_BASE_URL", chatgpt["base_url"]),
            client_id=chatgpt["client_id"],
            originator=chatgpt["originator"],
            timeout_seconds=chatgpt["timeout_seconds"],
            login_timeout_seconds=chatgpt["login_timeout_seconds"],
            min_poll_seconds=chatgpt["min_poll_seconds"],
            refresh_skew_seconds=chatgpt["refresh_skew_seconds"],
            model_list_client_versions=tuple(chatgpt["model_list_client_versions"]),
            test_instructions=chatgpt["test_instructions"],
        ),
        secrets_test_file=Path(secrets_test_file) if secrets_test_file else None,
    )
