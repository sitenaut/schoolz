import hashlib

# The public-source scans refresh every 12h. They used to all start at :00,
# ~85 of them in the same minute against one 1GB Chromium, and the heaviest
# sites (West, Knight, Beck, Carusi, Kilmer) routinely timed out mid-burst
# while succeeding every time on a manual run. Each job gets its own fixed
# minute instead, derived from what it scans so it's stable across restarts.


def public_scan_cron(kind: str, target_id: str) -> str:
    minute = int(hashlib.sha256(f"{kind}:{target_id}".encode()).hexdigest(), 16) % 60
    return f"{minute} */12 * * *"
