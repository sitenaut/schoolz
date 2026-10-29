"""Build backend/resources/nj_zip_towns.json: the town each New Jersey ZIP
in nj_zips.json is known by - the post office's name for it, the one on the
address line ("08034" is "Cherry Hill", "08012" is "Blackwood"). Neighborz
lists a bill by this town (docs/NEIGHBORZ_DESIGN.md).

Input: the GeoNames US postal code file, CC BY 4.0, credited on the
Neighborz page:
  https://download.geonames.org/export/zip/US.zip (unzipped: US.txt)

    python3 scripts/build_nj_zip_towns.py <US.txt>
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIPS = ROOT / "backend" / "resources" / "nj_zips.json"
OUT = ROOT / "backend" / "resources" / "nj_zip_towns.json"

# GeoNames spellings that read oddly on a listing.
RENAME = {"Township Of Washington": "Washington Township"}


def build(geonames_path: str) -> dict[str, str]:
    names: dict[str, str] = {}
    with open(geonames_path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) > 4 and row[0] == "US" and row[4] == "NJ":
                names[row[1]] = RENAME.get(row[2], row[2])
    zips = json.loads(ZIPS.read_text(encoding="utf-8"))
    missing = sorted(z for z in zips if z not in names)
    if missing:
        sys.exit(f"{len(missing)} ZIPs in nj_zips.json have no town: {missing[:10]}")
    return {z: names[z] for z in sorted(zips)}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    data = build(sys.argv[1])
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data)} ZIPs, {len(set(data.values()))} towns -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
