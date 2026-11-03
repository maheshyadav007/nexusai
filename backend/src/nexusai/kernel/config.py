import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal, cast


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
    suggested_pull: int
    check_every_seconds: float
    reconnect_min_seconds: float
    reconnect_max_seconds: float
    signature_max_bytes: int
    signature_repeat_count: int
    presets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SystemMail:
    """The company's server, set once for everyone. People only give a login and password."""

    label: str
    protocol: Literal["imap", "pop3"]
    host: str
    port: int
    secure: bool
    verify_cert: bool
    smtp_host: str
    smtp_port: int
    smtp_secure: bool
    domain: str | None


@dataclass(frozen=True)
class SystemModel:
    """The company's model server. People only choose among its models."""

    base_url: str
    # Not printed if a config is ever logged.
    api_key: str = field(repr=False)
    names: tuple[str, ...]
    supports_tools: bool


@dataclass(frozen=True)
class AgentConfig:
    daily_token_cap: int
    max_running_sessions: int
    triage_batch: int
    triage_retry_seconds: float
    max_recent_thread_messages: int
    max_thread_chars: int
    memory_max_chars: int
    triage_token_limit: int
    learn_emails: int
    learn_recent_days: int
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
    model_hub: str
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
    # What the model sees of a conversation. Settings can change it, so it's checked there.
    context: dict[str, Any]
    secrets_test_file: Path | None = None
    system_mail: SystemMail | None = None
    system_model: SystemModel | None = None
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


def _extra_origins() -> frozenset[str]:
    """Other addresses this app is reached at, named one by one. Never everything: any website a
    person visits could then read their mail through this local server."""
    listed = os.environ.get("NEXUSAI_ALLOWED_ORIGINS", "").split(",")
    return frozenset(origin.strip().rstrip("/") for origin in listed if origin.strip())


def _host_of(origin: str) -> str:
    return origin.split("://", 1)[-1]


def _env_file() -> dict[str, str]:
    """The .env file beside the code. Read here and not added to the process's environment, since
    the agent's commands inherit that and the API key would be one `env` away."""
    named = os.environ.get("NEXUSAI_ENV_FILE")
    path = Path(named) if named else Path(__file__).resolve().parents[4] / ".env"
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, equals, value = line.strip().removeprefix("export ").partition("=")
        if equals and not key.startswith("#"):
            found[key.strip()] = value.strip().strip("\"'")
    return found


def _is_on(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _system_mail(env: dict[str, str], raw: dict[str, Any]) -> SystemMail | None:
    host = env.get("NEXUSAI_MAIL_HOST")
    if not host:
        return None
    protocol = env.get("NEXUSAI_MAIL_PROTOCOL", raw["protocol"]).strip().lower()
    if protocol not in {"imap", "pop3"}:
        raise ValueError("NEXUSAI_MAIL_PROTOCOL must be pop3 or imap.")
    return SystemMail(
        label=env.get("NEXUSAI_MAIL_LABEL", raw["label"]),
        protocol=cast(Literal["imap", "pop3"], protocol),
        host=host,
        port=int(env.get("NEXUSAI_MAIL_PORT", raw["port"])),
        secure=_is_on(env.get("NEXUSAI_MAIL_SECURE", str(raw["secure"]))),
        verify_cert=_is_on(env.get("NEXUSAI_MAIL_VERIFY_CERT", str(raw["verify_cert"]))),
        smtp_host=env.get("NEXUSAI_SMTP_HOST") or host,
        smtp_port=int(env.get("NEXUSAI_SMTP_PORT", raw["smtp_port"])),
        smtp_secure=_is_on(env.get("NEXUSAI_SMTP_SECURE", str(raw["smtp_secure"]))),
        domain=env.get("NEXUSAI_MAIL_DOMAIN") or None,
    )


def _system_model(env: dict[str, str], raw: dict[str, Any]) -> SystemModel | None:
    url = env.get("NEXUSAI_MODEL_URL")
    if not url:
        return None
    names = env.get("NEXUSAI_MODEL_NAMES", "").split(",")
    return SystemModel(
        base_url=url.rstrip("/"),
        api_key=env.get("NEXUSAI_MODEL_API_KEY") or raw["no_key"],
        names=tuple(name.strip() for name in names if name.strip()),
        supports_tools=_is_on(env.get("NEXUSAI_MODEL_TOOLS", str(raw["supports_tools"]))),
    )


def load_config(home_dir: Path | None = None) -> Config:
    raw = tomllib.loads(resources.files(__package__).joinpath("defaults.toml").read_text("utf-8"))
    server, events, chatgpt = raw["server"], raw["events"], raw["chatgpt"]
    secrets_test_file = os.environ.get("NEXUSAI_SECRETS_TEST_FILE")
    extra_origins = _extra_origins()
    # What's really set wins over the file.
    env = {**_env_file(), **os.environ}
    return Config(
        host=os.environ.get("NEXUSAI_HOST", server["host"]),
        port=int(os.environ.get("NEXUSAI_PORT", server["port"])),
        allowed_hosts=frozenset(server["allowed_hosts"]) | {_host_of(o) for o in extra_origins},
        allowed_origins=frozenset(server["allowed_origins"]) | extra_origins,
        # Normally None: the user's choice is read from the pointer file at startup.
        home_dir=home_dir
        or (Path(fixed).resolve() if (fixed := os.environ.get("NEXUSAI_HOME")) else None),
        model_hub=os.environ.get("NEXUSAI_MODEL_HUB", raw["semantic"]["hub"]),
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
        agent=AgentConfig(
            **{
                **raw["agent"],
                "learn_emails": int(
                    os.environ.get("NEXUSAI_LEARN_EMAILS", raw["agent"]["learn_emails"])
                ),
            }
        ),
        context=raw["context"],
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
        system_mail=_system_mail(env, raw["system_mail"]),
        system_model=_system_model(env, raw["system_model"]),
    )
