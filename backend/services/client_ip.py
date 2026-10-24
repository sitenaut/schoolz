"""Who is calling, by address - for rate limits, the survey's hashed address,
and the audit columns on submissions and approval requests.

On Fly, `Fly-Client-IP`, which Fly's proxy sets itself and a client cannot
choose. Never `X-Forwarded-For`, nor `request.client.host`: the API runs with
`--forwarded-allow-ips='*'` (backend/fly.toml), so uvicorn fills
`request.client.host` from the first X-Forwarded-For entry, which the caller
writes - anyone could pick a fresh rate-limit bucket per request. Off Fly
(local, tests) there is no proxy, so the socket peer is the caller and a
`Fly-Client-IP` header is just something the client typed.
"""

import os

from fastapi import Request


def client_ip(request: Request) -> str | None:
    if os.getenv("FLY_MACHINE_ID"):
        fly_ip = request.headers.get("fly-client-ip", "").strip()
        if fly_ip:
            return fly_ip[:45]
    return request.client.host[:45] if request.client else None
