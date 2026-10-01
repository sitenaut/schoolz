import json
from datetime import date

import httpx
import pytest

from services import presence_documents
from services.lunch_menu import classify_presence_menu, pick_presence_menus, _sniff_image_type

SOMERDALE = [
    ("October Menu 2026", "jpg"),
    ("October Pre K Menu 2026 -Breakfast", "jpg"),
    ("October Pre K Menu 2026", "jpg"),
    ("September 2026 PreK Lunch", "pdf"),
    ("September 2026 Lunch", "pdf"),
    ("September 2026 PreK Breakfast", "pdf"),
    ("Wellness Policy Assessment Tool", "pdf"),
    ("Field Trip Order Form 2023-24", "pdf"),
]


def _items():
    return [{"title": t, "extension": e, "url": f"https://x/{i}"} for i, (t, e) in enumerate(SOMERDALE)]


def test_classifies_hand_typed_titles():
    c = {i["title"]: classify_presence_menu(i) for i in _items()}
    assert c["October Menu 2026"]["meal_type"] == "lunch" and not c["October Menu 2026"]["prek"]
    pb = c["October Pre K Menu 2026 -Breakfast"]
    assert (pb["meal_type"], pb["prek"], pb["month"], pb["year"]) == ("breakfast", True, 10, 2026)
    assert pb["period_label"] == "October 2026 (Pre-K)"
    assert c["September 2026 Lunch"]["month"] == 9
    assert c["Wellness Policy Assessment Tool"] is None
    assert c["Field Trip Order Form 2023-24"] is None


def test_picks_current_month_and_prefers_plain_menu_over_prek():
    picked = pick_presence_menus(_items(), date(2026, 10, 1))
    assert [(p["month"], p["meal_type"], p["prek"]) for p in picked] == [(10, "breakfast", True), (10, "lunch", False)]
    assert all(p["month"] >= 10 for p in pick_presence_menus(_items(), date(2026, 10, 1)))
    sept = pick_presence_menus(_items(), date(2026, 9, 15))
    assert [(p["month"], p["meal_type"], p["prek"]) for p in sept] == [(9, "breakfast", True), (9, "lunch", False), (10, "breakfast", True), (10, "lunch", False)]


def test_sniffs_images_by_bytes():
    assert _sniff_image_type(b"\xff\xd8\xff\xe0abc") == "image/jpeg"
    assert _sniff_image_type(b"%PDF-1.7") is None


PAGE = """<script>var x = new ContentItemListUI('111', null, '[]', {"ContextId":"9","Foo":"a}b"});</script>"""


def test_widget_settings_are_read_from_the_inline_script():
    assert presence_documents.widgets(PAGE) == [(111, {"ContextId": "9", "Foo": "a}b"})]


@pytest.mark.anyio
async def test_lists_documents_and_recurses_folders():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=PAGE)
        body = json.loads(request.content)
        seen.append(body["parentId"])
        assert json.loads(body["Params"])["searchVal"] == "" and request.headers["requestFrom"] == "contentItem"
        if body["parentId"] == 111:
            data = [{"Type": "folder", "ObjectId": 222, "Title": "Old"}, {"Type": "content_item", "Title": "October Menu 2026", "Extension": "JPG", "DownloadLink": "/common/pages/GetFile.ashx?key=a"}]
        else:
            data = [{"Type": "content_item", "Title": "Nested", "Extension": "pdf", "Link": "https://cdn/x.pdf"}]
        return httpx.Response(200, json={"d": {"DataObject": data}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        docs = await presence_documents.list_page_documents("https://school.example/departments/cafeteria", client)
    assert seen == [111, 222]
    assert {d["title"]: d["url"] for d in docs} == {
        "October Menu 2026": "https://school.example/common/pages/GetFile.ashx?key=a",
        "Nested": "https://cdn/x.pdf",
    }
    assert docs[0]["extension"] in {"jpg", "pdf"}


def test_marking_periods_come_from_the_calendar_pdf_sidebar():
    from pathlib import Path

    from services.marking_period import _pdf_text, parse_calendar_pdf_text

    rows = parse_calendar_pdf_text(_pdf_text((Path(__file__).parent / "fixtures" / "somerdale_calendar_2026_27.pdf").read_bytes()))
    got = sorted((r["start_date"].date().isoformat(), r["title"]) for r in rows)
    assert got == sorted(
        [
            ("2026-11-04", "Marking Period 1 Ends"), ("2027-01-22", "Marking Period 2 Ends"),
            ("2027-04-09", "Marking Period 3 Ends"), ("2027-06-10", "Marking Period 4 Ends"),
            ("2026-11-11", "Quarter 1 Report Card Grades Posted"), ("2027-01-27", "Quarter 2 Report Card Grades Posted"),
            ("2027-04-14", "Quarter 3 Report Card Grades Posted"), ("2027-06-15", "Quarter 4 Report Card Grades Posted"),
            ("2026-10-02", "Interim Reports Issued"), ("2026-12-11", "Interim Reports Issued"),
            ("2027-02-26", "Interim Reports Issued"), ("2027-05-12", "Interim Reports Issued"),
        ]
    )
    assert all(r["school_type"] is None for r in rows)


def _dated(name: str) -> list[tuple[str, str]]:
    from pathlib import Path

    from services.marking_period import parse_calendar_pdf_text

    text = (Path(__file__).parent / "fixtures" / name).read_text()
    return sorted((r["start_date"].date().isoformat(), r["title"]) for r in parse_calendar_pdf_text(text))


def test_stratford_calendar_pdf_interims_report_cards_and_quarters():
    assert _dated("stratford_calendar_2026_27.txt") == sorted(
        [
            ("2026-11-11", "Marking Period 1 Ends"), ("2027-01-29", "Marking Period 2 Ends"),
            ("2027-04-15", "Marking Period 3 Ends"), ("2027-06-18", "Marking Period 4 Ends"),
            ("2026-10-07", "Interim Reports Issued"), ("2026-12-14", "Interim Reports Issued"), ("2027-03-05", "Interim Reports Issued"),
            ("2026-11-18", "Report Cards Issued"), ("2027-02-05", "Report Cards Issued"), ("2027-04-20", "Report Cards Issued"),
        ]
    )


def test_laurel_springs_calendar_pdf_trimesters_and_report_cards():
    assert _dated("laurel_springs_calendar_2026_27.txt") == sorted(
        [
            ("2026-12-04", "Trimester 1 Ends"), ("2027-03-16", "Trimester 2 Ends"), ("2027-06-17", "Trimester 3 Ends"),
            ("2026-12-11", "Report Cards Issued"), ("2027-03-24", "Report Cards Issued"), ("2027-06-17", "Report Cards Issued"),
        ]
    )


def test_calendar_pdf_link_is_found_on_a_page_and_spaces_are_encoded():
    from services.marking_period import find_calendar_pdf

    html = '<a href="/other.pdf">Lunch</a><a href="https://www.x.org/26-27 New Calendar.pdf">26-27 District Calendar</a>'
    assert find_calendar_pdf(html, "https://www.x.org/") == "https://www.x.org/26-27%20New%20Calendar.pdf"
    assert find_calendar_pdf("<a href='/menu.pdf'>Menu</a>", "https://www.x.org/") is None
