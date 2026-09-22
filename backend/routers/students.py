import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import GuardianInvite, GuardianStudentLink, Notification, School, Student, User, student_match_key
from schemas import InviteCreate, InviteOut, StudentCreate, StudentOut

router = APIRouter(prefix="/students", tags=["students"])

INVITE_EXPIRY_DAYS = 7


async def _guardian_count(db: AsyncSession, student_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(GuardianStudentLink).where(GuardianStudentLink.student_id == student_id)
    )
    return result.scalar_one()


async def _student_out(db: AsyncSession, student: Student, link: GuardianStudentLink, matched_existing: bool = False) -> StudentOut:
    return StudentOut(
        id=student.id,
        first_name=student.first_name,
        last_name=student.last_name,
        student_id=student.student_id,
        school_name=student.school_name,
        school_id=student.school_id,
        school_type=(await db.get(School, student.school_id)).school_type if student.school_id else None,
        guardian_count=await _guardian_count(db, student.id),
        linked_via=link.linked_via,
        matched_existing=matched_existing,
    )


@router.get("", response_model=list[StudentOut])
async def list_my_students(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Student, GuardianStudentLink)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user.id)
        .order_by(GuardianStudentLink.created_at)
    )
    return [await _student_out(db, student, link) for student, link in result.all()]


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
async def add_student(payload: StudentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    school = (await db.execute(select(School).where(School.id == payload.school_id))).scalar_one_or_none()
    if not school:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown school")

    match_key = student_match_key(payload.first_name, payload.last_name, payload.student_id)

    result = await db.execute(select(Student).where(Student.match_key == match_key))
    existing = result.scalar_one_or_none()

    if existing:
        already_linked = await db.execute(
            select(GuardianStudentLink).where(
                GuardianStudentLink.guardian_user_id == user.id,
                GuardianStudentLink.student_id == existing.id,
            )
        )
        if already_linked.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "You already have this student on your profile")

        link = GuardianStudentLink(guardian_user_id=user.id, student_id=existing.id, linked_via="auto_matched")
        db.add(link)

        # Notify every other guardian already linked to this student - the
        # match is automatic (no approval gate), but never silent.
        other_links = await db.execute(
            select(GuardianStudentLink).where(GuardianStudentLink.student_id == existing.id)
        )
        for other in other_links.scalars().all():
            db.add(
                Notification(
                    user_id=other.guardian_user_id,
                    type="guardian_matched",
                    message=(
                        f"{user.username} added {existing.first_name} {existing.last_name} "
                        f"(ID {existing.student_id}) and now shares access to this student with you."
                    ),
                    student_id=existing.id,
                )
            )

        if not existing.school_id:
            existing.school_id = school.id
            existing.school_name = school.name

        await db.commit()
        await db.refresh(link)
        return await _student_out(db, existing, link, matched_existing=True)

    student = Student(
        first_name=payload.first_name,
        last_name=payload.last_name,
        student_id=payload.student_id,
        school_name=school.name,
        school_id=school.id,
        match_key=match_key,
    )
    db.add(student)
    await db.flush()

    link = GuardianStudentLink(guardian_user_id=user.id, student_id=student.id, linked_via="created")
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return await _student_out(db, student, link, matched_existing=False)


async def _get_own_link(db: AsyncSession, user_id: str, student_id: str) -> GuardianStudentLink:
    result = await db.execute(
        select(GuardianStudentLink).where(
            GuardianStudentLink.guardian_user_id == user_id,
            GuardianStudentLink.student_id == student_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found on your profile")
    return link


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_student(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Removes only the calling guardian's own link. Never touches the
    canonical Student row or any other guardian's link to it."""
    link = await _get_own_link(db, user.id, student_id)
    await db.delete(link)
    await db.commit()


@router.post("/{student_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    student_id: str,
    payload: InviteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_own_link(db, user.id, student_id)  # must already be a guardian of this student

    invite = GuardianInvite(
        student_id=student_id,
        inviter_user_id=user.id,
        invitee_email=payload.invitee_email,
        token=secrets.token_urlsafe(32),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRY_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    web_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173")
    return InviteOut(
        id=invite.id,
        token=invite.token,
        accept_url=f"{web_url}/invites/{invite.token}",
        invitee_email=invite.invitee_email,
        status=invite.status,
        expires_at=invite.expires_at,
    )
