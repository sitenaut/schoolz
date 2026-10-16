"""Build frontend/src/lib/njZips.json: every New Jersey ZIP (Census ZCTA) with
its county and center point, for Localz's "Set my location" - so a typed ZIP
or the phone's own location is turned into a county on the phone itself and
never sent anywhere (docs/LOCALZ_DESIGN.md).

Inputs, both public Census files:
  - ZCTA-to-county relationship file (2020):
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt
  - ZCTA gazetteer (internal points), e.g.
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip
    (unzipped)

A ZIP that straddles a county line is given the county holding most of its
land. Usage:

    python3 scripts/build_nj_zips.py <relationship.txt> <gazetteer.txt> [out.json]
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

NJ_STATE_FIPS = "34"


def build(rel_path: str, gaz_path: str) -> dict:
    land_by_zip: dict[str, dict[str, int]] = {}
    with open(rel_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="|"):
            zcta, county_geoid = row["GEOID_ZCTA5_20"], row["GEOID_COUNTY_20"]
            if not zcta or not county_geoid.startswith(NJ_STATE_FIPS):
                continue
            county = row["NAMELSAD_COUNTY_20"].removesuffix(" County")
            land_by_zip.setdefault(zcta, {})
            land_by_zip[zcta][county] = land_by_zip[zcta].get(county, 0) + int(row["AREALAND_PART"] or 0)

    points: dict[str, tuple[float, float]] = {}
    with open(gaz_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = [h.strip() for h in next(reader)]
        i_zip, i_lat, i_lon = header.index("GEOID"), header.index("INTPTLAT"), header.index("INTPTLONG")
        for row in reader:
            zcta = row[i_zip].strip()
            if zcta in land_by_zip:
                points[zcta] = (round(float(row[i_lat]), 3), round(float(row[i_lon]), 3))

    # {zip: [county, lat, lon]} - compact, since the phone downloads it.
    out = {}
    for zcta in sorted(land_by_zip):
        if zcta not in points:
            continue
        county = max(land_by_zip[zcta].items(), key=lambda kv: kv[1])[0]
        out[zcta] = [county, *points[zcta]]
    return out


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    default_out = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "njZips.json"
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else default_out
    data = build(sys.argv[1], sys.argv[2])
    counties = sorted({v[0] for v in data.values()})
    if len(counties) != 21:
        sys.exit(f"expected 21 NJ counties, got {len(counties)}: {counties}")
    out_path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(data)} ZIPs across {len(counties)} counties -> {out_path}")


if __name__ == "__main__":
    main()
