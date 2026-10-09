"""What a job reads, for display. A scan's params only carry its target's id;
the URL it fetches lives on the School/District/newsletter row, so the jobs
page had no way to say what a failed scan was trying to load.

Display-only: handlers don't read this table, so a handler that starts
fetching a new field needs its entry here updated by hand.
"""

# kind -> (label, attribute on the target row), in the order the handler prefers them.
_SCHOOL_FIELDS: dict[str, list[tuple[str, str]]] = {
    "documents.scan": [("School website", "website_url")],
    "school_info.scan": [("School website", "website_url")],
    "athletics_calendar.scan": [("Athletics schedule", "athletics_url")],
    "hs_activities_site.scan": [("Activities site", "activities_site_url")],
    "hs_announcements.scan": [("Announcements doc", "announcements_doc_url")],
    "hs_class_calendar.scan": [("Activities calendar (.ics)", "activities_calendar_ics_url")],
    "special_events.scan": [("Special events calendar", "special_events_calendar_url")],
    "presence_menu.scan": [("Menu page", "presence_menu_page_url")],
    "school_events_doc.scan": [("Events doc", "events_doc_url")],
    "student_bulletin.scan": [("Bulletin doc", "bulletin_doc_url")],
    "givebacks.scan": [("Givebacks shortname", "givebacks_shortname")],
    "fdmealplanner_menu.scan": [("FD MealPlanner location", "fdmealplanner_location")],
    "healthepro_menu.scan": [("Health-e Pro location", "healthepro_location")],
    "myschoolplate_menu.scan": [("MySchoolPlate location", "myschoolplate_location")],
    "nutrislice_menu.scan": [("Nutrislice location", "nutrislice_location")],
}

_DISTRICT_FIELDS: dict[str, list[tuple[str, str]]] = {
    "district_calendar_pdf.scan": [("Calendar PDF", "calendar_pdf_url")],
    "hs_rotation.scan": [("HS rotation page", "hs_rotation_url"), ("District website", "website_url")],
    "lunch_menu.scan": [("Food services menu page", "food_services_menu_url")],
    "marking_period.scan": [("Marking periods page", "marking_period_url")],
    "preschool_locations.scan": [("Preschool locations page", "preschool_locations_url")],
    "preschool_team.scan": [("Preschool team page", "preschool_team_url")],
    "transportation.scan": [("Transportation page", "transportation_url")],
    "schoolcafe_menu.scan": [("SchoolCafe shortname", "schoolcafe_shortname")],
}

_NEWSLETTER_KINDS = {"smore.scan", "ptboard.scan", "virtual_backpack.scan"}


def _fields(row, fields: list[tuple[str, str]]) -> list[dict]:
    return [{"label": label, "value": str(value)} for label, attr in fields if (value := getattr(row, attr, None))]


def job_sources(kind: str, *, school=None, district=None, newsletter_url: str | None = None) -> list[dict]:
    """`[{"label", "value"}]` for one job. `district` is the job's own
    district target, or the school's district for a school-targeted job."""
    if kind in _NEWSLETTER_KINDS:
        return [{"label": "Newsletter", "value": newsletter_url}] if newsletter_url else []

    if kind == "district_calendar.scan":
        return [
            {"label": f"Calendar feed: {feed.get('name') or 'unnamed'}", "value": feed["url"]}
            for feed in (getattr(district, "ics_feeds", None) or [])
            if feed.get("url")
        ]

    if kind == "staff_roster.scan" and school is not None:
        # Mirrors the handler's branch order: only one of these is the roster source.
        if school.apptegy_org_id:
            return [{"label": "Apptegy org", "value": str(school.apptegy_org_id)}]
        if school.staff_directory_url:
            out = [{"label": "Staff directory", "value": school.staff_directory_url}]
            if school.website_url:
                out.append({"label": "School website (nurse fallback)", "value": school.website_url})
            return out
        return _fields(school, [("School website", "website_url")])

    if kind in _SCHOOL_FIELDS and school is not None:
        out = _fields(school, _SCHOOL_FIELDS[kind])
        if kind == "documents.scan":
            # Elementary rotation calendars are district-wide, on the district home page.
            district_site = getattr(district, "website_url", None)
            if school.school_type == "elementary" and district_site and district_site.rstrip("/") != (school.website_url or "").rstrip("/"):
                out.append({"label": "District website (letter-day schedule)", "value": district_site})
            out.append({"label": "Also reads", "value": "this school's tracked newsletters"})
        return out

    if kind in _DISTRICT_FIELDS and district is not None:
        return _fields(district, _DISTRICT_FIELDS[kind])

    return []
