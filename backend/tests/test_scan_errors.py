import anthropic
import httpx
import pytest
import sqlalchemy.exc

import scraper_client

from scheduler.errors import ScanError, classify_exception, parse_warning


@pytest.fixture(autouse=True)
def _our_scraper(monkeypatch):
    monkeypatch.setattr(scraper_client, "SCRAPER_URL", "https://scraper.test")


def _http_status_error(status_code: int, url: str = "https://scraper.test/fetch-html") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_classify_scan_error_takes_priority():
    exc = ScanError("no_matches", "nothing found", stage="parse")
    assert classify_exception(exc) == ("no_matches", "parse")


def test_classify_502_is_site_did_not_load():
    assert classify_exception(_http_status_error(502)) == ("site_did_not_load", "fetch")


def test_classify_503_504_from_our_scraper_is_scraper_unavailable():
    assert classify_exception(_http_status_error(503)) == ("scraper_unavailable", "fetch")
    assert classify_exception(_http_status_error(504)) == ("scraper_unavailable", "fetch")


def test_classify_a_vendors_own_503_as_source_unavailable_not_scraper():
    """Barrington's SchoolCafé scan called the vendor's API directly and got a
    503; calling that scraper_unavailable sent the diagnosis to the scraper."""
    vendor = "https://webapis.schoolcafe.com/api/GetMealType"
    assert classify_exception(_http_status_error(503, vendor)) == ("source_unavailable", "fetch")
    assert classify_exception(_http_status_error(504, vendor)) == ("source_unavailable", "fetch")
    refused = httpx.ConnectError("refused", request=httpx.Request("GET", vendor))
    assert classify_exception(refused) == ("source_unavailable", "fetch")


def test_classify_other_http_status_is_source_http_error():
    assert classify_exception(_http_status_error(404)) == ("source_http_error", "fetch")


def test_classify_timeout():
    exc = httpx.TimeoutException("timed out")
    assert classify_exception(exc) == ("scraper_timeout", "fetch")


def test_classify_transport_error():
    exc = httpx.ConnectError("connection refused")
    assert classify_exception(exc) == ("scraper_unavailable", "fetch")


def test_classify_anthropic_rate_limit():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    exc = anthropic.RateLimitError("rate limited", response=response, body=None)
    assert classify_exception(exc) == ("llm_rate_limited", "extract")


def test_classify_anthropic_api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.APIConnectionError(message="down", request=request)
    assert classify_exception(exc) == ("llm_api_error", "extract")


def test_classify_sqlalchemy_pool_timeout():
    exc = sqlalchemy.exc.TimeoutError("pool exhausted")
    assert classify_exception(exc) == ("db_pool_timeout", "persist")


def test_classify_unknown_exception():
    assert classify_exception(ValueError("something else")) == ("unknown", "unknown")


def test_classify_walks_cause_chain():
    try:
        try:
            raise _http_status_error(502)
        except httpx.HTTPStatusError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as exc:
        assert classify_exception(exc) == ("site_did_not_load", "fetch")


def test_parse_warning_none_for_non_warning():
    assert parse_warning("all good") is None
    assert parse_warning(None) is None


def test_parse_warning_extracts_code():
    assert parse_warning("WARNING[no_staff_found]: no staff found") == "no_staff_found"


def test_parse_warning_falls_back_to_unspecified():
    assert parse_warning("WARNING: something vague") == "unspecified"
