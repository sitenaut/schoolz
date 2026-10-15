#!/usr/bin/env python3
"""Fly release command: bring the database to this image's schema.

Runs once per deploy, in a temporary machine with the app's secrets, before
any app or scheduler machine is replaced. A non-zero exit stops the deploy and
leaves the running version in place.

A database that is ahead of this image (an older image being redeployed) is
left alone: Alembic only moves forward here, never down.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def plan(current: set[str], known: set[str], heads: list[str]) -> str:
    """What to do given the database's revision(s) and this image's migrations."""
    if len(heads) != 1:
        return "bad_heads"
    if current - known:
        return "ahead"
    if current == {heads[0]}:
        return "current"
    return "upgrade"


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, pool, text

    from database import database_url

    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = list(script.get_heads())
    known = {rev.revision for rev in script.walk_revisions()}

    engine = create_engine(database_url(sync=True), poolclass=pool.NullPool)
    with engine.begin() as connection:
        # Same lock limit as the migrations (alembic/env.py): a held lock fails
        # the release in seconds rather than hanging the deploy.
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        current = set(MigrationContext.configure(connection).get_current_heads())
    engine.dispose()

    step = plan(current, known, heads)
    shown = ", ".join(sorted(current)) or "(empty)"
    if step == "bad_heads":
        print(f"release: expected one Alembic head, found {len(heads)}: {', '.join(heads) or '(none)'}", file=sys.stderr)
        return 1
    if step == "ahead":
        print(f"release: database is at {shown}, which this image does not know; it is newer, so nothing is run")
        return 0
    if step == "current":
        print(f"release: database is already at {heads[0]}")
        return 0

    print(f"release: upgrading {shown} -> {heads[0]}")
    command.upgrade(config, "head")
    print(f"release: database is at {heads[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
