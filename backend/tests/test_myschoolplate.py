"""Aramark MySchoolPlate: config discovery, address matching, and picking
entrées out of a month of serving stations."""

import json
from datetime import date

import httpx
import pytest

from services import myschoolplate as m


def _product(sku, name, rtype, marketing=None):
    attrs = [{"name": "master_recipe_type", "value": rtype}]
    if marketing:
        attrs.append({"name": "marketing_name", "value": marketing})
    return {"sku": sku, "name": name, "attributes": attrs}


RECIPES = {
    "locationRecipesMap": {
        "dateSkuMap": [
            {
                "date": "2026-10-05",
                "stations": [
                    {"id": 1, "skus": {"simple": ["a", "b"]}},  # Entree: a taco and its coleslaw
                    {"id": 2, "skus": {"simple": ["c"]}},  # Daily Serve Entree: the standing sandwich
                    {"id": 3, "skus": {"simple": ["d", "e"]}},  # Express: a salad and a roll
                    {"id": 4, "skus": {"simple": ["f"]}},  # Vegetable: not an entrée line
                    {"id": 5, "skus": {"simple": ["g"]}},  # Milk
                ],
            },
            {"date": "garbage", "stations": []},
            {"date": "2026-10-06", "stations": [{"id": 1, "skus": {"simple": ["a", "missing"]}}]},
        ]
    },
    "products": {
        "items": [
            _product("a", "TACO, FISH", "Taco", "Fish Tacos"),
            _product("b", "SLAW", "Vegetables - Non-Green", "Coleslaw"),
            _product("c", "SUN BUTTER", "Traditional Sandwich", "Sun Butter & Jelly Sandwich"),
            _product("d", "CHEF SALAD", "Salad Entrée", "Chef Salad"),
            _product("e", "ROLL", "Grains", "Dinner Roll"),
            _product("f", "BEANS", "Breakfast Meat", "Garbanzo Beans"),
            _product("g", "MILK", "Milk", "1% Milk"),
        ]
    },
}
STATIONS = {1: "Entree", 2: "Daily Serve Entree", 3: "Express", 4: "Vegetable", 5: "Milk"}


def test_entrees_come_from_entree_lines_without_their_sides():
    by_day = m.entrees_by_day(RECIPES, STATIONS)
    assert by_day[date(2026, 10, 5)] == ["Fish Tacos", "Sun Butter & Jelly Sandwich", "Chef Salad"]
    # A sku the products list doesn't carry is skipped; a bad date row is ignored.
    assert by_day[date(2026, 10, 6)] == ["Fish Tacos"]
    assert len(by_day) == 2


def test_an_unnamed_station_is_not_an_entree_line():
    assert m.entrees_by_day(RECIPES, {}) == {date(2026, 10, 5): [], date(2026, 10, 6): []}


def test_parse_location():
    assert m.parse_location("camden/davis-family-school") == ("camden", "davis-family-school")
    assert m.parse_location("camden") is None
    assert m.parse_location("a/b/c") is None
    assert m.parse_location("") is None
    assert m.location_page_url("camden", "x") == "https://camden.myschoolplate.com/en/location/x"


def test_config_is_read_from_the_pages_escaped_json_and_headers_derive_from_it():
    html = r'<script>self.__next_f.push([1,"{\"commerce\":{\"url\":\"https://api.example.test/mesh/graphql\",\"websiteCode\":\"sn_camden_en\"},\"x\":1}"])</script>'
    cfg = m.parse_config(html)
    assert cfg.url == "https://api.example.test/mesh/graphql"
    assert cfg.headers["store"] == cfg.headers["magento-store-view-code"] == "sn_camden_en"
    assert cfg.headers["magento-website-code"] == cfg.headers["magento-store-code"] == "sn_camden"
    assert cfg.headers["x-api-key"]
    assert m.parse_config("<html>no config</html>") is None


@pytest.mark.parametrize(
    "a,b",
    [
        ("1700 Park Boulevard", "1700 Park Blvd., Camden, NJ 08104"),
        ("1251 Collings Avenue", "1251 Collings Road, Camden, NJ 08104"),
    ],
)
def test_address_key_ignores_street_suffix_and_town(a, b):
    assert m.address_key(a) == m.address_key(b) is not None


def test_address_key_without_a_street_number():
    assert m.address_key("Main Office") is None and m.address_key(None) is None


@pytest.mark.anyio
async def test_fetch_month_entrees_resolves_station_names_over_graphql():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        query = request.url.params["query"]
        if "getLocationRecipes" in query:
            variables = json.loads(request.url.params["variables"])
            assert variables["viewType"] == "MONTHLY" and variables["locationUrlKey"] == "davis-family-school"
            return httpx.Response(200, json={"data": {"getLocationRecipes": RECIPES}})
        ids = json.loads(request.url.params["variables"])["ids"]
        return httpx.Response(200, json={"data": {"Commerce_categoryList": [{"id": int(i), "name": STATIONS[int(i)]} for i in ids]}})

    cfg = m.Config("https://api.example.test/graphql", "sn_camden_en")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        by_day = await m.fetch_month_entrees(client, cfg, "davis-family-school", 25, date(2026, 10, 7))
    assert by_day[date(2026, 10, 5)][0] == "Fish Tacos"
    assert all(r.headers["store"] == "sn_camden_en" for r in seen)
