import asyncio
import logging
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import auth as auth_module
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness, and what Fly's machine check asks (fly.toml): never touches
    the database, so a database blip can't take every machine out of rotation."""
    return {
        "status": "ok",
        "app_env": os.getenv("APP_ENV", "local"),
        "auth_mode": auth_module.AUTH_MODE,
    }


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness, for outside probes and the deploy smoke check: 200 only
    when the database answers within 2 seconds."""
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=2)
    except Exception:  # noqa: BLE001 - any failure means not ready
        logger.warning("ready_check_failed", exc_info=True)
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
