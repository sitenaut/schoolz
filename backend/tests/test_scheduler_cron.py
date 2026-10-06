import collections
import importlib.util
from pathlib import Path

from scheduler.cron import DAILY_KINDS, WEEKLY_KINDS, public_scan_cron


def test_public_scans_spread_across_the_hour_and_stay_put():
    crons = [public_scan_cron("district_calendar.scan", f"district-{i}") for i in range(85)]
    minutes = [int(c.split()[0]) for c in crons]
    assert all(c.endswith(" */12 * * *") for c in crons)
    assert len(set(minutes)) > 30  # not a burst any more
    assert public_scan_cron("district_calendar.scan", "district-1") == crons[1]  # stable


def test_weekly_scans_spread_across_nights_and_hours():
    kinds = ("documents.scan", "school_info.scan", "staff_roster.scan")
    crons = [public_scan_cron(k, f"school-{i}") for k in kinds for i in range(103)]
    slots = collections.Counter((c.split()[1], c.split()[4]) for c in crons)
    days = {c.split()[4] for c in crons}
    hours = {int(c.split()[1]) for c in crons}
    assert days == {str(d) for d in range(7)}
    assert hours <= {0, 3, 4, 5, 22, 23}  # never 1-2 AM: DST skips/repeats them
    # 309 jobs over 42 night-hours: no hour gets more than a handful, where
    # one hour used to get all of them.
    assert max(slots.values()) <= 20


def test_a_schools_heavy_scans_land_on_different_slots():
    # Not guaranteed for every school, but across many the three kinds must
    # not move in lockstep (that would just rebuild the burst per night).
    same = sum(
        len({" ".join(public_scan_cron(k, f"school-{i}").split()[1:]) for k in ("documents.scan", "school_info.scan", "staff_roster.scan")}) == 1
        for i in range(100)
    )
    assert same < 10


def test_daily_menus_run_early_morning():
    for i in range(20):
        _, hour, *rest = public_scan_cron("lunch_menu.scan", f"district-{i}").split()
        assert int(hour) in {3, 4, 5} and rest == ["*", "*", "*"]


def test_migration_copy_matches_live_cadence():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0075_tiered_scan_cadence.py"
    spec = importlib.util.spec_from_file_location("m0075", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The migration is applied history: it retimed the jobs that existed then.
    # A kind added later has no rows for it to retime, so it lives only in
    # cron.py - but nothing the migration retimed may be missing or moved.
    assert set(mod._WEEKLY_KINDS) <= WEEKLY_KINDS
    assert set(mod._DAILY_KINDS) <= DAILY_KINDS
    for kind in set(mod._WEEKLY_KINDS) | set(mod._DAILY_KINDS):
        assert mod._cron(kind, "school-x") == public_scan_cron(kind, "school-x")
