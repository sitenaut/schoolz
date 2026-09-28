"""FD MealPlanner (fdmealplanner.com, Whitsons / "Culinary Digital") menus -
Haddon Township's lunch vendor. The site is a client-rendered Next.js app,
but the per-day menu comes from a plain JSON endpoint that answers without
the site's encrypted anonymous token (the browser sends one; the server
doesn't check it on this call - confirmed with a bare request). Only the
location *search* needs the token, and that's a one-time lookup: a school's
location is stored as "tenant/account/location" (e.g. "3/297/1469").

Each day's row carries `xmlMenuRecipes`, every item tagged IsEntreeType /
MealType, so entrées are picked out deterministically - no model. Real
menus list the same standing options every day (the HS's burgers, pizza and
wraps; an elementary's Caesar salad, bagel lunch and PB&J), which would bury
the one thing a parent is looking for - the day's rotating entrée - so
items served on most days of the fetched window are dropped from the line.
"""

import html
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx

_MEALS_URL = "https://apiservicelocatorstenant.fdmealplanner.com/api/v1/data-locator-webapi/{tenant}/meals"
_CALENDAR_URL = "https://www.fdmealplanner.com/pages/calendar/?tenantId={tenant}&accountId={account}&locationId={location}&mealPeriodId={meal}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)", "Accept": "application/json", "x-jsonresponsecase": "camel"}

MEAL_PERIODS = {1: "breakfast", 2: "lunch"}
# An item on at least this share of the window's days is a standing option,
# not the day's entrée. Only applied with enough days to tell the difference.
_STANDING_SHARE = 0.6
_MIN_DAYS_FOR_STANDING = 5


def parse_location(value: str) -> tuple[str, str, str] | None:
    parts = [p.strip() for p in (value or "").split("/")]
    return tuple(parts) if len(parts) == 3 and all(p.isdigit() for p in parts) else None


def calendar_url(tenant: str, account: str, location: str, meal_period_id: int) -> str:
    return _CALENDAR_URL.format(tenant=tenant, account=account, location=location, meal=meal_period_id)


def entrees(xml_menu_recipes: str | None) -> list[str]:
    """Entrée names from one day's xmlMenuRecipes, in menu order, deduped."""
    if not xml_menu_recipes:
        return []
    try:
        root = ET.fromstring(xml_menu_recipes)
    except ET.ParseError:
        return []
    names = []
    for d in root.iter("Details"):
        is_entree = d.get("IsEntreeType") == "1" or (d.get("MealType") or "").strip().lower() == "entree"
        name = html.unescape(d.get("ComponentEnglishName") or d.get("ComponentName") or "").strip()
        if is_entree and name:
            names.append(name)
    return list(dict.fromkeys(names))


def day_descriptions(by_day: dict[date, list[str]]) -> dict[date, str]:
    """Each day's one-line description: the rotating entrées, with the
    standing options dropped - unless that would leave the day empty, in
    which case the standing options are the menu."""
    days = [d for d, items in by_day.items() if items]
    standing: set[str] = set()
    if len(days) >= _MIN_DAYS_FOR_STANDING:
        counts: dict[str, int] = {}
        for d in days:
            for item in by_day[d]:
                counts[item] = counts.get(item, 0) + 1
        standing = {item for item, n in counts.items() if n / len(days) >= _STANDING_SHARE}
    out = {}
    for d in days:
        rotating = [i for i in by_day[d] if i not in standing]
        out[d] = ", ".join(rotating or by_day[d])[:500]
    return out


def _month_spans(start: date, end: date) -> list[tuple[date, date]]:
    """The endpoint clamps a range to its monthId, so a window crossing a
    month boundary takes one call per month."""
    spans = []
    cur = start
    while cur <= end:
        next_month = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        spans.append((cur, min(end, next_month - timedelta(days=1))))
        cur = next_month
    return spans


async def fetch_entrees(client: httpx.AsyncClient, location: tuple[str, str, str], meal_period_id: int, start: date, end: date) -> dict[date, list[str]]:
    tenant, account, loc = location
    out: dict[date, list[str]] = {}
    for span_start, span_end in _month_spans(start, end):
        resp = await client.get(
            _MEALS_URL.format(tenant=tenant),
            params={
                "menuId": 0,
                "accountId": account,
                "locationId": loc,
                "mealPeriodId": meal_period_id,
                "tenantId": tenant,
                "monthId": f"{span_start.month:02d}",
                "startDate": span_start.strftime("%Y/%m/%d"),
                "endDate": span_end.strftime("%Y/%m/%d"),
                "timeOffset": 0,
            },
            headers=_HEADERS,
        )
        resp.raise_for_status()
        for row in resp.json().get("result") or []:
            try:
                day = date.fromisoformat(row["strMenuForDate"])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= day <= end:
                out[day] = entrees(row.get("xmlMenuRecipes"))
    return out
