

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


def test_presence_site_is_read_over_plain_http_never_the_scraper(monkeypatch):
    import asyncio

    import httpx

    import scraper_client
    from services import school_documents

    home = (
        '<html><head><title>Home</title></head><body><a href="/students/student_handbook">Student Handbook</a>'
        '<a href="/x"><img alt="SchoolMessenger Presence"></a></body></html>'
    )
    handbook_page = (
        "<html><head><title>Student Handbook 2026-2027</title></head><body>"
        '<a href="/cms/lib/NJ/Centricity/Domain/1/Sterling%20High%20School%20Handbook%202026-2027.pdf">Download</a>'
        "</body></html>"
    )
    pages = {"/": home, "/students/student_handbook": handbook_page}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages[request.url.path])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        school_documents.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    async def boom(*a, **kw):
        raise AssertionError("scraper must not be used for a Presence site")

    monkeypatch.setattr(scraper_client, "fetch_html", boom)

    docs = asyncio.run(school_documents.discover_from_website("https://www.sterling.k12.nj.us"))
    assert [d["doc_type"] for d in docs] == ["handbook"]
    assert docs[0]["url"].endswith("Sterling%20High%20School%20Handbook%202026-2027.pdf")
    assert docs[0]["academic_year"] == "2026-2027"


def test_file_download_detected_from_headers_not_url():
    import httpx

    from services.school_documents import looks_like_file_download

    assert looks_like_file_download(httpx.Headers({"content-type": "application/pdf"}))
    assert looks_like_file_download(httpx.Headers({"content-type": "text/html", "content-disposition": 'attachment; filename="h.pdf"'}))
    assert not looks_like_file_download(httpx.Headers({"content-type": "text/html; charset=utf-8"}))
    assert not looks_like_file_download(httpx.Headers({}))


def test_extensionless_link_that_serves_a_file_is_kept_without_rendering_it(monkeypatch):
    # Lenape Regional: /students/student-handbook answers with the PDF itself,
    # which Chromium can only report as "Download is starting".
    import asyncio

    import httpx

    import scraper_client
    from services import school_documents

    home = '<html><body><a href="/students/student-handbook">Student Handbook 2026-2027</a></body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/students/student-handbook":
            return httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})
        return httpx.Response(200, html=home)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        school_documents.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    rendered = []

    async def fake_fetch_html(url, **kw):
        rendered.append(url)
        if url.rstrip("/") == "https://www.lrhsd.org":
            return {"html": home, "title": "Home"}
        raise AssertionError(f"a file download must not be rendered: {url}")

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    docs = asyncio.run(school_documents.discover_from_website("https://www.lrhsd.org"))
    assert docs == [
        {
            "title": "Student Handbook 2026-2027",
            "url": "https://www.lrhsd.org/students/student-handbook",
            "academic_year": "2026-2027",
            "doc_type": "handbook",
        }
    ]
    assert rendered == ["https://www.lrhsd.org/"]


def test_find_doc_anchors_skips_fragment_and_scheme_links():
    from services.school_documents import _find_doc_anchors
    html = ('<a href="#">Student Handbook</a><a href="javascript:void(0)">Handbook</a>'
            '<a href="mailto:a@b.org">Handbook</a><a href="/handbook.pdf">Student Handbook</a>')
    assert [r["url"] for r in _find_doc_anchors(html, "https://x.test")] == ["https://x.test/handbook.pdf"]


def test_dead_url_is_not_retried_or_fallen_back():
    import httpx
    from scraper_client import _is_retryable
    req = httpx.Request("POST", "http://s/fetch-html")
    dead = httpx.HTTPStatusError("x", request=req, response=httpx.Response(502, request=req, text="net::ERR_NAME_NOT_RESOLVED at https://x/"))
    flaky = httpx.HTTPStatusError("x", request=req, response=httpx.Response(502, request=req, text="Timeout 15000ms exceeded"))
    assert not _is_retryable(dead) and _is_retryable(flaky)
