"""The on-site chatbot's HTTP surface. Public, no auth required - same
access model as every other MCP-backed tool (see mcp_server.py's module
docstring). A signed-in caller additionally gets personal tools over their
own children's data (services/chatbot_personal.py); an invalid or expired
token degrades to the public tools rather than 401ing, like GET /calendar.

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

from auth import get_optional_user, oauth2_scheme
from models import User
from services.chatbot import run_chat_turn
from services.chatbot_personal import PersonalTools

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
) -> ChatResponse:
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    # Only a token get_optional_user actually accepted is forwarded - the
    # personal tools then re-present it to each route, which re-checks it.
    personal = PersonalTools(request.app, token) if user and token else None
    try:
        result = await run_chat_turn(
            request.app.state.mcp,
            history=[m.model_dump() for m in body.history],
            message=body.message,
            already_escalated=body.escalated,
            personal=personal,
        )
    finally:
        if personal:
            await personal.aclose()
    return ChatResponse(**result)
