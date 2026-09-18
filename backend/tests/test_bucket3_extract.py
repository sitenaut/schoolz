"""Tests for services/bucket3_extract.py against sanitized fixtures shaped
after real Backpack Capture exports (see that module's docstring - every
regex here was validated against a real capture before being committed).
No real student data in any fixture."""
import os
from datetime import datetime, timezone

from services import bucket3_extract as ex

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "bucket3")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_classify_page_recognizes_known_shapes():
    assert ex.classify_page("classroom", "https://classroom.google.com/u/2/w/ABC123/t/all").pattern == (
        "classroom:/u/N/w/:courseId/t/all"
    )
    assert ex.classify_page("classroom", "https://classroom.google.com/u/2/c/ABC123").pattern == "classroom:/u/N/c/:courseId"
    assert ex.classify_page("classroom", "https://classroom.google.com/u/2/h/st").pattern == "classroom:/u/N/h"
    assert (
        ex.classify_page("genesis", "https://parents.example.org/genesis/parents?tab2=studentsummary&studentid=1").pattern
        == "genesis:studentsummary"
    )
    assert ex.classify_page("classroom", "https://classroom.google.com/u/2/weird").pattern == "classroom:other"


def test_extract_course_map_reads_both_slug_and_numeric_id():
    text = _load("classroom_classwork.txt")
    cm = ex.extract_course_map(text)
    assert cm.by_slug["AAAASLUG"] == "ALGEBRA I"
    assert cm.by_numeric["111111111"] == "ALGEBRA I"
    assert cm.by_slug["BBBBSLUG"] == "ENGLISH 9"


def test_extract_classroom_account_reads_the_embedded_newline_email():
    text = _load("classroom_classwork.txt")
    result = ex.extract_classroom_account(text)
    assert result == ("Sample Student", "9999999@chclc.org")


def test_classroom_account_student_id_extracts_numeric_local_part():
    text = _load("classroom_classwork.txt")
    assert ex.classroom_account_student_id(text) == "9999999"


def test_classroom_account_student_id_returns_none_for_non_numeric_login():
    text = "[aria-label] Google Account: Jane Doe  \n(jane.doe@example.org) (role=button)"
    assert ex.classroom_account_student_id(text) is None


def test_extract_classroom_work_items_combines_both_shapes():
    text = _load("classroom_classwork.txt")
    cm = ex.extract_course_map(text)
    items = {i.external_uid: i for i in ex.extract_classroom_work_items("https://classroom.google.com/u/2/w/AAAASLUG/t/all", text, cm)}

    assert items["si:900001"].title == "Reading Response 1"
    assert items["si:900001"].course_name == "ALGEBRA I"
    assert items["si:900001"].due_raw is None

    assert items["si:900002"].title == "Chapter Quiz"
    assert items["si:900002"].due_raw == "Sep 16, 9:30 AM"
    assert items["si:900002"].item_type == "assignment"

    assert items["si:900003"].title == "Vocab Sheet"
    assert items["si:900003"].due_raw == "Tomorrow"
    assert items["si:900003"].course_name == "ENGLISH 9"


def test_button_without_a_type_line_is_not_treated_as_a_work_item():
    text = _load("classroom_classwork.txt")
    cm = ex.extract_course_map(text)
    items = ex.extract_classroom_work_items("https://classroom.google.com/u/2/w/AAAASLUG/t/all", text, cm)
    titles = {i.title for i in items}
    assert "Lunch Period" not in titles


def test_extract_genesis_identity():
    text = _load("genesis_daily_view.txt")
    identity = ex.extract_genesis_identity(text)
    assert identity.first_name == "Sample"
    assert identity.last_name == "Student"
    assert identity.student_id == "9999999"
    assert identity.school == "Cherry Hill High School East"


def test_extract_genesis_cycle():
    assert ex.extract_genesis_cycle(_load("genesis_daily_view.txt")) == "1"


def test_extract_genesis_daily_blocks_handles_lunch_with_no_teacher():
    date_, blocks = ex.extract_genesis_daily_blocks(_load("genesis_daily_view.txt"))
    assert date_ == "09/14"
    by_period = {b.period: b for b in blocks}
    assert by_period["A"].course == "GEOMETRY A"
    assert by_period["A"].teacher == "Borrelli/Squazzo"
    assert by_period["A"].time_start == "7:30 AM"
    assert by_period["A"].time_end == "8:27 AM"
    assert by_period["A"].room == "C203"
    assert by_period["A"].term == "FY"
    # Lunch has no teacher line in real Genesis markup - must not shift
    # the room into the teacher field or vice versa.
    assert by_period["L2"].teacher is None
    assert by_period["L2"].room == "CAF"


def test_extract_genesis_list_blocks():
    blocks = ex.extract_genesis_list_blocks(_load("genesis_list_view.txt"))
    by_period = {b.period: b for b in blocks}
    assert by_period["A"].course == "GEOMETRY A"
    assert by_period["A"].term == "FY"
    assert by_period["A"].teacher == "Borrelli/Squazzo"
    assert by_period["A"].room == "C203"
    assert by_period["A"].days == "123456"


def test_extract_genesis_list_blocks_returns_none_on_daily_view_text():
    assert ex.extract_genesis_list_blocks(_load("genesis_daily_view.txt")) is None


def test_resolve_due_date_relative_words():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)  # a Monday
    assert ex.resolve_due_date("Tomorrow", anchor) == "2026-09-15"
    assert ex.resolve_due_date("Today", anchor) == "2026-09-14"
    assert ex.resolve_due_date(None, anchor) is None


def test_resolve_due_date_weekday_name_finds_next_occurrence():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)  # Monday
    assert ex.resolve_due_date("Friday", anchor) == "2026-09-18"


def test_resolve_due_date_month_day_uses_school_year_boundary():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    assert ex.resolve_due_date("Sep 16, 9:30 AM", anchor) == "2026-09-16"
    # A June date captured in September is the end of the school year that
    # just started (2026-27), i.e. June 2027 - not ~3 months in the past.
    assert ex.resolve_due_date("Jun 10", anchor) == "2027-06-10"


def test_course_codes_from_name_excludes_academic_year_ranges():
    codes = ex.course_codes_from_name("INTERMEDIATE GERMAN I H FY Period G 2026-27 682A-2, 682-2")
    assert ("682", "2") in codes
    assert ("2026", "27") not in codes


def test_course_codes_from_name_finds_trailing_code():
    assert ex.course_codes_from_name("F: CHEM-1A 331-10") == [("331", "10")]


def test_genesis_course_code_from_url():
    url = "https://parents.example.org/genesis/parents?tab2=gradebook&tab3=coursesummary&studentid=1&courseCode=331&courseSection=10"
    assert ex.genesis_course_code_from_url(url) == ("331", "10")
    assert ex.genesis_course_code_from_url("https://parents.example.org/genesis/parents") is None


def test_genesis_student_id_from_url_works_even_without_the_identity_block():
    # Gradebook pages have no page-body identity block (confirmed real:
    # they have "Grade:" from an assignment score but no "Student ID:")
    # so the URL param is the only universal identity signal.
    url = "https://parents.example.org/genesis/parents?tab2=gradebook&studentid=9999999"
    assert ex.genesis_student_id_from_url(url) == "9999999"


def test_normalize_title_is_case_and_punctuation_insensitive():
    assert ex.normalize_title('"Course Syllabus"') == ex.normalize_title("Course syllabus")
    assert ex.normalize_title("Reading Quiz (Informational Texts)") != ex.normalize_title(
        "Reading Quiz (Syllabus + Pros and Cons)"
    )


def test_classify_page_recognizes_gradebook_pages():
    course_url = "https://parents.example.org/genesis/parents?tab2=gradebook&tab3=coursesummary&studentid=1"
    weekly_url = "https://parents.example.org/genesis/parents?tab2=gradebook&tab3=weeklysummary&studentid=1"
    assert ex.classify_page("genesis", course_url).pattern == "genesis:gradebook-course"
    assert ex.classify_page("genesis", weekly_url).pattern == "genesis:gradebook-weekly"


def test_extract_genesis_course_grades_handles_description_weight_and_exempt():
    sheet = ex.extract_genesis_course_grades(_load("genesis_course_grades.txt"))
    assert sheet.marking_period == "MP1"
    assert sheet.marking_period_grade_pct == 80.0
    assert sheet.last_grade_posted == "9/10/26"
    by_title = {e.title: e for e in sheet.entries}

    reading = by_title["Reading Quiz"]
    assert reading.description == "Chapters 1-3"
    assert reading.category == "Minor Assessments"
    assert reading.score_earned == 8.0 and reading.score_possible == 10.0 and reading.percent == 80.0

    essay = by_title["Essay Draft"]
    assert essay.description is None  # no description line for this entry
    assert essay.updated is True

    syllabus = by_title["Course Syllabus"]
    assert syllabus.status == "Exempt"
    assert syllabus.score_earned is None
    assert syllabus.score_possible == 5.0  # from "Assignment Pts: 5"

    vocab = by_title["Vocab Worksheet"]
    assert vocab.score_earned == 0.0 and vocab.score_possible == 10.0


def test_extract_genesis_course_grades_handles_no_assignments():
    sheet = ex.extract_genesis_course_grades(_load("genesis_course_grades_empty.txt"))
    assert sheet.entries == []
    assert sheet.marking_period_grade_pct == 0.0


def test_extract_genesis_marking_periods_resolves_school_year_and_dedups_repeats():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    mps = ex.extract_genesis_marking_periods(_load("genesis_weekly_summary.txt"), anchor)
    assert [mp.label for mp in mps] == ["MP1", "MP2", "MP3", "MP4"]
    by_label = {mp.label: mp for mp in mps}
    assert by_label["MP1"].start_date == "2026-09-02"
    assert by_label["MP1"].end_date == "2026-11-10"
    # MP2 crosses the calendar year boundary (Nov -> Jan).
    assert by_label["MP2"].start_date == "2026-11-11"
    assert by_label["MP2"].end_date == "2027-01-27"
    assert by_label["MP3"].start_date == "2027-01-28"
    assert by_label["MP4"].end_date == "2027-06-17"


FEED_URL = "https://classroom.google.com/u/2/w/AAAASLUG/t/all"


def _feed_items():
    text = _load("classroom_stream_feed.txt")
    cm = ex.extract_course_map(text)
    return text, cm, {i.external_uid: i for i in ex.extract_classroom_work_items(FEED_URL, text, cm)}


def test_feed_card_and_grid_row_merge_into_one_item_with_teacher_posted_and_status():
    _text, _cm, items = _feed_items()
    pre = items["si:900010"]
    assert pre.title == "Pre-Test Form"
    assert pre.teacher_name == "Pat Jones"
    assert pre.posted_raw == "Sep 11"
    assert pre.status == "Graded"  # card shows both "Completed" and "Graded"; the specific one wins
    assert pre.due_raw == "Sep 12"  # only the grid row has it
    assert not any(uid.startswith("hash:") for uid in items)


def test_two_line_button_label_is_rejoined():
    _text, _cm, items = _feed_items()
    lab = items["si:900030"]
    assert lab.title.startswith("Lab Safety Contract")
    assert lab.due_raw == "Fri, Sep 18, 11:59 PM"
    assert lab.status is None


def test_rows_take_their_course_from_the_enclosing_view_not_a_stale_url():
    # Real shape: Classroom kept English's view (opened just before) in the
    # DOM of a capture taken under Geometry's Classwork URL.
    text = "\n".join(
        [
            "[aria-label] GEOM A Per A 2026-27 210-1 (role=menuitem) (href: /u/2/c/ODcyNDkxNDc4MTk4) (data-id: 872491478198)",
            "[aria-label] ENG 2A Block B (26-27) 121-1 (role=menuitem) (href: /u/2/c/ODc2NDQ0NzExNTM3) (data-id: 876444711537)",
            "Classwork for GEOM A Per A 2026-27 210-1 - Classroom",
            "[aria-label] Loading (role=status)",
            '(data-p: %.@."ODc2NDQ0NzExNTM3"]) (data-node-index: 0;0) (data-view-id: ucc-58)',
            "(data-include-stream-item-materials: true) (data-draggable-item-id: 884889938985) (data-stream-item-id: 884889938985)",
            "[aria-label] Part One of F451 + Study Guide (DUE) (role=button)",
            "Assignment",
            "assignment",
            "(data-type: 2) (data-visibility: 2) (data-stream-item-id: 884889938985)",
            "Due Sep 23",
        ]
    )
    cm = ex.extract_course_map(text)
    assert cm.by_code[("121", "1")] == "ENG 2A Block B (26-27) 121-1"
    assert ex.course_codes_from_name("ENG 2A Block B (26-27) 121-1") == [("121", "1")]
    [item] = ex.extract_classroom_work_items("https://classroom.google.com/u/2/w/ODcyNDkxNDc4MTk4/t/all", text, cm)
    assert item.course_id == "ODc2NDQ0NzExNTM3"
    assert item.course_name == "ENG 2A Block B (26-27) 121-1"


def test_stream_id_is_decoded_from_the_item_link():
    assert ex._stream_id_from_href("/u/2/c/X/a/ODg0NjAzNzc3NzY1/details") == "884603777765"
    assert ex._stream_id_from_href("/u/2/c/X/a/ITEM1/details") is None
    assert ex._stream_id_from_href(None) is None


def test_extract_classroom_announcements():
    text, cm, _items = _feed_items()
    [a] = ex.extract_classroom_announcements(FEED_URL, text, cm)
    assert a.external_uid == "si:900020"
    assert a.item_type == "announcement"
    assert a.teacher_name == "Pat Jones"
    assert a.posted_raw == "Sep 3"
    assert a.title == "Bring your Chromebook"
    assert a.body == "Dear Students,\nBring your Chromebook to class every day next week."
    assert a.course_name == "ALGEBRA I 101-1"


def test_resolve_due_date_handles_weekday_prefixes_times_and_local_date():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)  # Monday
    assert ex.resolve_due_date("Fri, Sep 18, 11:59 PM", anchor) == "2026-09-18"
    assert ex.resolve_due_date("Friday, 11:59 PM", anchor) == "2026-09-18"
    assert ex.resolve_due_date("7:30 AM", anchor) == "2026-09-14"
    assert ex.resolve_due_date("Due Sep 16", anchor) == "2026-09-16"
    assert ex.resolve_due_date("Today, 10:30 AM", anchor) == "2026-09-14"
    # 01:52 UTC on Sep 14 is still Sep 13 in New York - "Tomorrow" means the 14th.
    late_evening = datetime(2026, 9, 14, 1, 52, tzinfo=timezone.utc)
    assert ex.resolve_due_date("Tomorrow", late_evening) == "2026-09-14"


def test_resolve_posted_date_is_never_in_the_future():
    anchor = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    assert ex.resolve_posted_date("Sep 11", anchor) == "2026-09-11"
    assert ex.resolve_posted_date("10:12 AM", anchor) == "2026-09-14"
    assert ex.resolve_posted_date("Yesterday", anchor) == "2026-09-13"
    january = datetime(2027, 1, 5, 15, 0, tzinfo=timezone.utc)
    assert ex.resolve_posted_date("Dec 20", january) == "2026-12-20"
    assert ex.resolve_posted_date(None, anchor) is None
