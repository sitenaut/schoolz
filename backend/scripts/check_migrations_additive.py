#!/usr/bin/env python3
"""Fail if a migration's upgrade() can lose data, unless it says why it may.

Migrations add and backfill; they do not drop, truncate or delete
(backend/alembic/CLAUDE.md). This looks inside upgrade() only (downgrade() is
expected to undo things) for:

  op.drop_table, op.drop_column, and SQL containing DROP TABLE, DROP COLUMN,
  DROP SCHEMA, TRUNCATE or DELETE FROM.

A revision that genuinely has to do one of these carries a line

  # destructive-ok: <why, and which backup was taken first>

and is then reported but allowed. Revisions up to BASELINE predate the rule
and are not checked.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
BASELINE = 99  # 0099_local_event_source_locations.py, the head when the rule began
_SQL = re.compile(r"\b(DROP\s+TABLE|DROP\s+COLUMN|DROP\s+SCHEMA|TRUNCATE|DELETE\s+FROM)\b", re.IGNORECASE)
_OPS = {"drop_table", "drop_column"}
_MARKER = re.compile(r"^[ \t]*#[ \t]*destructive-ok:[ \t]*\S", re.MULTILINE)


def findings(source: str) -> list[str]:
    """What in upgrade() can lose data, as 'line N: what'."""
    tree = ast.parse(source)
    upgrade = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None)
    if upgrade is None:
        return []
    found = []
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _OPS:
            found.append(f"line {node.lineno}: {ast.unparse(node.func)}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = _SQL.search(node.value)
            if match:
                found.append(f"line {node.lineno}: SQL {' '.join(match.group(1).upper().split())}")
    return found


def _before_baseline(path: Path) -> bool:
    prefix = path.name.split("_", 1)[0]
    return prefix.isdigit() and int(prefix) <= BASELINE


def main(paths: list[str]) -> int:
    files = [Path(p) for p in paths] or sorted(VERSIONS.glob("*.py"))
    blocked = 0
    for path in files:
        if not paths and _before_baseline(path):
            continue
        source = path.read_text()
        found = findings(source)
        if not found:
            continue
        if _MARKER.search(source):
            print(f"{path.name}: allowed by its destructive-ok note: {'; '.join(found)}")
            continue
        blocked += 1
        print(f"{path.name}: upgrade() can lose data: {'; '.join(found)}", file=sys.stderr)
    if blocked:
        print(
            "Migrations must be additive (backend/alembic/CLAUDE.md). If this one really must "
            "remove data, take a backup first and add a '# destructive-ok: <why, which backup>' line.",
            file=sys.stderr,
        )
        return 1
    print("Migration check passed: nothing after the baseline removes data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
