from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolDocument
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.school_documents import discover_from_smore, discover_from_website


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
    if school.website_url:
        for entry in await discover_from_website(school.website_url):
            found.append({**entry, "source": "website"})
    for entry in await discover_from_smore(db, school_id):
        found.append({**entry, "source": "newsletter"})

    if not found:
        return "WARNING[no_documents_found]: no handbook or bell schedule found on site or in newsletters"

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
    # retire a 2025-26 handbook that hasn't been republished yet.
    for doc_type in doc_types:
        docs = (
            await db.execute(select(SchoolDocument).where(SchoolDocument.school_id == school_id, SchoolDocument.doc_type == doc_type))
        ).scalars().all()
        years = [d.academic_year for d in docs if d.academic_year]
        max_year = max(years) if years else None
        for d in docs:
            d.is_current = d.academic_year == max_year if max_year else True

    summary = ", ".join(f"{t}: {sum(1 for e in found if e['doc_type'] == t)}" for t in sorted(doc_types))
    return f"documents: {created} new, {updated} updated ({summary})"
