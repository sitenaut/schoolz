import os

from fastapi import APIRouter

import auth as auth_module

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app_env": os.getenv("APP_ENV", "local"),
        "auth_mode": auth_module.AUTH_MODE,
    }
