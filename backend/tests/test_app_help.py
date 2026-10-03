import asyncio
import re

from fastapi import FastAPI

from mcp_server import build_mcp_server
from services.app_help import TOPICS, app_help


def test_no_topic_lists_every_topic_with_its_summary():
    assert app_help()["topics"] == {key: entry["summary"] for key, entry in TOPICS.items()}


def test_a_topic_returns_its_guide_text():
    result = app_help("invites")
    assert result["topic"] == "invites"
    assert "Invite another guardian" in result["text"]


def test_topic_names_are_forgiving_about_case_spaces_and_dashes():
    assert app_help("Getting Started")["topic"] == "getting_started"
    assert app_help("kids-schoolwork")["topic"] == "kids_schoolwork"


def test_an_unknown_topic_returns_the_list_so_the_model_can_pick_again():
    result = app_help("billing")
    assert "error" in result
    assert set(result["topics"]) == set(TOPICS)


def test_the_tool_description_names_exactly_the_guide_topics():
    # The model only knows the topic names from the tool description, so a
    # topic added to the guide but not listed there would never be asked for.
    mcp = build_mcp_server(FastAPI())
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "get_app_help")
    listed = re.search(r"topic: one of (.*?)\.", tool.description, re.S).group(1)
    assert {name.strip() for name in listed.split(",")} == set(TOPICS)
