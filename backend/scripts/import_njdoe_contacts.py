"""Upsert NJ DOE directory contacts (principal, anti-bullying specialist,
homeless liaison) into StaffMember for every tracked school.

    python scripts/import_njdoe_contacts.py /path/NJPubSchool.csv [--district NAME ...] [--apply]

--district limits the run to districts whose name contains NAME (case-
insensitive; repeat it for several) - what a newly onboarded district wants,
since without it every tracked school is touched.

The CSV is kept at backend/seed/njdoe/NJPubSchool.csv (the state's site is behind
a bot wall, so it is re-downloaded by hand each year). Run this locally only;
prod gets the rows it wrote through the API, carried with the district's other
results by scripts/seed-with-results.sh (`--results-only` for a district
already on prod) - never a shell on a prod machine or a laptop against the
prod DB.

Dry run unless --apply. The principal rule is njdoe_directory.apply_contacts':
a school's own roster principal wins, and only gains the state's email."""

import asyncio
import sys

sys.path.insert(0, ".")
from sqlalchemy import select  # noqa: E402

import database  # noqa: E402
from models import District, School  # noqa: E402
from services import njdoe_directory as nj  # noqa: E402


def in_districts(district_name: str, wanted: list[str]) -> bool:
    return not wanted or any(w.lower() in district_name.lower() for w in wanted)


async def main(path: str, apply: bool, districts: list[str]) -> None:
    rows = nj.read_rows(path)
    async with database.SessionLocal() as db:
        pairs = (await db.execute(select(School, District).join(District, District.id == School.district_id))).all()
        pairs = [p for p in pairs if in_districts(p[1].name, districts)]
        if districts and not pairs:
            sys.exit(f"no tracked district matches {districts}")
        for school, district in sorted(pairs, key=lambda p: (p[1].name, p[0].name)):
            row = nj.match_row(rows, district.name, school.name)
            if not row:
                print(f"NO MATCH  {district.name} / {school.name}")
                continue
            added, patched = await nj.apply_contacts(db, school.id, nj.contacts(row))
            print(f"ok        {school.name} <- {row['School Name']}: {list(nj.contacts(row))} (+{added}, {patched} email(s) added to roster rows)")
        if apply:
            await db.commit()
        else:
            await db.rollback()
            print("dry run - pass --apply to write")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv_path")
    parser.add_argument("--district", action="append", default=[], metavar="NAME")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, args.apply, args.district))
