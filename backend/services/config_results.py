"""Carries what the model-backed scans already produced from one environment
to another, so onboarding a district doesn't pay for the same extraction
twice (once on the local verification runs, again on prod's first runs).

Only sources whose scan is gated on stored state are carried, because that
state is what makes the target's first run find nothing new:

- newsletters (Smore, virtual backpack, PT Board): blocks by content_hash
- Givebacks PTA pages: blocks by content_hash
- lunch menu PDFs: LunchMenu by source_pdf_url
- district calendar PDF: items whose external_uid carries the file hash
- contact-page staff: School.contact_page_hash

Scans with no model call are left to run in the target; they cost nothing.

Rows are keyed the way routers/admin_config.py keys config (district name,
school slug, newsletter url), never by id. A source that already has results
in the target is left alone, so re-importing a file changes nothing and a
stale local copy can never overwrite what prod scanned for itself.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ContentTranslation,
    District,
    GivebacksBlock,
    JobRun,
    LunchMenu,
    LunchMenuItem,
    School,
    SchoolContentItem,
    SmoreBlock,
    SmoreNewsletter,
    StaffMember,
    normalize_name,
)
from schemas import (
    ConfigResults,
    ResultBlock,
    ResultDistrict,
    ResultItem,
    ResultLunchDay,
    ResultLunchMenu,
    ResultNewsletter,
    ResultRun,
    ResultSchool,
    ResultStaff,
    ResultTranslation,
)
from services import district_calendar_pdf
from services.contact_page import CONSTITUENT_PREFIX
from services.content_extractor import _title_dedup_key
from services.staff_roles import classify_role

GIVEBACKS_SOURCE = "givebacks_pta"
IMPORTED = "imported"

_ITEM_FIELDS = (
    "scope", "source", "external_uid", "applies_to_school_types", "applies_to_grad_years", "category", "title",
    "description", "start_date", "end_date", "is_all_day", "link_url", "person_name", "person_title",
    "source_excerpt", "extracted_at", "is_current",
)
_BLOCK_FIELDS = (
    "position", "block_type", "text_content", "image_url", "link_url", "content_hash",
    "pending_vision_extraction", "vision_extracted_text", "first_seen_at",
)


# --- Export ---


async def _last_run(db: AsyncSession, job_id: str | None) -> ResultRun | None:
    if not job_id:
        return None
    run = (
        await db.execute(
            select(JobRun)
            .where(JobRun.job_id == job_id, JobRun.status.in_(("success", "warning")), JobRun.triggered_by != IMPORTED)
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    return ResultRun(status=run.status, finished_at=run.finished_at or run.started_at, summary=run.log_excerpt)


async def _items_out(
    db: AsyncSession,
    rows: list[SchoolContentItem],
    schools: dict[str, School],
    districts: dict[str, District],
    block_hash_by_id: dict[str, str] | None = None,
) -> list[ResultItem]:
    if not rows:
        return []
    ids = {r.id for r in rows}
    translations: dict[str, list[ResultTranslation]] = {}
    for t in (await db.execute(select(ContentTranslation).where(ContentTranslation.item_id.in_(ids)))).scalars():
        translations.setdefault(t.item_id, []).append(ResultTranslation.model_validate(t, from_attributes=True))
    return [
        ResultItem(
            ref=r.id,
            school_slug=schools[r.school_id].slug if r.school_id in schools else None,
            district_name=districts[r.district_id].name if r.district_id in districts else None,
            superseded_by_ref=r.superseded_by_id,
            source_block_hash=(block_hash_by_id or {}).get(r.source_block_id),
            translations=translations.get(r.id, []),
            **{f: getattr(r, f) for f in _ITEM_FIELDS},
        )
        for r in rows
    ]


async def _menus_out(db: AsyncSession, menus: list[LunchMenu]) -> list[ResultLunchMenu]:
    out = []
    for m in menus:
        days = (
            await db.execute(select(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == m.id).order_by(LunchMenuItem.menu_date))
        ).scalars().all()
        out.append(
            ResultLunchMenu(
                school_type=m.school_type,
                meal_type=m.meal_type,
                period_label=m.period_label,
                source_pdf_url=m.source_pdf_url,
                parsed_at=m.parsed_at,
                days=[ResultLunchDay(menu_date=d.menu_date, description=d.description, notes=d.notes) for d in days],
            )
        )
    return out


def _blocks_out(rows: list) -> list[ResultBlock]:
    return [
        ResultBlock(page_path=getattr(r, "page_path", None), **{f: getattr(r, f) for f in _BLOCK_FIELDS}) for r in rows
    ]


async def export_results(db: AsyncSession, district_names: list[str]) -> ConfigResults:
    found = (await db.execute(select(District).where(District.name.in_(district_names)))).scalars().all()
    missing = sorted(set(district_names) - {d.name for d in found})
    if missing:
        raise HTTPException(status_code=404, detail=f"No district named: {', '.join(missing)}")
    districts = {d.id: d for d in found}
    schools = {
        s.id: s for s in (await db.execute(select(School).where(School.district_id.in_(districts)))).scalars().all()
    }

    out = ConfigResults(exported_at=datetime.now(timezone.utc))

    for d in found:
        menus = (await db.execute(select(LunchMenu).where(LunchMenu.district_id == d.id))).scalars().all()
        pdf_items = (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.district_id == d.id, SchoolContentItem.source == district_calendar_pdf.SOURCE
                )
            )
        ).scalars().all()
        out.districts.append(
            ResultDistrict(
                name=d.name,
                lunch_menus=await _menus_out(db, menus),
                lunch_last_run=await _last_run(db, d.scheduled_job_id),
                calendar_pdf_items=await _items_out(db, pdf_items, schools, districts),
                calendar_pdf_last_run=await _last_run(db, d.calendar_pdf_job_id),
            )
        )

    for s in schools.values():
        menus = (await db.execute(select(LunchMenu).where(LunchMenu.school_id == s.id))).scalars().all()
        blocks = (
            await db.execute(
                select(GivebacksBlock).where(GivebacksBlock.school_id == s.id).order_by(GivebacksBlock.page_path, GivebacksBlock.position)
            )
        ).scalars().all()
        items = (
            await db.execute(
                select(SchoolContentItem).where(SchoolContentItem.school_id == s.id, SchoolContentItem.source == GIVEBACKS_SOURCE)
            )
        ).scalars().all()
        staff = []
        if s.contact_page_hash:
            staff = (
                await db.execute(
                    select(StaffMember).where(
                        StaffMember.school_id == s.id, StaffMember.source_constituent_id.startswith(CONSTITUENT_PREFIX)
                    )
                )
            ).scalars().all()
        entry = ResultSchool(
            slug=s.slug,
            lunch_menus=await _menus_out(db, menus),
            givebacks_blocks=_blocks_out(blocks),
            givebacks_items=await _items_out(db, items, schools, districts),
            givebacks_last_run=await _last_run(db, s.givebacks_job_id),
            contact_page_hash=s.contact_page_hash if staff else None,
            contact_staff=[
                ResultStaff(
                    constituent_id=m.source_constituent_id, full_name=m.full_name, title=m.title,
                    department=m.department, email=m.email, phone=m.phone,
                )
                for m in staff
            ],
        )
        if entry.lunch_menus or entry.givebacks_blocks or entry.contact_staff:
            out.schools.append(entry)

    newsletters = (
        await db.execute(
            select(SmoreNewsletter).where(
                SmoreNewsletter.school_id.in_(schools) | SmoreNewsletter.district_id.in_(districts)
            )
        )
    ).scalars().all()
    for n in newsletters:
        blocks = (
            await db.execute(select(SmoreBlock).where(SmoreBlock.newsletter_id == n.id).order_by(SmoreBlock.position))
        ).scalars().all()
        if not blocks:
            continue
        items = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.newsletter_id == n.id))).scalars().all()
        out.newsletters.append(
            ResultNewsletter(
                url=n.url,
                latest_summary=n.latest_summary,
                blocks=_blocks_out(blocks),
                items=await _items_out(db, items, schools, districts, {b.id: b.content_hash for b in blocks}),
                last_run=await _last_run(db, n.scheduled_job_id),
            )
        )
    return out


# --- Import ---


class _Importer:
    def __init__(self, db: AsyncSession, districts: dict[str, District], schools: dict[str, School]):
        self.db = db
        self.districts = districts  # by name
        self.schools = schools  # by slug
        self.applied: dict[str, int] = {}
        self.skipped: list[str] = []
        self._item_by_ref: dict[str, SchoolContentItem] = {}
        self._superseded: list[tuple[SchoolContentItem, str]] = []
        self._staff_by_name: dict[str, dict[str, str]] = {}

    def _count(self, key: str, n: int = 1) -> None:
        if n:
            self.applied[key] = self.applied.get(key, 0) + n

    async def _exists(self, stmt) -> bool:
        return (await self.db.execute(stmt.limit(1))).first() is not None

    async def _staff_id(self, school_id: str | None, item: ResultItem) -> str | None:
        """Same lookup content_extractor does at extraction time; null when
        the roster hasn't been scanned here yet."""
        names = [n for n in (item.person_name, item.title if item.category == "person" else None) if n]
        if not school_id or not names:
            return None
        if school_id not in self._staff_by_name:
            rows = (await self.db.execute(select(StaffMember).where(StaffMember.school_id == school_id))).scalars().all()
            self._staff_by_name[school_id] = {normalize_name(s.full_name): s.id for s in rows}
        by_name = self._staff_by_name[school_id]
        return next((by_name[normalize_name(n)] for n in names if normalize_name(n) in by_name), None)

    async def _is_district_duplicate(self, district_id: str, item: ResultItem) -> bool:
        """The check content_extractor makes before storing a district-scoped
        newsletter item: another school's newsletter in a district already
        tracked here may have reported the same closure."""
        candidates = (
            await self.db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.scope == "district",
                    SchoolContentItem.district_id == district_id,
                    SchoolContentItem.start_date == item.start_date,
                    ~SchoolContentItem.title.regexp_match(r"^Day \d$"),
                )
            )
        ).scalars().all()
        return any(c.category == item.category or _title_dedup_key(c.title) == _title_dedup_key(item.title) for c in candidates)

    async def _add_items(
        self,
        items: list[ResultItem],
        *,
        newsletter_id: str | None = None,
        block_id_by_hash: dict[str, str] | None = None,
        dedupe_district: bool = False,
    ) -> int:
        added: list[tuple[SchoolContentItem, ResultItem]] = []
        for item in items:
            school = self.schools.get(item.school_slug) if item.school_slug else None
            district = self.districts.get(item.district_name) if item.district_name else None
            if (item.scope == "school" and not school) or (item.scope == "district" and not district):
                continue
            if dedupe_district and item.scope == "district" and item.is_current and await self._is_district_duplicate(district.id, item):
                continue
            row = SchoolContentItem(
                school_id=school.id if item.scope == "school" else None,
                district_id=district.id if item.scope == "district" else None,
                newsletter_id=newsletter_id,
                source_block_id=(block_id_by_hash or {}).get(item.source_block_hash),
                staff_member_id=await self._staff_id(school.id if school else None, item),
                **{f: getattr(item, f) for f in _ITEM_FIELDS},
            )
            self.db.add(row)
            added.append((row, item))
        await self.db.flush()
        for row, item in added:
            self._item_by_ref[item.ref] = row
            if item.superseded_by_ref:
                self._superseded.append((row, item.superseded_by_ref))
            for t in item.translations:
                self.db.add(ContentTranslation(item_id=row.id, **t.model_dump()))
        return len(added)

    async def _add_menus(self, menus: list[ResultLunchMenu], *, district: District | None = None, school: School | None = None) -> int:
        added = 0
        for m in menus:
            owner = (
                (LunchMenu.district_id == district.id, LunchMenu.school_type == m.school_type)
                if district
                else (LunchMenu.school_id == school.id,)
            )
            if await self._exists(
                select(LunchMenu.id).where(*owner, LunchMenu.meal_type == m.meal_type, LunchMenu.source_pdf_url == m.source_pdf_url)
            ):
                continue
            menu = LunchMenu(
                district_id=district.id if district else None,
                school_id=school.id if school else None,
                school_type=m.school_type,
                meal_type=m.meal_type,
                period_label=m.period_label,
                source_pdf_url=m.source_pdf_url,
                parsed_at=m.parsed_at,
            )
            self.db.add(menu)
            await self.db.flush()
            for day in m.days:
                self.db.add(LunchMenuItem(lunch_menu_id=menu.id, **day.model_dump()))
            added += 1
        return added

    def _record_run(self, job_id: str | None, run: ResultRun | None) -> None:
        """One history row so the job shows what the carried data came from.
        last_run_at stays null on purpose: the job's real first run still
        fires here, proving this environment can reach the source."""
        if not job_id or run is None:
            return
        when = run.finished_at or datetime.now(timezone.utc)
        self.db.add(
            JobRun(
                job_id=job_id,
                status=run.status,
                triggered_by=IMPORTED,
                started_at=when,
                finished_at=when,
                log_excerpt=f"Results carried over from another environment's run: {run.summary or 'no summary'}",
            )
        )

    async def district(self, d: ResultDistrict) -> None:
        district = self.districts.get(d.name)
        if district is None:
            self.skipped.append(f"district {d.name}: not tracked here")
            return
        menus = await self._add_menus(d.lunch_menus, district=district)
        self._count("lunch_menus", menus)
        if menus:
            self._record_run(district.scheduled_job_id, d.lunch_last_run)

        if d.calendar_pdf_items:
            if await self._exists(
                select(SchoolContentItem.id).where(
                    SchoolContentItem.district_id == district.id, SchoolContentItem.source == district_calendar_pdf.SOURCE
                )
            ):
                self.skipped.append(f"district {d.name}: calendar PDF already scanned here")
            else:
                self._count("items", await self._add_items(d.calendar_pdf_items))
                self._count("calendar_pdfs")
                self._record_run(district.calendar_pdf_job_id, d.calendar_pdf_last_run)

    async def school(self, s: ResultSchool) -> None:
        school = self.schools.get(s.slug)
        if school is None:
            self.skipped.append(f"school {s.slug}: not tracked here")
            return
        self._count("lunch_menus", await self._add_menus(s.lunch_menus, school=school))

        if s.givebacks_blocks:
            if await self._exists(select(GivebacksBlock.id).where(GivebacksBlock.school_id == school.id)):
                self.skipped.append(f"school {s.slug}: Givebacks page already scanned here")
            else:
                for b in s.givebacks_blocks:
                    self.db.add(GivebacksBlock(school_id=school.id, page_path=b.page_path or "", **b.model_dump(include=set(_BLOCK_FIELDS))))
                await self.db.flush()
                self._count("blocks", len(s.givebacks_blocks))
                self._count("items", await self._add_items(s.givebacks_items))
                self._count("givebacks_pages")
                self._record_run(school.givebacks_job_id, s.givebacks_last_run)

        if s.contact_page_hash and s.contact_staff and not school.contact_page_hash:
            have = set(
                (await self.db.execute(select(StaffMember.source_constituent_id).where(StaffMember.school_id == school.id))).scalars()
            )
            for m in s.contact_staff:
                if m.constituent_id.startswith(CONSTITUENT_PREFIX) and m.constituent_id not in have:
                    self.db.add(
                        StaffMember(
                            school_id=school.id, source_constituent_id=m.constituent_id, full_name=m.full_name, title=m.title,
                            role=classify_role(m.title), department=m.department, email=m.email, phone=m.phone,
                        )
                    )
            school.contact_page_hash = s.contact_page_hash
            await self.db.flush()
            self._staff_by_name.pop(school.id, None)
            self._count("contact_pages")

    async def newsletter(self, n: ResultNewsletter, by_url: dict[str, SmoreNewsletter]) -> None:
        newsletter = by_url.get(n.url)
        if newsletter is None:
            self.skipped.append(f"newsletter {n.url}: not tracked here")
            return
        if await self._exists(select(SmoreBlock.id).where(SmoreBlock.newsletter_id == newsletter.id)):
            self.skipped.append(f"newsletter {n.url}: already scanned here")
            return
        rows = {b.content_hash: SmoreBlock(newsletter_id=newsletter.id, **b.model_dump(include=set(_BLOCK_FIELDS))) for b in n.blocks}
        self.db.add_all(rows.values())
        await self.db.flush()
        self._count("blocks", len(rows))
        self._count(
            "items",
            await self._add_items(
                n.items, newsletter_id=newsletter.id, block_id_by_hash={h: r.id for h, r in rows.items()}, dedupe_district=True
            ),
        )
        if n.latest_summary and not newsletter.latest_summary:
            newsletter.latest_summary = n.latest_summary
        self._count("newsletters")
        self._record_run(newsletter.scheduled_job_id, n.last_run)

    async def finish(self) -> None:
        for row, ref in self._superseded:
            target = self._item_by_ref.get(ref)
            if target is not None:
                row.superseded_by_id = target.id
        await self.db.flush()


async def import_results(
    db: AsyncSession, results: ConfigResults, *, districts: dict[str, District], schools: dict[str, School]
) -> tuple[dict[str, int], list[str]]:
    """Applies `results` inside the caller's transaction. `districts` is by
    name and `schools` by slug, as import_config already has them."""
    importer = _Importer(db, districts, schools)
    # Contact-page staff first, so newsletter "person" items can link to them.
    for s in results.schools:
        await importer.school(s)
    for d in results.districts:
        await importer.district(d)
    by_url = {n.url: n for n in (await db.execute(select(SmoreNewsletter))).scalars().all()}
    for n in results.newsletters:
        await importer.newsletter(n, by_url)
    await importer.finish()
    return importer.applied, importer.skipped
