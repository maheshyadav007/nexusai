"""Mail accounts, in one encrypted file in Home: servers, usernames and passwords together.

It's sealed with a key made from this Home's own key, so it needs nothing else to open, and it
moves with the Home: the recovery key that opens the Home on a new computer opens this too.
"""

import base64
import json
import os
import re
import socket
import threading
from pathlib import Path
from typing import Any

import keyring
import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from keyring.errors import KeyringError

from nexusai.contracts.mail import MailProfile, ServerProbe
from nexusai.kernel.config import Config
from nexusai.kernel.files import replace_file
from nexusai.kernel.home import app_data_dir
from nexusai.kernel.secrets import FileStore

log = structlog.get_logger()
# Where accounts were kept before: profiles in plain text, passwords in the OS credential store.
KEYCHAIN_SERVICE = "NexusAI Mail"
PLAIN_FILE = "mail-accounts.json"
FILE_NAME = "mail-accounts.enc"
LOCAL_ACCOUNT = "local"
KEY_INFO = b"nexusai-mail-accounts-v1"
KEY_BYTES = 32
NONCE_BYTES = 12
IMAP_PORTS = (993,)
SMTP_PORTS = (465, 587)
PROBE_SECONDS = 3.0
_lock = threading.RLock()


def _path(config: Config) -> Path:
    return config.home / "system" / FILE_NAME


def _key(config: Config) -> bytes:
    if not config.database_key:
        raise RuntimeError("Home isn't open yet")
    derive = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=KEY_INFO)
    return derive.derive(bytes.fromhex(config.database_key))


def _write(config: Config, body: dict[str, Any]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(_key(config)).encrypt(nonce, json.dumps(body).encode("utf-8"), KEY_INFO)
    fields = {
        "version": 1,
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(sealed).decode(),
    }
    temporary = path.with_suffix(".tmp")
    temporary.touch(mode=0o600)
    temporary.write_text(json.dumps(fields), encoding="utf-8")
    replace_file(temporary, path)


def _empty() -> dict[str, Any]:
    return {"activeProfile": None, "profiles": {}, "passwords": {}}


def _old_password(config: Config, user: str) -> str | None:
    if config.secrets_test_file:
        return FileStore(config.secrets_test_file).get(f"mail:{user}")
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, user)
    except KeyringError:
        return None


def _forget_old_password(config: Config, user: str) -> None:
    try:
        if config.secrets_test_file:
            FileStore(config.secrets_test_file).delete(f"mail:{user}")
        elif keyring.get_password(KEYCHAIN_SERVICE, user) is not None:
            keyring.delete_password(KEYCHAIN_SERVICE, user)
    except KeyringError:
        log.info("old_mail_password_kept")


def _move_in_old_accounts(config: Config) -> dict[str, Any] | None:
    """Accounts saved the old way move in once, and the plain copies are removed."""
    here = config.home / "system" / PLAIN_FILE
    earlier = app_data_dir() / PLAIN_FILE
    source = here if here.exists() else earlier if earlier.exists() else None
    if source is None:
        return None
    raw = json.loads(source.read_text(encoding="utf-8"))
    profiles = raw.get("profiles", {})
    body = {"activeProfile": raw.get("activeProfile"), "profiles": profiles, "passwords": {}}
    for profile in profiles.values():
        user = profile["auth"]["user"]
        password = _old_password(config, user)
        if password:
            body["passwords"][user] = password
    _write(config, body)
    for profile in profiles.values():
        _forget_old_password(config, profile["auth"]["user"])
    here.unlink(missing_ok=True)
    earlier.unlink(missing_ok=True)
    return body


def _load(config: Config) -> dict[str, Any]:
    path = _path(config)
    if not path.exists():
        return _move_in_old_accounts(config) or _empty()
    try:
        fields = json.loads(path.read_text(encoding="utf-8"))
        plain = AESGCM(_key(config)).decrypt(
            base64.b64decode(fields["nonce"]), base64.b64decode(fields["data"]), KEY_INFO
        )
        return {**_empty(), **json.loads(plain)}
    except (InvalidTag, ValueError, KeyError) as error:
        # Kept aside rather than overwritten, in case it can still be recovered.
        log.error("mail_accounts_unreadable", kind=type(error).__name__)
        path.replace(path.with_suffix(".damaged"))
        return _empty()


def read_accounts(config: Config) -> tuple[str | None, dict[str, MailProfile]]:
    with _lock:
        body = _load(config)
    profiles = {name: MailProfile.model_validate(p) for name, p in body["profiles"].items()}
    active = body["activeProfile"]
    return (active if active in profiles else None), profiles


def current_account(config: Config) -> str:
    """Where mail is filed. A PST can come in before any account is connected."""
    active, _ = read_accounts(config)
    return active or LOCAL_ACCOUNT


def write_accounts(config: Config, active: str | None, profiles: dict[str, MailProfile]) -> None:
    with _lock:
        body = _load(config)
        body["activeProfile"] = active
        body["profiles"] = {name: profile.model_dump() for name, profile in profiles.items()}
        _write(config, body)


def get_password(config: Config, user: str) -> str | None:
    with _lock:
        found = _load(config)["passwords"].get(user)
    return str(found) if found else None


def set_password(config: Config, user: str, password: str) -> None:
    with _lock:
        body = _load(config)
        body["passwords"][user] = password
        _write(config, body)


def delete_password(config: Config, user: str) -> None:
    with _lock:
        body = _load(config)
        if body["passwords"].pop(user, None) is not None:
            _write(config, body)


def forget_everything(config: Config) -> None:
    """For a reset. The file goes with Home, so this clears what could outlive it."""
    with _lock:
        for profile in _load(config)["profiles"].values():
            _forget_old_password(config, profile["auth"]["user"])
    (app_data_dir() / PLAIN_FILE).unlink(missing_ok=True)


def _answers(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=PROBE_SECONDS):
            return True
    except OSError:
        return False


def probe(server: str) -> ServerProbe:
    """From just a server name, the likely settings. Only knocks on ports, and sends nothing."""
    imap_port = next((port for port in IMAP_PORTS if _answers(server, port)), IMAP_PORTS[0])
    # Often the same machine does both, or there's an smtp. beside an imap.
    named = re.sub(r"^imap\.", "smtp.", server)
    hosts = [named, server] if named != server else [server]
    for host in hosts:
        for port in SMTP_PORTS:
            if _answers(host, port):
                return ServerProbe(imap_port=imap_port, smtp_host=host, smtp_port=port)
    return ServerProbe(imap_port=imap_port, smtp_host=named, smtp_port=SMTP_PORTS[0])


def require_encrypted(profile: MailProfile) -> str | None:
    """Plain connections are only allowed to this computer, for local test servers."""
    for name, server in (("IMAP", profile.imap), ("SMTP", profile.smtp)):
        if not server.secure and server.host not in {"127.0.0.1", "localhost"}:
            return f"{name} must use an encrypted connection."
    return None
