"""Public district budget pages (/budgets): every district in the state's
files, not only the ones schoolz tracks. Data from services/district_budget.py."""

import os

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import database
from database import get_db
from schemas import BudgetDistrictOut, BudgetIndexOut
from services.district_budget import budget_district, budget_index
from services.response_cache import SingleFlightTTLCache

router = APIRouter(prefix="/budgets", tags=["budgets"])

# A district page reads every district's row for its medians, and crawlers
# will ask for all ~585 pages; the figures change only on an import (a few
# times a year), so ten minutes stale costs nothing. 0 disables it; the test
# suite does. An unknown slug is cached as an empty body, counted at 256
# bytes so made-up URLs can't grow the cache past its bound.
_CACHE = SingleFlightTTLCache(
    ttl_s=float(os.getenv("BUDGETS_CACHE_TTL_S", "600")), max_total_bytes=8 * 1024 * 1024, sizeof=lambda body: max(len(body), 256)
)


async def _cached(key: tuple, compute_out) -> Response:
    async def compute() -> bytes:
        # Its own session: other visitors wait on this same computation.
        async with database.SessionLocal() as own_db:
            out = await compute_out(own_db)
            return JSONResponse(jsonable_encoder(out)).body if out is not None else b""

    body = await _CACHE.get_or_compute(key, compute)
    if not body:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "District not found")
    return Response(content=body, media_type="application/json")


@router.get("", response_model=BudgetIndexOut)
async def list_budgets(db: AsyncSession = Depends(get_db)):
    """Public. Every district with figures for the latest budget year, by name."""
    if not _CACHE.enabled:
        return await budget_index(db)
    return await _cached(("index",), budget_index)


@router.get("/{slug}", response_model=BudgetDistrictOut)
async def get_budget(slug: str, db: AsyncSession = Depends(get_db)):
    """Public. One district's latest budget year with its county and state medians."""
    if not _CACHE.enabled:
        out = await budget_district(db, slug)
        if out is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "District not found")
        return out
    return await _cached(("district", slug), lambda own_db: budget_district(own_db, slug))
