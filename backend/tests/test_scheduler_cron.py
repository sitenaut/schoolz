import collections
import importlib.util
from pathlib import Path

from scheduler.cron import BIWEEKLY_KINDS, DAILY_KINDS, MONTHLY_KINDS, WEEKLY_KINDS, public_scan_cron, smore_scan_cron, spread_default_smore_cron


def test_public_scans_spread_across_the_hour_and_stay_put():
    crons = [public_scan_cron("district_calendar.scan", f"district-{i}") for i in range(85)]
    minutes = [int(c.split()[0]) for c in crons]
    assert all(c.endswith(" */12 * * *") for c in crons)
    assert len(set(minutes)) > 30  # not a burst any more
    assert public_scan_cron("district_calendar.scan", "district-1") == crons[1]  # stable


def test_weekly_scans_spread_across_nights_and_hours():
    kinds = ("marking_period.scan", "transportation.scan", "hs_rotation.scan")
    crons = [public_scan_cron(k, f"district-{i}") for k in kinds for i in range(103)]
    slots = collections.Counter((c.split()[1], c.split()[4]) for c in crons)
    days = {c.split()[4] for c in crons}
    hours = {int(c.split()[1]) for c in crons}
    assert days == {str(d) for d in range(7)}
    assert hours <= {0, 3, 4, 5, 22, 23}  # never 1-2 AM: DST skips/repeats them
    assert max(slots.values()) <= 20


def test_biweekly_scans_fire_on_two_days_fourteen_apart():
    crons = [public_scan_cron(k, f"school-{i}") for k in BIWEEKLY_KINDS for i in range(103)]
    for c in crons:
        minute, hour, days, month, dow = c.split()
        first, second = (int(d) for d in days.split(","))
        assert second == first + 14 and 1 <= first <= 14 and second <= 28  # exists in every month
        assert month == "*" and dow == "*"
        assert int(hour) in {0, 3, 4, 5, 22, 23}
    # 206 jobs over 14 days x 6 hours: no night-hour gets more than a few.
    assert max(collections.Counter((c.split()[1], c.split()[2]) for c in crons).values()) <= 8
    assert {c.split()[2].split(",")[0] for c in crons} == {str(d) for d in range(1, 15)}


def test_monthly_scans_fire_on_one_day_that_exists_every_month():
    crons = [public_scan_cron("school_info.scan", f"school-{i}") for i in range(103)]
    for c in crons:
        _, hour, day, month, dow = c.split()
        assert 1 <= int(day) <= 28 and month == "*" and dow == "*"
        assert int(hour) in {0, 3, 4, 5, 22, 23}
    assert len({c.split()[2] for c in crons}) > 20


def test_a_schools_heavy_scans_land_on_different_slots():
    # Not guaranteed for every school, but across many the three kinds must
    # not move in lockstep (that would just rebuild the burst per night).
    kinds = ("documents.scan", "school_info.scan", "staff_roster.scan")
    same = sum(len({" ".join(public_scan_cron(k, f"school-{i}").split()[1:3]) for k in kinds}) == 1 for i in range(100))
    assert same < 10


def test_smore_scans_keep_monday_8am_but_spread_the_minute():
    crons = [smore_scan_cron(f"newsletter-{i}") for i in range(60)]
    assert all(c.endswith(" 8 * * 1") for c in crons)
    assert len({c.split()[0] for c in crons}) > 25
    assert smore_scan_cron("newsletter-1") == crons[1]  # stable
    # Only the shared default is spread; a cron someone chose is theirs.
    assert spread_default_smore_cron("0 8 * * 1", "newsletter-1") == crons[1]
    assert spread_default_smore_cron("30 6 * * 5", "newsletter-1") == "30 6 * * 5"


def test_daily_menus_run_early_morning():
    for i in range(20):
        _, hour, *rest = public_scan_cron("lunch_menu.scan", f"district-{i}").split()
        assert int(hour) in {3, 4, 5} and rest == ["*", "*", "*"]


def _load_migration(name: str, filename: str):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_copy_matches_live_cadence():
    mod = _load_migration("m0075", "0075_tiered_scan_cadence.py")
    # 0075 is applied history: it retimed the jobs that existed then, and 0080
    # later moved three of its kinds off weekly. A kind added since has no rows
    # for 0075 to retime, so it lives only in cron.py - but nothing 0075 retimed
    # may vanish from the tiers, and what is still weekly or daily must agree.
    moved = BIWEEKLY_KINDS | MONTHLY_KINDS
    assert set(mod._WEEKLY_KINDS) <= WEEKLY_KINDS | moved
    assert set(mod._DAILY_KINDS) <= DAILY_KINDS
    for kind in (set(mod._WEEKLY_KINDS) - moved) | set(mod._DAILY_KINDS):
        assert mod._cron(kind, "school-x") == public_scan_cron(kind, "school-x")


def test_slowdown_migration_copy_matches_live_cadence():
    mod = _load_migration("m0080", "0080_slower_school_scans.py")
    assert set(mod._BIWEEKLY_KINDS) == BIWEEKLY_KINDS and set(mod._MONTHLY_KINDS) == MONTHLY_KINDS
    old = _load_migration("m0075_for_0080", "0075_tiered_scan_cadence.py")
    for kind in BIWEEKLY_KINDS | MONTHLY_KINDS:
        for i in range(30):
            assert mod._new_cron(kind, f"school-{i}") == public_scan_cron(kind, f"school-{i}")
            assert mod._old_cron(kind, f"school-{i}") == old._cron(kind, f"school-{i}")  # what existing rows hold
            # same minute and hour, so the move is only a change of day
            assert mod._old_cron(kind, f"school-{i}").split()[:2] == mod._new_cron(kind, f"school-{i}").split()[:2]
    assert mod._smore_cron("newsletter-9") == smore_scan_cron("newsletter-9")


def test_the_trigger_fires_on_the_weekday_cron_names():
    # APScheduler numbers weekdays from Monday, cron and croniter from Sunday.
    # Passed through unchanged, every weekly job fired a day late and a
    # restart in between ran it twice (catch-up, then the late fire).
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from croniter import croniter

    from scheduler.runner import cron_trigger

    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 10, 5, 12, 0, tzinfo=tz)  # a Monday
    exprs = [public_scan_cron("marking_period.scan", f"district-{i}") for i in range(40)]
    exprs += ["35 3 * * 3", "0 3 * * 0", "23 23 * * 6", "0 6 * * 7", "0 6 * * 1-5", "0 6 * * 0-6",
              "0 6 * * 0,3", "0 6 * * 1-5/2", "0 6 * * mon", "8 */12 * * *", "0 5,17 * * *"]
    for expr in exprs:
        # Three fires: enough to see the weekday, and short of the November
        # clock change, where croniter itself is an hour out.
        fires, at = [], base
        for _ in range(3):
            at = cron_trigger(expr, tz).get_next_fire_time(None, at.replace(second=1))
            fires.append(at)
        it = croniter(expr, base)
        assert fires == [it.get_next(datetime) for _ in range(3)], expr


def test_reconcile_leaves_an_unchanged_job_alone():
    # Rebuilding every job on every 30s reconcile logged two lines per job and
    # recomputed each next fire from "now".
    from types import SimpleNamespace

    from apscheduler.schedulers.background import BackgroundScheduler

    from scheduler.runner import build_apscheduler_job

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.start(paused=True)
    try:
        job = SimpleNamespace(id="reconcile-test", cron_expr="5 4 * * 3", timezone="America/New_York", enabled=True)
        build_apscheduler_job(scheduler, job)
        first = scheduler.get_job("job-reconcile-test")
        build_apscheduler_job(scheduler, job)
        assert scheduler.get_job("job-reconcile-test") is not None
        assert scheduler.get_job("job-reconcile-test").trigger is first.trigger  # same job, not a rebuilt one

        job.cron_expr = "6 4 * * 3"
        build_apscheduler_job(scheduler, job)
        assert scheduler.get_job("job-reconcile-test").trigger is not first.trigger

        job.enabled = False
        build_apscheduler_job(scheduler, job)
        assert scheduler.get_job("job-reconcile-test") is None
        job.enabled = True
        build_apscheduler_job(scheduler, job)
        assert scheduler.get_job("job-reconcile-test") is not None
    finally:
        scheduler.shutdown(wait=False)


def test_biweekly_and_monthly_triggers_fire_on_the_days_named():
    # Kept before the November clock change (see above): croniter is an hour out after it.
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from croniter import croniter

    from scheduler.runner import cron_trigger

    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 10, 5, 12, 0, tzinfo=tz)
    for expr, count in (("10 4 8,22 * *", 2), ("5 23 9,23 * *", 2), ("40 3 27 * *", 1)):
        fires, at = [], base
        for _ in range(count):
            at = cron_trigger(expr, tz).get_next_fire_time(None, at.replace(second=1))
            fires.append(at)
        it = croniter(expr, base)
        assert fires == [it.get_next(datetime) for _ in range(count)], expr
        assert [f.day for f in fires] == [int(d) for d in expr.split()[2].split(",")][:count]
