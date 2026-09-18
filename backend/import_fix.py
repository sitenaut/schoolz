"""One-off: import a backpack-captures export for one student, doing the
same work import_bucket3 does, minus the HTTP auth dependency."""
import asyncio
import hashlib
import json
import sys

from sqlalchemy import select

import database
import services.bucket3_extract as ex
from models import Bucket3Capture, Student
from routers import bucket3 as b3


async def main(student_id: str, owner_user_id: str, path: str) -> None:
    payload = json.load(open(path))
    captures = sorted(payload["captures"], key=lambda c: c.get("captured_at", ""))

    async with database.SessionLocal() as db:
        student = (
            await db.execute(select(Student).where(Student.student_id == student_id))
        ).scalars().first()
        if student is None:
            print(f"no student with student_id={student_id}")
            return

        course_map = await b3._course_map_for(db, student, captures)
        counters = b3._Counters()
        skipped_duplicate = 0
        page_kinds: set[str] = set()

        for envelope in captures:
            adapter = envelope.get("adapter")
            source_url = envelope.get("source_url", "")
            reduced_text = envelope.get("reduced_text", "")
            if not adapter or not source_url or envelope.get("status") == "login_wall":
                continue

            page_kinds.add(ex.classify_page(adapter, source_url).pattern)
            await b3._upsert_page_kind(db, adapter, source_url)

            content_hash = hashlib.sha256(reduced_text.encode("utf-8")).hexdigest()
            existing = await db.execute(
                select(Bucket3Capture.id).where(
                    Bucket3Capture.student_id == student.id,
                    Bucket3Capture.source_url == source_url,
                    Bucket3Capture.content_hash == content_hash,
                )
            )
            if existing.scalar_one_or_none():
                skipped_duplicate += 1
                continue

            captured_at = b3._parse_captured_at(envelope["captured_at"])
            db.add(
                Bucket3Capture(
                    owner_user_id=owner_user_id,
                    student_id=student.id,
                    adapter=adapter,
                    source_url=source_url,
                    captured_at=captured_at,
                    status=envelope.get("status", "ok"),
                    char_count=envelope.get("char_count", len(reduced_text)),
                    content_hash=content_hash,
                    reduced_text=reduced_text,
                )
            )
            await b3._apply_capture(
                db, student, adapter, source_url, reduced_text, captured_at, course_map, counters
            )

        await db.commit()
        print(
            "processed=%d skipped_duplicate=%d schedule=%d work_items=%d grades=%d page_kinds=%d"
            % (
                len(captures) - skipped_duplicate,
                skipped_duplicate,
                counters.schedule,
                counters.work_items,
                counters.grades,
                len(page_kinds),
            )
        )
        for m in counters.mismatches:
            print("mismatch:", m)


asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
