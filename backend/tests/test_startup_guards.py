"""A deployed API refuses to start in local auth mode (SZ-7), and only the
local stack serves the API docs (SZ-8)."""
import pytest

import auth


@pytest.fixture
def deployed(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", "m1")
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://example.supabase.co")


def test_local_stack_is_not_deployed(monkeypatch):
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    assert not auth.is_deployed()
    monkeypatch.delenv("AUTH_MODE", raising=False)
    auth.check_deployed_auth_mode()  # anything goes locally


def test_app_env_prod_counts_as_deployed(monkeypatch):
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    monkeypatch.setenv("APP_ENV", "prod")
    assert auth.is_deployed()


@pytest.mark.parametrize("mode", [None, "local", "", "Supabase"])
def test_deployed_refuses_anything_but_supabase(deployed, monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("AUTH_MODE", raising=False)
    else:
        monkeypatch.setenv("AUTH_MODE", mode)
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        auth.check_deployed_auth_mode()


def test_deployed_needs_a_supabase_url(deployed, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        auth.check_deployed_auth_mode()


def test_deployed_supabase_starts(deployed, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    auth.check_deployed_auth_mode()


def test_docs_are_served_locally():
    from main import app

    # Tests run as the local stack; deploy.yml's smoke check asserts the
    # opposite on prod (/openapi.json answers 404).
    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"
