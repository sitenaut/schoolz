"""District budget figures (models.StateDistrict, models.DistrictBudget): the
/budgets pages and the school page's budget section.

The import file is built outside the request path by
scripts/build_budget_facts.py, from one commit of the NJ school-funding audit;
this module only stores it and reads it back, plus the county and state
medians a district page is read against."""

import statistics
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, DistrictBudget, School, StateDistrict
from schemas import (
    BudgetDistrictOut,
    BudgetImport,
    BudgetImportResult,
    BudgetIndexDistrict,
    BudgetIndexOut,
    BudgetMedian,
    BudgetSchoolLink,
)

FIGURES = (
    "comparable", "benefits_prior", "benefits_budget", "other_spending_prior", "other_spending_budget", "prior_basis",
    "formula_aid_change", "levy_prior", "levy_budget", "levy_change_pct", "fund_balance_prior", "fund_balance_budget",
    "budget_report_url", "aid_source_url",
)
# Fewer comparable districts than this with a figure, and there is no median
# worth printing (Cape May has a handful of districts, some without staffing).
BUDGET_MEDIAN_MIN = 3
DISTRICT_SCHOOL_TYPES = ("elementary", "middle", "high", "alternative")


async def import_budget(db: AsyncSession, payload: BudgetImport) -> BudgetImportResult:
    """Upsert one state district per row and one budget row per (state
    district, budget year). A row is also tied to one of our districts when we
    track it: found by state code, failing that by our own name for it, which
    then gets the code (a district never gets a second code, and a code never
    moves to a second district). A state district's slug is set once, when it
    is created, and never changes."""
    districts = (await db.execute(select(District))).scalars().all()
    by_code = {(d.state, d.state_code): d for d in districts if d.state_code}
    by_name = {(d.state, d.name): d for d in districts}
    state_districts = {(s.state, s.state_code): s for s in (await db.execute(select(StateDistrict))).scalars().all()}
    slugs = {s.slug for s in state_districts.values()}
    year_rows = (await db.execute(select(DistrictBudget).where(DistrictBudget.budget_year == payload.budget_year))).scalars().all()
    by_state_district = {b.state_district_id: b for b in year_rows if b.state_district_id}
    # Rows imported before there were state districts have only district_id.
    by_district = {b.district_id: b for b in year_rows if b.district_id}

    # State districts first, flushed on their own: there is no relationship()
    # between the two models, so one flush could insert a budget row ahead of
    # the state district it points at.
    state_created = 0
    for row in payload.districts:
        key = (row.state, row.state_code)
        name = row.name or row.state_code
        state_district = state_districts.get(key)
        if state_district is None:
            slug = row.slug or row.state_code.lower()
            if slug in slugs:
                slug = f"{slug}-{row.state_code.lower()}"
            state_district = StateDistrict(id=str(uuid.uuid4()), state=row.state, state_code=row.state_code, name=name, county=row.county, slug=slug)
            db.add(state_district)
            state_districts[key] = state_district
            slugs.add(slug)
            state_created += 1
        else:
            state_district.name = name
            state_district.county = row.county or state_district.county
    await db.flush()

    created = updated = codes_set = tracked = 0
    for row in payload.districts:
        key = (row.state, row.state_code)
        state_district = state_districts[key]
        district = by_code.get(key)
        if district is None and row.name:
            named = by_name.get((row.state, row.name))
            if named is not None and not named.state_code:
                named.state_code = row.state_code
                by_code[key] = named
                district = named
                codes_set += 1
        if district is not None:
            tracked += 1

        budget = by_state_district.get(state_district.id) or (by_district.get(district.id) if district else None)
        if budget is None:
            budget = DistrictBudget(budget_year=payload.budget_year)
            db.add(budget)
            created += 1
        else:
            updated += 1
        budget.state_district_id = state_district.id
        budget.district_id = district.id if district else None
        by_state_district[state_district.id] = budget
        for field in FIGURES:
            setattr(budget, field, getattr(row, field))
        budget.health_costs = row.health_costs.model_dump() if row.health_costs else None
        budget.staffing = row.staffing.model_dump() if row.staffing else None
        budget.statements = [s.model_dump() for s in row.statements]
        budget.source_commit = payload.source_commit
    await db.flush()
    return BudgetImportResult(created=created, updated=updated, codes_set=codes_set, tracked=tracked, state_districts_created=state_created)


async def latest_budget(db: AsyncSession, district_id: str) -> DistrictBudget | None:
    """The newest budget year on file for one of our districts ("2026-27" sorts after "2025-26")."""
    return (
        await db.execute(
            select(DistrictBudget).where(DistrictBudget.district_id == district_id).order_by(DistrictBudget.budget_year.desc()).limit(1)
        )
    ).scalar_one_or_none()


def _pct(prior: float | None, budget: float | None) -> float | None:
    return round((budget - prior) / prior * 100, 1) if prior and budget is not None else None


def metrics(budget: DistrictBudget) -> dict[str, float | None]:
    """The figures a district page sets against its county and the state."""
    health = budget.health_costs or {}
    staffing = budget.staffing or {}
    ratio = (staffing.get("students_per_teacher") or {}).get("end") or {}
    salary = staffing.get("median_teacher_salary") or {}
    return {
        "benefits_change_pct": _pct(budget.benefits_prior, budget.benefits_budget),
        "other_spending_change_pct": _pct(budget.other_spending_prior, budget.other_spending_budget),
        "levy_change_pct": budget.levy_change_pct,
        "health_change_pct": _pct(health["start"]["value"], health["end"]["value"]) if health else None,
        "students_per_teacher": ratio.get("value"),
        "median_teacher_salary": salary.get("value"),
    }


def _median(values: list[float]) -> float | None:
    if len(values) < BUDGET_MEDIAN_MIN:
        return None
    return round(statistics.median(values), 1)


async def _latest_year(db: AsyncSession) -> str | None:
    return (
        await db.execute(
            select(DistrictBudget.budget_year)
            .where(DistrictBudget.state_district_id.is_not(None))
            .order_by(DistrictBudget.budget_year.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _year_rows(db: AsyncSession, year: str) -> list[tuple[StateDistrict, DistrictBudget]]:
    return [
        (s, b)
        for s, b in (
            await db.execute(
                select(StateDistrict, DistrictBudget)
                .join(DistrictBudget, DistrictBudget.state_district_id == StateDistrict.id)
                .where(DistrictBudget.budget_year == year)
                .order_by(StateDistrict.name)
            )
        ).all()
    ]


async def budget_index(db: AsyncSession) -> BudgetIndexOut:
    year = await _latest_year(db)
    if year is None:
        return BudgetIndexOut(budget_year=None, districts=[])
    return BudgetIndexOut(
        budget_year=year,
        districts=[
            BudgetIndexDistrict(
                slug=s.slug,
                name=s.name,
                county=s.county,
                tracked=b.district_id is not None,
                levy_change_pct=b.levy_change_pct,
                benefits_change_pct=_pct(b.benefits_prior, b.benefits_budget),
            )
            for s, b in await _year_rows(db, year)
        ],
    )


async def budget_district(db: AsyncSession, slug: str) -> BudgetDistrictOut | None:
    state_district = (await db.execute(select(StateDistrict).where(StateDistrict.slug == slug))).scalar_one_or_none()
    if state_district is None:
        return None
    budget = (
        await db.execute(
            select(DistrictBudget)
            .where(DistrictBudget.state_district_id == state_district.id)
            .order_by(DistrictBudget.budget_year.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if budget is None:
        return None

    county_values: dict[str, list[float]] = defaultdict(list)
    state_values: dict[str, list[float]] = defaultdict(list)
    for other, other_budget in await _year_rows(db, budget.budget_year):
        if not other_budget.comparable:
            continue
        for name, value in metrics(other_budget).items():
            if value is None:
                continue
            state_values[name].append(value)
            if other.county == state_district.county:
                county_values[name].append(value)
    medians = {
        name: BudgetMedian(county=_median(county_values[name]), state=_median(state_values[name])) for name in metrics(budget)
    }

    # The district's own schools on schoolz. Not "other": that is where a
    # town's private preschools and child care sit, under the district only so
    # the picker groups them by town, and the district's budget isn't theirs.
    schools: list[BudgetSchoolLink] = []
    if budget.district_id:
        schools = [
            BudgetSchoolLink(slug=slug, name=name)
            for slug, name in (
                await db.execute(
                    select(School.slug, School.name)
                    .where(School.district_id == budget.district_id, School.school_type.in_(DISTRICT_SCHOOL_TYPES))
                    .order_by(School.name)
                )
            ).all()
        ]
    return BudgetDistrictOut(
        slug=state_district.slug,
        name=state_district.name,
        county=state_district.county,
        state=state_district.state,
        budget_year=budget.budget_year,
        schools=schools,
        health_costs=budget.health_costs,
        staffing=budget.staffing,
        statements=budget.statements or [],
        medians=medians,
        imported_at=budget.imported_at,
        **{field: getattr(budget, field) for field in FIGURES},
    )
