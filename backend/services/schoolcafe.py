"""SchoolCafé (Cybersoft) menus - the public JSON API behind
www.schoolcafe.com/<SHORTNAME>/menus, the same calls that page makes for a
guest. Structured per school/date/meal/serving line with items grouped by
category, so unlike the district PDF menus there's nothing for a model to
read: each day's entrées become that day's one-line description.

Confirmed against Voorhees Township (shortname VOORHEESTWPPSNUTRISERVE,
district id 4651): one "Lunch" meal type and one "Regular" line per school.
"""

import re
from datetime import date

import httpx

_BASE = "https://webapis.schoolcafe.com/api/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)", "Accept": "application/json"}
# Menus can differ by grade band within a school; one representative grade
# per school type is enough for a one-line "what's for lunch".
_GRADE_FOR_TYPE = {"elementary": "03", "middle": "07", "high": "10", "alternative": "10", "other": "PK"}
_ENTREE_CATEGORIES = ("ENTREE", "ENTREES", "MAIN", "MAIN DISH", "ENTRÉES")
# Deliberately does NOT strip "elementary"/"middle"/"high" - confirmed real
# at Collingswood: the high school and middle school are literally named
# "Collingswood High School" and "Collingswood Middle School", nothing else
# distinguishes them, so stripping those words collapsed both to the same
# "collingswood" token and made them ambiguous against each other. The
# symmetric containment check in match_school() already handles a level
# word present on only one side (Kresson vs Kresson Elementary School), so
# there's no need to strip it as noise - only strip words that are never
# part of a real school's name.
_ORDINALS = {"1": "first", "2": "second", "3": "third", "4": "fourth", "5": "fifth", "6": "sixth", "7": "seventh", "8": "eighth", "9": "ninth"}
_NAME_NOISE = re.compile(r"\b(school|the|of|and)\b")


def _norm(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    cleaned = re.sub(r"\bmt\b", "mount", cleaned)
    # "Haines 6th Grade Center" is "Haines Sixth Grade Center" on SchoolCafé.
    for digit, word in _ORDINALS.items():
        cleaned = re.sub(rf"\b{digit}(?:st|nd|rd|th)\b", word, cleaned)
    return " ".join(_NAME_NOISE.sub(" ", cleaned).split())


def _squash(name: str) -> str:
    # Mount Laurel's SchoolCafé names are hand-typed: "Country Side Elem
    # School", "SpringvilleElem School". Spaces and "Elem" carry no identity.
    return re.sub(r"elem(?!entary)", "elementary", _norm(name).replace(" ", ""))


def _either_contains(a: set[str], b: set[str]) -> bool:
    return bool(a) and bool(b) and (a <= b or b <= a)


def match_school(our_name: str, cafe_schools: list[dict]) -> dict | None:
    """SchoolCafé's name for the same building ("Edward T Hamilton
    Elementary School" vs our "Edward T. Hamilton Elementary"). Only an
    unambiguous match counts - a wrong school's menu is worse than none."""
    ours = _norm(our_name)
    exact = [s for s in cafe_schools if _norm(s["SchoolName"]) == ours]
    if len(exact) == 1:
        return exact[0]
    ours_tokens = set(ours.split())
    # Containment has to work either direction: ours can be missing a word
    # theirs has ("Zane Elementary" vs their "Zane North Elementary
    # School"), but ours can just as easily have an extra word theirs
    # doesn't - confirmed real, Collingswood's "William P. Tatem Elementary"
    # (our middle initial) against their "William Tatem Elementary School"
    # (no middle initial) failed a ours-must-be-subset-of-theirs check even
    # though every other token lines up exactly.
    contained = [s for s in cafe_schools if _either_contains(ours_tokens, set(_norm(s["SchoolName"]).split()))]
    if len(contained) == 1:
        return contained[0]
    squashed = [s for s in cafe_schools if _squash(s["SchoolName"]) == _squash(our_name)]
    return squashed[0] if len(squashed) == 1 else None


def day_description(categories: dict[str, list[dict]]) -> str | None:
    """Entrées only ("General Tso's Chicken, Hot Ham & Cheese Sandwich") -
    sides, fruit and milk are the same every day and would bury the one
    thing a parent is looking for."""
    for key, items in categories.items():
        if key.strip().upper() in _ENTREE_CATEGORIES:
            names = [i.get("MenuItemDescription", "").strip() for i in items]
            names = [n for n in dict.fromkeys(names) if n]
            return ", ".join(names)[:500] or None
    return None


class SchoolCafeClient:
    def __init__(self, client: httpx.AsyncClient):
        self._c = client

    async def _get(self, path: str, **params):
        r = await self._c.get(_BASE + path, params=params, headers=_HEADERS)
        r.raise_for_status()
        return r.json()

    async def district_id(self, shortname: str) -> int | None:
        rows = await self._get("GetISDByShortName", shortname=shortname)
        return rows[0]["ISDId"] if rows else None

    async def schools(self, district_id: int) -> list[dict]:
        return await self._get("GetSchoolsList", districtId=district_id)

    async def day(self, school_id: str, day: date, school_type: str | None) -> dict[str, str]:
        """{meal_type: description} for one school and date."""
        d = day.strftime("%m/%d/%Y")
        out: dict[str, str] = {}
        for meal in await self._get("GetMealType", schoolid=school_id, startdate=d, enddate=d):
            meal_name = meal.get("MealTypeDescription")
            if not meal_name:
                continue
            lines = await self._get("GetServiceLine", schoolid=school_id, startdate=d, enddate=d, mealtype=meal_name)
            for line in lines:
                line_name = line.get("ServingLineDescription")
                if not line_name:
                    continue
                categories = await self._get(
                    "CalendarView/GetDailyMenuitemsByGrade",
                    SchoolId=school_id,
                    ServingDate=d,
                    ServingLine=line_name,
                    MealType=meal_name,
                    Grade=_GRADE_FOR_TYPE.get(school_type or "", "05"),
                    PersonId="null",
                )
                description = day_description(categories or {})
                if description:
                    out.setdefault(meal_name.strip().lower(), description)
                    break
        return out
