import httpx
import pytest

import scraper_client
from services.public_url import PUBLIC_ONLY, NotPublicURL, check_public_page, public_url_error


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/health/deep",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fdaa::3]:8080/",
        "http://[::ffff:10.0.0.1]/",
        "http://schoolz-scraper.internal:8765/",
        "http://localhost/",
        "ftp://example.org/file",
    ],
)
async def test_private_and_odd_addresses_are_refused(url):
    assert await public_url_error(url) is not None


@pytest.mark.anyio
async def test_a_public_address_passes():
    assert await public_url_error("http://93.184.216.34/") is None


@pytest.mark.anyio
async def test_a_redirect_into_the_private_network_is_refused_at_that_hop():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8765/health/deep"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        assert await check_public_page(client, "http://93.184.216.34/flyer") == "This URL isn't on the public internet"
        assert seen == ["http://93.184.216.34/flyer"]  # the private hop was never requested


@pytest.mark.anyio
async def test_a_public_redirect_is_followed_and_a_404_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(404 if request.url.path == "/new" else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        assert "404" in await check_public_page(client, "http://93.184.216.34/old")
        assert await check_public_page(client, "http://93.184.216.34/fine") is None


@pytest.mark.anyio
async def test_a_scraped_file_fetch_stops_at_a_private_hop_before_requesting_it():
    # A newsletter image or flyer URL is chosen by whoever wrote the page.
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, content=b"not for you")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True, event_hooks=PUBLIC_ONLY
    ) as client:
        with pytest.raises(NotPublicURL):
            await client.get("http://93.184.216.34/flyer.png")
        assert seen == ["http://93.184.216.34/flyer.png"]

    with pytest.raises(httpx.RequestError):
        await scraper_client.get_bytes("http://127.0.0.1:8765/health/deep")
