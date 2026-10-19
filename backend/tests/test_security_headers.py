"""Security headers on API responses (security_headers.py)."""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.testclient import TestClient

import security_headers
from main import app as real_app


def _app(monkeypatch=None, app_env="local"):
    if monkeypatch:
        monkeypatch.setenv("APP_ENV", app_env)
    app = FastAPI()

    @app.get("/json")
    def json_route():
        return {"ok": True}

    @app.get("/cached")
    def cached():
        return JSONResponse({"ok": True}, headers={"Cache-Control": "public, max-age=60"})

    @app.get("/page")
    def page():
        return HTMLResponse("<script>window.close()</script>")

    @app.get("/pdf")
    def pdf():
        return Response(b"%PDF-1.7", media_type="application/pdf")

    @app.get("/prerender")
    def prerender():
        return HTMLResponse("<html></html>")

    app.add_middleware(security_headers.SecurityHeadersMiddleware)
    return TestClient(app)


def test_json_gets_the_full_set():
    res = _app().get("/json")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["content-security-policy"] == security_headers.API_CSP.decode()
    assert res.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in res.headers


def test_hsts_outside_local(monkeypatch):
    res = _app(monkeypatch, "prod").get("/json")
    assert res.headers["strict-transport-security"] == security_headers.HSTS.decode()


def test_a_routes_own_header_is_kept():
    assert _app().get("/cached").headers["cache-control"] == "public, max-age=60"


def test_html_allows_its_inline_script_only():
    res = _app().get("/page")
    assert res.headers["content-security-policy"] == security_headers.HTML_CSP.decode()
    assert "cache-control" not in res.headers


def test_files_get_no_csp():
    res = _app().get("/pdf")
    assert "content-security-policy" not in res.headers
    assert res.headers["x-content-type-options"] == "nosniff"


def test_prerender_is_left_to_nginx():
    # nginx adds its own CSP; a second one from the API would block the
    # prerendered page's scripts.
    res = _app().get("/prerender")
    assert "content-security-policy" not in res.headers
    assert "x-frame-options" not in res.headers


def test_the_real_app_sends_them():
    res = TestClient(real_app).get("/health")
    assert res.headers["content-security-policy"] == security_headers.API_CSP.decode()
    assert res.headers["cache-control"] == "no-store"
