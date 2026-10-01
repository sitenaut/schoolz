"""Presence (ex-SharpSchool / SchoolMessenger Presence) "Documents" widgets.

A page's document list is not in its HTML: an inline script builds
`new ContentItemListUI('<folderId>', null, '[]', {"ContextId":...})` and the
browser then POSTs the folder id plus that settings dict to the anonymous
`/portal/svc/ContentItemSvc.asmx/GetItemList`. Plain httpx can do the same;
headless Chromium is not needed (and gets 502s from these hosts). A bare
`parentId`, or `Params` of "{}", answers "error processing the request" - the
page's own settings dict has to be echoed back, as a JSON *string*.
"""

import json
import re
from urllib.parse import urljoin

import httpx

_WIDGET_RE = re.compile(r"new ContentItemListUI\('(\d+)'")
_UA = "Mozilla/5.0 (schoolz directory sync)"
_MAX_DEPTH = 3


def widgets(html: str) -> list[tuple[int, dict]]:
    """(folder id, settings dict) for every documents widget on the page."""
    out = []
    decoder = json.JSONDecoder()
    for m in _WIDGET_RE.finditer(html):
        start = html.find('{"ContextId"', m.end())
        if start < 0:
            continue
        try:
            settings, _ = decoder.raw_decode(html[start:])
        except ValueError:
            continue
        out.append((int(m.group(1)), settings))
    return out


async def _folder_items(client: httpx.AsyncClient, base: str, folder_id: int, settings: dict, depth: int) -> list[dict]:
    resp = await client.post(
        urljoin(base, "/portal/svc/ContentItemSvc.asmx/GetItemList"),
        json={"parentId": folder_id, "Params": json.dumps({**settings, "searchVal": ""})},
        headers={"requestFrom": "contentItem"},
    )
    resp.raise_for_status()
    out = []
    for item in (resp.json().get("d") or {}).get("DataObject") or []:
        if item.get("Type") == "folder" or item.get("FolderCount"):
            if depth < _MAX_DEPTH:
                out.extend(await _folder_items(client, base, item["ObjectId"], settings, depth + 1))
            continue
        link = item.get("DownloadLink") or item.get("Link")
        if link and item.get("Title"):
            out.append(
                {
                    "title": item["Title"].strip(),
                    "extension": (item.get("Extension") or "").lower().lstrip("."),
                    "modified": item.get("ModifiedDateString"),
                    "url": urljoin(base, link),
                }
            )
    return out


async def list_page_documents(page_url: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Every document in every documents widget on `page_url`, newest first as
    the site orders them. [] for a page with no widgets (or not Presence)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": _UA})
    try:
        page = await client.get(page_url)
        page.raise_for_status()
        out: list[dict] = []
        for folder_id, settings in widgets(page.text):
            out.extend(await _folder_items(client, str(page.url), folder_id, settings, 0))
        return out
    finally:
        if own:
            await client.aclose()
