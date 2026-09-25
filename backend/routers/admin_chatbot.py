"""Admin controls for the chatbot: which provider/model each audience runs
on, the price table behind cost estimates, and a side-by-side compare that
runs one question through several configurations at once - the point is
judging whether a much cheaper model (Gemini) answers well enough.

A compare runs the real agent loop with the real tools. "As signed in" uses
the admin's own account, so the personal tools see the admin's own
children - and that data goes to whichever provider is being compared.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import oauth2_scheme, require_admin
from database import get_db
from models import User
from services.chat_providers import KNOWN_PROVIDERS, configured_providers
from services.chat_settings import AudienceConfig, ChatbotSettings, estimate_cost, get_settings, save_settings
from services.chatbot import run_chat_turn
from services.chatbot_personal import PersonalTools

router = APIRouter(prefix="/admin/chatbot", tags=["admin-chatbot"])


class ProviderStatus(BaseModel):
    name: str
    configured: bool


class ChatbotAdminOut(BaseModel):
    settings: ChatbotSettings
    providers: list[ProviderStatus]


def _validate(settings: ChatbotSettings) -> None:
    for audience in (settings.anonymous, settings.signed_in):
        if audience.provider not in KNOWN_PROVIDERS:
            raise HTTPException(400, f"Unknown provider {audience.provider!r}")
        if not audience.model.strip():
            raise HTTPException(400, "Model is required")


@router.get("", response_model=ChatbotAdminOut)
async def get_chatbot_admin(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    configured = configured_providers()
    return ChatbotAdminOut(
        settings=await get_settings(db, fresh=True),
        providers=[ProviderStatus(name=p, configured=p in configured) for p in KNOWN_PROVIDERS],
    )


@router.put("", response_model=ChatbotAdminOut)
async def put_chatbot_admin(body: ChatbotSettings, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _validate(body)
    configured = configured_providers()
    for audience in (body.anonymous, body.signed_in):
        if audience.provider not in configured:
            # Saving it would make the live chatbot answer "not configured".
            raise HTTPException(400, f"{audience.provider} has no API key set on the server")
    settings = await save_settings(db, body, user.id)
    return ChatbotAdminOut(settings=settings, providers=[ProviderStatus(name=p, configured=p in configured) for p in KNOWN_PROVIDERS])


@router.get("/models", response_model=list[str])
async def list_provider_models(provider: str, _: User = Depends(require_admin)):
    prov = configured_providers().get(provider)
    if prov is None:
        raise HTTPException(400, f"{provider} has no API key set on the server")
    try:
        return await prov.list_models()
    except Exception as exc:  # noqa: BLE001 - surface the provider's own error to the admin
        raise HTTPException(502, f"Couldn't list {provider} models: {exc}") from exc


class CompareIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    signed_in: bool = False
    configs: list[AudienceConfig] = Field(min_length=1, max_length=3)


class CompareResult(BaseModel):
    provider: str
    requested_model: str
    model: str | None
    escalated: bool = False
    reply: str | None = None
    error: str | None = None
    rounds: int = 0
    tools_called: list[str] = []
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0


@router.post("/compare", response_model=list[CompareResult])
async def compare(
    body: CompareIn,
    request: Request,
    user: User = Depends(require_admin),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_settings(db)
    providers = configured_providers()

    async def run_one(config: AudienceConfig) -> CompareResult:
        personal = PersonalTools(request.app, token) if body.signed_in and token else None
        started = time.monotonic()
        try:
            result: dict[str, Any] = await run_chat_turn(
                request.app.state.mcp, history=[], message=body.message, already_escalated=False,
                personal=personal, config=config, providers=providers,
            )
        except Exception as exc:  # noqa: BLE001 - one side failing shouldn't sink the comparison
            return CompareResult(provider=config.provider, requested_model=config.model, model=None,
                                 error=f"{type(exc).__name__}: {exc}"[:800], latency_ms=int((time.monotonic() - started) * 1000))
        finally:
            if personal:
                await personal.aclose()
        out = CompareResult(
            provider=config.provider, requested_model=config.model, model=result.get("model"),
            escalated=result.get("escalated", False), reply=result.get("reply"),
            rounds=result.get("rounds", 0), tools_called=result.get("tools_called", []),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        costs: list[float | None] = []
        for model, usage in (result.get("usage_by_model") or {}).items():
            out.input_tokens += usage.input_tokens
            out.output_tokens += usage.output_tokens
            out.cache_read_tokens += usage.cache_read_tokens
            out.cache_write_tokens += usage.cache_write_tokens
            costs.append(estimate_cost(settings, model, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens))
        # Only a total when every model involved has a price on file.
        out.cost_usd = sum(costs) if costs and all(c is not None for c in costs) else None
        if result.get("model") is None and out.reply:
            out.error, out.reply = out.reply, None
        return out

    return await asyncio.gather(*(run_one(c) for c in body.configs))
