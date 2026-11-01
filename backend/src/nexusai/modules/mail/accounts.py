"""Mail profiles live in Home; passwords live in the OS credential store."""

import json
import shutil
from pathlib import Path

import keyring

from nexusai.contracts.mail import MailProfile
from nexusai.kernel.config import Config
from nexusai.kernel.home import app_data_dir
from nexusai.kernel.secrets import FileStore

KEYCHAIN_SERVICE = "NexusAI Mail"
FILE_NAME = "mail-accounts.json"
LOCAL_ACCOUNT = "local"


def _path(config: Config) -> Path:
    return config.home / "system" / FILE_NAME


def adopt_earlier_accounts(config: Config) -> None:
    """Profiles saved before Home existed move into it once."""
    earlier = app_data_dir() / FILE_NAME
    target = _path(config)
    if earlier.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(earlier, target)


def read_accounts(config: Config) -> tuple[str | None, dict[str, MailProfile]]:
    path = _path(config)
    if not path.exists():
        return None, {}
    raw = json.loads(path.read_text())
    profiles = {name: MailProfile.model_validate(p) for name, p in raw.get("profiles", {}).items()}
    active = raw.get("activeProfile")
    return (active if active in profiles else None), profiles


def current_account(config: Config) -> str:
    """Where mail is filed. A PST can come in before any account is connected."""
    active, _ = read_accounts(config)
    return active or LOCAL_ACCOUNT


def write_accounts(config: Config, active: str | None, profiles: dict[str, MailProfile]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    body = {"activeProfile": active, "profiles": {n: p.model_dump() for n, p in profiles.items()}}
    temporary.write_text(json.dumps(body, indent=2))
    temporary.replace(path)


def get_password(config: Config, user: str) -> str | None:
    if config.secrets_test_file:
        return FileStore(config.secrets_test_file).get(f"mail:{user}")
    return keyring.get_password(KEYCHAIN_SERVICE, user)


def set_password(config: Config, user: str, password: str) -> None:
    if config.secrets_test_file:
        FileStore(config.secrets_test_file).set(f"mail:{user}", password)
    else:
        keyring.set_password(KEYCHAIN_SERVICE, user, password)


def require_encrypted(profile: MailProfile) -> str | None:
    """Plain connections are only allowed to this computer, for local test servers."""
    for name, server in (("IMAP", profile.imap), ("SMTP", profile.smtp)):
        if not server.secure and server.host not in {"127.0.0.1", "localhost"}:
            return f"{name} must use an encrypted connection."
    return None
