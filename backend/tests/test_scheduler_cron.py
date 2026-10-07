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
    exprs = [public_scan_cron("staff_roster.scan", f"school-{i}") for i in range(40)]
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
