import asyncio

import pytest

import scraper_client
from services import smore_parser
from services.links import unwrap_redirect

# The confirmed real shape (a PTA Google Form on a newsletter), with the
# data= blob shortened.
WRAPPED = (
    "https://nam04.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.google.com%2Fforms%2Fd%2Fe%2F"
    "1FAIpQLSfGU%2Fviewform%3Fusp%3Dsf_link&data=05%7C02%7Cx%40example.org%7C&sdata=abc&reserved=0"
)
REAL = "https://docs.google.com/forms/d/e/1FAIpQLSfGU/viewform?usp=sf_link"


def test_unwraps_real_safelinks_shape():
    assert unwrap_redirect(WRAPPED) == REAL


def test_unwraps_a_wrapper_inside_a_wrapper():
    from urllib.parse import quote

    double = "https://eur01.safelinks.protection.outlook.com/?url=" + quote(WRAPPED, safe="") + "&data=x"
    assert unwrap_redirect(double) == REAL


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://docs.google.com/forms/d/e/x/viewform",
        # Lookalike host, not Microsoft's.
        "https://safelinks.protection.outlook.com.evil.example/?url=https%3A%2F%2Fx.org",
        # No target, or a target that isn't http(s): leave the wrapper alone.
        "https://nam04.safelinks.protection.outlook.com/?data=x",
        "https://nam04.safelinks.protection.outlook.com/?url=javascript%3Aalert(1)",
    ],
)
def test_leaves_everything_else_alone(url):
    assert unwrap_redirect(url) == url


def test_smore_link_block_stores_unwrapped_url_but_hashes_the_published_one(monkeypatch):
    async def fake_fetch_html(url, **kwargs):
        return {"html": f'<div class="block-wrapper"><a href="{WRAPPED.replace("&", "&amp;")}"></a></div>'}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)
    [block] = asyncio.run(smore_parser.fetch_and_parse("https://www.smore.com/n/x"))
    assert block["block_type"] == "link"
    assert block["link_url"] == REAL
    # Unchanged dedup key: an already-stored wrapped link block must not
    # look new on the next scan.
    assert block["content_hash"] == smore_parser._content_hash("link", WRAPPED)
