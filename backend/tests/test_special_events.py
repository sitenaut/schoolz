from pathlib import Path

from services.special_events import _find_calendar_pdf_url

_FIXTURE = Path(__file__).parent / "fixtures" / "special_events" / "chesterbrook_calendars_menu_2026_09.html"


def test_finds_the_special_events_calendar_pdf_on_the_real_page():
    html = _FIXTURE.read_text()
    url = _find_calendar_pdf_url(html)
    assert url == "https://www.chesterbrookacademy.com/wp-content/uploads/sites/2/2026/08/September-2026-Special-Events-Calendar.pdf"


def test_ignores_the_other_pdf_links_on_the_page():
    # The same page also links a lunch menu and a newsletter PDF for the
    # month - neither should be picked up as the special-events calendar.
    html = """
    <a href="https://example.com/wp-content/uploads/2026/09/September-2026-Lunch-Menu.pdf">Lunch Menu</a>
    <a href="https://example.com/wp-content/uploads/2026/09/September-2026-Newsletter.pdf">Newsletter</a>
    """
    assert _find_calendar_pdf_url(html) is None


def test_no_calendar_posted_yet_returns_none():
    assert _find_calendar_pdf_url("<html><body>no pdfs here</body></html>") is None


# -- lunch menus on the same page ----------------------------------------------

import os  # noqa: E402
import uuid  # noqa: E402
from datetime import date, datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

import database  # noqa: E402
from models import LunchMenu, LunchMenuItem, School  # noqa: E402
from scheduler.jobs import special_events_scan  # noqa: E402
from services import special_events  # noqa: E402
from services.special_events import (  # noqa: E402
    calendar_pdfs_from_pages,
    discover_menu_pdf_urls,
    menu_links_from_html,
    menu_url_guesses,
    month_from_filename,
)

_UPLOADS = "https://www.chesterbrookacademy.com/wp-content/uploads/sites/2/"
_OCT_MENU = _UPLOADS + "2026/10/October-2026-Lunch-Menu.pdf"


def test_menu_links_on_the_real_page():
    links = menu_links_from_html(_FIXTURE.read_text())
    assert links[(2026, 9)] == _UPLOADS + "2026/08/September-2026-Lunch-Menu-1.pdf"
    assert (2026, 10) not in links


def test_month_comes_from_the_filename():
    assert month_from_filename(_UPLOADS + "2026/08/September-2026-Special-Events-Calendar.pdf") == (2026, 9)
    assert month_from_filename("https://x.test/menu.pdf") is None
    # The page ignores ?mm=, so October's page still lists September's
    # calendar - it must stay September, not be filed (and parsed) as October.
    html = _FIXTURE.read_text()
    assert calendar_pdfs_from_pages([(2026, 10, html), (2026, 11, html)]) == [
        (2026, 9, _UPLOADS + "2026/08/September-2026-Special-Events-Calendar.pdf")
    ]


def test_upload_path_guesses():
    guesses = menu_url_guesses(_UPLOADS, 2026, 10)
    assert guesses[0] == _OCT_MENU
    assert _UPLOADS + "2026/09/October-2026-Lunch-Menu-1.pdf" in guesses
    assert menu_url_guesses(_UPLOADS, 2027, 1)[3].startswith(_UPLOADS + "2026/12/January-2027")


@pytest.mark.anyio
async def test_finds_an_unlinked_menu_at_its_upload_path(monkeypatch):
    async def fake_is_pdf(client, url):
        return url == _OCT_MENU

    monkeypatch.setattr(special_events, "_is_pdf", fake_is_pdf)
    html = _FIXTURE.read_text()
    found = await discover_menu_pdf_urls([(2026, 10, html)], date(2026, 10, 4))
    assert found == [(2026, 10, _OCT_MENU)]


@pytest.mark.anyio
async def test_scan_stores_the_month_menu_once(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Preschool {tag}", slug=f"preschool-{tag}", special_events_calendar_url="https://x.test/calendars-menu/")
        db.add(school)
        await db.commit()
        await db.refresh(school)

    html = _FIXTURE.read_text()
    calls = []

    async def fake_pages(url, today=None):
        return [(2026, 10, html)]

    async def fake_menus(pages, today=None):
        return [(2026, 10, _OCT_MENU)]

    async def fake_parse(url, label, meal_type=None):
        calls.append((url, label))
        return [{"date": datetime(2026, 10, 5, tzinfo=ZoneInfo("America/New_York")), "description": "Baked Ziti", "notes": None}]

    async def no_events(*a, **k):
        return []

    monkeypatch.setattr(special_events_scan, "fetch_month_pages", fake_pages)
    monkeypatch.setattr(special_events_scan, "discover_menu_pdf_urls", fake_menus)
    monkeypatch.setattr(special_events_scan, "parse_menu_pdf", fake_parse)
    monkeypatch.setattr(special_events_scan, "parse_special_events_pdf", no_events)

    async with database.SessionLocal() as db:
        result = await special_events_scan.run(db, {"school_id": school.id})
        await db.commit()
        assert "1 newly parsed" in result and not result.startswith("WARNING")
        again = await special_events_scan.run(db, {"school_id": school.id})
        assert "0 newly parsed" in again
        menus = (await db.execute(select(LunchMenu).where(LunchMenu.school_id == school.id))).scalars().all()
        assert [(m.period_label, m.source_pdf_url) for m in menus] == [("October 2026", _OCT_MENU)]
        items = (await db.execute(select(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menus[0].id))).scalars().all()
        assert [i.description for i in items] == ["Baked Ziti"]
    assert calls == [(_OCT_MENU, "October 2026")]


def test_portions_are_stripped():
    raw = "Cheeseburger Meatloaf, 1ea; Wheat Dinner Roll, 1ea; Spinach, 4oz; Shredded Mozzarella, 1/2oz; Pizza Day! Cheese Pizza, 1sl"
    assert special_events.strip_portions(raw) == "Cheeseburger Meatloaf, Wheat Dinner Roll, Spinach, Shredded Mozzarella, Pizza Day! Cheese Pizza"
    assert special_events.strip_portions("Buffalo Cheese Pizza Sticks (LTO)") == "Buffalo Cheese Pizza Sticks (LTO)"


def test_menu_days_keep_only_the_month_and_real_meals():
    tz = ZoneInfo("America/New_York")
    days = [
        {"date": datetime(2026, 9, 30, tzinfo=tz), "description": "Pizza Day! Cheese Pizza"},
        {"date": datetime(2026, 10, 1, tzinfo=tz), "description": "Cheeseburger Meatloaf"},
        {"date": datetime(2026, 10, 16, tzinfo=tz), "description": "No meal listed"},
        {"date": datetime(2026, 11, 2, tzinfo=tz), "description": "Tacos"},
    ]
    kept = special_events_scan.menu_days_for_month(days, 2026, 10)
    assert [d["description"] for d in kept] == ["Cheeseburger Meatloaf"]


@pytest.mark.anyio
async def test_menu_stored_before_the_fix_is_reparsed(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Preschool {tag}", slug=f"preschool-{tag}", special_events_calendar_url="https://x.test/calendars-menu/")
        db.add(school)
        await db.flush()
        old = LunchMenu(school_id=school.id, meal_type="lunch", period_label="October 2026", source_pdf_url=_OCT_MENU)
        db.add(old)
        await db.flush()
        old.parsed_at = datetime(2026, 10, 5, 3, 45, tzinfo=ZoneInfo("UTC"))
        db.add(LunchMenuItem(lunch_menu_id=old.id, menu_date=datetime(2026, 9, 30, tzinfo=ZoneInfo("America/New_York")), description="Pizza Day!"))
        await db.commit()
        school_id, menu_id = school.id, old.id

    async def fake_pages(url, today=None):
        return []

    async def fake_menus(pages, today=None):
        return [(2026, 10, _OCT_MENU)]

    async def fake_parse(url, label, meal_type=None):
        return [{"date": datetime(2026, 10, 5, tzinfo=ZoneInfo("America/New_York")), "description": "Grilled Chicken Patty, 1ea", "notes": None}]

    monkeypatch.setattr(special_events_scan, "fetch_month_pages", fake_pages)
    monkeypatch.setattr(special_events_scan, "discover_menu_pdf_urls", fake_menus)
    monkeypatch.setattr(special_events_scan, "parse_menu_pdf", fake_parse)

    async with database.SessionLocal() as db:
        result = await special_events_scan.run(db, {"school_id": school_id})
        assert "1 newly parsed" in result
        items = (await db.execute(select(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu_id))).scalars().all()
        assert [i.description for i in items] == ["Grilled Chicken Patty"]
