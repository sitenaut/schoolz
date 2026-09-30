from datetime import date, datetime

from services import student_bulletin as sb

TEXT = open(__file__.replace("test_student_bulletin.py", "fixtures/student_bulletin.txt"), encoding="utf-8").read()
TODAY = date(2026, 9, 29)


def test_sports_are_split_off_and_parsed_with_times_and_default_time():
    body, sports = sb.split_sports(TEXT)
    assert "Girls Soccer" not in body and "Girls Soccer" in sports
    games = sb.parse_sports(sports, TODAY)
    assert len(games) == 8 + 8 + 9 + 8
    first = games[0]
    assert first["title"] == "Girls Soccer: MMS at Medford"
    assert first["start_date"] == datetime(2026, 9, 30, 15, 15, tzinfo=sb._ET)
    xc = [g for g in games if g["title"].startswith("Cross Country")]
    assert xc[0]["title"] == "Cross Country: at MMS"
    assert xc[0]["start_date"].hour == 15 and xc[0]["start_date"].minute == 45
    assert not xc[0]["is_all_day"]


def test_house_offices():
    houses = sb.parse_houses(TEXT)
    assert [h["email"] for h in houses] == ["beattym@evesham.k12.nj.us", "hainesm@evesham.k12.nj.us"]
    assert houses[0]["phone"] == "(856)988-0684 ext. 8509"
    assert houses[0]["constituent_id"] == "bulletin:blue-house"


def test_resolve_year_rolls_across_new_year():
    assert sb.resolve_year(10, 5, TODAY) == date(2026, 10, 5)
    assert sb.resolve_year(1, 10, TODAY) == date(2027, 1, 10)
    assert sb.resolve_year(2, 30, TODAY) is None


def test_build_items_rolls_a_stale_year_and_infers_all_day():
    items = sb.build_items(
        [
            {"category": "event", "title": "Spirit Day: Pink Out", "start_date": "2025-10-09"},
            {"category": "event", "title": "Half day dismissal 11:30am", "start_date": "2026-10-13T11:30"},
            {"category": "procedure", "title": "Late buses"},
            {"category": "event", "title": ""},
            {"category": "event", "title": "Delayed Opening *9:15am*", "start_date": "2026-10-12"},
        ],
        TODAY,
        "http://doc",
    )
    assert len(items) == 4 and items[3]['title'] == 'Delayed Opening 9:15am'
    assert items[0]["start_date"].year == 2026 and items[0]["is_all_day"]
    assert not items[1]["is_all_day"]
    assert items[2]["start_date"] is None and items[2]["link_url"] == "http://doc"
