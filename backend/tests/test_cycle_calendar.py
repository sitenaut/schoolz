import datetime
import pathlib

import pytest

from services.cycle_calendar import parse_cycle_pdf

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "medford_lakes_cycle_2026_27.pdf"


def _days():
    parsed = parse_cycle_pdf(FIXTURE.read_bytes())
    return parsed, {d["date"]: d for d in parsed["days"]}


def test_title_year_and_cycle_length():
    parsed, _ = _days()
    assert (parsed["academic_year"], parsed["cycle_length"]) == ("2026-2027", 6)


def test_both_month_columns_are_read_and_dates_pair_with_their_own_digit():
    _, days = _days()
    # Left column (Sep) and right column (Feb) of the same grid rows.
    assert days["2026-09-01"]["day_number"] == 1
    assert days["2026-09-08"]["day_number"] == 5  # after Labor Day (X)
    assert days["2027-02-01"]["day_number"] == 5
    assert days["2027-06-11"]["day_number"] == 6


def test_x_cells_are_closed_with_no_day_number():
    _, days = _days()
    for d in ("2026-09-07", "2026-09-21", "2026-11-26", "2027-03-29", "2027-05-31"):
        assert days[d] == {"date": d, "day_number": None, "closed": True}


def test_every_school_day_is_a_weekday_and_the_cycle_never_breaks():
    parsed, _ = _days()
    school = [d for d in parsed["days"] if not d["closed"]]
    assert len(school) == 180
    assert all(datetime.date.fromisoformat(d["date"]).weekday() < 5 for d in parsed["days"])
    for prev, cur in zip(school, school[1:], strict=False):
        assert cur["day_number"] == prev["day_number"] % 6 + 1


def test_pick_cycle_pdf_prefers_newest_year_and_ignores_other_documents():
    from scheduler.jobs.hs_rotation_scan import pick_cycle_pdf

    docs = [
        {"doc_type": "letter_day_schedule", "title": "2026-2027 6 Day Cycle Calendar", "url": "https://x/a-2026.pdf", "academic_year": "2026-2027"},
        {"doc_type": "letter_day_schedule", "title": "2027-2028 6 Day Cycle Calendar", "url": "https://x/a-2027.pdf", "academic_year": "2027-2028"},
        {"doc_type": "letter_day_schedule", "title": "What Day is It?", "url": "https://drive.google.com/file/d/1/view", "academic_year": None},
        {"doc_type": "bell_schedule", "title": "Bell cycle", "url": "https://x/bell.pdf", "academic_year": "2030-2031"},
    ]
    assert pick_cycle_pdf(docs) == "https://x/a-2027.pdf"
    assert pick_cycle_pdf([]) is None


@pytest.mark.anyio
async def test_next_years_cycle_pdf_leaves_the_rest_of_this_year_alone(monkeypatch):
    # L6: the district posts next year's PDF in the spring; the scan picked it
    # and deleted every stored day it didn't list, emptying the rest of this
    # year's rotation until June. Only days inside the new PDF's dates go.
    import uuid
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    import database
    from models import District, SchoolContentItem
    from scheduler.jobs import hs_rotation_scan

    tz = ZoneInfo("America/New_York")
    pdf_url = "https://district.example.org/2027-2028-6-day-cycle.pdf"
    async with database.SessionLocal() as db:
        district = District(name=f"Cycle District {uuid.uuid4().hex[:8]}", hs_rotation_url="https://district.example.org/2026-2027-6-day-cycle.pdf")
        db.add(district)
        await db.flush()
        for day, n in [("2027-05-03", 4), ("2027-09-09", 2)]:
            db.add(SchoolContentItem(scope="district", district_id=district.id, category="event", is_all_day=True,
                                     source="rotation_pdf", external_uid=f"hs_rotation:{day}", title=f"Day {n}",
                                     start_date=datetime.combine(datetime.fromisoformat(day).date(), time.min, tz)))
        await db.commit()
        district_id = district.id

    async def fake_fetch(district):
        return pdf_url, {"academic_year": "2027-2028", "days": [
            {"date": "2027-09-08", "day_number": 1},
            {"date": "2027-09-10", "day_number": 2},
        ]}

    monkeypatch.setattr(hs_rotation_scan, "_fetch_cycle_pdf", fake_fetch)
    async with database.SessionLocal() as db:
        result = await hs_rotation_scan.run(db, {"district_id": district_id})
        await db.commit()
        rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.district_id == district_id))).scalars().all()
    assert "1 removed" in result
    assert sorted(r.external_uid for r in rows) == ["hs_rotation:2027-05-03", "hs_rotation:2027-09-08", "hs_rotation:2027-09-10"]
