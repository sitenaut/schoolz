"""Nutrislice (`<district>.nutrislice.com`) menus - Cinnaminson's lunch
vendor site. The public site is an app over a plain JSON API that needs no
token. A school's location is stored as "district/school-slug" (e.g.
"cinnaminson/eleanor-rush-school"):

- `GET https://<district>.api.nutrislice.com/menu/api/schools/?format=json`
  lists the schools with their slugs and `active_menu_types` (find a new
  school's slug here).
- `GET .../menu/api/weeks/school/<school>/menu-type/<meal>/<y>/<m>/<d>/?format=json`
  is the Sunday-to-Saturday week holding that date: `days[]`, each with a flat
  `menu_items` list of station headers, text rows and foods.

Entrées are the foods whose `food_category` is "entree" (for a breakfast
with none, its "grain" foods; a day with no entrée whose first food is
uncategorized, that first food), read deterministically - no model. Every day repeats the same standing choices (a
ham and cheese sandwich), so the shared `day_descriptions` rule
(`fdmealplanner.day_descriptions`) drops items served on most days.
"""

import re
from datetime import date, timedelta

import httpx

_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)", "Accept": "application/json"}
_LOCATION_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")

MEAL_TYPES = ("breakfast", "lunch")


def parse_location(value: str) -> tuple[str, str] | None:
    value = (value or "").strip()
    return tuple(value.split("/")) if _LOCATION_RE.match(value) else None


def menu_page_url(district: str, school: str) -> str:
    return f"https://{district}.nutrislice.com/menu/{school}"


def entrees(menu_items: list[dict] | None, meal: str = "lunch") -> list[str]:
    """Entrée names from one day's `menu_items`, in menu order, deduped. An
    elementary breakfast is often a muffin or cereal bar filed under "grain"
    with no entrée at all, so a breakfast day without one falls back to its
    grains."""
    by_category: dict[str, list[str]] = {}
    first_category = None
    for item in menu_items or []:
        food = item.get("food") or {}
        name = (food.get("name") or "").strip()
        if name:
            category = (food.get("food_category") or "").lower()
            if first_category is None:
                first_category = category
            by_category.setdefault(category, []).append(name)
    if "entree" not in by_category and first_category == "":
        # A tenant that files little or nothing (Pennsauken: lunch never,
        # breakfast only the odd "grain") lists the day's main item first,
        # then its sides and the standing cereal/milk/fruit rows.
        return by_category[""][:1]
    names = by_category.get("entree") or (by_category.get("grain", []) if meal == "breakfast" else [])
    return list(dict.fromkeys(names))


def _week_starts(start: date, end: date) -> list[date]:
    """One date per Sunday-to-Saturday week touching [start, end]."""
    day = start - timedelta(days=start.isoweekday() % 7)
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


async def fetch_entrees(client: httpx.AsyncClient, district: str, school: str, meal: str, start: date, end: date) -> dict[date, list[str]]:
    """Entrées per school day in [start, end]. A meal the school doesn't
    serve is a 404, which just means no days."""
    out: dict[date, list[str]] = {}
    for day in _week_starts(start, end):
        resp = await client.get(
            f"https://{district}.api.nutrislice.com/menu/api/weeks/school/{school}/menu-type/{meal}/{day.year}/{day.month:02d}/{day.day:02d}/",
            params={"format": "json"},
            headers=_HEADERS,
        )
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        for row in resp.json().get("days") or []:
            try:
                menu_date = date.fromisoformat(row["date"][:10])
            except (KeyError, TypeError, ValueError):
                continue
            names = entrees(row.get("menu_items"), meal)
            if names and start <= menu_date <= end:
                out[menu_date] = names
    return out
