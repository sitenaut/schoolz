"""The on-site chatbot's HTTP surface. Public, no auth required - same
access model as every other MCP-backed tool (see mcp_server.py's module
docstring). Every caller, signed in or not, gets find_local_events
(LocalEventTools); a signed-in caller additionally gets personal tools over
their own children's data (services/chatbot_personal.py). An invalid or
expired token degrades to the public tools rather than 401ing, like GET
/calendar.

Rate-limited per connection: a count per salted IP hash per fixed
10-minute window, in the database (models.ChatRateWindow) so every API
machine shares it and a deploy doesn't reset it. This is the one public
route that costs money per request.
"""

import hashlib
import logging
import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_user, oauth2_scheme
from database import get_db
from models import ChatRateWindow, User
from services.chat_providers import ProviderUnavailable
from services.chat_settings import get_settings
from services.chatbot import run_chat_turn
from services.chatbot_personal import PERSONAL_TOOL_NAMES, LocalEventTools, PersonalTools
from services.client_ip import client_ip
from services.i18n import request_lang

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

UNAVAILABLE_REPLY = (
    "The assistant isn't available right now - please try again later. Everything else on schoolz "
    "(school pages, the calendar, lunch menus) works as usual."
)

SIGNED_OUT_REPLY = (
    "Your sign-in has expired, so I can't go on with a conversation about your children. Sign in again to keep "
    "asking about them, or ask me anything about schools in general."
)

_WINDOW_SECONDS = 600
_MAX_MESSAGES_PER_WINDOW = 20


def _ip_hash(ip: str) -> str:
    salt = os.getenv("JWT_SECRET", "schoolz-chat-salt")
    return hashlib.sha256(f"{salt}:chat:{ip}".encode()).hexdigest()


async def _check_rate_limit(db: AsyncSession, ip: str) -> None:
    now = datetime.now(UTC)
    window = datetime.fromtimestamp(now.timestamp() // _WINDOW_SECONDS * _WINDOW_SECONDS, UTC)
    stmt = (
        insert(ChatRateWindow)
        .values(ip_hash=_ip_hash(ip), window_start=window, count=1)
        .on_conflict_do_update(
            index_elements=[ChatRateWindow.ip_hash, ChatRateWindow.window_start],
            set_={"count": ChatRateWindow.count + 1},
        )
        .returning(ChatRateWindow.count)
    )
    count = (await db.execute(stmt)).scalar_one()
    if count == 1:
        # A new window for this connection: a cheap moment to clear old rows.
        await db.execute(delete(ChatRateWindow).where(ChatRateWindow.window_start < now - timedelta(days=1)))
    await db.commit()
    if count > _MAX_MESSAGES_PER_WINDOW:
        logger.warning("chat_rate_limited")
        raise HTTPException(status_code=429, detail="Too many messages - please wait a few minutes and try again.")


def _looked_up_a_child(history: list) -> bool:
    for message in history:
        content = message.content if isinstance(message.content, list) else []
        if any(b.get("type") == "tool_use" and b.get("name") in PERSONAL_TOOL_NAMES for b in content if isinstance(b, dict)):
            return True
    return False


class ChatMessage(BaseModel):
    role: str
    content: list[dict] | str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Only a size guard: run_chat_turn keeps the most recent turns itself
    # (chatbot.trim_history). At 40 this refused long conversations outright.
    history: list[ChatMessage] = Field(default_factory=list, max_length=200)
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
    ip = client_ip(request) or "unknown"
    await _check_rate_limit(db, ip)

    # Only a token get_optional_user actually accepted is forwarded - the
    # personal tools then re-present it to each route, which re-checks it.
    personal = PersonalTools(request.app, token) if user and token else None
    if personal is None and _looked_up_a_child(body.history):
        # A signed-in conversation whose token no longer validates: its
        # history (tool results and the answers quoting them) holds a child's
        # grades and schedule, which never go to the anonymous provider -
        # the two are configured apart on purpose (chatbot skill).
        logger.info("chat_signed_out_mid_conversation")
        return ChatResponse(reply=SIGNED_OUT_REPLY, model=None, history=[], escalated=False)
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
    except ProviderUnavailable as exc:
        logger.error("chatbot_provider_unavailable", extra={"error": str(exc)[:500]})
        # The visitor's history comes back unchanged, so asking again later just works.
        return ChatResponse(reply=UNAVAILABLE_REPLY, model=None, history=body.history, escalated=body.escalated)
    finally:
        await local_events.aclose()
        if personal:
            await personal.aclose()
    return ChatResponse(reply=result["reply"], model=result["model"], history=result["history"], escalated=result["escalated"])
