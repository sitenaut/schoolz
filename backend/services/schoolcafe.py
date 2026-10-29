"""SchoolCafé (Cybersoft) menus - the public JSON API behind
www.schoolcafe.com/<SHORTNAME>/menus, the same calls that page makes for a
guest. Structured per school/date/meal/serving line with items grouped by
category, so unlike the district PDF menus there's nothing for a model to
read: each day's entrées become that day's one-line description.

Confirmed against Voorhees Township (shortname VOORHEESTWPPSNUTRISERVE,
district id 4651): one "Lunch" meal type and one "Regular" line per school.
"""

import asyncio
import re
from datetime import date
from difflib import SequenceMatcher

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
# Lindenwold's own "School Five" is "School 5" on SchoolCafé.
_CARDINALS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _norm(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    cleaned = re.sub(r"\bmt\b", "mount", cleaned)
    # Bellmawr's Bell Oaks is "Middle School" on its own site and "Upper
    # Elementary School" on SchoolCafé (and the state directory).
    cleaned = re.sub(r"\bupper elementary\b", "middle", cleaned)
    # "Haines 6th Grade Center" is "Haines Sixth Grade Center" on SchoolCafé.
    for digit, word in _ORDINALS.items():
        cleaned = re.sub(rf"\b{digit}(?:st|nd|rd|th)\b", word, cleaned)
    cleaned = re.sub(r"\b(" + "|".join(_CARDINALS) + r")\b", lambda m: _CARDINALS[m.group(1)], cleaned)
    return " ".join(_NAME_NOISE.sub(" ", cleaned).split())


def _squash(name: str) -> str:
    # Mount Laurel's SchoolCafé names are hand-typed: "Country Side Elem
    # School", "SpringvilleElem School". Spaces and "Elem" carry no identity.
    return re.sub(r"elem(?!entary)", "elementary", _norm(name).replace(" ", ""))


_LEVEL_WORDS = {"elementary", "elem", "middle", "junior", "senior", "high", "primary", "intermediate", "ms", "hs"}  # Burlington City's "MS/HS"


def _core_tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if (len(t) > 1 or t.isdigit()) and t not in _LEVEL_WORDS}


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
    if len(squashed) == 1:
        return squashed[0]
    # Last resort: the same name with a different level word and/or a middle
    # initial (Mount Ephraim's "Raymond W. Kershaw Middle School" is "Raymond
    # Kershaw Elementary" on SchoolCafé). Only when exactly one site is left.
    core = _core_tokens(our_name)
    cored = [s for s in cafe_schools if core and _core_tokens(s["SchoolName"]) == core]
    if len(cored) == 1:
        return cored[0]
    # Hand-typed names carry typos (Burlington City's "Wilber Watts" for
    # Wilbur): same core, each name token equal or a near-miss.
    fuzzy = [s for s in cafe_schools if core and _tokens_nearly_equal(core, _core_tokens(s["SchoolName"]))]
    return fuzzy[0] if len(fuzzy) == 1 else None


_SITE_TYPE = {"elementary": "elementary", "middle": "middle", "high": "high"}


def match_by_site_type(school, district_schools, cafe_schools: list[dict]) -> dict | None:
    """When no name matches (Northern Burlington's "NBC Regional High School"
    for "Northern Burlington County Regional High School"), the one site of
    the school's own type, if the district has exactly one school of that
    type and SchoolCafé exactly one site of it."""
    wanted = _SITE_TYPE.get(school.school_type or "")
    if not wanted or sum(1 for s in district_schools if s.school_type == school.school_type) != 1:
        return None
    sites = [c for c in cafe_schools if (c.get("SiteTypeDescription") or "").strip().lower() == wanted]
    return sites[0] if len(sites) == 1 else None


def _tokens_nearly_equal(a: set[str], b: set[str]) -> bool:
    if len(a) != len(b):
        return False
    remaining = set(b)
    for token in sorted(a):
        hit = next((o for o in remaining if o == token or (len(token) >= 5 and SequenceMatcher(None, token, o).ratio() >= 0.8)), None)
        if hit is None:
            return False
        remaining.discard(hit)
    return True


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


# SchoolCafé's API answers 503s in bursts: Barrington's scan, then due at
# 3:00 ET, got one every night for a week on a different endpoint each time,
# while neighbours at 3:04-3:22 didn't. One scan makes dozens of calls, so a
# single blip failed the whole district. Retried after these waits, then raised.
_RETRY_STATUSES = {502, 503, 504}
_RETRY_DELAYS_S = (5.0, 20.0)


class SchoolCafeClient:
    def __init__(self, client: httpx.AsyncClient):
        self._c = client

    async def _get(self, path: str, **params):
        for delay in (*_RETRY_DELAYS_S, None):
            r = await self._c.get(_BASE + path, params=params, headers=_HEADERS)
            if r.status_code not in _RETRY_STATUSES or delay is None:
                break
            await asyncio.sleep(delay)
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
