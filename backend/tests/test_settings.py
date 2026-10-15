"""Start-up settings check (SZ-16): names what is missing or malformed,
never a value, and only refuses to start when SETTINGS_ENFORCE is on."""
import logging

import pytest
from cryptography.fernet import Fernet

import settings

KEY = Fernet.generate_key().decode()

PROD = {
    "FLY_MACHINE_ID": "m1",
    "APP_ENV": "prod",
    "AUTH_MODE": "supabase",
    "DATABASE_URL": "postgresql://u:p@db.example.com:5432/postgres",
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "srk",
    "PUBLIC_API_URL": "https://schoolz-api.sitenaut.com",
    "PUBLIC_WEB_URL": "https://schoolz.sitenaut.com",
    "DATA_ENCRYPTION_KEYS": KEY,
    "SECRETS_UNLOCK_KEY": "unlock",
    "TURNSTILE_SECRET_KEY": "ts",
    "SCRAPER_URL": "http://schoolz-scraper.internal:8765",
    "SCRAPER_API_KEY": "sk",
    "ANTHROPIC_API_KEY": "ak",
    "GOOGLE_CLIENT_ID": "gid",
    "GOOGLE_CLIENT_SECRET": "gsecret",
}


def test_a_complete_prod_environment_is_clean():
    assert settings.problems("api", PROD) == []
    assert settings.problems("scheduler", PROD) == []


def test_missing_settings_are_named_per_process():
    env = {k: v for k, v in PROD.items() if k not in ("DATA_ENCRYPTION_KEYS", "SECRETS_UNLOCK_KEY")}
    assert settings.problems("api", env) == ["DATA_ENCRYPTION_KEYS is not set", "SECRETS_UNLOCK_KEY is not set"]
    # The scheduler never answers secret-access requests.
    assert settings.problems("scheduler", env) == ["DATA_ENCRYPTION_KEYS is not set"]


def test_nothing_is_required_locally_but_shapes_are_checked():
    assert settings.problems("api", {}) == []
    found = settings.problems(
        "api",
        {"DB_POOL_SIZE": "four", "PUBLIC_API_URL": "schoolz-api", "DATA_ENCRYPTION_KEYS": "hunter2", "LOG_LEVEL": "loud"},
    )
    assert "DB_POOL_SIZE is not a whole number" in found
    assert "PUBLIC_API_URL is not a URL" in found
    assert "DATA_ENCRYPTION_KEYS holds a value that is not a Fernet key" in found
    assert any(p.startswith("LOG_LEVEL must be one of") for p in found)
    assert not any("hunter2" in p for p in found)


def test_half_pairs_and_local_only_settings_in_prod():
    env = {**PROD, "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example.com", "JWT_SECRET": "x" * 32}
    found = settings.problems("api", env)
    assert "OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS must be set together" in found
    assert "JWT_SECRET is set but is only for the local stack" in found


def test_logs_by_default_and_refuses_only_when_enforcing(monkeypatch, caplog):
    for k in list(PROD):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLY_MACHINE_ID", "m1")
    monkeypatch.delenv("SETTINGS_ENFORCE", raising=False)
    with caplog.at_level(logging.ERROR, logger="settings"):
        found = settings.check_settings("api")
    assert "DATABASE_URL is not set" in found
    assert any(r.message == "settings_validation_failed" for r in caplog.records)

    monkeypatch.setenv("SETTINGS_ENFORCE", "1")
    with pytest.raises(settings.SettingsError, match="DATABASE_URL is not set"):
        settings.check_settings("api")
