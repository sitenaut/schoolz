import anthropic
import httpx
import httpx2
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import chat as chat_router
from services.chat_providers import AnthropicProvider, OpenAICompatibleProvider, ProviderUnavailable


@pytest.mark.anyio
async def test_a_provider_refusal_is_a_plain_reply_not_a_500(monkeypatch):
    """The public key hitting its monthly spend limit 500'd every question."""

    async def refused(*args, **kwargs):
        raise ProviderUnavailable("anthropic: You have reached your specified API usage limits.")

    monkeypatch.setattr(chat_router, "run_chat_turn", refused)
    monkeypatch.setattr(chat_router, "_requests_by_ip", chat_router.defaultdict(chat_router.deque))
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "answer"}]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "hi", "history": history, "escalated": True})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == chat_router.UNAVAILABLE_REPLY
    # Unchanged, so asking again later carries on the same conversation.
    assert body["history"] == history
    assert body["escalated"] is True


@pytest.mark.anyio
async def test_anthropic_errors_become_provider_unavailable():
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "You have reached your specified API usage limits."}})

    provider = AnthropicProvider("test-key")
    provider._client = anthropic.AsyncAnthropic(
        api_key="test-key", http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(refuse)), max_retries=0
    )
    with pytest.raises(ProviderUnavailable, match="usage limits"):
        await provider.complete(model="claude-haiku-4-5", system="s", dynamic_system=None, tools=[], messages=[{"role": "user", "content": "hi"}])


@pytest.mark.anyio
async def test_openai_compatible_errors_become_provider_unavailable(monkeypatch):
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="quota exceeded")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(refuse), **kw))
    provider = OpenAICompatibleProvider("gemini", "https://example.invalid/v1", "test-key")
    with pytest.raises(ProviderUnavailable, match="429"):
        await provider.complete(model="gemini-x", system="s", dynamic_system=None, tools=[], messages=[{"role": "user", "content": "hi"}])
