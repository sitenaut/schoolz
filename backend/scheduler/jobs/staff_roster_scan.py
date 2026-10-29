import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, School, StaffMember
from scheduler.registry import register_job
from services.apptegy import fetch_staff as fetch_apptegy_staff
from services.contact_page import CONSTITUENT_PREFIX, fetch_contacts
from services.role_pages import fetch_role_staff_scraped
from services.staff_roles import classify_role
from services.staff_roster import drop_sibling_school_staff, fetch_directory_document, fetch_roster


async def _known_contacts(db: AsyncSession, school: School) -> tuple[str, list[dict]] | None:
    """The contact-page people already on file and the page hash they were
    read from, so an unchanged page costs no model call."""
    if not school.contact_page_hash:
        return None
    rows = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.school_id == school.id, StaffMember.source_constituent_id.startswith(CONSTITUENT_PREFIX)
            )
        )
    ).scalars().all()
    people = [
        {
            "constituent_id": r.source_constituent_id,
            "full_name": r.full_name,
            "title": r.title,
            "department": r.department,
            "email": r.email,
            "phone": r.phone,
        }
        for r in rows
    ]
    return school.contact_page_hash, people


_TYPE_DEPARTMENTS = {"elementary": "ES", "middle": "MS", "high": "HS"}


def apptegy_school_departments(school: School, same_type_siblings: int) -> set[str]:
    """Department chips on a district org's directory that mean this school:
    its own `/o/<alias>` (Shamong: IMS, IMMS), its type code (Clayton: ES,
    MS, HS) when no sibling shares the type, or its own name."""
    codes = set()
    alias = re.search(r"/o/([A-Za-z0-9_-]+)", school.website_url or "")
    if alias:
        codes.add(alias.group(1).upper())
    if not same_type_siblings and school.school_type in _TYPE_DEPARTMENTS:
        codes.add(_TYPE_DEPARTMENTS[school.school_type])
    # Township of Franklin's chips are the building's full name ("Mary F. Janvier School").
    if school.name:
        codes.add(school.name.upper())
        codes.add(re.sub(r"\s+SCHOOL$", "", school.name.upper()))
    return codes


async def _apptegy_district_roster(db: AsyncSession, school: School, checked: str) -> tuple[list[dict], str]:
    """Some districts keep every school's staff on the district org, with a
    department chip per building, and leave the school orgs empty."""
    district = await db.get(District, school.district_id) if school.district_id else None
    org = next(
        (f.get("org_id") for f in (district.ics_feeds if district else []) if f.get("platform") == "apptegy" and not f.get("school_slug")),
        None,
    )
    if not org or org == school.apptegy_org_id:
        return [], checked
    siblings = (
        await db.execute(
            select(func.count()).select_from(School).where(
                School.district_id == school.district_id, School.school_type == school.school_type, School.id != school.id
            )
        )
    ).scalar_one()
    codes = apptegy_school_departments(school, siblings)
    roster = [p for p in await fetch_apptegy_staff(org) if (p["department"] or "").upper() in codes]
    return roster, f"{checked} and district org {org} ({', '.join(sorted(codes))})"


@register_job(
    kind="staff_roster.scan",
    default_name="Staff roster scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh like the other non-Smore scans
    description="Fetches and parses a school's staff directory into StaffMember records.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    contacts_added = 0  # people read from a contact or nurse page rather than a directory
    if school.apptegy_org_id:
        # Apptegy's own directory API already carries title/email/phone
        # directly - no Finalsite-style contact-page fallback needed (or
        # possible: apptegy.py has no website scraper of its own).
        roster = await fetch_apptegy_staff(school.apptegy_org_id)
        checked = f"Apptegy org {school.apptegy_org_id}"
        if not roster:
            roster, checked = await _apptegy_district_roster(db, school, checked)
    elif school.staff_directory_url:
        # A directory the school publishes as a document (PDF table, Google Slides) - there is no page to parse.
        roster = await fetch_directory_document(school.staff_directory_url, [school.short_name, school.name])
        checked = school.staff_directory_url
        # A document rarely carries the nurse; a school's own nurse page does.
        if school.website_url and not any(classify_role(e["title"]) == "nurse" for e in roster):
            have = {(e["email"] or "").lower() for e in roster}
            extra = [e for e in await fetch_role_staff_scraped(school.website_url) if e["email"] not in have]
            roster = roster + extra
            contacts_added = len(extra)
    elif school.website_url:
        roster = await fetch_roster(school.website_url, [school.short_name, school.name])
        # A directory with no titles (Voorhees: teachers' websites only) can't
        # say who the nurse or principal is - read the school's own contact
        # page for those instead.
        if not any(classify_role(e["title"]) for e in roster):
            roster_emails = {(e["email"] or "").lower() for e in roster}
            contacts, page_hash = await fetch_contacts(school.website_url, await _known_contacts(db, school))
            # An empty read isn't remembered, so the next scan asks again.
            if contacts and page_hash:
                school.contact_page_hash = page_hash
            extra = [c for c in contacts if c["email"] not in roster_emails]
            roster = roster + extra
            contacts_added = len(extra)
        checked = school.website_url
        if school.website_url and not any(classify_role(e["title"]) == "nurse" for e in roster):
            have = {(e["email"] or "").lower() for e in roster}
            extra = [e for e in await fetch_role_staff_scraped(school.website_url) if e["email"] not in have]
            roster = roster + extra
            contacts_added += len(extra)
    else:
        return "school has no website_url or apptegy_org_id configured"

    dropped_ids: set[str] = set()
    if school.website_url and not school.apptegy_org_id:
        siblings = (
            await db.execute(select(School).where(School.website_url == school.website_url, School.id != school.id))
        ).scalars().all()
        roster, dropped = drop_sibling_school_staff(
            roster, [school.short_name, school.name], [[s.short_name, s.name] for s in siblings]
        )
        dropped_ids = {e["constituent_id"] for e in dropped}

    existing = (await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))).scalars().all()
    for row in existing:
        if row.source_constituent_id in dropped_ids:
            await db.delete(row)
    existing = [row for row in existing if row.source_constituent_id not in dropped_ids]
    if any(e.get("location_filter") for e in roster):
        # The directory was narrowed to this school, so a directory person
        # (a bare numeric id) it no longer lists works elsewhere or has left.
        # Before the filter, Lenape Regional's four high schools each held
        # the whole district's staff and named four "principals".
        seen = {e["constituent_id"] for e in roster}
        for row in existing:
            if row.source_constituent_id.isdigit() and row.source_constituent_id not in seen:
                await db.delete(row)
        existing = [row for row in existing if not row.source_constituent_id.isdigit() or row.source_constituent_id in seen]
    existing_by_constituent = {s.source_constituent_id: s for s in existing}

    created = updated = 0
    now = datetime.now(UTC)
    for entry in roster:
        row = existing_by_constituent.get(entry["constituent_id"])
        if row:
            row.full_name = entry["full_name"]
            row.title = entry["title"]
            row.role = classify_role(entry["title"])
            row.department = entry["department"]
            # A directory with no addresses (Edlio) mustn't wipe one filled in from the NJ DOE directory.
            row.email = entry["email"] or row.email
            row.phone = entry["phone"]
            row.last_synced_at = now
            updated += 1
        else:
            db.add(
                StaffMember(
                    school_id=school.id,
                    source_constituent_id=entry["constituent_id"],
                    full_name=entry["full_name"],
                    title=entry["title"],
                    role=classify_role(entry["title"]),
                    department=entry["department"],
                    email=entry["email"],
                    phone=entry["phone"],
                )
            )
            created += 1

    # The NJ DOE principal (scripts/import_njdoe_contacts.py) is only a stand-in for a school
    # with no roster of its own; once the school's own site names a principal, drop it.
    if any(classify_role(e["title"]) == "principal" for e in roster):
        for row in existing:
            if row.source_constituent_id == "njdoe:principal":
                await db.delete(row)

    if not roster:
        return (
            f"WARNING[no_staff_found]: no staff found at {checked} - site may use a directory "
            "structure this parser doesn't recognize (or genuinely has no public directory)"
        )
    note = f" ({contacts_added} from the contact page)" if contacts_added else ""
    return f"roster: {created} new, {updated} updated, {len(roster)} total{note}"
