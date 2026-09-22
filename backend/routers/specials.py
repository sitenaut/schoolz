from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import School, StudentSpecial, User
from routers.bucket3 import _get_own_student
from schemas import StudentSpecialIn, StudentSpecialOut, StudentSpecialsOut
from services.specials import rotation_day_numbers

router = APIRouter(prefix="/students", tags=["specials"])


async def _out(db: AsyncSession, student) -> StudentSpecialsOut:
    school = await db.get(School, student.school_id) if student.school_id else None
    rows = (
        await db.execute(select(StudentSpecial).where(StudentSpecial.student_id == student.id).order_by(StudentSpecial.rotation_day))
    ).scalars().all()
    return StudentSpecialsOut(
        rotation_days=await rotation_day_numbers(db, school) if school else [],
        specials=[StudentSpecialOut.model_validate(r) for r in rows],
    )


@router.get("/{student_id}/specials", response_model=StudentSpecialsOut)
async def get_specials(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _out(db, await _get_own_student(db, user.id, student_id))


@router.put("/{student_id}/specials", response_model=StudentSpecialsOut)
async def replace_specials(
    student_id: str, body: list[StudentSpecialIn], user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Replaces the whole table - the form edits every rotation day at once,
    and a day left blank is deleted (unknown), never stored as empty."""
    student = await _get_own_student(db, user.id, student_id)
    days = [s.rotation_day for s in body]
    if len(days) != len(set(days)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Each rotation day can only appear once")
    await db.execute(delete(StudentSpecial).where(StudentSpecial.student_id == student.id))
    for s in body:
        subject = s.subject.strip()
        if subject:
            db.add(
                StudentSpecial(
                    student_id=student.id,
                    rotation_day=s.rotation_day,
                    subject=subject,
                    teacher=(s.teacher or "").strip() or None,
                    updated_by_user_id=user.id,
                )
            )
    await db.commit()
    return await _out(db, student)
