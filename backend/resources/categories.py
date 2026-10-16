"""Localz categories, and how Inform USA (211 LA) taxonomy codes map to them.

The codes are hierarchical ("BD-1800.2000" is Food Pantries, under "BD"
Food, under "B" Basic Needs), so a code takes the categories of its longest
matching prefix. A code can feed more than one category (child care
expense assistance is both money and kids). A code with no matching prefix
gets no category: the record is still searchable by text, just not listed
under a tab.
"""
from __future__ import annotations

# Order is the nav order.
CATEGORIES: dict[str, str] = {
    "food": "Food",
    "housing-bills": "Housing & Bills",
    "health": "Health",
    "kids-family": "Kids & Family",
    "money-work": "Money & Work",
    "legal-safety": "Legal & Safety",
    "everyday-needs": "Everyday Needs",
}

_PREFIXES: dict[str, tuple[str, ...]] = {
    # B - Basic Needs
    "BD": ("food",),
    "BH": ("housing-bills",),
    "BV": ("housing-bills",),
    "BM": ("everyday-needs",),
    "BM-6500.1500-150": ("everyday-needs", "kids-family"),  # diapers
    "BT": ("everyday-needs",),
    # D - Consumer Services
    "DM": ("money-work",),
    "DT": ("money-work",),  # tax preparation
    # F - Criminal Justice and Legal Services
    "F": ("legal-safety",),
    # H - Education
    "HD": ("kids-family",),  # early childhood education, Head Start, preschool
    "HH": ("money-work",),  # adult education: GED, ESL
    "HL": ("kids-family",),
    # L - Health Care
    "L": ("health",),
    "LR-1700": ("health", "kids-family"),  # early intervention
    # N - Income Support and Employment
    "N": ("money-work",),
    "NL-3000.1500": ("money-work", "kids-family"),  # child care expense assistance
    # P - Individual and Family Life
    "PH": ("kids-family",),
    "PH-2950": ("everyday-needs",),  # holiday programs: baskets, toys
    "PL": ("kids-family",),  # recreation, camps
    "PN": ("health",),  # support groups
    # R - Mental Health and Substance Use Disorder Services
    "R": ("health",),
    # T - Organizational/Community Services (mostly referral lines; only the
    # codes NJ 211's own topic tiles use are mapped)
    "TH-2600.1880": ("housing-bills",),  # warming centers
}


def categories_for_code(code: str) -> tuple[str, ...]:
    code = (code or "").strip().upper()
    best = ""
    for prefix in _PREFIXES:
        if code.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return _PREFIXES.get(best, ())


def categories_for_codes(codes: list[str]) -> list[str]:
    found = {c for code in codes for c in categories_for_code(code)}
    return [key for key in CATEGORIES if key in found]
