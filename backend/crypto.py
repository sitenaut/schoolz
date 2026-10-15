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


def fernet() -> MultiFernet | None:
    return _fernet_for(_keys_env())


def is_encrypted(stored: Any) -> bool:
    return isinstance(stored, str) and stored.startswith(PREFIX)


def encrypt(plain: str) -> str:
    """The stored form of `plain`: encrypted when a key is set, else unchanged."""
    f = fernet()
    if f is None:
        if _required():
            raise EncryptionError("ENCRYPTION_REQUIRE is on but DATA_ENCRYPTION_KEYS is not set")
        return plain
    return PREFIX + f.encrypt(plain.encode()).decode()


def decrypt(stored: str) -> str:
    """The plain value of a stored one. A legacy plaintext value is returned
    as is, unless ENCRYPTION_REQUIRE says every value must be encrypted by now."""
    if not is_encrypted(stored):
        if _required():
            raise EncryptionError("a credential column holds plaintext and ENCRYPTION_REQUIRE is on")
        return stored
    f = fernet()
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
    migration."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt(value)
