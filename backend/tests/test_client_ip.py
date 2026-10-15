"""services/client_ip.py: the address rate limits key on can't be chosen by
the caller."""
from starlette.requests import Request

from services.client_ip import client_ip


def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    })


def test_on_fly_the_proxy_header_wins_and_forwarded_for_is_ignored(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", "m1")
    req = _request({"Fly-Client-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"})
    assert client_ip(req) == "203.0.113.7"


def test_on_fly_without_the_header_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", "m1")
    assert client_ip(_request({"X-Forwarded-For": "198.51.100.1"})) == "10.0.0.9"


def test_off_fly_a_typed_header_is_ignored(monkeypatch):
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    req = _request({"Fly-Client-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"})
    assert client_ip(req) == "10.0.0.9"


def test_no_peer_is_none(monkeypatch):
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    req = Request({"type": "http", "headers": [], "client": None})
    assert client_ip(req) is None
