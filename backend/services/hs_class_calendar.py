"""Fetches a school's OWN public Google Calendar (.ics) - confirmed real on
Cherry Hill East's activities site: a club/interest-meeting calendar
embedded on the homepage, entirely separate from the district's own
calendar feeds (District.ics_feeds).

Deliberately reuses services/district_calendar.py's fetch/parse code
wholesale rather than duplicating it - a public Google Calendar .ics feed
is the same shape whether it's a district's or one school's own. Only the
attribution differs: these events are tagged source="school_ics" (not
"ics_feed") and scoped to this one School (school_id set, district_id
null), specifically so the frontend can default them off in the general
calendar - a school's own activities feed runs to dozens of club interest
meetings a week, exactly the "too much detail for a district-wide view"
case docs/HS_CLASS_PAGES_DESIGN.md calls out. They're always shown within
that school's own class pages instead.
"""

from services.district_calendar import fetch_district_calendar

# Re-exported so scheduler/jobs/hs_class_calendar_scan.py has one obvious
# place to import from, without every caller needing to know this is a
# thin wrapper over the district calendar fetcher.
fetch_school_calendar = fetch_district_calendar
