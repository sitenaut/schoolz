#!/usr/bin/env python3
"""Encrypt the stored credentials that are still plain text (SEC-7).

    python scripts/encrypt_secrets.py            # count only, changes nothing
    python scripts/encrypt_secrets.py --apply    # encrypt the plaintext rows
    python scripts/encrypt_secrets.py --rotate --apply   # re-encrypt every row with the first key

Run it where the app runs, with the same DATA_ENCRYPTION_KEYS (on Fly, the
always-on scheduler machine: `fly ssh console -a schoolz-api
--process-group scheduler -C "python /app/scripts/encrypt_secrets.py"`). It
rewrites only the credential columns, one row per transaction, and can be run
again at any time: a row already in the wanted form is left alone. Each value
is decrypted and checked against the original before the row is committed,
so a key that cannot read back what it wrote never replaces a token.

Prints counts per column, never a value.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, type_coerce  # noqa: E402
from sqlalchemy.orm import attributes  # noqa: E402

import crypto  # noqa: E402
import database  # noqa: E402
import models  # noqa: E402, F401  (registers every table)
from database import Base  # noqa: E402


def encrypted_columns() -> dict[type, list[str]]:
    """Every mapped class with a column typed EncryptedText."""
    found: dict[type, list[str]] = {}
    for mapper in Base.registry.mappers:
        cols = [
            attr.key for attr in mapper.column_attrs
            if isinstance(attr.columns[0].type, crypto.EncryptedText)
        ]
        if cols:
            found[mapper.class_] = cols
    return dict(sorted(found.items(), key=lambda item: item[0].__tablename__))


def _wants_rewrite(stored: object, rotate: bool) -> bool:
    if stored is None:
        return False
    return rotate or not crypto.is_encrypted(stored)


def _plain(column_type: object, stored: str) -> object:
    return crypto.decrypt(stored, getattr(column_type, "purpose", None), getattr(column_type, "required", False))


async def run(
    apply: bool, rotate: bool, session_factory=None, tables: set[str] | None = None
) -> dict[str, dict[str, int]]:
    """Counts per `table.column`: rows `plaintext` (or, with rotate, `to_rotate`)
    and `rewritten`."""
    # Looked up at call time (database.SessionLocal), so tests' rolled-back
    # session applies here too.
    session_factory = session_factory or database.SessionLocal
    report: dict[str, dict[str, int]] = {}
    for model, cols in encrypted_columns().items():
        table = model.__table__
        if tables is not None and table.name not in tables:
            continue
        pk = list(table.primary_key.columns)
        # The stored form, bypassing decryption.
        raw = [type_coerce(table.c[c], table.c[c].type.impl) for c in cols]
        async with session_factory() as db:
            rows = (await db.execute(select(*pk, *raw))).all()
        pending: list[tuple] = []
        for row in rows:
            key, stored = tuple(row[: len(pk)]), row[len(pk):]
            todo = [c for c, value in zip(cols, stored, strict=True) if _wants_rewrite(value, rotate)]
            for c in todo:
                entry = report.setdefault(f"{table.name}.{c}", {"to_rotate" if rotate else "plaintext": 0, "rewritten": 0})
                entry["to_rotate" if rotate else "plaintext"] += 1
            if todo:
                pending.append((key, todo))
        if not apply:
            continue
        for key, todo in pending:
            async with session_factory() as db:
                obj = await db.get(model, key)
                if obj is None:
                    continue
                before = {c: getattr(obj, c) for c in todo}
                for c in todo:
                    # Same plain value; marking it dirty makes the column type
                    # write it again, now in encrypted form with the first key.
                    attributes.flag_modified(obj, c)
                await db.flush()
                check = (await db.execute(
                    select(*[type_coerce(table.c[c], table.c[c].type.impl) for c in todo])
                    .where(*[col == value for col, value in zip(pk, key, strict=True)])
                )).one()
                for c, stored in zip(todo, check, strict=True):
                    if not crypto.is_encrypted(stored) or _plain(table.c[c].type, stored) != before[c]:
                        await db.rollback()
                        raise crypto.EncryptionError(
                            f"{table.name}.{c} did not read back after encrypting; that row was left as it was"
                        )
                await db.commit()
            for c in todo:
                report[f"{table.name}.{c}"]["rewritten"] += 1
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: count only)")
    parser.add_argument("--rotate", action="store_true", help="re-encrypt every value with the first key")
    args = parser.parse_args()
    if crypto.fernet() is None:
        print("DATA_ENCRYPTION_KEYS is not set here; nothing can be encrypted.", file=sys.stderr)
        if args.apply:
            return 1

    report = asyncio.run(run(apply=args.apply and crypto.fernet() is not None, rotate=args.rotate))
    for name, counts in sorted(report.items()):
        print(name, " ".join(f"{k}={v}" for k, v in counts.items()))
    left = sum(c.get("plaintext", 0) - c["rewritten"] for c in report.values())
    if args.rotate:
        print("rotation:", "done" if args.apply else "dry run")
    else:
        print(f"plaintext values left: {left if args.apply else sum(c['plaintext'] for c in report.values())}"
              + ("" if args.apply else " (dry run; --apply to encrypt)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
