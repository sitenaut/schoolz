"""The chat serves the whole community: a question about activities or help
gets searched, what's typed into a Localz search stays out of the logs, and a
reply with no text never reaches the visitor as a blank bubble."""
import json
import logging
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import database
from main import app
from mcp_server import build_mcp_server
from models import LocalEvent, ResourceService
from services.chat_providers import Completion, Usage
from services.chat_search_words import own_terms, search_terms, singular
from services.chat_settings import AudienceConfig
from services.chatbot import NO_ANSWER_REPLY, SYSTEM_PROMPT, _run_tool, run_chat_turn
from services.chatbot_personal import LocalEventTools


class _Scripted:
    """A provider that answers from a list, in order."""

    def __init__(self, *turns):
        self.turns = list(turns)

    async def complete(self, **_):
        content, stop = self.turns.pop(0)
        return Completion(content=content, usage=Usage(), stop_reason=stop)


async def _listing(**fields):
    defaults = {"source": "test", "source_record_id": uuid.uuid4().hex, "taxonomy_codes": [], "service_areas": ["Camden County"]}
    async with database.SessionLocal() as db:
        db.add(ResourceService(**{**defaults, **fields}))
        await db.commit()


async def _search(**args):
    return json.loads(await _run_tool(build_mcp_server(app), "search_resources", args))


@pytest.mark.parametrize(
    ("word", "stem"),
    [("seniors", "senior"), ("classes", "class"), ("libraries", "library"), ("class", "class"), ("bus", "bus"), ("news", "news")],
)
def test_singular(word, stem):
    assert singular(word) == stem


def test_search_terms_reach_what_listings_say():
    assert own_terms("seniors") == ("senior",)  # text matching: "senior" also finds "seniors"
    assert own_terms("libraries") == ("libraries", "library")
    assert "crochet" in search_terms("knitting")
    assert "older adult" in search_terms("seniors")
    assert "smartphone" in search_terms("iphone")


def test_prompt_covers_everyone_and_crisis_lines():
    assert "people of every age" in SYSTEM_PROMPT
    for line in ("911", "988", "1-800-572-7233", "88788", "211"):
        assert line in SYSTEM_PROMPT
    assert "immigration status" in SYSTEM_PROMPT


@pytest.mark.anyio
async def test_an_open_event_search_needs_no_dates_and_finds_the_singular():
    src = f"chat_{uuid.uuid4().hex[:8]}"
    soon = datetime.now(UTC) + timedelta(days=10)
    async with database.SessionLocal() as db:
        db.add(LocalEvent(source=src, source_event_id="a", title="Xqzsenior Chair Yoga", start_time=soon, categories=["library"]))
        db.add(LocalEvent(source=src, source_event_id="b", title="Xqzsenior Next Season", start_time=soon + timedelta(days=60), categories=["library"]))
        await db.commit()

    tools = LocalEventTools(app)
    try:
        defs = await tools.tool_defs()
        assert "required" not in defs[0]["input_schema"]
        res = json.loads(await tools.run("find_local_events", {"query": "xqzseniors"}))
        assert [e["title"] for e in res["items"]] == ["Xqzsenior Chair Yoga"]
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_three_words_are_a_list_of_interests_not_a_failed_match():
    src = f"chat_{uuid.uuid4().hex[:8]}"
    soon = datetime.now(UTC) + timedelta(days=3)
    async with database.SessionLocal() as db:
        db.add(LocalEvent(source=src, source_event_id="a", title="Xqzknit Circle", start_time=soon, categories=["library"]))
        await db.commit()

    tools = LocalEventTools(app)
    try:
        res = json.loads(await tools.run("find_local_events", {"query": "xqzknit xqzcoding xqzsenior"}))
        assert [e["title"] for e in res["items"]] == ["Xqzknit Circle"]
        assert "closest matches" not in res.get("note", "")
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_search_resources_falls_back_to_words_and_ranks_by_name():
    await _listing(name="Alpha Services", phone="856-555-0100", description="Also serves xqzelder neighbors")
    await _listing(name="Zeta Xqzelder Center", city="Blackwood", address="512 Lakeland Rd", hours_text="Mon-Fri")

    # Nothing is listed as the whole phrase; a wrong category doesn't hide them.
    res = await _search(query="xqzelder activities", category="kids-family", county="Camden County")
    assert [i["name"] for i in res["items"]] == ["Zeta Xqzelder Center", "Alpha Services"]
    top = res["items"][0]
    assert top["where"] == "512 Lakeland Rd, Blackwood" and top["hours"] == "Mon-Fri"
    assert "/localz/r/" in top["url"]


@pytest.mark.anyio
async def test_search_resources_tolerates_a_county_or_category_it_does_not_know():
    await _listing(name="Xqzpantry", service_areas=["NJ"])
    res = await _search(query="xqzpantry", county="Philadelphia", category="not-a-category")
    assert [i["name"] for i in res["items"]] == ["Xqzpantry"]


@pytest.mark.anyio
async def test_search_resources_never_gives_a_shelter_address():
    await _listing(name="Xqzrefuge Safe House", address="1 Hidden St", city="Camden", description="Emergency shelter")
    await _listing(name="Xqzrefuge Program", address="2 Hidden St", description="A domestic violence emergency shelter for adults.")
    await _listing(name="Xqzrefuge Line", address=None, city=None, address_kind="confidential")
    await _listing(name="Xqzrefuge Pantry", address="3 Open St")

    res = await _search(query="xqzrefuge")
    where = {i["name"]: i["where"] for i in res["items"]}
    assert where["Xqzrefuge Pantry"] == "3 Open St"
    for name in ("Xqzrefuge Safe House", "Xqzrefuge Program", "Xqzrefuge Line"):
        assert where[name] == "Location shared after you call"
    assert "Hidden" not in json.dumps(res)


@pytest.mark.anyio
async def test_a_localz_search_keeps_its_words_out_of_the_logs(caplog):
    secret = "xqzhusband hits me"
    await _listing(name="Xqzhusband Help")
    provider = _Scripted(
        ([{"type": "tool_use", "id": "t1", "name": "search_resources", "input": {"query": secret, "category": "legal-safety", "county": "Camden"}}], "tool_use"),
        ([{"type": "text", "text": "Here is help."}], "end_turn"),
    )
    with caplog.at_level(logging.DEBUG):
        result = await run_chat_turn(
            build_mcp_server(app), [], "where can I go", False, config=AudienceConfig(), providers={"anthropic": provider}
        )

    assert result["reply"] == "Here is help."
    assert result["tools_called"] == ["search_resources"]
    logged = [r for r in caplog.records if r.getMessage() == "chatbot_tool_call"]
    assert json.loads(logged[0].tool_input) == {"category": "legal-safety", "county": "Camden"}
    everything = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "xqzhusband" not in everything


@pytest.mark.anyio
@pytest.mark.parametrize("stop", ["refusal", "max_tokens", "end_turn"])
async def test_a_reply_with_no_text_is_never_blank(stop):
    """A safety decline is HTTP 200 with no text. An empty turn would also make
    the provider refuse every later turn of the conversation."""
    result = await run_chat_turn(
        build_mcp_server(app), [], "hello", False, config=AudienceConfig(), providers={"anthropic": _Scripted(([], stop))}
    )
    assert result["reply"] == NO_ANSWER_REPLY
    assert "988" in result["reply"]
    assert result["history"][-1] == {"role": "assistant", "content": [{"type": "text", "text": NO_ANSWER_REPLY}]}
