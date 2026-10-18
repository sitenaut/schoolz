from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from local_events.sources.base import RawEvent
from local_events.sources.event_pages import EventPageSource
from local_events.sources.theatre import TheatreSiteSource, to_raw_events

TODAY = date(2026, 10, 18)
TEXT = (
    "Holiday Parade - Saturday, November 28 beginning at 10 am. Boos and Brews: Join us Friday, October 10. "
    "Community Buy Nothing Exchange on May 17. " + "Bring gently used items to share with neighbors. " * 4
    + "Summer Bummer Fest: Sunday, June 20, 2027. "
    "Parade of Lights December 4, 2026, 6:30pm, Knight Park. Small Business Saturday"
)


def run(events):
    return to_raw_events(
        events, TEXT, source="cw", venue_name=None, venue_address=None, default_categories=["community"],
        page_url="https://town.example/events", today=TODAY, id_prefix="page", town="Collingswood, NJ",
    )


def titles(events):
    return [e.title for e in run(events)]


def test_a_written_weekday_must_match_the_date():
    # Boos and Brews' page is last year's: Oct 10, 2027 is a Sunday, not a Friday.
    assert titles([{"title": "Boos and Brews", "start_date": "2027-10-10", "weekday": "Friday", "year_written": False}]) == []
    assert titles([{"title": "Holiday Parade", "start_date": "2026-11-28", "weekday": "Saturday", "year_written": False}]) == ["Holiday Parade"]


def test_a_yearless_date_must_be_soon_whatever_the_model_says():
    # The model claimed the year was written; the page never says 2027.
    assert titles([{"title": "Community Buy Nothing Exchange", "start_date": "2027-05-17", "year_written": True}]) == []
    # A year the page does write is believed, however far off.
    assert titles([{"title": "Summer Bummer Fest", "start_date": "2027-06-20", "weekday": "Sunday", "year_written": True}]) == ["Summer Bummer Fest"]


def test_a_named_venue_is_placed_in_the_town():
    (ev,) = run([{"title": "Parade of Lights", "start_date": "2026-12-04", "start_time": "18:30", "venue": "Knight Park", "year_written": True}])
    assert ev.venue_name == "Knight Park" and ev.venue_address == "Knight Park, Collingswood, NJ"
    assert ev.source_event_id.startswith("page:") and not ev.all_day


def test_theatre_entries_without_the_new_fields_are_unaffected():
    (ev,) = to_raw_events(
        [{"title": "Holiday Parade", "start_date": "2027-11-28"}], TEXT, source="t", venue_name="Home", venue_address="1 Main",
        default_categories=["theatre"], page_url="https://x", today=TODAY,
    )
    assert ev.source_event_id.startswith("theatre:") and ev.venue_address == "1 Main"


@pytest.mark.anyio
async def test_the_same_event_on_two_pages_is_kept_once(monkeypatch):
    at = datetime(2026, 11, 28, 10, tzinfo=ZoneInfo("America/New_York"))

    async def both(self):
        return [
            RawEvent(source="cw", source_event_id="a", title="Holiday Parade", start_time=at),
            RawEvent(source="cw", source_event_id="b", title="2026 Collingswood Holiday Parade", start_time=at, venue_name="Haddon Avenue"),
            RawEvent(source="cw", source_event_id="c", title="Small Business Saturday", start_time=at),
        ]

    monkeypatch.setattr(TheatreSiteSource, "fetch", both)
    kept = await EventPageSource(name="cw", urls=["https://town.example"]).fetch()
    assert sorted(e.source_event_id for e in kept) == ["b", "c"]  # the copy naming a venue wins


@pytest.mark.anyio
async def test_a_page_read_once_is_not_paid_for_again_after_a_restart(monkeypatch):
    import uuid

    from local_events.sources import theatre

    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            block = type("B", (), {"type": "tool_use", "input": {"events": [{"title": "Holiday Parade", "start_date": "2026-11-28"}]}})()
            return type("R", (), {"content": [block], "stop_reason": "tool_use", "usage": None})()

    monkeypatch.setattr(theatre, "AsyncAnthropic", lambda **_: type("C", (), {"messages": FakeMessages()})())
    monkeypatch.setattr(theatre.observability, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(theatre, "_CACHE", {})
    src = EventPageSource(name="cw", urls=["https://town.example"])
    text = f"Holiday Parade, Saturday November 28 {uuid.uuid4()}"

    first = await src._extract(text)
    theatre._CACHE.clear()  # what a deploy does to the in-process cache
    second = await src._extract(text)
    assert first == second and len(calls) == 1


@pytest.mark.anyio
async def test_live_feed_posts_keep_events_honour_moves_and_ignore_the_posting_date(monkeypatch):
    from local_events.sources import thrillshare

    posts = [
        {"id": 3, "time": "2026-10-09T08:44:16-04:00", "status": "The Civic Association moved the Town Picnic to next Sunday, October 18th, 12 to 3 p.m."},
        {"id": 2, "time": "2026-10-06T10:48:57-04:00", "status": "Green Team Movie Night flyer attached"},
        {"id": 1, "time": "2026-10-06T10:22:45-04:00", "status": "<p>Oaklyn Town Picnic - Sunday, October 25 - 12 p.m. to 3 p.m.</p>"},
        {"id": 0, "time": "2026-10-05T09:00:00-04:00", "status": "PSE&G gas main work Monday 10/19 on Landis Ave, 7am to 5pm"},
    ]
    answers = {
        3: [{"title": "Town Picnic", "start_date": "2026-10-18", "start_time": "12:00", "weekday": "Sunday", "year_written": False, "moved_from": "2026-10-25"}],
        2: [{"title": "Green Team Movie Night", "start_date": "2026-10-06", "year_written": False}],
        1: [{"title": "Oaklyn Town Picnic", "start_date": "2026-10-25", "weekday": "Sunday", "year_written": False}],
        0: [],
    }

    class Resp:
        def __init__(self, page):
            self.page = page

        def raise_for_status(self):
            pass

        def json(self):
            return {"live_feeds": posts if self.page == 1 else []}

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params):
            return Resp(params["page_no"])

    async def extract(self, text):
        return next(answers[p["id"]] for p in posts if thrillshare.page_text(p["status"], "") in text)

    monkeypatch.setattr(thrillshare.httpx, "AsyncClient", Client)
    monkeypatch.setattr(EventPageSource, "_extract", extract)
    monkeypatch.setattr(thrillshare, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: datetime(2026, 10, 12, 9, tzinfo=tz))}))
    src = thrillshare.ThrillshareSource("oaklyn", "1", site_url="https://oaklyn.example/", live_feed=True, location="Oaklyn, NJ")
    events = await src._live_feed()
    # Oct 25 was taken back by the later post; the movie night had no date of its own.
    assert [(e.title, e.start_time.date().isoformat()) for e in events] == [("Town Picnic", "2026-10-18")]
    assert events[0].url == "https://oaklyn.example/live-feed" and events[0].source_event_id.startswith("post:")


_NEWS_HTML = """
<div class="editNews"><a name="news_rz790"></a></div>
<div style="width: 20%; float: left;"><img src="newsimage/fall fest.jpg?t=1" alt="" /></div>
<div style="width: 72%; float: right;"> October 14, 2026
  <h3 class="news-title">PTA Fall Festival</h3>
  <div class="news-desc"><p><img src="Fall Festival Flyer.jpg?t=2" /></p></div>
  <div class="news-post clearfix"><a href="news_detail_T6_R790.php" class="readmore">Read More</a></div>
</div>
<div class="editNews"><a name="news_rz700"></a></div>
<div style="width: 20%; float: left;"></div>
<div style="width: 72%; float: right;"> May 2, 2026
  <h3 class="news-title">May Fair</h3>
  <div class="news-desc"><p>Saturday, May 9</p></div>
</div>
"""


def test_revize_news_list_gives_recent_posts_with_their_flyers():
    from local_events.sources.revize_calendar_app import parse_news

    posts = parse_news(_NEWS_HTML, "https://town.example", since=datetime(2026, 9, 1, tzinfo=ZoneInfo("America/New_York")))
    assert [p.body for p in posts] == ["PTA Fall Festival"]  # May's post is past the window
    assert posts[0].url == "https://town.example/news_detail_T6_R790.php"
    assert posts[0].images == ["https://town.example/newsimage/fall%20fest.jpg?t=1", "https://town.example/Fall%20Festival%20Flyer.jpg?t=2"]


@pytest.mark.anyio
async def test_a_post_that_is_only_a_title_over_a_flyer_is_read_from_the_flyer(monkeypatch):
    from local_events.sources import event_pages
    from local_events.sources.event_pages import Post, read_posts

    async def flyer(client, url):
        return "" if "thumb" in url else "COSTUME EXCHANGE\nFALL FESTIVAL\nSATURDAY, OCT 24 2026 | KNIGHT PARK"

    seen = []

    async def extract(self, text):
        seen.append(text)
        return [{"title": "Fall Festival", "start_date": "2026-10-24", "weekday": "Saturday", "year_written": True, "venue": "Knight Park"}]

    monkeypatch.setattr(event_pages, "flyer_text", flyer)
    monkeypatch.setattr(EventPageSource, "_extract", extract)
    reader = EventPageSource(name="cw", urls=["https://town.example/newslist.php"], town="Collingswood, NJ")
    post = Post(ref="r1", posted=datetime(2026, 10, 14, tzinfo=ZoneInfo("America/New_York")), body="Fall Festival",
                url="https://town.example/news_detail_T6_R790.php", images=["https://town.example/thumb.jpg", "https://town.example/flyer.jpg"])
    events = await read_posts(reader, [post], default_categories=["collingswood"], id_prefix="news", today=date(2026, 10, 18), failures=[])
    assert "KNIGHT PARK" in seen[0] and "Posted Wednesday, October 14, 2026" in seen[0]
    assert [(e.title, e.start_time.date().isoformat(), e.venue_address) for e in events] == [("Fall Festival", "2026-10-24", "Knight Park, Collingswood, NJ")]
    assert events[0].source_event_id.startswith("news:")


@pytest.mark.anyio
async def test_a_flyer_is_transcribed_once_ever_and_non_flyers_come_back_empty(monkeypatch):
    import io
    import os

    from PIL import Image

    from local_events.sources import flyers, theatre

    buf = io.BytesIO()
    Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3)).save(buf, format="PNG")
    images = {"https://x/flyer.png": buf.getvalue(), "https://x/agenda.png": buf.getvalue()[:-1] + b"\0"}
    replies = iter(["MOVIE NIGHT\nFRIDAY, OCTOBER 9", "NONE"])
    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return type("R", (), {"content": [type("B", (), {"type": "text", "text": next(replies)})()], "stop_reason": "end_turn", "usage": None})()

    class Client:
        async def get(self, url):
            return type("Resp", (), {"content": images[url], "raise_for_status": lambda self: None})()

    monkeypatch.setattr(flyers, "AsyncAnthropic", lambda **_: type("C", (), {"messages": FakeMessages()})())
    monkeypatch.setattr(flyers.observability, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(theatre, "_CACHE", {})

    assert await flyers.flyer_text(Client(), "https://x/flyer.png") == "MOVIE NIGHT\nFRIDAY, OCTOBER 9"
    theatre._CACHE.clear()  # a deploy
    assert await flyers.flyer_text(Client(), "https://x/flyer.png") == "MOVIE NIGHT\nFRIDAY, OCTOBER 9"
    assert await flyers.flyer_text(Client(), "https://x/agenda.png") == ""
    assert len(calls) == 2


@pytest.mark.anyio
async def test_a_dead_flyer_link_is_skipped_without_a_warning(monkeypatch):
    import httpx

    from local_events.sources import event_pages
    from local_events.sources.event_pages import Post, read_posts

    async def flyer(client, url):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("x", request=request, response=httpx.Response(403 if "dead" in url else 503, request=request))

    async def extract(self, text):
        return []

    monkeypatch.setattr(event_pages, "flyer_text", flyer)
    monkeypatch.setattr(EventPageSource, "_extract", extract)
    failures = []
    post = Post(ref="r", posted=datetime(2026, 10, 14, tzinfo=ZoneInfo("America/New_York")), body="Borough news post text",
                url="https://town.example/n", images=["https://town.example/dead.png", "https://town.example/busy.png"])
    await read_posts(EventPageSource(name="cw", urls=["https://town.example"]), [post], default_categories=[], id_prefix="news", today=date(2026, 10, 18), failures=failures)
    assert failures == ["flyer https://town.example/busy.png: HTTP 503"]
