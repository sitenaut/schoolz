"""services/givebacks.py against synthetic responses shaped like the two
real Givebacks page-content formats confirmed live: the newer block-tree
builder's pre-rendered html_raw (Bret Harte's real pages) and the older
page builder's named HTML-blob-with-embedded-data-URI format (Thomas
Sharp's real pages)."""
from functools import partial

import httpx
import pytest

from services import givebacks

# A 1x1 transparent PNG, standing in for a real flyer image embedded as a
# data: URI - the real thing is hundreds of KB, which isn't worth carrying
# in a fixture just to prove the decode path works.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

_LEGACY_PAGE = {
    "id": 1,
    "path": "/eventsandopportunities",
    "content": {
        "html_raw": "",
        "design": {},
        "content": {
            "title": "Mark your calendars!",
            "text": f'<p><img src="data:image/png;base64,{_TINY_PNG_B64}"></p>',
        },
    },
}

_BLOCK_TREE_PAGE = {
    "id": 2,
    "path": "/UpcomingEvents",
    "content": {
        "html_raw": (
            '<body><div class="u_content_text">PTA Events!</div>'
            '<div class="u_content_image"><img src="https://s3.example.com/flyer.png"></div>'
            '<div class="u_content_text">Questions? Email us at <a href="mailto:pta@example.org">pta@example.org</a></div>'
            "</body>"
        ),
        "design": {"body": {"rows": []}},
    },
}

_HOME_PAGE_BLOCK1_BLOCK2 = {
    "id": 3,
    "path": "/",
    "content": {
        "html_raw": "",
        "block1": {"title": "", "text": "<p>Welcome to our PTA!</p>"},
        "block2": {"title": "", "text": '<p>Join us: <a href="https://example.org/join">sign up</a></p>'},
    },
}


def test_parse_page_legacy_blob_decodes_embedded_image():
    blocks = givebacks.parse_page(_LEGACY_PAGE)
    assert len(blocks) == 1
    block = blocks[0]
    assert block["page_path"] == "/eventsandopportunities"
    assert block["block_type"] == "image"
    assert block["image_url"] is None  # no fetchable URL for a data: URI - see module docstring
    assert block["_image_bytes"].startswith(b"\x89PNG")


def test_parse_page_block_tree_uses_html_raw_directly():
    blocks = givebacks.parse_page(_BLOCK_TREE_PAGE)
    assert [b["block_type"] for b in blocks] == ["text", "image", "text"]
    assert blocks[0]["text_content"] == "PTA Events!"
    assert blocks[1]["image_url"] == "https://s3.example.com/flyer.png"
    assert blocks[1]["_image_bytes"] is None
    assert blocks[2]["link_url"] == "mailto:pta@example.org"


def test_parse_page_home_page_reads_block1_then_block2_in_order():
    blocks = givebacks.parse_page(_HOME_PAGE_BLOCK1_BLOCK2)
    assert len(blocks) == 2
    assert blocks[0]["text_content"] == "Welcome to our PTA!"
    assert blocks[1]["text_content"] == "Join us: sign up"
    assert blocks[1]["link_url"] == "https://example.org/join"
    # Positions are renumbered across both blobs on one page, not reset per blob.
    assert [b["position"] for b in blocks] == [0, 1]


def test_parse_page_skips_pages_with_no_content():
    assert givebacks.parse_page({"path": "/empty", "content": {"html_raw": "", "content": {"text": "", "title": ""}}}) == []


@pytest.mark.anyio
async def test_resolve_org_returns_none_for_unknown_shortname():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Cause not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await givebacks.resolve_org(client, "nosuchpta") is None


@pytest.mark.anyio
async def test_resolve_org_returns_cause_dict_for_a_real_org():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/services/core/causes/bretharte"
        return httpx.Response(200, json={"cause": {"name": "Bret Harte School PTA", "address": "1909 Queen Anne Rd, Cherry Hill, NJ", "memberhub_id": "abc-123"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        org = await givebacks.resolve_org(client, "bretharte")
        assert org["memberhub_id"] == "abc-123"


def test_verified_match_by_name_containment():
    org = {"name": "Bret Harte School PTA", "address": ""}
    assert givebacks.verified_match(org, "Bret Harte Elementary School", None) is True


def test_verified_match_rejects_unrelated_org():
    org = {"name": "Some Other School PTA", "address": "1 Main St"}
    assert givebacks.verified_match(org, "Bret Harte Elementary School", "1909 Queen Anne Rd") is False


def test_verified_match_falls_back_to_address_token_overlap():
    org = {"name": "PTA", "address": "1909 Queen Anne Rd, Cherry Hill, NJ"}
    assert givebacks.verified_match(org, "Bret Harte Elementary School", "1909 Queen Anne Rd") is True


@pytest.mark.anyio
async def test_fetch_and_parse_crawls_every_page(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "causes" in request.url.path:
            return httpx.Response(200, json={"cause": {"name": "Bret Harte School PTA", "memberhub_id": "abc-123"}})
        assert request.url.params["organization_uuid"] == "abc-123"
        return httpx.Response(200, json={"webpages": [_BLOCK_TREE_PAGE, _HOME_PAGE_BLOCK1_BLOCK2]})

    monkeypatch.setattr(givebacks.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    blocks = await givebacks.fetch_and_parse("bretharte")
    paths = {b["page_path"] for b in blocks}
    assert paths == {"/UpcomingEvents", "/"}


@pytest.mark.anyio
async def test_fetch_and_parse_returns_empty_for_unknown_shortname(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Cause not found"})

    monkeypatch.setattr(givebacks.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    assert await givebacks.fetch_and_parse("nosuchpta") == []
