"""Imports district budget figures (services/district_budget.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_permission
from database import get_db
from schemas import BudgetImport, BudgetImportResult
from services.district_budget import import_budget

router = APIRouter(prefix="/admin/budget", tags=["admin-budget"])


@router.post("/import", response_model=BudgetImportResult, dependencies=[Depends(require_permission("schools.manage"))])
async def import_district_budgets(payload: BudgetImport, db: AsyncSession = Depends(get_db)):
    """The file scripts/build_budget_facts.py writes (backend/seed/budget/).
    Re-importing the same year replaces that year's figures and quotes."""
    result = await import_budget(db, payload)
    await db.commit()
    return result
