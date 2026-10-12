"""Print a seed `sacc` block from an AlphaBEST location page.

    docker exec -i schoolz-api-local sh -c 'cd /app && python scripts/fill_alphabest_sacc.py https://www.alphabest.org/gloucesternj/'

Paste the output under the host school's `sacc` in the district seed. SACC is a
one-off, not a scheduled scan (see models.SaccProgram)."""

import asyncio
import json
import sys

sys.path.insert(0, ".")
from services.alphabest import fetch_location  # noqa: E402

if __name__ == "__main__":
    block = asyncio.run(fetch_location(sys.argv[1]))
    print(json.dumps(block, indent=2))
