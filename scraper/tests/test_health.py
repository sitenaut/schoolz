from fastapi.testclient import TestClient

from main import app


def test_health():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


def test_fetch_html_requires_api_key():
    with TestClient(app) as client:
        res = client.post("/fetch-html", json={"url": "https://example.com"})
        assert res.status_code == 401
