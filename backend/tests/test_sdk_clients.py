"""The Anthropic SDK against the dependencies actually installed.

Every other test stubs the provider, so nothing built a real client: when
httpx 0.28 landed, anthropic 0.34 couldn't construct one (it passed the
removed `proxies=` argument) and every Claude call in prod failed for three
hours with the suite green. This builds the client the way services do and
sends one request through the SDK's own HTTP stack to a mock transport.
"""
import json

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient


@pytest.mark.anyio
async def test_a_real_client_sends_a_message_request():
    sent = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content), path=request.url.path, key=request.headers.get("x-api-key"))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1, "cache_read_input_tokens": 2},
        })

    AsyncAnthropic(api_key="test-key")  # what services do: must not raise
    client = AsyncAnthropic(api_key="test-key", http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))
    response = await client.messages.create(
        model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "hello"}],
        extra_body={"temperature": 0},
    )

    assert response.content[0].text == "hi" and response.usage.cache_read_input_tokens == 2
    assert sent["path"] == "/v1/messages" and sent["key"] == "test-key"
    assert sent["temperature"] == 0  # extra_body reaches the wire, as the services rely on
