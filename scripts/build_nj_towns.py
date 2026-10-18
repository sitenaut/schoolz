"""Writes frontend/src/lib/njTowns.json: New Jersey's towns, each with its county.

Two Census lists (public domain), so the list has both what a town
legally is and what people call it:
- county subdivisions: the 564 municipalities ("Cherry Hill township")
- places: incorporated places and CDPs ("Blackwood CDP", which is part of
  Gloucester Township but is what Blackwood residents write)

A municipality's county is in its GEOID; a place's comes from the Census
place-by-county file (a place in two counties is listed in both). Suffixes are dropped
("Cherry Hill", not "Cherry Hill township"); the same name in two counties
stays twice, told apart by the county.

    python3 scripts/build_nj_towns.py [YEAR]
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2024"
BASE = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{YEAR}_Gazetteer/{YEAR}_gaz_{{}}_34.txt"
PLACE_BY_COUNTY = "https://www2.census.gov/geo/docs/reference/codes2020/place_by_cou/st34_nj_place_by_county2020.txt"

COUNTIES = {
    "001": "Atlantic", "003": "Bergen", "005": "Burlington", "007": "Camden", "009": "Cape May",
    "011": "Cumberland", "013": "Essex", "015": "Gloucester", "017": "Hudson", "019": "Hunterdon",
    "021": "Mercer", "023": "Middlesex", "025": "Monmouth", "027": "Morris", "029": "Ocean",
    "031": "Passaic", "033": "Salem", "035": "Somerset", "037": "Sussex", "039": "Union", "041": "Warren",
}
SUFFIX = re.compile(r"\s+(city|township|borough|town|village|CDP)$", re.IGNORECASE)


def rows(url: str, delimiter: str = "\t") -> list[dict]:
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("latin-1")
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text), delimiter=delimiter)]


def main() -> None:
    towns: set[tuple[str, str]] = set()
    for row in rows(BASE.format("cousubs")):
        county = COUNTIES.get(row["GEOID"][2:5])
        name = SUFFIX.sub("", row["NAME"])
        if county and not name.startswith("County subdivisions"):
            towns.add((name, county))
    for row in rows(PLACE_BY_COUNTY, delimiter="|"):
        county = COUNTIES.get(row["COUNTYFP"])
        if county:
            towns.add((SUFFIX.sub("", row["PLACENAME"]), county))

    out = sorted(towns, key=lambda t: (t[0].lower(), t[1]))
    path = ROOT / "frontend/src/lib/njTowns.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(out)} towns -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
