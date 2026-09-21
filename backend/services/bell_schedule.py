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


_STATUS_VARIANTS = {
    "open": ("regular", "long_block"),
    "early_dismissal": ("early_dismissal",),
    "delayed": ("delayed_opening",),
}


def _is_shared_slot(name: str) -> bool:
    return name.upper().startswith("L")


def lettered_day(bell_periods: dict | None, status: str, letters: list[str] | None) -> tuple[str, list[dict]] | None:
    """Names each clock slot with the block letter that fills it on this
    rotation day: the rotation legend lists a day's letters in clock order
    (Day 2 = D,A,B,H,E,F), so they zip onto the variant's numbered slots,
    while the L1/L2 lunch band keeps its own name. A variant only fits when
    its slot count equals the letter count - a 4-block Day 5 can't be laid
    onto a 6-slot table - and with no fitting table this returns None
    rather than guessing (no published timetable exists for a long-block
    early dismissal)."""
    if not bell_periods or not letters:
        return None
    for variant in _STATUS_VARIANTS.get(status, ()):
        slots = bell_periods.get(variant) or []
        numbered = [s for s in slots if not _is_shared_slot(s["name"])]
        if not numbered or len(numbered) != len(letters):
            continue
        it = iter(letters)
        return variant, [
            {"name": s["name"] if _is_shared_slot(s["name"]) else next(it), "start": s["start"], "end": s["end"]} for s in slots
        ]
    return None


def is_long_block_day(bell_periods: dict | None, letters: list[str] | None) -> bool:
    """Fewer blocks meet than the regular day has slots, so each runs long -
    true of the rotation itself, whether or not this school's long-block
    clock times are on file."""
    regular = [s for s in (bell_periods or {}).get("regular") or [] if not _is_shared_slot(s["name"])]
    return bool(letters and regular and len(letters) < len(regular))
