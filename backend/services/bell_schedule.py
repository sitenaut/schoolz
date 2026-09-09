"""Computes "what period is it right now" from a school's bell_periods
table (services/school_info.py's discovery covers the school's logo/
address; this is a separate, deliberately simple piece of arithmetic -
no network call, just comparing the current local time against a static
table already on the School row).
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/New_York")


def _parse_hm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _variant_for_status(status: str) -> str | None:
    """Maps a school-day status (services/school_today.py:classify_day)
    to which of the school's bell_periods variants applies - "closed"
    and "weekend" have no periods at all."""
    return {"open": "regular", "early_dismissal": "early_dismissal", "delayed": "delayed_opening"}.get(status)


def current_period(bell_periods: dict | None, status: str, now: datetime | None = None) -> dict | None:
    """Returns {"name", "start", "end", "start_label", "end_label",
    "minutes_in", "minutes_left", "next_name"} for whichever period
    `now` falls in, or None if there's no table, the day has no bell
    schedule concept (closed/weekend), or `now` is outside every listed
    period (before first period, during a lunch gap the table doesn't
    cover as a named period, or after the last one)."""
    if not bell_periods:
        return None
    variant = _variant_for_status(status)
    if not variant:
        return None
    periods = bell_periods.get(variant)
    if not periods:
        return None

    now = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    today = now.date()
    current_time = now.time()

    for idx, p in enumerate(periods):
        start = _parse_hm(p["start"])
        end = _parse_hm(p["end"])
        if start <= current_time < end:
            start_dt = datetime.combine(today, start, LOCAL_TZ)
            end_dt = datetime.combine(today, end, LOCAL_TZ)
            next_name = periods[idx + 1]["name"] if idx + 1 < len(periods) else None
            return {
                "name": p["name"],
                "start_label": start.strftime("%-I:%M %p"),
                "end_label": end.strftime("%-I:%M %p"),
                "minutes_in": int((now - start_dt).total_seconds() // 60),
                "minutes_left": int((end_dt - now).total_seconds() // 60),
                "next_name": next_name,
            }
    return None
