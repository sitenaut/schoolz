"""Per-graduating-class pages for a high school - see
docs/HS_CLASS_PAGES_DESIGN.md. Nested under /schools/{school_id} rather
than its own top-level resource, same as /schools/{id}/content etc:
a class year only ever makes sense in the context of its school.

Public like every other read (school/calendar data is public by default -
see CLAUDE.md). The payment-tick endpoints are the one authenticated
corner: "have I personally paid this" is per-account, never school-wide.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_optional_user, require_admin
from database import get_db
from models import ClassPayment, ClassPaymentTick, School, SchoolClassYear, SchoolContentItem, StaffMember, User
from schemas import (
    ClassPaymentCreate,
    ClassPaymentOut,
    ClassPaymentUpdate,
    SchoolClassYearOut,
    SchoolClassYearUpdate,
    SchoolContentItemOut,
    StaffMiniOut,
)
from services.class_years import CLASS_PAGE_SOURCES, default_label, ensure_current_class_years, get_or_create_class_year
from routers.schools import resolve_school

router = APIRouter(prefix="/schools/{school_id}/class-years", tags=["class-years"])


async def _staff_minis(db: AsyncSession, ids: list[str] | None) -> list[StaffMiniOut]:
    if not ids:
        return []
    rows = (await db.execute(select(StaffMember).where(StaffMember.id.in_(ids)))).scalars().all()
    by_id = {r.id: r for r in rows}
    # Preserve the order ids were stored in, not query order.
    return [StaffMiniOut.model_validate(by_id[i], from_attributes=True) for i in ids if i in by_id]


async def _to_out(db: AsyncSession, class_year: SchoolClassYear) -> SchoolClassYearOut:
    return SchoolClassYearOut(
        id=class_year.id,
        school_id=class_year.school_id,
        grad_year=class_year.grad_year,
        label=class_year.label or default_label(class_year.grad_year),
        grade_level_principals=await _staff_minis(db, class_year.grade_level_principal_staff_ids),
        advisors=await _staff_minis(db, class_year.advisor_staff_ids),
        instagram_url=class_year.instagram_url,
        source_page_url=class_year.source_page_url,
        updated_at=class_year.updated_at,
    )


@router.get("", response_model=list[SchoolClassYearOut])
async def list_class_years(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    """The four currently-enrolled classes (seniors first), auto-provisioned
    on first read - see services/class_years.py. Returns [] for a non-high
    school rather than 404ing; the frontend simply doesn't render the strip
    when this is empty."""
    if school.school_type != "high":
        return []
    class_years = await ensure_current_class_years(db, school.id)
    await db.commit()
    return [await _to_out(db, c) for c in class_years]


async def _resolve_class_year(school_id: str, grad_year: int, db: AsyncSession) -> SchoolClassYear:
    """Reached-directly-by-URL never 404s - a link to a class two years
    out (already graduated) or one not yet a freshman still resolves,
    consistent with School.slug never breaking an old link."""
    row = await get_or_create_class_year(db, school_id, grad_year)
    await db.commit()
    return row


@router.get("/{grad_year}", response_model=SchoolClassYearOut)
async def get_class_year(grad_year: int, school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    class_year = await _resolve_class_year(school.id, grad_year, db)
    return await _to_out(db, class_year)


@router.patch("/{grad_year}", response_model=SchoolClassYearOut)
async def update_class_year(
    grad_year: int,
    payload: SchoolClassYearUpdate,
    school: School = Depends(resolve_school),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manual correction of what services/hs_activities_site.py extracted -
    e.g. an ambiguous advisor-name match it deliberately left unresolved."""
    class_year = await get_or_create_class_year(db, school.id, grad_year)
    if payload.label is not None:
        class_year.label = payload.label or None
    if payload.instagram_url is not None:
        class_year.instagram_url = payload.instagram_url or None
    if payload.grade_level_principal_staff_ids is not None:
        class_year.grade_level_principal_staff_ids = payload.grade_level_principal_staff_ids or None
    if payload.advisor_staff_ids is not None:
        class_year.advisor_staff_ids = payload.advisor_staff_ids or None
    await db.commit()
    await db.refresh(class_year)
    return await _to_out(db, class_year)


@router.get("/{grad_year}/content", response_model=list[SchoolContentItemOut])
async def list_class_year_content(
    grad_year: int,
    category: str | None = None,
    school: School = Depends(resolve_school),
    db: AsyncSession = Depends(get_db),
):
    """Items scoped to this class specifically, plus the school's own
    activities calendar (always shown within a class page, even though it
    defaults OFF in the general calendar - see CLAUDE.md/the design doc).
    Deliberately excludes plain newsletter items - those already have a
    home on the main school page."""
    query = select(SchoolContentItem).where(
        SchoolContentItem.school_id == school.id,
        SchoolContentItem.is_current.is_(True),
        SchoolContentItem.source.in_(CLASS_PAGE_SOURCES),
    )
    if category:
        query = query.where(SchoolContentItem.category == category)
    query = query.order_by(SchoolContentItem.start_date)
    items = (await db.execute(query)).scalars().all()
    # Filtered in Python, not SQL, same convention as every other
    # applies_to_* filter in this codebase (calendar.py's
    # _applies_to_types, school_today.py, bucket3.py) - these are plain
    # JSON columns (Postgres "json", not "jsonb"), which don't support the
    # @> containment operator .contains() would generate.
    return [
        SchoolContentItemOut.model_validate(i, from_attributes=True)
        for i in items
        if not i.applies_to_grad_years or grad_year in i.applies_to_grad_years
    ]


@router.get("/{grad_year}/payments", response_model=list[ClassPaymentOut])
async def list_class_payments(
    grad_year: int,
    school: School = Depends(resolve_school),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    class_year = await _resolve_class_year(school.id, grad_year, db)
    payments = (
        (await db.execute(select(ClassPayment).where(ClassPayment.school_class_year_id == class_year.id).order_by(ClassPayment.sequence)))
        .scalars()
        .all()
    )
    ticked_ids: set[str] = set()
    if user and payments:
        ticked_ids = set(
            (
                await db.execute(
                    select(ClassPaymentTick.class_payment_id).where(
                        ClassPaymentTick.user_id == user.id,
                        ClassPaymentTick.class_payment_id.in_([p.id for p in payments]),
                    )
                )
            )
            .scalars()
            .all()
        )
    return [
        ClassPaymentOut.model_validate(p, from_attributes=True).model_copy(update={"ticked": p.id in ticked_ids if user else None})
        for p in payments
    ]


@router.post("/{grad_year}/payments", response_model=ClassPaymentOut, status_code=status.HTTP_201_CREATED)
async def create_class_payment(
    grad_year: int,
    payload: ClassPaymentCreate,
    school: School = Depends(resolve_school),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    class_year = await get_or_create_class_year(db, school.id, grad_year)
    payment = ClassPayment(school_class_year_id=class_year.id, **payload.model_dump())
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return ClassPaymentOut.model_validate(payment, from_attributes=True)


async def _resolve_payment(school_id: str, grad_year: int, payment_id: str, db: AsyncSession) -> ClassPayment:
    class_year = (
        await db.execute(select(SchoolClassYear).where(SchoolClassYear.school_id == school_id, SchoolClassYear.grad_year == grad_year))
    ).scalar_one_or_none()
    payment = None
    if class_year:
        payment = (
            await db.execute(select(ClassPayment).where(ClassPayment.id == payment_id, ClassPayment.school_class_year_id == class_year.id))
        ).scalar_one_or_none()
    if not payment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return payment


@router.patch("/{grad_year}/payments/{payment_id}", response_model=ClassPaymentOut)
async def update_class_payment(
    grad_year: int,
    payment_id: str,
    payload: ClassPaymentUpdate,
    school: School = Depends(resolve_school),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    payment = await _resolve_payment(school.id, grad_year, payment_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(payment, field, value)
    await db.commit()
    await db.refresh(payment)
    return ClassPaymentOut.model_validate(payment, from_attributes=True)


@router.delete("/{grad_year}/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class_payment(
    grad_year: int,
    payment_id: str,
    school: School = Depends(resolve_school),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    payment = await _resolve_payment(school.id, grad_year, payment_id, db)
    await db.delete(payment)
    await db.commit()


@router.post("/{grad_year}/payments/{payment_id}/tick", response_model=ClassPaymentOut)
async def toggle_payment_tick(
    grad_year: int,
    payment_id: str,
    school: School = Depends(resolve_school),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-account, never per-student, same reasoning as
    CourseDisplayPreference - two guardians of the same kid track their own
    "have I paid this" independently. Toggles: ticking an already-ticked
    payment un-ticks it."""
    payment = await _resolve_payment(school.id, grad_year, payment_id, db)
    existing = (
        await db.execute(
            select(ClassPaymentTick).where(ClassPaymentTick.user_id == user.id, ClassPaymentTick.class_payment_id == payment.id)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        ticked = False
    else:
        db.add(ClassPaymentTick(user_id=user.id, class_payment_id=payment.id, ticked_at=datetime.now(timezone.utc)))
        ticked = True
    await db.commit()
    return ClassPaymentOut.model_validate(payment, from_attributes=True).model_copy(update={"ticked": ticked})
