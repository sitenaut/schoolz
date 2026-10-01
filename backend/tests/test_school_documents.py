

def test_eschoolview_takes_only_direct_handbook_files_not_menu_landing_pages():
    from services.school_documents import _find_eschoolview_handbooks

    html = (
        "<a href='https://docs.google.com/document/d/AAA/edit'>Student Parent Handbook</a>"
        "<a href='https://docs.google.com/document/d/AAA/edit'>Family Handbook</a>"
        "<a href='https://www.mtlaurelschools.org/Downloads/Dyslexia%20Handbook.pdf'>Dyslexia Handbook</a>"
        "<a href='https://www.mtlaurelschools.org/Downloads/discipline%20code.pdf'>Discipline Code</a>"
        "<a href='https://www.mtlaurelschools.org/FamilyHandbook.aspx'>Handbook page</a>"
    )
    found = _find_eschoolview_handbooks(html)
    assert [d["url"] for d in found] == ["https://docs.google.com/document/d/AAA/edit"]
    assert found[0]["doc_type"] == "handbook"


def test_letter_day_article_is_found_from_the_home_page_and_only_its_schedules_kept():
    from datetime import date

    from services.school_documents import _find_letter_day_page, _find_letter_day_pdfs

    home = '<a href="protected/ArticleView.aspx?iid=4P0IY&amp;dasi=3GGI">Letter Day Schedule</a><a href="/x.pdf">Letter Day</a>'
    assert _find_letter_day_page(home, "https://www.mtlaurelschools.org/hillside_home.aspx") == (
        "https://www.mtlaurelschools.org/protected/ArticleView.aspx?iid=4P0IY&dasi=3GGI"
    )
    article = (
        '<a href="/MenuItem/Goals.pdf">District Goals</a>'
        '<a href="https://f.example/a.pdf">September Letter Day Schedule 2026.pdf</a>'
        '<a href="http://f.example/b.pdf">October Letter Day Schedule.pdf</a>'
    )
    docs = _find_letter_day_pdfs(article, "https://www.mtlaurelschools.org/protected/ArticleView.aspx", today=date(2026, 9, 30))
    assert [d["title"] for d in docs] == ["September Letter Day Schedule 2026", "October Letter Day Schedule"]
    assert {d["academic_year"] for d in docs} == {"2026-2027"}
    assert {d["doc_type"] for d in docs} == {"letter_day_schedule"}


def test_whats_day_is_it_link_is_a_letter_day_schedule():
    from services.school_documents import _find_doc_anchors, classify_doc_type

    assert classify_doc_type("What Day is It?") == "letter_day_schedule"
    html = '<a href="https://drive.google.com/file/d/abc/view?usp=sharing">What Day is It?</a>'
    found = _find_doc_anchors(html, "https://x.test")
    assert [(d["doc_type"], d["url"]) for d in found] == [("letter_day_schedule", "https://drive.google.com/file/d/abc/view?usp=sharing")]


def test_edlio_policy_nav_skipped_and_cycle_calendar_classified():
    from services.school_documents import _find_doc_anchors, _find_doc_file_anchors, classify_doc_type

    html = (
        '<a href="/apps/pages/?uREC_ID=1">Policy, Procedure and Handbook</a>'
        '<a href="/apps/pages/?uREC_ID=2">Parent/Student Handbook</a>'
        '<a href="/apps/pages/?uREC_ID=3">District Calendars</a>'
    )
    types = {(r["title"], r["doc_type"]) for r in _find_doc_anchors(html, "https://x")}
    assert types == {("Parent/Student Handbook", "handbook"), ("District Calendars", "calendar_hub")}
    assert classify_doc_type("2026-2027 6 Day Cycle Calendar - Sheet1-3.pdf") == "letter_day_schedule"
    assert classify_doc_type("2026-2027 District Calendar Final.pdf") is None

    page = (
        '<footer><a href="/pdfs/footer.pdf">Footer</a></footer>'
        '<div id="pageContentWrapper"><a href="/ourpages/a.pdf">Cycle</a></div>'
    )
    assert _find_doc_file_anchors(page, "https://x") == [("https://x/ourpages/a.pdf", "Cycle")]


def test_my_food_days_link_is_kept_as_lunch_ordering():
    from services.school_documents import _find_doc_anchors

    html = (
        '<a href="https://secure.myfooddays.com/Home.aspx">My Food Days</a>'
        '<a href="https://example.com/myfooddays.com-notes">Notes</a>'
    )
    assert [(r["title"], r["doc_type"], r["url"]) for r in _find_doc_anchors(html, "https://x")] == [
        ("My Food Days", "lunch_ordering", "https://secure.myfooddays.com/Home.aspx")
    ]


def test_shared_site_bell_schedules_narrow_to_the_schools_own():
    from services.school_documents import keep_own_school_bell_schedules

    neeta = {"doc_type": "bell_schedule", "title": "Bell Schedule", "url": "https://x/NEETA%20SCHOOL%20BELL%20SCHEDULE%202025-2026.pdf"}
    nokomis = {"doc_type": "bell_schedule", "title": "Bell Schedule", "url": "https://x/NOKOMIS%20SCHOOL%20BELL%20SCHEDULE%202025-2026.pdf"}
    handbook = {"doc_type": "handbook", "title": "Handbook", "url": "https://x/hb.pdf"}
    assert keep_own_school_bell_schedules([neeta, nokomis, handbook], ["Neeta"]) == ([neeta, handbook], True)
    # Nothing names the school (one schedule for all), or every one does: leave them alone.
    assert keep_own_school_bell_schedules([neeta, nokomis], ["Other"]) == ([neeta, nokomis], False)
    assert keep_own_school_bell_schedules([neeta], ["Neeta"]) == ([neeta], False)
