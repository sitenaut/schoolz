import httpx

from scraper_client import _is_retryable


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://scraper/fetch-html")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_scraper_502_is_retried():
    # The scraper answers 502 whenever the *school's* site fails to load in
    # time - transient, so worth another go.
    assert _is_retryable(_status_error(502))


def test_gateway_timeouts_are_retried():
    assert _is_retryable(_status_error(503))
    assert _is_retryable(_status_error(504))


def test_client_side_timeout_is_retried():
    assert _is_retryable(httpx.ReadTimeout("slow", request=httpx.Request("POST", "http://scraper")))
    assert _is_retryable(httpx.ConnectError("refused", request=httpx.Request("POST", "http://scraper")))


def test_auth_and_client_errors_are_not_retried():
    assert not _is_retryable(_status_error(401))
    assert not _is_retryable(_status_error(404))
    assert not _is_retryable(_status_error(422))


def test_unrelated_exceptions_are_not_retried():
    assert not _is_retryable(ValueError("bad json"))
