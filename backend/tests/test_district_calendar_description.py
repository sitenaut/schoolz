from services.district_calendar import description_text


def test_plain_text_passes_through():
    assert description_text("  PSAT DAY Early Dismissal(?)  ") == "PSAT DAY Early Dismissal(?)"
    assert description_text("") is None
    assert description_text(None) is None


def test_google_calendar_html_is_flattened():
    # Real shape from Cherry Hill East's school calendar (PSAT DAY).
    raw = (
        "Preliminary SAT/National Merit Qualifying Scholarship Test\xa0 (PSAT/NMSQT) will be administered to all"
        "<i> </i><b><i>10</i></b><b><i>th </i></b><b><i>and 11</i></b><b><i>th </i></b>"
        "<b><i>grade students</i></b> at no cost to students."
    )
    out = description_text(raw)
    assert "<" not in out
    assert "administered to all 10th and 11th grade students at no cost" in out


def test_breaks_and_links():
    raw = 'Line one<br>Line two<p>Para &amp; more</p><a href="https://x.org/signup">Sign up</a>'
    assert description_text(raw) == "Line one\nLine two\nPara & more\nSign up (https://x.org/signup)"
