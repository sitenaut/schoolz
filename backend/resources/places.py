"""Where a listing is, when its source gives only a ZIP.

ChildCareNJ has no coordinates, and a provider typing an address into the
portal has none either; the ZIP's center (Census ZCTA internal point) is
close enough to sort "closest first" - and for a family child care home it
is deliberately not the home. `nj_zips.json` is the same table the browser
uses for "Set my location" (scripts/build_nj_zips.py writes both copies).
"""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path


@cache
def _zips() -> dict[str, list]:
    return json.loads((Path(__file__).with_name("nj_zips.json")).read_text(encoding="utf-8"))


def zip_point(postal_code: str | None) -> tuple[float, float] | None:
    """(lat, lon) of a New Jersey ZIP's center, or None if it isn't one."""
    row = _zips().get((postal_code or "").strip()[:5])
    return (row[1], row[2]) if row else None
