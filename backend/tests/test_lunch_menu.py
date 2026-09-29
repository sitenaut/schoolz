from services.lunch_menu import _classify_pdf_link


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
