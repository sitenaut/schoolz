"""Aramark MySchoolPlate ("Elevate DXP") menus - Camden City's lunch vendor
site, `<tenant>.myschoolplate.com`. The public site is a Next.js app over a
GraphQL mesh that needs no login, only a fixed API key plus Magento store
headers. A school's location is stored as "tenant/location-url-key"
(e.g. "camden/davis-family-school"):

- The mesh URL and store code are in the page's own config, so a tenant needs
  no setup: `GET https://<tenant>.myschoolplate.com/en/locations` carries
  `"commerce":{"url": <mesh>, "websiteCode": "sn_camden_en"}`. The store
  headers derive from that code.
- `getLocationRecipes(viewType: MONTHLY)` returns a whole month of days as
  `dateSkuMap` (day -> serving stations -> product skus) plus the products
  themselves. The catalog call fails without the Magento headers; the cheaper
  meal-period and category lookups don't need them.
- Stations are serving lines and their ids resolve to names through
  `Commerce_categoryList` ("Entree", "Daily Serve Entree", "Express", "Grill",
  "Vegetable", "Fruit", "Milk", "Condiments"). Entrées are the products on an
  entrée-ish line, minus sides that ride along on those lines (a dinner roll,
  a sauce). A product's own `master_recipe_type` is too loose to pick entrées
  alone - a bean side is typed "Breakfast Meat" - but it's reliable for
  recognising the sides.

Every day also offers the same standing sandwich, so the shared
`fdmealplanner.day_descriptions` rule drops items served on most days.
"""

import hashlib
import json
import re
from datetime import date

import httpx

_API_KEY = "ElevateAPIProd"
_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)", "Accept": "application/json"}
CAMPUS = "campus"
MEAL_NAMES = {"breakfast": "breakfast", "lunch": "lunch"}  # the vendor's meal-period name -> ours

_LOCATION_RE = re.compile(r"^([a-z0-9-]+)/([a-z0-9-]+)$")
_CONFIG_RE = re.compile(
    r'commerce\\*"\s*:\s*\{\\*"url\\*"\s*:\s*\\*"([^"\\]+)\\*"\s*,\s*\\*"websiteCode\\*"\s*:\s*\\*"([^"\\]+)'
)
_ENTREE_STATION_RE = re.compile(r"entr[eé]e|grill|express", re.I)
_SIDE_TYPE_RE = re.compile(
    r"^(grains|spread|salad dressing|garnish|other - starchy|vegetable|legume|rice|milk|fresh fruit|canned fruit|juice|fruit)", re.I
)

_RECIPES_QUERY = (
    "query q($campusUrlKey:String!$locationUrlKey:String!$date:String!$mealPeriod:Int$viewType:Commerce_MenuViewType!)"
    "{getLocationRecipes(campusUrlKey:$campusUrlKey locationUrlKey:$locationUrlKey date:$date mealPeriod:$mealPeriod viewType:$viewType)"
    "{locationRecipesMap{dateSkuMap{date stations{id skus{simple}}}} products{items{name sku attributes{name value}}}}}"
)
_LOCATIONS_QUERY = (
    "query q($campus_url_key:String!){getLocations(campusUrlKey:$campus_url_key)"
    "{commerceAttributes{url_key address_line_1 postal_code} aemAttributes{name}}}"
)


class Config:
    def __init__(self, url: str, website_code: str):
        self.url = url
        store = re.sub(r"_[a-z]{2}$", "", website_code)
        self.headers = {
            **_HEADERS,
            "x-api-key": _API_KEY,
            "store": website_code,
            "magento-store-view-code": website_code,
            "magento-website-code": store,
            "magento-store-code": store,
            "magento-customer-group": hashlib.sha1(b"0").hexdigest(),
        }


def parse_location(value: str) -> tuple[str, str] | None:
    m = _LOCATION_RE.match((value or "").strip())
    return (m.group(1), m.group(2)) if m else None


def location_page_url(tenant: str, key: str) -> str:
    return f"https://{tenant}.myschoolplate.com/en/location/{key}"


def parse_config(html: str) -> Config | None:
    m = _CONFIG_RE.search(html)
    return Config(m.group(1), m.group(2)) if m else None


async def fetch_config(client: httpx.AsyncClient, tenant: str) -> Config | None:
    resp = await client.get(f"https://{tenant}.myschoolplate.com/en/locations", headers=_HEADERS, follow_redirects=True)
    resp.raise_for_status()
    return parse_config(resp.text)


async def _gql(client: httpx.AsyncClient, cfg: Config, query: str, variables: dict | None = None) -> dict:
    resp = await client.get(cfg.url, params={"query": query, "variables": json.dumps(variables or {})}, headers=cfg.headers)
    body = resp.json()
    if not body.get("data"):
        message = (body.get("errors") or [{}])[0].get("message", resp.text[:200])
        raise RuntimeError(f"MySchoolPlate GraphQL error: {message}")
    return body["data"]


async def fetch_meal_periods(client: httpx.AsyncClient, cfg: Config) -> dict[str, int]:
    """{"breakfast": id, "lunch": id} - the vendor's own ids, never assumed."""
    data = await _gql(client, cfg, "{Commerce_mealPeriods{id name}}")
    return {MEAL_NAMES[p["name"].strip().lower()]: p["id"] for p in data["Commerce_mealPeriods"] if p["name"].strip().lower() in MEAL_NAMES}


async def fetch_locations(client: httpx.AsyncClient, cfg: Config) -> list[dict]:
    """[{key, name, address, postal_code}] - for matching a school to its location."""
    data = await _gql(client, cfg, _LOCATIONS_QUERY, {"campus_url_key": CAMPUS})
    return [
        {
            "key": loc["commerceAttributes"]["url_key"],
            "name": loc["aemAttributes"]["name"],
            "address": loc["commerceAttributes"]["address_line_1"],
            "postal_code": loc["commerceAttributes"]["postal_code"],
        }
        for loc in data["getLocations"]
    ]


def address_key(address: str | None) -> str | None:
    """Street number + first street word, lowercased: "1700 Park Boulevard"
    and "1700 Park Blvd., Camden, NJ" agree; "1251 Collings Road" and
    "...Avenue" do too."""
    m = re.match(r"\s*(\d+)\s+([A-Za-z]+)", address or "")
    return f"{m.group(1)} {m.group(2).lower()}" if m else None


def entrees_by_day(recipes: dict, station_names: dict[int, str]) -> dict[date, list[str]]:
    """Entrée names per day from one `getLocationRecipes` payload, in serving
    order, deduped. Only products on an entrée-ish station count, and a side
    that rides on one (roll, sauce, vegetable) is dropped by its own type."""
    products = {p["sku"]: p for p in (recipes.get("products") or {}).get("items") or []}
    out: dict[date, list[str]] = {}
    for day in (recipes.get("locationRecipesMap") or {}).get("dateSkuMap") or []:
        try:
            when = date.fromisoformat(day["date"][:10])
        except (KeyError, TypeError, ValueError):
            continue
        names: list[str] = []
        for station in day.get("stations") or []:
            if not _ENTREE_STATION_RE.search(station_names.get(station["id"], "")):
                continue
            for sku in (station.get("skus") or {}).get("simple") or []:
                product = products.get(sku)
                if not product:
                    continue
                attrs = {a["name"]: a["value"] for a in product.get("attributes") or []}
                if _SIDE_TYPE_RE.match(str(attrs.get("master_recipe_type") or "")):
                    continue
                name = str(attrs.get("marketing_name") or product.get("name") or "").strip()
                if name:
                    names.append(name)
        out[when] = list(dict.fromkeys(names))
    return out


async def fetch_month_entrees(
    client: httpx.AsyncClient, cfg: Config, location_key: str, meal_period: int, month_day: date
) -> dict[date, list[str]]:
    """Entrées for every school day of `month_day`'s month. The vendor's
    monthly view is whole weeks, so it can include a few days either side;
    the caller filters to its window."""
    recipes = (
        await _gql(
            client,
            cfg,
            _RECIPES_QUERY,
            {"campusUrlKey": CAMPUS, "locationUrlKey": location_key, "date": month_day.isoformat(), "mealPeriod": meal_period, "viewType": "MONTHLY"},
        )
    )["getLocationRecipes"]
    station_ids = sorted(
        {s["id"] for d in recipes["locationRecipesMap"]["dateSkuMap"] for s in d.get("stations") or []}
    )
    names: dict[int, str] = {}
    if station_ids:
        data = await _gql(client, cfg, "query($ids:[String]){Commerce_categoryList(filters:{ids:{in:$ids}}){id name}}", {"ids": [str(i) for i in station_ids]})
        names = {int(c["id"]): c["name"] for c in data["Commerce_categoryList"]}
    return entrees_by_day(recipes, names)
