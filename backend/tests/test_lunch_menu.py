import asyncio

from services import lunch_menu
from services.lunch_menu import _classify_pdf_link, _classify_unbanded_pdf_link


def test_classifies_elementary_lunch():
    result = _classify_pdf_link(".../September2026-ES-Lunch.pdf")
    assert result == {
        "school_type": "elementary",
        "meal_type": "lunch",
        "period_label": "September 2026",
        "pdf_url": ".../September2026-ES-Lunch.pdf",
    }


def test_classifies_middle_breakfast_despite_real_district_typo():
    # Confirmed real filename from the district: "Setember" not "September".
    result = _classify_pdf_link(".../Setember2026-MS-Breakfast.pdf")
    assert result["school_type"] == "middle"
    assert result["meal_type"] == "breakfast"


def test_high_school():
    result = _classify_pdf_link(".../September2026-HS-Lunch.pdf")
    assert result["school_type"] == "high"


def test_unrelated_pdf_is_ignored():
    assert _classify_pdf_link(".../parent-handbook.pdf") is None


def test_classifies_audubon_elementary_lunch_no_hyphens():
    # Confirmed real filename from Audubon: no hyphens, band spelled out, "Menu" suffix.
    result = _classify_pdf_link(".../September2026ElementaryLunchMenu.pdf")
    assert result == {
        "school_type": "elementary",
        "meal_type": "lunch",
        "period_label": "September 2026",
        "pdf_url": ".../September2026ElementaryLunchMenu.pdf",
    }


def test_classifies_audubon_combined_jh_hs_lunch():
    result = _classify_pdf_link(".../September2026JH-HSLunchMenu.pdf")
    assert result["school_type"] == "high"
    assert result["meal_type"] == "lunch"


def test_classifies_audubon_prek_lunch():
    result = _classify_pdf_link(".../September2026PreKLunchMenu.pdf")
    assert result["school_type"] == "other"


def test_unbanded_skips_spreadsheet_siblings():
    assert _classify_unbanded_pdf_link(".../September2026_lunch_spreadsheet.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../September_2026_Breakfast.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../September_2026.pdf", "elementary")["period_label"] == "September 2026"


def test_unbanded_menu_serves_every_school_type(monkeypatch):
    html = (
        '<a href="/f/January_2020.pdf"></a><a href="/f/September_2099.pdf"></a><a href="/f/October_2099.pdf"></a>'
        '<a href="/f/October_2099_lunch_spreadsheet.pdf"></a>'
    )

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x", school_types=["elementary", "middle", "other"]))
    assert sorted(e["school_type"] for e in found) == ["elementary", "elementary", "middle", "middle", "other", "other"]
    assert {e["pdf_url"] for e in found} == {"/f/September_2099.pdf", "/f/October_2099.pdf"}
