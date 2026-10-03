from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from scheduler.runner import missed_fire_time

# 2026-10-03 11:45 UTC = 07:45 America/New_York; "50 */12" last fired 00:50 ET (04:50 UTC).
NOW = datetime(2026, 10, 3, 11, 45, tzinfo=timezone.utc)
PREV_FIRE_UTC = datetime(2026, 10, 3, 4, 50, tzinfo=timezone.utc)


def _job(**overrides):
    fields = dict(
        enabled=True,
        run_once=False,
        cron_expr="50 */12 * * *",
        timezone="America/New_York",
        last_run_at=None,
        created_at=NOW - timedelta(days=30),
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_a_fire_lost_to_a_crash_is_caught_up():
    job = _job(last_run_at=NOW - timedelta(days=3))
    assert missed_fire_time(job, NOW) == PREV_FIRE_UTC


def test_a_run_that_started_late_counts_as_having_run():
    job = _job(last_run_at=PREV_FIRE_UTC + timedelta(minutes=40))
    assert missed_fire_time(job, NOW) is None


def test_a_job_that_never_ran_is_caught_up_only_if_it_existed_when_due():
    assert missed_fire_time(_job(), NOW) == PREV_FIRE_UTC
    assert missed_fire_time(_job(created_at=PREV_FIRE_UTC + timedelta(minutes=1)), NOW) is None


def test_no_catch_up_when_the_next_fire_is_close():
    # Next fire is 12:50 ET = 16:50 UTC; 20 minutes before it, just wait.
    job = _job(last_run_at=NOW - timedelta(days=3))
    assert missed_fire_time(job, datetime(2026, 10, 3, 16, 30, tzinfo=timezone.utc)) is None


def test_disabled_and_one_shot_jobs_are_never_caught_up():
    stale = NOW - timedelta(days=3)
    assert missed_fire_time(_job(enabled=False, last_run_at=stale), NOW) is None
    assert missed_fire_time(_job(run_once=True, last_run_at=stale), NOW) is None


def test_a_bad_cron_expression_is_ignored():
    assert missed_fire_time(_job(cron_expr="not a cron"), NOW) is None
