import hashlib

# The public-source scans used to all start at :00 every 12h, ~85 of them in
# the same minute against one 1GB Chromium, and the heaviest sites (West,
# Knight, Beck, Carusi, Kilmer) routinely timed out mid-burst while
# succeeding every time on a manual run. Each job gets its own fixed minute,
# derived from what it scans so it's stable across restarts.
#
# Spreading the minute wasn't enough: the per-school documents/school-info/
# staff-roster scans still added up to ~6.6h of job time per 12h cycle
# through a 3-slot scraper client, so every cycle queued for ~2h and the
# roster scans (no fallback scraper for /fetch-paginated) failed in the
# tail. Those pages change a few times a year, so they run weekly, each on
# its own night and hour. Menus run daily. Calendar feeds are cheap plain
# HTTP where a reschedule matters the same day, so they keep 12h.

# Heavy Chromium scans of pages that change around August-September and
# rarely otherwise. Edit a school and use run-now when something's urgent.
WEEKLY_KINDS = frozenset({
    "documents.scan",
    "school_info.scan",
    "staff_roster.scan",
    "marking_period.scan",
    "preschool_locations.scan",
    "preschool_team.scan",
    "transportation.scan",
    "hs_rotation.scan",
})

# Published monthly or weekly; daily still catches a new month's file the
# night it appears.
DAILY_KINDS = frozenset({
    "lunch_menu.scan",
    "schoolcafe_menu.scan",
    "fdmealplanner_menu.scan",
    "healthepro_menu.scan",
    "myschoolplate_menu.scan",
    "nutrislice_menu.scan",
    "presence_menu.scan",
    "givebacks.scan",
    "hs_activities_site.scan",
})

# America/New_York hours. 1-2 AM are skipped on purpose: the March DST
# change has no 2:xx and the November one repeats 1:xx.
_WEEKLY_HOURS = (0, 3, 4, 5, 22, 23)
_DAILY_HOURS = (3, 4, 5)


def public_scan_cron(kind: str, target_id: str) -> str:
    h = int(hashlib.sha256(f"{kind}:{target_id}".encode()).hexdigest(), 16)
    minute = h % 60
    if kind in WEEKLY_KINDS:
        hour = _WEEKLY_HOURS[(h // 60) % len(_WEEKLY_HOURS)]
        return f"{minute} {hour} * * {(h // 3600) % 7}"
    if kind in DAILY_KINDS:
        return f"{minute} {_DAILY_HOURS[(h // 60) % len(_DAILY_HOURS)]} * * *"
    return f"{minute} */12 * * *"
