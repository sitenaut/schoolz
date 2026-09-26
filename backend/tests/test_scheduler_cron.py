from scheduler.cron import public_scan_cron


def test_public_scans_spread_across_the_hour_and_stay_put():
    crons = [public_scan_cron("staff_roster.scan", f"school-{i}") for i in range(85)]
    minutes = [int(c.split()[0]) for c in crons]
    assert all(c.endswith(" */12 * * *") for c in crons)
    assert len(set(minutes)) > 30  # not a burst any more
    assert public_scan_cron("staff_roster.scan", "school-1") == crons[1]  # stable
