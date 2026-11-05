"""The key that encrypts a Home's databases, and the recovery key that gets it back on a new PC.

The key itself lives in the system's secure store. The Home holds it only sealed with the
recovery key, so copying the folder doesn't copy access to it.
"""

import base64
import json
import os
import secrets
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from nexusai.kernel.database import PLAIN_HEADER, connect_raw, key_pragma
from nexusai.kernel.files import replace_file
from nexusai.kernel.secrets import SecretStore

KEY_BYTES = 32
RECOVERY_CHARS = 32
RECOVERY_GROUP = 4
NONCE_BYTES = 12
SALT_BYTES = 16
# Crockford's base32 leaves out letters that are easily misread.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MISREAD = str.maketrans({"O": "0", "I": "1", "L": "1"})
WRAP_INFO = b"nexusai-recovery-v1"
# Internal Beta onboarding uses one known initial key and does not stop setup to display it.
# Replacing it from Settings still creates a unique, high-entropy recovery key.
INITIAL_RECOVERY_KEY = "admin"


class VaultLocked(Exception):
    """This Home is encrypted, and this computer doesn't have its key yet."""


class WrongRecoveryKey(Exception):
    pass


def _path(home: Path) -> Path:
    return home / "system" / "vault.json"


def _key_name(vault_id: str) -> str:
    return f"home-key:{vault_id}"


def _pending_name(vault_id: str) -> str:
    return f"home-recovery:{vault_id}"


def _new_recovery_key() -> str:
    # 160 random bits, so it needs no slow password hashing to be safe.
    chars = "".join(secrets.choice(ALPHABET) for _ in range(RECOVERY_CHARS))
    return "-".join(chars[i : i + RECOVERY_GROUP] for i in range(0, RECOVERY_CHARS, RECOVERY_GROUP))


def _normalize(text: str) -> str:
    return "".join(c for c in text.upper().translate(MISREAD) if c in ALPHABET)


def _wrapping_key(recovery: str, salt: bytes) -> bytes:
    # Treat this as key material. The beta's initial `admin` key is a deliberate
    # convenience tradeoff; replacement and legacy recovery keys are random.
    derive = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, info=WRAP_INFO)
    return derive.derive(_normalize(recovery).encode("ascii"))


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    replace_file(temporary, path)


def _seal(home: Path, vault_id: str, key: str, recovery: str) -> None:
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    sealed = AESGCM(_wrapping_key(recovery, salt)).encrypt(
        nonce, bytes.fromhex(key), vault_id.encode("ascii")
    )
    fields = {"salt": salt, "nonce": nonce, "sealed_key": sealed}
    encoded = {name: base64.b64encode(value).decode("ascii") for name, value in fields.items()}
    _write_atomic(_path(home), json.dumps({"version": 1, "id": vault_id, **encoded}))


def _read(home: Path) -> dict[str, str] | None:
    try:
        data: dict[str, str] = json.loads(_path(home).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return data


def open_key(home: Path, store: SecretStore) -> str:
    """The database key for this Home, creating one the first time."""
    vault = _read(home)
    if vault is None:
        vault_id = uuid.uuid4().hex
        key = secrets.token_hex(KEY_BYTES)
        legacy = (home / "system" / "nexusai.db").exists()
        recovery = _new_recovery_key() if legacy else INITIAL_RECOVERY_KEY
        # The key is saved first: a Home sealed with a key nobody kept could never open.
        store.set(_key_name(vault_id), key)
        if legacy:
            store.set(_pending_name(vault_id), recovery)
        _seal(home, vault_id, key, recovery)
        return key
    saved = store.get(_key_name(vault["id"]))
    if saved is None:
        raise VaultLocked
    return saved


def unlock(home: Path, store: SecretStore, recovery: str) -> None:
    vault = _read(home)
    if vault is None:
        raise WrongRecoveryKey
    decode = base64.b64decode
    try:
        key = AESGCM(_wrapping_key(recovery, decode(vault["salt"]))).decrypt(
            decode(vault["nonce"]), decode(vault["sealed_key"]), vault["id"].encode("ascii")
        )
    except InvalidTag as error:
        raise WrongRecoveryKey from error
    store.set(_key_name(vault["id"]), key.hex())


def pending_recovery_key(home: Path, store: SecretStore) -> str | None:
    """Kept only until the person says they've saved it, and never written in the Home."""
    vault = _read(home)
    return store.get(_pending_name(vault["id"])) if vault else None


def confirm_saved(home: Path, store: SecretStore) -> None:
    vault = _read(home)
    if vault:
        store.delete(_pending_name(vault["id"]))


def new_recovery_key(home: Path, store: SecretStore) -> str:
    """The old recovery key stops working."""
    vault = _read(home)
    if vault is None:
        raise VaultLocked
    key = store.get(_key_name(vault["id"]))
    if key is None:
        raise VaultLocked
    recovery = _new_recovery_key()
    store.set(_pending_name(vault["id"]), recovery)
    _seal(home, vault["id"], key, recovery)
    return recovery


def forget(home: Path, store: SecretStore) -> None:
    """For a reset: removes this Home's keys from the credential store."""
    found = _read(home)
    if found:
        store.delete(_key_name(found["id"]))
        store.delete(_pending_name(found["id"]))


def encrypt_existing(path: Path, key: str) -> bool:
    """A database from before encryption is rewritten in place. Returns whether it was."""
    if not path.exists():
        return False
    with path.open("rb") as file:
        if file.read(len(PLAIN_HEADER)) != PLAIN_HEADER:
            return False
    temporary = path.with_name(f"{path.name}.encrypting")
    temporary.unlink(missing_ok=True)
    plain = connect_raw(path, None)
    try:
        version = plain.execute("PRAGMA user_version").fetchone()[0]
        plain.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        plain.execute(f"ATTACH DATABASE ? AS encrypted KEY {key_pragma(key)}", (str(temporary),))
        plain.execute("SELECT sqlcipher_export('encrypted')")
        plain.execute(f"PRAGMA encrypted.user_version = {int(version)}")
        plain.commit()
        plain.execute("DETACH DATABASE encrypted")
    finally:
        plain.close()
    # Proves it opens before the only copy of the data is replaced.
    check = connect_raw(temporary, key)
    try:
        check.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    finally:
        check.close()
    replace_file(temporary, path)
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    return True
