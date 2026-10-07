import asyncio
from datetime import datetime, timedelta, timezone

from scheduler import runner
from scheduler.backoff import back_off_reason

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _runs(*specs):
    """(status, code, days_ago), newest first."""
    return [(status, code, NOW - timedelta(days=days)) for status, code, days in specs]


EMPTY = ("warning", "no_staff_found")


def test_three_empty_results_in_a_row_skip_the_next_fire():
    recent = _runs((*EMPTY, 14), (*EMPTY, 28), (*EMPTY, 42))
    assert "backed off" in back_off_reason("staff_roster.scan", "cron", recent, NOW)
    assert back_off_reason("staff_roster.scan", "catchup", recent, NOW)


def test_the_skipped_job_still_runs_once_the_last_run_is_a_month_old():
    recent = _runs((*EMPTY, 28), (*EMPTY, 42), (*EMPTY, 56))
    assert back_off_reason("staff_roster.scan", "cron", recent, NOW) is None


def test_a_streak_needs_three_and_all_of_them_empty():
    assert back_off_reason("staff_roster.scan", "cron", _runs((*EMPTY, 14), (*EMPTY, 28)), NOW) is None
    assert back_off_reason("staff_roster.scan", "cron", _runs((*EMPTY, 14), ("success", None, 28), (*EMPTY, 42)), NOW) is None
    assert back_off_reason("staff_roster.scan", "cron", _runs((*EMPTY, 14), ("error", "site_did_not_load", 28), (*EMPTY, 42)), NOW) is None
    # A different warning is not "nothing there".
    other = ("warning", "something_else")
    assert back_off_reason("staff_roster.scan", "cron", _runs((*other, 14), (*other, 28), (*other, 42)), NOW) is None


def test_people_and_first_runs_are_never_held_back():
    recent = _runs((*EMPTY, 14), (*EMPTY, 28), (*EMPTY, 42))
    for trigger in ("manual", "first_run"):
        assert back_off_reason("staff_roster.scan", trigger, recent, NOW) is None


def test_only_the_scans_that_can_come_up_empty_back_off():
    recent = _runs(("warning", "school_info_missing_fields", 14), ("warning", "school_info_missing_fields", 28), ("warning", "school_info_missing_fields", 42))
    assert back_off_reason("school_info.scan", "cron", recent, NOW) is None
    docs = _runs(("warning", "no_documents_found", 14), ("warning", "no_documents_found", 28), ("warning", "no_documents_found", 42))
    assert back_off_reason("documents.scan", "cron", docs, NOW)
    assert back_off_reason("documents.scan", "cron", recent, NOW) is None  # wrong code for the kind


def test_catch_up_runs_are_started_apart_not_all_at_once(monkeypatch):
    started: list[tuple[str, float]] = []

    async def fake_execute(job_id, *, triggered_by):
        started.append((job_id, asyncio.get_running_loop().time()))

    monkeypatch.setattr(runner, "_execute", fake_execute)

    async def go():
        runner.launch_staggered(["a", "b", "c"], "catchup", spacing_s=0.05)
        assert not started or len(started) < 3  # not launched in one burst
        await asyncio.sleep(0.3)
        await asyncio.gather(*list(runner._background_tasks))

    asyncio.run(go())
    assert [j for j, _ in started] == ["a", "b", "c"]  # order kept
    times = [t for _, t in started]
    assert times[1] - times[0] >= 0.04 and times[2] - times[1] >= 0.04
