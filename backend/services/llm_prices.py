"""List prices for the models schoolz calls, $ per million tokens, for the
daily cost report (scheduler/jobs/llm_cost_report.py).

Anthropic list prices, looked up 2026-10-20 (platform.claude.com pricing).
scripts/build_grafana_dashboards.py:MODEL_PRICES holds the same table for the
cost dashboard; change both together. A model that matches nothing here is
reported as unpriced rather than as free.
"""
from __future__ import annotations

import re

# (input, output, cache_write, cache_read), first match wins.
PRICES: list[tuple[str, tuple[float, float, float, float]]] = [
    # Prompts up to 100K tokens; every schoolz call is far below that.
    (r"^claude-haiku-5-5", (0.10, 0.50, 0.125, 0.01)),
    (r"^claude-haiku-4-5", (1.00, 5.00, 1.25, 0.10)),
    (r"^claude-sonnet-5", (2.00, 10.00, 2.50, 0.20)),  # Sonnet 5 and 5.5
    (r"^claude-opus-5-5", (4.00, 20.00, 5.00, 0.20)),  # before Opus 5
    (r"^claude-opus-5", (5.00, 25.00, 6.25, 0.50)),
    (r"^claude-fable-5", (10.00, 50.00, 12.50, 0.25)),
]


def cost(model: str, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int) -> float | None:
    """Dollars for one row's tokens, or None for a model with no price here."""
    for pattern, (pi, po, pw, pr) in PRICES:
        if re.match(pattern, model):
            return (input_tokens * pi + output_tokens * po + cache_write * pw + cache_read * pr) / 1_000_000
    return None
