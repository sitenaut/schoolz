"""Encryption at rest for Gmail tokens (SZ-9): new writes are encrypted once
a key is set, old plaintext rows still read, the script encrypts them in
place, and nothing changes while no key is configured."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text, type_coerce

import crypto
import database
from models import GmailToken, User
from scripts import encrypt_secrets

KEY_A, KEY_B = Fernet.generate_key().decode(), Fernet.generate_key().decode()


@pytest.fixture
def keys(monkeypatch):
    def _set(value: str | None, require: bool = False):
        if value is None:
            monkeypatch.delenv("DATA_ENCRYPTION_KEYS", raising=False)
        else:
            monkeypatch.setenv("DATA_ENCRYPTION_KEYS", value)
        monkeypatch.setenv("ENCRYPTION_REQUIRE", "true" if require else "false")

    _set(None)
    return _set


def test_round_trip_and_legacy_plaintext(keys):
    keys(KEY_A)
    stored = crypto.encrypt("ya29.secret")
    assert stored.startswith("enc:v1:") and "ya29.secret" not in stored
    assert crypto.decrypt(stored) == "ya29.secret"
    assert crypto.decrypt("legacy-plain") == "legacy-plain"


def test_no_key_stores_plain_and_cannot_read_ciphertext(keys):
    keys(KEY_A)
    stored = crypto.encrypt("t")
    keys(None)
    assert crypto.encrypt("t") == "t"
    with pytest.raises(crypto.EncryptionError, match="DATA_ENCRYPTION_KEYS is not set"):
        crypto.decrypt(stored)


def test_rotation_reads_old_and_writes_with_the_first_key(keys):
    keys(KEY_A)
    old = crypto.encrypt("t")
    keys(f"{KEY_B},{KEY_A}")
    assert crypto.decrypt(old) == "t"
    new = crypto.encrypt("t")
    keys(KEY_B)
    assert crypto.decrypt(new) == "t"
    with pytest.raises(crypto.EncryptionError, match="no key"):
        crypto.decrypt(old)


def test_require_refuses_plaintext_and_a_missing_key(keys):
    keys(KEY_A, require=True)
    with pytest.raises(crypto.EncryptionError):
        crypto.decrypt("legacy-plain")
    keys(None, require=True)
    with pytest.raises(crypto.EncryptionError):
        crypto.encrypt("t")


def test_a_bad_key_is_named_not_shown(keys):
    keys("not-a-key")
    with pytest.raises(crypto.EncryptionError, match="not a Fernet key") as err:
        crypto.encrypt("t")
    assert "not-a-key" not in str(err.value)


def test_derived_keys_differ_by_purpose_and_follow_the_first_key(keys):
    assert crypto.derived_key("gmail-connect") is None
    keys(KEY_A)
    a = crypto.derived_key("gmail-connect")
    assert a is not None and len(a) == 32
    assert crypto.derived_key("other") != a
    keys(f"{KEY_B},{KEY_A}")
    assert crypto.derived_key("gmail-connect") != a


async def _user(db) -> User:
    run = uuid.uuid4().hex[:8]
    user = User(email=f"crypt_{run}@example.com", username=f"crypt_{run}")
    db.add(user)
    await db.flush()
    return user


async def _raw(db, user_id: str, column):
    return (
        await db.execute(select(type_coerce(column, column.type.impl)).where(GmailToken.user_id == user_id))
    ).scalar_one()


def _token(user_id: str) -> GmailToken:
    return GmailToken(
        user_id=user_id,
        google_email="admin@example.com",
        access_token="ya29.access",
        refresh_token="1//refresh",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.mark.anyio
async def test_gmail_tokens_are_stored_encrypted(keys):
    keys(KEY_A)
    async with database.SessionLocal() as db:
        user_id = (await _user(db)).id
        db.add(_token(user_id))
        await db.flush()
        assert crypto.is_encrypted(await _raw(db, user_id, GmailToken.refresh_token))
        db.expire_all()
        row = (await db.execute(select(GmailToken).where(GmailToken.user_id == user_id))).scalar_one()
        assert (row.access_token, row.refresh_token) == ("ya29.access", "1//refresh")


@pytest.mark.anyio
async def test_script_encrypts_legacy_rows_in_place(keys):
    async with database.SessionLocal() as db:
        user = await _user(db)
        db.add(_token(user.id))  # no key yet: written as plaintext
        await db.commit()
        user_id = user.id

    keys(KEY_A)
    dry = await encrypt_secrets.run(apply=False, rotate=False, tables={"gmail_tokens"})
    assert dry["gmail_tokens.refresh_token"]["plaintext"] >= 1
    assert dry["gmail_tokens.refresh_token"]["rewritten"] == 0

    await encrypt_secrets.run(apply=True, rotate=False, tables={"gmail_tokens"})
    async with database.SessionLocal() as db:
        assert crypto.is_encrypted(await _raw(db, user_id, GmailToken.access_token))
        assert crypto.is_encrypted(await _raw(db, user_id, GmailToken.refresh_token))
        row = (await db.execute(select(GmailToken).where(GmailToken.user_id == user_id))).scalar_one()
        assert row.refresh_token == "1//refresh"
        # Nothing plaintext is left behind in the column.
        plain = (
            await db.execute(text("select count(*) from gmail_tokens where user_id = :u and refresh_token not like 'enc:v1:%'"), {"u": user_id})
        ).scalar_one()
        assert plain == 0
