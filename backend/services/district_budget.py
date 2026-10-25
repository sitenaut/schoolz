"""District budget figures for the school page (models.DistrictBudget).

The import file is built outside the request path by
scripts/build_budget_facts.py, from one commit of the NJ school-funding audit;
this module only stores it and reads it back."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, DistrictBudget
from schemas import BudgetImport, BudgetImportResult

FIGURES = (
    "benefits_prior", "benefits_budget", "prior_basis", "formula_aid_change", "levy_change_pct",
    "fund_balance_prior", "fund_balance_budget", "budget_report_url", "aid_source_url",
)


async def import_budget(db: AsyncSession, payload: BudgetImport) -> BudgetImportResult:
    """Upsert one row per (district, budget year). A district is found by its
    state code; failing that by our own name for it, which then gets the code
    (a district never gets a second code, and a code never moves to a second
    district). Rows for districts we don't track are reported, not created."""
    districts = (await db.execute(select(District))).scalars().all()
    by_code = {(d.state, d.state_code): d for d in districts if d.state_code}
    by_name = {(d.state, d.name): d for d in districts}
    existing = {
        b.district_id: b
        for b in (await db.execute(select(DistrictBudget).where(DistrictBudget.budget_year == payload.budget_year))).scalars().all()
    }
    created = updated = codes_set = 0
    unmatched: list[str] = []
    for row in payload.districts:
        district = by_code.get((row.state, row.state_code))
        if district is None and row.name:
            named = by_name.get((row.state, row.name))
            if named is not None and not named.state_code:
                named.state_code = row.state_code
                by_code[(row.state, row.state_code)] = named
                district = named
                codes_set += 1
        if district is None:
            unmatched.append(f"{row.state_code} {row.name or ''}".strip())
            continue
        budget = existing.get(district.id)
        if budget is None:
            budget = DistrictBudget(district_id=district.id, budget_year=payload.budget_year)
            db.add(budget)
            existing[district.id] = budget
            created += 1
        else:
            updated += 1
        for field in FIGURES:
            setattr(budget, field, getattr(row, field))
        budget.statements = [s.model_dump() for s in row.statements]
        budget.source_commit = payload.source_commit
    await db.flush()
    return BudgetImportResult(created=created, updated=updated, codes_set=codes_set, unmatched=unmatched)


async def latest_budget(db: AsyncSession, district_id: str) -> DistrictBudget | None:
    """The newest budget year on file ("2026-27" sorts after "2025-26")."""
    return (
        await db.execute(
            select(DistrictBudget).where(DistrictBudget.district_id == district_id).order_by(DistrictBudget.budget_year.desc()).limit(1)
        )
    ).scalar_one_or_none()
