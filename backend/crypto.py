"""Encryption at rest for third-party credentials (SEC-7), ported from billz.

Columns typed `EncryptedText` are encrypted on write and decrypted on read,
so the code that uses them sees plain values. A database dump or a leaked
pooler connection then yields no usable Gmail token without the key, which
lives only in the app's environment (`DATA_ENCRYPTION_KEYS`), never in the
database.

Stored form: `enc:v1:<Fernet token>`. Values without the prefix are rows
written before encryption was switched on; they read back unchanged until
`scripts/encrypt_secrets.py --apply` rewrites them. With no key configured,
nothing is encrypted and the columns behave as plain text, so shipping this
changes nothing until a key is set.

Keys are comma-separated Fernet keys, newest first: new values use the first,
reads try each. To rotate, put the new key in front, deploy, run the script
with `--rotate --apply`, then drop the old key. Losing every key makes each
encrypted Gmail connection unreadable (each would have to be connected
again), so a key goes into the `schoolz-prod` vault before it goes into Fly.

`ENCRYPTION_REQUIRE=1` (set once every row is encrypted) makes a missing key
or a plaintext row an error instead of a silent fallback.

`derived_key(purpose)` gives other code its own key from the same secret
(HKDF, one key per purpose), so a signing key doesn't need a secret of its
own and can never be confused with the encryption key.

`EncryptedText(purpose=..., required=True)` encrypts a column with keys
derived for that purpose (one per configured key, so rotation works the same
way), and refuses to store or read plaintext whatever ENCRYPTION_REQUIRE
says. The saved services profile uses it: its ciphertext can't be opened
with the Gmail tokens' key, and with no key configured it isn't stored at all.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

PREFIX = "enc:v1:"


class EncryptionError(RuntimeError):
    """A value cannot be encrypted or decrypted with the configured keys.
    The message names the variable, never a key or a value."""


def _keys_env() -> str:
    return os.getenv("DATA_ENCRYPTION_KEYS", "")


def _required() -> bool:
    return os.getenv("ENCRYPTION_REQUIRE", "").lower() in ("1", "true", "yes")


def split_keys(keys: str) -> list[str]:
    return [k.strip() for k in keys.split(",") if k.strip()]


@lru_cache(maxsize=4)
def _fernet_for(keys: str) -> MultiFernet | None:
    parts = split_keys(keys)
    if not parts:
        return None
    try:
        return MultiFernet([Fernet(k) for k in parts])
    except ValueError:
        raise EncryptionError("DATA_ENCRYPTION_KEYS holds a value that is not a Fernet key") from None


@lru_cache(maxsize=16)
def _purpose_fernet_for(keys: str, purpose: str) -> MultiFernet | None:
    parts = split_keys(keys)
    if not parts:
        return None
    _fernet_for(keys)  # same "not a Fernet key" error as everywhere else
    return MultiFernet([Fernet(base64.urlsafe_b64encode(_derive(k, purpose))) for k in parts])


def fernet(purpose: str | None = None) -> MultiFernet | None:
    if purpose is None:
        return _fernet_for(_keys_env())
    return _purpose_fernet_for(_keys_env(), purpose)


def is_encrypted(stored: Any) -> bool:
    return isinstance(stored, str) and stored.startswith(PREFIX)


def encrypt(plain: str, purpose: str | None = None, required: bool = False) -> str:
    """The stored form of `plain`: encrypted when a key is set, else unchanged
    (or an error, when encryption is required)."""
    f = fernet(purpose)
    if f is None:
        if required or _required():
            raise EncryptionError("encryption is required but DATA_ENCRYPTION_KEYS is not set")
        return plain
    return PREFIX + f.encrypt(plain.encode()).decode()


def decrypt(stored: str, purpose: str | None = None, required: bool = False) -> str:
    """The plain value of a stored one. A legacy plaintext value is returned
    as is, unless ENCRYPTION_REQUIRE (or the column) says every value must be
    encrypted by now."""
    if not is_encrypted(stored):
        if required or _required():
            raise EncryptionError("an encrypted column holds plaintext and encryption is required")
        return stored
    f = fernet(purpose)
    if f is None:
        raise EncryptionError("an encrypted credential was read but DATA_ENCRYPTION_KEYS is not set")
    try:
        return f.decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise EncryptionError("no key in DATA_ENCRYPTION_KEYS opens a stored credential") from None


@lru_cache(maxsize=16)
def _derive(first_key: str, purpose: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=f"schoolz:{purpose}".encode()
    ).derive(base64.urlsafe_b64decode(first_key))


def can_encrypt() -> bool:
    """True when DATA_ENCRYPTION_KEYS is set, so a required column can be written."""
    return bool(split_keys(_keys_env()))


def derived_key(purpose: str) -> bytes | None:
    """A 32-byte key for `purpose`, derived from the first DATA_ENCRYPTION_KEYS
    key; None when no key is set. Rotating that key changes it."""
    parts = split_keys(_keys_env())
    if not parts:
        return None
    fernet()  # same "not a Fernet key" error as everywhere else
    return _derive(parts[0], purpose)


class EncryptedText(TypeDecorator):
    """A String column whose value is encrypted at rest. The database type is
    unchanged (unbounded VARCHAR), so switching a column to it needs no
    migration.

    `purpose` encrypts with keys derived for that purpose instead of the
    configured keys themselves; `required` never stores or reads plaintext."""

    impl = String
    cache_ok = True

    def __init__(self, *args: Any, purpose: str | None = None, required: bool = False, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.purpose = purpose
        self.required = required

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt(value, self.purpose, self.required)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt(value, self.purpose, self.required)
