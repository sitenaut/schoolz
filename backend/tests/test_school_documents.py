

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
