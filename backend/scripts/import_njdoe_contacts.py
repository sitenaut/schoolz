"""Upsert NJ DOE directory contacts (principal, anti-bullying specialist,
homeless liaison) into StaffMember for every tracked school.

    python scripts/import_njdoe_contacts.py /path/NJPubSchool.csv [--apply]

The CSV is kept at backend/seed/njdoe/NJPubSchool.csv (the state's site is behind
a bot wall, so it is re-downloaded by hand each year). For prod, copy it onto the
scheduler machine and run this there as a one-off - never from a laptop against
the prod DB.

Dry run unless --apply. A school that already has a principal from its own
roster keeps that one and the state's principal row is skipped for it - except
that, when it is the same person and the roster row has no email, the state's
email (kept only if it contains the person's surname) is copied onto it."""

import asyncio
import sys

sys.path.insert(0, ".")
import database  # noqa: E402
from sqlalchemy import select  # noqa: E402

from models import District, School, StaffMember  # noqa: E402
from services import njdoe_directory as nj  # noqa: E402
from services.staff_roles import classify_role  # noqa: E402


async def main(path: str, apply: bool) -> None:
    rows = nj.read_rows(path)
    async with database.SessionLocal() as db:
        pairs = (await db.execute(select(School, District).join(District, District.id == School.district_id))).all()
        for school, district in sorted(pairs, key=lambda p: (p[1].name, p[0].name)):
            row = nj.match_row(rows, district.name, school.name)
            if not row:
                print(f"NO MATCH  {district.name} / {school.name}")
                continue
            existing = (await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))).scalars().all()
            by_id = {s.source_constituent_id: s for s in existing}
            own_principals = [s for s in existing if s.role == "principal" and not s.source_constituent_id.startswith("njdoe:")]
            added = patched = 0
            for cid, p in nj.contacts(row).items():
                if cid == "njdoe:principal" and own_principals:
                    for own in own_principals:
                        if p["email"] and not own.email and nj.same_person(own.full_name, p["full_name"]):
                            own.email = p["email"]
                            patched += 1
                    continue
                cur = by_id.get(cid)
                if cur:
                    cur.full_name, cur.title, cur.email, cur.role = p["full_name"], p["title"], p["email"], classify_role(p["title"])
                else:
                    db.add(StaffMember(school_id=school.id, source_constituent_id=cid, full_name=p["full_name"],
                                       title=p["title"], email=p["email"], role=classify_role(p["title"])))
                    added += 1
            print(f"ok        {school.name} <- {row['School Name']}: {list(nj.contacts(row))} (+{added}, {patched} email(s) added to roster rows)")
        if apply:
            await db.commit()
        else:
            await db.rollback()
            print("dry run - pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--apply" in sys.argv))
