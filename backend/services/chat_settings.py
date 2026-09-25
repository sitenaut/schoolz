"""Which provider/model the chatbot runs on, per audience - edited in
/admin -> Chatbot, stored in app_settings under "chatbot".

Anonymous visitors and signed-in users are configured separately on
purpose: a signed-in conversation can carry a family's children's names,
grades and schedules to the provider, so moving public questions to a
cheaper provider shouldn't silently move those too.

`prices` ($ per million tokens) only feeds the cost estimates on the admin
compare panel; Gemini's are left for the admin to fill in from Google's
pricing page rather than guessed here.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppSetting

KEY = "chatbot"
_CACHE_TTL_SECONDS = 30
_cache: dict[str, Any] = {"value": None, "at": 0.0}


class AudienceConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    # Used for the rest of a conversation once a turn looks compound (see
    # chatbot._should_escalate). None = never escalate.
    escalation_model: str | None = "claude-sonnet-5"
    # OpenAI-compatible providers only (Gemini): its thinking tokens count
    # against the output budget, so it defaults low. Ignored for Anthropic.
    reasoning_effort: str | None = "low"


class ModelPrice(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float | None = Field(default=None, ge=0)


class ChatbotSettings(BaseModel):
    anonymous: AudienceConfig = Field(default_factory=AudienceConfig)
    signed_in: AudienceConfig = Field(default_factory=AudienceConfig)
    prices: dict[str, ModelPrice] = Field(
        default_factory=lambda: {
            # Anthropic list prices, $/MTok. Cache writes are 1.25x input.
            "claude-haiku-4-5-20251001": ModelPrice(input=1.0, output=5.0, cache_read=0.10),
            "claude-haiku-4-5": ModelPrice(input=1.0, output=5.0, cache_read=0.10),
            "claude-sonnet-5": ModelPrice(input=2.0, output=10.0, cache_read=0.20),
        }
    )


def estimate_cost(settings: ChatbotSettings, model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float | None:
    price = settings.prices.get(model)
    if price is None:
        return None
    read_rate = price.cache_read if price.cache_read is not None else price.input
    return (input_tokens * price.input + cache_write * price.input * 1.25 + cache_read * read_rate + output_tokens * price.output) / 1_000_000


async def get_settings(db: AsyncSession, *, fresh: bool = False) -> ChatbotSettings:
    now = time.monotonic()
    if not fresh and _cache["value"] is not None and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return copy.deepcopy(_cache["value"])
    row = await db.get(AppSetting, KEY)
    value = ChatbotSettings.model_validate(row.value) if row and row.value else ChatbotSettings()
    _cache.update(value=value, at=now)
    return copy.deepcopy(value)


async def save_settings(db: AsyncSession, settings: ChatbotSettings, user_id: str) -> ChatbotSettings:
    row = await db.get(AppSetting, KEY)
    data = settings.model_dump(mode="json")
    if row is None:
        db.add(AppSetting(key=KEY, value=data, updated_by_user_id=user_id))
    else:
        row.value = data
        row.updated_by_user_id = user_id
    await db.commit()
    _cache.update(value=settings, at=time.monotonic())
    return settings
