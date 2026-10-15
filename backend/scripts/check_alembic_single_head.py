#!/usr/bin/env python3
"""Fail if Alembic has zero or multiple heads (run by CI)."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = list(ScriptDirectory.from_config(config).get_heads())
    if len(heads) != 1:
        print(f"Expected exactly 1 Alembic head, found {len(heads)}: {', '.join(heads) or '(none)'}", file=sys.stderr)
        return 1
    print(f"Alembic head check passed: {heads[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
