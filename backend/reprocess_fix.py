"""One-off: re-run current extraction over every stored bucket3 capture for
one student, the same work reprocess_bucket3 does, minus the HTTP auth
dependency. Repairs rows written by older parser generations."""
import asyncio
import sys

from sqlalchemy import delete, select

import database
from models import Bucket3Capture, ChildWorkItem, ChildWorkItemProgress, Student
from routers import bucket3 as b3


async def main(student_id: str) -> None:
    async with database.SessionLocal() as db:
        student = (
            await db.execute(select(Student).where(Student.student_id == student_id))
        ).scalars().first()
        if student is None:
            print(f"no student with student_id={student_id}")
            return

        stored = (
            await db.execute(
                select(Bucket3Capture)
                .where(Bucket3Capture.student_id == student.id)
                .order_by(Bucket3Capture.captured_at)
            )
        ).scalars().all()

        course_map = await b3._course_map_for(db, student, [])
        print("course map: slugs=%d by_code=%d" % (len(course_map.by_slug), len(course_map.by_code)))

        counters = b3._Counters()
        for c in stored:
            await b3._apply_capture(
                db, student, c.adapter, c.source_url, c.reduced_text, c.captured_at, course_map, counters
            )

        removed = 0
        if counters.seen_work_uids:
            marked = select(ChildWorkItemProgress.work_item_id).where(
                ChildWorkItemProgress.student_id == student.id
            )
            res = await db.execute(
                delete(ChildWorkItem).where(
                    ChildWorkItem.student_id == student.id,
                    ChildWorkItem.external_uid.not_in(counters.seen_work_uids),
                    ChildWorkItem.id.not_in(marked),
                )
            )
            removed = res.rowcount or 0

        await db.commit()
        print(
            "captures=%d schedule=%d work_items=%d grades=%d stale_removed=%d"
            % (len(stored), counters.schedule, counters.work_items, counters.grades, removed)
        )
        for m in counters.mismatches:
            print("mismatch:", m)


asyncio.run(main(sys.argv[1]))
