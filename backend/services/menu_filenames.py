"""Reads a menu file's name without knowing how a district orders its parts.

lunch_menu.py has a classifier per district's naming scheme, each pinned to one
order of month, year, band and meal. The districts onboarded since publish
files whose names carry the same four facts in yet another order:

    october rough lunch.pdf                      Mantua (a month, a filler word, the meal)
    2026_Oct_Breakfast_2.pdf                     Mantua (year first)
    K-6 Aura LunchMenu_2026-10-OCT.pptx.png      Elk (a Drive title; "PREK-V-..." is its Pre-K twin)
    FTS-LunchMenu_2026-10-OCT.pdf                Township of Franklin
    SWE-ELEMLUNCHMENU-OCT26.pdf                  Swedesboro-Woolwich (glued, a 2-digit year)
    SWE-HILLLUNCHMENU-NOV2026.pdf                ... and Hill School's own
    Secondary Menu October 2026.pdf              Deptford (MS and HS on one menu)

So this finds each fact wherever it sits. It is the fallback: the per-district
classifiers still run first, and only a page none of them reads comes here.
What the name can't say, it leaves out (no band -> `bands` is None, no year ->
the nearest one to today), and a file naming nothing menu-like is not one.
"""

import re
from datetime import date, datetime
from urllib.parse import unquote
from zoneinfo import ZoneInfo

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")

_MONTH_RE = re.compile(
    r"(?<![a-z])(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)(?![a-z])",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_NUMERIC_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-_.](0[1-9]|1[0-2])(?!\d)")
_TWO_DIGIT_YEAR_RE = re.compile(r"^(\d{2})(?!\d)")
_EXTENSIONS_RE = re.compile(r"(\.[a-z0-9]{2,5})+$", re.IGNORECASE)
# Never a menu, even with a month in the name: nutrition tables, allergen sheets, summer programs.
_NOT_A_MENU_RE = re.compile(r"spreadsheet|nutrition|allergen|summer|snack|application|policy|newsletter|minutes|wellness", re.IGNORECASE)

# Each pattern finds one band; a name can name more than one ("MS-HS", "Secondary").
_BANDS = (
    (re.compile(r"pre-?k|preschool", re.IGNORECASE), ("other",)),
    (re.compile(r"elem|(?<![a-z0-9])k-?[1-8](?![0-9a-z])", re.IGNORECASE), ("elementary",)),
    (re.compile(r"secondary|mshs|hsms|jr-?sr|(?<![0-9])[67]-?12(?![0-9])", re.IGNORECASE), ("middle", "high")),
    (re.compile(r"middle|(?<![a-z])ms(?![a-z])", re.IGNORECASE), ("middle",)),
    (re.compile(r"high|(?<![a-z])hs(?![a-z])", re.IGNORECASE), ("high",)),
)
# Words in a school's name that name no school in particular.
_GENERIC_SCHOOL_WORDS = {
    "school", "schools", "elementary", "middle", "high", "junior", "senior", "township", "regional", "public", "district",
    "academy", "early", "childhood", "center", "learning", "primary", "intermediate", "memorial", "street", "road",
}


def _infer_year(month_idx: int, today: date) -> int:
    return min((today.year - 1, today.year, today.year + 1), key=lambda y: abs((date(y, month_idx + 1, 15) - today).days))


def _bands(stem: str) -> tuple[str, ...] | None:
    found: list[str] = []
    for pattern, types in _BANDS:
        if pattern.search(stem):
            if types == ("other",):
                return types  # a Pre-K file is the Pre-K's, whatever else its name says
            found += [t for t in types if t not in found]
    return tuple(found) or None


def classify(url: str, today: date | None = None) -> dict | None:
    """{"meal_type", "period_label", "_sort", "bands", "stem"} for a monthly
    menu file's name, or None when it isn't one. `bands` is a tuple of school
    types (None when the name names none); `stem` is the lowercased name
    without its extension, for matching school names."""
    name = unquote(url.rsplit("/", 1)[-1].split("?", 1)[0])
    stem = _EXTENSIONS_RE.sub("", name)
    if _NOT_A_MENU_RE.search(stem):
        return None

    month_m = _MONTH_RE.search(stem)
    numeric_m = _NUMERIC_MONTH_RE.search(stem)
    if month_m:
        month_idx = next(i for i, m in enumerate(MONTHS) if m.startswith(month_m.group(1).lower()[:3]))
        year_m = _YEAR_RE.search(stem)
        short_m = _TWO_DIGIT_YEAR_RE.match(stem[month_m.end():]) if not year_m else None
        year = int(year_m.group(1)) if year_m else 2000 + int(short_m.group(1)) if short_m else None
    elif numeric_m:
        month_idx, year = int(numeric_m.group(2)) - 1, int(numeric_m.group(1))
    else:
        return None
    if year is None:
        year = _infer_year(month_idx, today or datetime.now(ZoneInfo("America/New_York")).date())

    lowered = stem.lower()
    if "breakfast" in lowered:
        meal = "breakfast"
    elif "lunch" in lowered or "menu" in lowered:
        meal = "lunch"
    elif not re.search(r"[a-z]", _YEAR_RE.sub("", _MONTH_RE.sub("", lowered))):
        meal = "lunch"  # "2026October.pdf": nothing but the month, so it is the page's menu
    else:
        return None

    return {
        "meal_type": meal,
        "period_label": f"{MONTHS[month_idx].title()} {year}",
        "_sort": (year, month_idx),
        "bands": _bands(stem),
        "stem": lowered,
    }


def named_school(stem: str, schools: list[dict]) -> dict | None:
    """The one school whose own name `stem` contains ("SWE-HILLLUNCHMENU": Hill),
    or None. A word must be four letters or more and belong to no other school
    of the district, so "Elementary" and a name two schools share name nobody."""
    words: dict[str, set[int]] = {}
    for i, school in enumerate(schools):
        for text in (school.get("name"), school.get("short_name")):
            for word in re.findall(r"[a-z]{4,}", (text or "").lower()):
                if word not in _GENERIC_SCHOOL_WORDS:
                    words.setdefault(word, set()).add(i)
    hits = {next(iter(owners)) for word, owners in words.items() if len(owners) == 1 and word in stem}
    return schools[hits.pop()] if len(hits) == 1 else None
