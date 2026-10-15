import pytest

from mcp_server import _with_day_effect
from services.chat_school_hint import match_schools, school_hint


def _s(slug, name, short_name, school_type, town):
    return {"slug": slug, "name": name, "short_name": short_name, "school_type": school_type, "address": f"1 Main St, {town}, NJ 08000"}


SCHOOLS = [
    _s("beck", "Henry C. Beck Middle School", "Beck", "middle", "Cherry Hill"),
    _s("kingston", "Kingston Elementary School", "Kingston", "elementary", "Cherry Hill"),
    _s("cherry-hill-high-school-east", "Cherry Hill High School East", "Cherry Hill High School East", "high", "Cherry Hill"),
    _s("cherry-hill-high-school-west", "Cherry Hill High School West", "Cherry Hill High School West", "high", "Cherry Hill"),
    _s("garfield-east-elementary-ecdc", "Garfield East Elementary & ECDC", "Garfield East", "other", "Garfield"),
    _s("haddonfield-memorial-high", "Haddonfield Memorial High School", "Haddonfield HS", "high", "Haddonfield"),
    _s("haddonfield-middle", "Haddonfield Middle School", "Haddonfield Middle", "middle", "Haddonfield"),
    _s("james-johnson", "James Johnson Elementary", "James Johnson", "elementary", "Cherry Hill"),
    _s("johnson-es", "Thomas Johnson Elementary School", "Thomas Johnson", "elementary", "Somerdale"),
    _s("signal-hill", "Signal Hill Elementary School", "Signal Hill", "elementary", "Voorhees"),
    _s("big-picture", "Big Picture Learning Academy", "Big Picture", "high", "Camden"),
    _s("head-start", "Mosaic Early Learning Center Head Start", "Head Start", "other", "Voorhees"),
    _s("demasi-es", "Marlton DeMasi Elementary", "DeMasi", "elementary", "Marlton"),
    _s("demasi-ms", "DeMasi Middle School", "DeMasi", "middle", "Marlton"),
]


def _slugs(message):
    return [s["slug"] for s in match_schools(message, SCHOOLS)]


def test_one_school_by_its_short_name():
    assert _slugs("What bus does my kid take to Beck Middle?") == ["beck"]
    assert _slugs("Is Kingston Elementary closed for Election Day?") == ["kingston"]


def test_the_most_specific_name_wins():
    assert _slugs("Is there school on Election Day at Cherry Hill East?") == ["cherry-hill-high-school-east"]


def test_a_town_alone_names_no_school():
    assert _slugs("Is there school tomorrow in Cherry Hill?") == []
    assert _slugs("When is the next day off for Haddonfield schools?") == []
    assert _slugs("What time does Haddonfield Middle School get out?") == ["haddonfield-middle"]


def test_a_last_name_alone_lists_every_school_it_fits():
    assert sorted(_slugs("When is picture day at Johnson Elementary?")) == ["james-johnson", "johnson-es"]
    assert sorted(_slugs("lunch at DeMasi tomorrow?")) == ["demasi-es", "demasi-ms"]


def test_an_ordinary_word_is_not_a_school_name():
    assert _slugs("When is picture day at Johnson Elementary?") == ["james-johnson", "johnson-es"]
    assert _slugs("When does winter break start in Voorhees?") == []
    assert _slugs("Is there a band concert at Johnson?") == ["james-johnson", "johnson-es"]


def test_the_hint_says_look_it_up_or_ask():
    one = school_hint("What bus does my kid take to Beck Middle?", SCHOOLS)
    assert "Henry C. Beck Middle School in Cherry Hill (slug 'beck')" in one and "don't ask" in one
    several = school_hint("lunch at DeMasi tomorrow?", SCHOOLS)
    assert "DeMasi Middle School in Marlton" in several and "ask which one" in several
    assert school_hint("Are there any fall festivals this weekend?", SCHOOLS) is None


def test_calendar_items_say_whether_they_close_school():
    items = _with_day_effect([
        {"title": "Board of Education Election Day"},
        {"title": "SCHOOLS CLOSED - NJEA Convention"},
        {"title": "EARLY DISMISSAL - Conferences"},
    ])
    assert [i["day_effect"] for i in items] == [
        "none - not a closing, the school day runs as usual",
        "no school",
        "early dismissal",
    ]


def test_days_covered_treats_an_all_day_end_as_exclusive():
    from datetime import date

    from mcp_server import _days_covered

    njea = {"start_date": "2026-11-05T00:00:00-05:00", "end_date": "2026-11-07T00:00:00-05:00", "is_all_day": True}
    assert _days_covered(njea) == [date(2026, 11, 5), date(2026, 11, 6)]
    one = {"start_date": "2026-11-03T00:00:00-05:00", "end_date": None, "is_all_day": True}
    assert _days_covered(one) == [date(2026, 11, 3)]


@pytest.mark.anyio
async def test_get_school_day_answers_one_date():
    import json
    import uuid
    from datetime import UTC, datetime

    import database
    from main import app
    from models import District, School, SchoolContentItem
    from services.chatbot import _run_tool

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Day Test District {tag}")
        db.add(district)
        await db.flush()
        db.add(School(name=f"Day Test High {tag}", slug=f"day-test-{tag}", school_type="high", district_id=district.id, address="1 Main St, Cherry Hill, NJ 08002"))
        common = dict(scope="district", district_id=district.id, category="event", is_current=True, source="ics_feed", is_all_day=True)
        db.add_all([
            SchoolContentItem(title="Day 3", start_date=datetime(2026, 11, 3, 5, tzinfo=UTC), end_date=datetime(2026, 11, 4, 5, tzinfo=UTC), **common),
            SchoolContentItem(title="Board of Education Election Day", start_date=datetime(2026, 11, 3, 5, tzinfo=UTC), **common),
            SchoolContentItem(title="SCHOOLS CLOSED - NJEA Convention", start_date=datetime(2026, 11, 5, 5, tzinfo=UTC), end_date=datetime(2026, 11, 7, 5, tzinfo=UTC), **common),
            SchoolContentItem(title="K-8 Single Session", start_date=datetime(2026, 11, 10, 5, tzinfo=UTC), **common),
        ])
        await db.commit()

    async def day(d):
        return json.loads(await _run_tool(app.state.mcp, "get_school_day", {"school_id_or_slug": f"day-test-{tag}", "date": d}))

    election = await day("2026-11-03")
    assert election["school_day"] == "regular school day" and election["rotation_day"] == "Day 3"
    assert election["other_items"] == ["Board of Education Election Day"] and election["school"].endswith("in Cherry Hill")
    njea = await day("2026-11-06")  # the second day of a two-day closing
    assert njea["school_day"] == "no school" and njea["reason"] == "NJEA Convention"
    assert (await day("2026-11-10"))["school_day"] == "regular school day"  # a K-8 half day, not the high school's
    assert (await day("2026-11-07"))["school_day"] == "weekend"
    assert "error" in await day("Nov 3")
