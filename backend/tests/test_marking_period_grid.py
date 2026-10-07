from services import marking_period as mp

# pdfplumber's text for Pine Hill's 2026-27 calendar: the legend and month
# totals share lines with the marking-period block.
TEXT = """9/17/26 - John Glenn Elementary High School Full Day
PHMS/OHS Marking Period Dates School Closed for Students - Full Day Staff In-Service
1st MP 2nd MP
9/1/26 - 11/4/26 11/9/26 -1/27/27 December 17 17
3rd MP 4th MP
1/28/27 - 4/9/27 4/12/27 - 6/16/27 January 18 19
Glenn/Bean Marking Period Dates Snow Day - School Emergency Closure
1st MP 2nd MP
9/1/26-12/2/26 12/3/26-3/11/27 March 19 19
3rd MP Trimester Marking
3/12/27-6/17/27 Periods April 20 20
"""


def test_grid_reads_each_level_and_names_trimesters():
    got = {(e["school_type"], e["title"], e["start_date"].date().isoformat()) for e in mp.parse_calendar_pdf_text(TEXT)}
    assert got == {
        *{(t, f"Marking Period {n} Ends", d) for t in ("middle", "high") for n, d in ((1, "2026-11-04"), (2, "2027-01-27"), (3, "2027-04-09"), (4, "2027-06-16"))},
        ("elementary", "Trimester 1 Ends", "2026-12-02"),
        ("elementary", "Trimester 2 Ends", "2027-03-11"),
        ("elementary", "Trimester 3 Ends", "2027-06-17"),
    }
    uids = [e["external_uid"] for e in mp.parse_calendar_pdf_text(TEXT)]
    assert len(uids) == len(set(uids)) == 11


def test_newest_calendar_pdf_wins_over_last_years():
    html = '<a href="/f/2025_2026_School_Calendar_3_24_26.pdf">Calendar</a><a href="/f/2026_2027_Calendar_9_8-26_Final.pdf">Calendar</a>'
    assert mp.find_calendar_pdf(html, "https://x.test/p").endswith("2026_2027_Calendar_9_8-26_Final.pdf")
