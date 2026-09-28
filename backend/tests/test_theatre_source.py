from datetime import date

from local_events.sources.theatre import page_text, to_raw_events

TODAY = date(2026, 9, 27)
TEXT = "Sweeney Todd - Oct 30-Nov 8 at Haddonfield Memorial High. Tickets [https://x.org/tix] Taylor Too Oct 25 7:00pm"


def run(prods):
    return to_raw_events(
        prods, TEXT, source="hp", venue_name="Home", venue_address="1 Main St",
        default_categories=["theatre"], page_url="https://x.org/season", today=TODAY,
    )


def test_run_range_is_all_day_with_end():
    (ev,) = run([{"title": "Sweeney Todd", "start_date": "2026-10-30", "end_date": "2026-11-08", "ticket_url": "https://x.org/tix"}])
    assert ev.all_day and ev.end_time.date() == date(2026, 11, 8)
    assert ev.url == "https://x.org/tix" and ev.venue_name == "Home"


def test_time_makes_it_timed_eastern():
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25", "start_time": "19:00"}])
    assert not ev.all_day and ev.start_time.hour == 19 and ev.start_time.utcoffset().total_seconds() == -4 * 3600


def test_invented_title_and_invented_url_are_dropped():
    assert run([{"title": "Hamilton", "start_date": "2026-10-25"}]) == []
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25", "ticket_url": "https://evil.example/"}])
    assert ev.url == "https://x.org/season"


def test_past_and_unparseable_dropped():
    assert run([{"title": "Taylor Too", "start_date": "2025-10-25"}, {"title": "Sweeney Todd", "start_date": "soon"}]) == []


def test_page_text_inlines_links():
    assert "[https://x.org/a]" in page_text('<p>Show <a href="/a">Tickets</a></p>', "https://x.org")
