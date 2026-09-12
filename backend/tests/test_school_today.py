from datetime import date, datetime
from zoneinfo import ZoneInfo

from models import SchoolContentItem
from services.school_today import _item_date_range, classify_day, week_window
from services.staff_roles import classify_role

_ET = ZoneInfo("America/New_York")


def test_classify_role_keyword_map():
    assert classify_role("Assistant Principal") == "assistant_principal"
    assert classify_role("Principal") == "principal"
    assert classify_role("Preschool Nurse") == "nurse"
    assert classify_role("Guidance Counselor") == "counselor"
    assert classify_role("School counselor") == "counselor"
    assert classify_role("SACC Coordinator") == "sacc"
    assert classify_role("Secretary") == "secretary"
    assert classify_role("Preschool Social Worker") == "social_worker"
    assert classify_role("Third Grade Teacher") is None
    assert classify_role(None) is None


def test_classify_day_precedence_and_labels():
    assert classify_day([]) == ("open", None)
    assert classify_day(["Day 3", "SCHOOLS CLOSED - Labor Day"]) == ("closed", "Labor Day")
    assert classify_day(["DISTRICT CLOSED"]) == ("closed", None)
    assert classify_day(["EARLY DISMISSAL - Staff In-Service"]) == ("early_dismissal", "Early dismissal")
    # Closed wins over early dismissal on the same day.
    assert classify_day(["EARLY DISMISSAL", "SCHOOLS CLOSED - Snow"])[0] == "closed"
    assert classify_day(["2 Hour Delay"])[0] == "delayed"
    assert classify_day(["Back to School Night"]) == ("open", None)


def test_item_date_range_expands_multi_day_all_day_closure():
    # Real case: "SCHOOLS CLOSED - NJEA Convention", start=Nov 5, end=Nov 7
    # (ICS all-day convention: end is exclusive, the day after the last
    # actual day) - covers Nov 5 and Nov 6, not just Nov 5.
    item = SchoolContentItem(
        title="SCHOOLS CLOSED - NJEA Convention",
        start_date=datetime(2026, 11, 5, tzinfo=_ET),
        end_date=datetime(2026, 11, 7, tzinfo=_ET),
        is_all_day=True,
    )
    assert _item_date_range(item) == [date(2026, 11, 5), date(2026, 11, 6)]


def test_item_date_range_single_day_all_day_item():
    item = SchoolContentItem(title="x", start_date=datetime(2026, 9, 7, tzinfo=_ET), end_date=None, is_all_day=True)
    assert _item_date_range(item) == [date(2026, 9, 7)]


def test_item_date_range_no_end_date_returns_start_only():
    item = SchoolContentItem(title="x", start_date=datetime(2026, 9, 22, 18, 30, tzinfo=_ET), end_date=None, is_all_day=False)
    assert _item_date_range(item) == [date(2026, 9, 22)]


def test_item_date_range_timed_multi_day_treats_end_as_inclusive():
    item = SchoolContentItem(
        title="x",
        start_date=datetime(2026, 10, 5, 9, 0, tzinfo=_ET),
        end_date=datetime(2026, 10, 7, 16, 0, tzinfo=_ET),
        is_all_day=False,
    )
    assert _item_date_range(item) == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]


def test_week_window_mon_to_fri_and_weekend_rolls_forward():
    tue = date(2026, 9, 8)
    assert week_window(tue) == [date(2026, 9, 7 + i) for i in range(5)]
    sat = date(2026, 9, 12)
    assert week_window(sat)[0] == date(2026, 9, 14)


def test_doc_type_classification_and_short_year():
    from services.school_documents import _extract_year, classify_doc_type

    assert classify_doc_type("CHW Bell Schedule") == "bell_schedule"
    assert classify_doc_type("/our-school/bell-schedule") == "bell_schedule"
    assert classify_doc_type("Parent/Student Handbook 2026-2027") == "handbook"
    assert classify_doc_type("Athletics") is None
    # Real file name on West's site: WestBellSchedule26-27.pdf
    assert _extract_year(".../WestBellSchedule26-27.pdf") == "2026-2027"
    assert _extract_year("Handbook 2025-2026") == "2025-2026"
    assert _extract_year("BELL_SCHEDULE__Regula_Delayed_and_Half_Day.pdf") is None


def test_find_logo_url_skips_google_translate_badge():
    from services.school_info import _find_logo_url

    html = """
    <header>
      <img src="https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_42x16dp.png" alt="Google Translate">
      <img src="/images/Harte-transparent.png" alt="Bret Harte Elementary">
    </header>
    """
    assert _find_logo_url(html, "https://harte.chclc.org") == "https://harte.chclc.org/images/Harte-transparent.png"


def test_find_logo_url_first_header_image_when_no_widget():
    from services.school_info import _find_logo_url

    html = '<header><img src="https://cdn.example.com/east_shield.png" alt="Cherry Hill East High School Logo"></header>'
    assert _find_logo_url(html, "https://east.chclc.org") == "https://cdn.example.com/east_shield.png"


def test_find_logo_url_none_when_no_header_images():
    from services.school_info import _find_logo_url

    assert _find_logo_url("<body><p>no images</p></body>", "https://x") is None


def test_find_logo_url_resolves_absolute_path_against_domain_not_full_page_path():
    from services.school_info import _find_logo_url

    html = '<header><img src="/content/dam/gsi/brand-mark.svg" alt="logo"></header>'
    # A real bug: website_url with its own path (not a bare domain like the
    # Finalsite sites) must not get the img's absolute path concatenated
    # onto that path - it has to resolve against the domain root.
    assert _find_logo_url(html, "https://www.goddardschool.com/schools/nj/cherry-hill/cherry-hill") == "https://www.goddardschool.com/content/dam/gsi/brand-mark.svg"


def test_find_logo_url_prefers_logo_labeled_image_over_first_header_image():
    from services.school_info import _find_logo_url

    html = '<header><img src="/cart.png" alt="Shopping cart"><img src="/logo-large.png" alt="Home"></header>'
    assert _find_logo_url(html, "https://example.com") == "https://example.com/logo-large.png"


def test_find_logo_url_known_overrides_bypass_generic_heuristic():
    from services.school_info import _find_logo_url

    html = '<header><img src="/anything.png" alt="logo"></header>'
    assert _find_logo_url(html, "https://www.primroseschools.com/schools/cherry-hill") == "https://www.primroseschools.com/favicon.ico"
    assert _find_logo_url(html, "https://www.centerffs.org/early-learning") is None
