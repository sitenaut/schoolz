from datetime import date
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, School, SchoolDocument, SmoreNewsletter
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.class_years import academic_year_start
from services.school_documents import (
    discover_district_letter_days,
    discover_from_smore,
    discover_from_website,
    keep_own_school_bell_schedules,
    school_name_tokens,
)


@register_job(
    kind="documents.scan",
    default_name="Documents scan",
    default_cron="0 */12 * * *",  # every 12h - the website side of this is a public-source scan, kept fresh like the others
    description="Discovers a school's reference documents (handbook, bell schedule) from its site and Smore newsletters.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    found: list[dict] = []
    site_error: Exception | None = None
    if school.website_url:
        try:
            for entry in await discover_from_website(school.website_url):
                found.append({**entry, "source": "website"})
        except Exception as exc:
            # Don't let a site fetch failure override a Smore-side find
            # below - only fatal if nothing else turns up anything either.
            site_error = exc
    # Elementary rotation calendars are district-wide and live on the district home page.
    if school.school_type == "elementary" and school.district_id and not any(e["doc_type"] == "letter_day_schedule" for e in found):
        district = (await db.execute(select(District).where(District.id == school.district_id))).scalar_one_or_none()
        if district and district.website_url and district.website_url.rstrip("/") != (school.website_url or "").rstrip("/"):
            try:
                for entry in await discover_district_letter_days(district.website_url):
                    found.append({**entry, "source": "district_website"})
            except Exception:
                pass  # the school's own site result still stands
    for entry in await discover_from_smore(db, school_id):
        found.append({**entry, "source": "newsletter"})
    district_name = None
    siblings: list[School] = []
    if school.district_id:
        district_name = (await db.execute(select(District.name).where(District.id == school.district_id))).scalar_one_or_none()
        siblings = (await db.execute(select(School).where(School.district_id == school.district_id, School.id != school.id))).scalars().all()
    found, bells_narrowed = keep_own_school_bell_schedules(
        found,
        school_name_tokens(school.name, school.short_name, district_name),
        [school_name_tokens(s.name, s.short_name, district_name) for s in siblings],
    )

    if not found:
        if site_error is not None:
            # A real fetch failure (site down, timeout, scraper 502, ...)
            # is worth a classified error_code + traceback (see
            # scheduler/errors.py), not a generic content-not-found
            # warning that gives no clue what actually went wrong.
            raise site_error
        # State exactly what was checked - a bare "no_documents_found" told
        # an admin nothing about which URL was fetched or whether there was
        # even a newsletter to look at (a real complaint: "which document
        # were you trying to fetch that you didn't find? it doesn't say").
        checked = [f"site: {school.website_url}" if school.website_url else "site: none (no website_url set)"]
        newsletter_count = (
            await db.execute(select(func.count()).select_from(SmoreNewsletter).where(SmoreNewsletter.school_id == school_id))
        ).scalar()
        checked.append(f"{newsletter_count} newsletter(s) scanned" if newsletter_count else "no newsletters tracked")
        return f"WARNING[no_documents_found]: no handbook or bell schedule found - checked {', '.join(checked)}"

    for entry in found:
        if not entry.get("academic_year"):
            record_parse_issue("documents.scan", "no_matches", school_id=school_id, sample=entry["title"][:200])

    doc_types = {e["doc_type"] for e in found}
    existing = (
        await db.execute(select(SchoolDocument).where(SchoolDocument.school_id == school_id, SchoolDocument.doc_type.in_(doc_types)))
    ).scalars().all()
    existing_by_key = {(d.doc_type, d.url): d for d in existing}

    created = updated = 0
    for entry in found:
        row = existing_by_key.get((entry["doc_type"], entry["url"]))
        if row:
            row.title = entry["title"]
            row.academic_year = entry["academic_year"]
            updated += 1
        else:
            row = SchoolDocument(
                school_id=school_id,
                doc_type=entry["doc_type"],
                title=entry["title"],
                url=entry["url"],
                academic_year=entry["academic_year"],
                source=entry["source"],
            )
            db.add(row)
            existing_by_key[(entry["doc_type"], entry["url"])] = row
            created += 1

    await db.flush()

    # Year preference is per doc_type - a 2026-27 bell schedule shouldn't
    # retire a 2025-26 handbook that hasn't been republished yet. A narrowing
    # that left none (every listed bell schedule was a sibling's) still
    # retires the ones stored before.
    for doc_type in doc_types | ({"bell_schedule"} if bells_narrowed else set()):
        docs = (
            await db.execute(select(SchoolDocument).where(SchoolDocument.school_id == school_id, SchoolDocument.doc_type == doc_type))
        ).scalars().all()
        # A Google sign-in URL is never the document (older scans stored the
        # Drive viewer's sign-in link, with a year read off the viewer page),
        # and neither is one an admin dismissed.
        dead = {d.id for d in docs if d.dismissed_at or urlparse(d.url).hostname == "accounts.google.com"}
        found_urls = {e["url"] for e in found if e["doc_type"] == doc_type}
        if doc_type == "letter_day_schedule" or (doc_type == "bell_schedule" and bells_narrowed):
            # A replaced rotation sheet gets a new URL; only what this run found is live.
            live = {d.id for d in docs if d.id not in dead and d.url in found_urls}
        else:
            live = _current_ids(docs, dead, found_urls, site_unread=site_error is not None)
        for d in docs:
            d.is_current = d.id in live

    summary = ", ".join(f"{t}: {sum(1 for e in found if e['doc_type'] == t)}" for t in sorted(doc_types))
    return f"documents: {created} new, {updated} updated ({summary})"


def _current_ids(docs: list[SchoolDocument], dead: set[str], found_urls: set[str], site_unread: bool, today: date | None = None) -> set[str]:
    """Which of one doc type's rows are current. Only what this run found
    counts: a stored "2024-2025 Handbook" the site no longer lists used to
    outrank the undated "Student Handbook" it lists now, and stayed current
    for as long as it held the highest year. When the site couldn't be read,
    its rows weren't checked, so they still count.

    Among those, the latest year wins (nav and newsletter genuinely
    disagree), and a dated row beats an undated one, except when the latest
    year is already over: an undated handbook found today is more likely
    this year's than last year's is."""
    seen = [d for d in docs if d.id not in dead and (d.url in found_urls or (site_unread and d.source == "website"))]
    dated = [d for d in seen if d.academic_year]
    if not dated:
        return {d.id for d in seen}
    max_year = max(d.academic_year for d in dated)
    undated = [d for d in seen if not d.academic_year]
    if undated and int(max_year[:4]) < academic_year_start(today):
        return {d.id for d in undated}
    return {d.id for d in dated if d.academic_year == max_year}
