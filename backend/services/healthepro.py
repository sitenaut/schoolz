"""Health-e Pro (menus.healthepro.com) menus - Maple Shade's lunch vendor
site. The public site is a Vue app over a plain JSON API that needs no token.
A school's location is stored as "org/site" (e.g. "2984/16222"):

- `GET /api/organizations/{org}/sites/{site}/menus/` lists the site's menus,
  each with a `meal_type_id` (1 breakfast, 2 lunch). A site can carry several
  per meal (Yocum: "Elementary Lunch" and a "Pre-Lunch" for preschool).
- `GET /api/organizations/{org}/menus/{menu}/year/{y}/month/{m}/date_overwrites`
  is the per-day layout. Despite the name it holds *every* school day of the
  month, as one row per day whose `setting.current_display` is a flat list of
  category headers ("Lunch Entree", "Vegetables", ...) each followed by its
  recipes. The `.../recipes/` endpoint is only a pool of recipe records with
  no day on them, so it can't answer "what is served Tuesday".

Entrées are the recipes under a category whose name ends in "Entree", read
deterministically - no model. Every day also offers the same standing
alternatives (cereal and yogurt, a PB&J), so the shared `day_descriptions`
rule (`fdmealplanner.day_descriptions`) drops items served on most days.
"""

import json
import re
from datetime import date

import httpx

_API = "https://menus.healthepro.com/api/organizations"
_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)", "Accept": "application/json"}

MEAL_TYPES = {1: "breakfast", 2: "lunch"}
# A preschool-only menu on a school's site ("Pre-Lunch", "Pre-k Breakfast")
# would otherwise compete with the school's own menu for the same slot.
_PRESCHOOL_MENU_RE = re.compile(r"\bpre[\s-]*(k|lunch|school)\b", re.IGNORECASE)


def parse_location(value: str) -> tuple[str, str] | None:
    parts = [p.strip() for p in (value or "").split("/")]
    return tuple(parts) if len(parts) == 2 and all(p.isdigit() for p in parts) else None


def menu_page_url(org: str, site: str) -> str:
    return f"https://menus.healthepro.com/organizations/{org}/sites/{site}"


def pick_menus(menus: list[dict]) -> dict[str, dict]:
    """One menu per meal type: the first that isn't preschool-only, in the
    site's own listing order. Returns {"lunch": menu, "breakfast": menu}."""
    chosen: dict[str, dict] = {}
    for menu in menus:
        meal = MEAL_TYPES.get(menu.get("meal_type_id"))
        name = menu.get("public_name") or menu.get("name") or ""
        if meal and meal not in chosen and not _PRESCHOOL_MENU_RE.search(name):
            chosen[meal] = menu
    return chosen


def entrees(setting: str | dict | None) -> list[str]:
    """Entrée names from one day's `setting`, in menu order, deduped. A
    category header switches the current section; only recipes inside an
    "...Entree" section count."""
    if isinstance(setting, str):
        try:
            setting = json.loads(setting)
        except ValueError:
            return []
    names: list[str] = []
    in_entree = False
    for item in (setting or {}).get("current_display") or []:
        kind = item.get("type")
        if kind == "category":
            in_entree = (item.get("name") or "").strip().lower().endswith("entree")
        elif kind == "recipe" and in_entree:
            name = (item.get("name") or "").strip()
            if name:
                names.append(name)
    return list(dict.fromkeys(names))


def _months(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def fetch_site_menus(client: httpx.AsyncClient, org: str, site: str) -> list[dict]:
    resp = await client.get(f"{_API}/{org}/sites/{site}/menus/", headers=_HEADERS)
    resp.raise_for_status()
    return resp.json().get("data") or []


async def fetch_entrees(client: httpx.AsyncClient, org: str, menu_id: int, start: date, end: date) -> dict[date, list[str]]:
    """Entrées per school day in [start, end]. A month the vendor hasn't
    published yet is a 404/empty, which just means no days from it."""
    out: dict[date, list[str]] = {}
    for year, month in _months(start, end):
        resp = await client.get(f"{_API}/{org}/menus/{menu_id}/year/{year}/month/{month}/date_overwrites", headers=_HEADERS)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        for row in resp.json().get("data") or []:
            try:
                day = date.fromisoformat(row["day"][:10])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= day <= end:
                out[day] = entrees(row.get("setting"))
    return out
