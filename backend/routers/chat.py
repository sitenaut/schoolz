"""The on-site chatbot's HTTP surface. Public, no auth required - same
access model as every other MCP-backed tool (see mcp_server.py's module
docstring). Every caller, signed in or not, gets find_local_events
(LocalEventTools); a signed-in caller additionally gets personal tools over
their own children's data (services/chatbot_personal.py). An invalid or
expired token degrades to the public tools rather than 401ing, like GET
/calendar.

Rate-limited per client IP with a simple in-memory sliding window: good
enough for a single Fly machine (min_machines_running=1 - see fly.toml),
not correct if this app ever scales to multiple machines, since each
machine would enforce the limit independently rather than sharing one
counter. Swap for a Redis-backed limiter first if that scaling happens -
this is deliberately not that, to avoid adding a new infra dependency for
a first version of a feature nobody's used in prod yet.
"""

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_user, oauth2_scheme
from database import get_db
from models import User
from services.chat_settings import get_settings
from services.chatbot import run_chat_turn
from services.i18n import request_lang
from services.chatbot_personal import LocalEventTools, PersonalTools

router = APIRouter(prefix="/chat", tags=["chat"])

_WINDOW_SECONDS = 600
_MAX_MESSAGES_PER_WINDOW = 20
_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window = _requests_by_ip[ip]
    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _MAX_MESSAGES_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many messages - please wait a few minutes and try again.")
    window.append(now)


class ChatMessage(BaseModel):
    role: str
    content: list[dict] | str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    escalated: bool = False


class ChatResponse(BaseModel):
    reply: str
    model: str | None
    history: list[ChatMessage]
    escalated: bool


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    body: ChatRequest,
    request: Request,
    user: User | None = Depends(get_optional_user),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(request_lang),
) -> ChatResponse:
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    # Only a token get_optional_user actually accepted is forwarded - the
    # personal tools then re-present it to each route, which re-checks it.
    personal = PersonalTools(request.app, token) if user and token else None
    # Offered to every caller, signed in or not - /local-events needs no login.
    local_events = LocalEventTools(request.app)
    settings = await get_settings(db)
    try:
        result = await run_chat_turn(
            request.app.state.mcp,
            history=[m.model_dump() for m in body.history],
            message=body.message,
            already_escalated=body.escalated,
            local_events=local_events,
            personal=personal,
            config=settings.signed_in if personal else settings.anonymous,
            lang=lang,
        )
    finally:
        await local_events.aclose()
        if personal:
            await personal.aclose()
    return ChatResponse(reply=result["reply"], model=result["model"], history=result["history"], escalated=result["escalated"])
