import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import GuardianInvite, GuardianStudentLink, Notification, School, Student, User, student_match_key
from schemas import CaptureStudentOut, InviteCreate, InviteOut, StudentCreate, StudentOut, StudentUpdate
from services import rate_limit
from services.client_ip import client_ip

router = APIRouter(prefix="/students", tags=["students"])

INVITE_EXPIRY_DAYS = 7

# Adding a child whose name and student ID match an existing record links
# the account to that child with no approval (CLAUDE.md, "Auto-matching").
# Names are often public, so what keeps a stranger from guessing the ID is
# how few guesses they get: a family adds a handful of children once.
ADDS_PER_ACCOUNT_PER_DAY = 10
ADDS_PER_CONNECTION_PER_DAY = 30
_TOO_MANY_ADDS = "That's a lot of children added today. If you're still setting up, try again tomorrow."


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
        grad_year=student.grad_year,
        guardian_count=await _guardian_count(db, student.id),
        linked_via=link.linked_via,
        matched_existing=matched_existing,
    )


@router.get("", response_model=list[StudentOut] | list[CaptureStudentOut])
async def list_my_students(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Student, GuardianStudentLink)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user.id)
        .order_by(GuardianStudentLink.created_at)
    )
    rows = result.all()
    if getattr(request.state, "capture_device_id", None):
        # A Backpack Capture key gets the names it labels pages and asks
        # about, never the student ID: first + last + ID is the auto-match
        # key (add_student), so a phished or stolen key would otherwise let
        # its holder link their own account to the child. The server checks
        # a numeric Classroom login against the ID itself, on import
        # (services/capture_routing.py).
        return [CaptureStudentOut(id=s.id, first_name=s.first_name, last_name=s.last_name) for s, _ in rows]
    return [await _student_out(db, student, link) for student, link in rows]


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
async def add_student(
    payload: StudentCreate, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    school = (await db.execute(select(School).where(School.id == payload.school_id))).scalar_one_or_none()
    if not school:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown school")
    await rate_limit.enforce(
        db, "students.add", user.id, limit=ADDS_PER_ACCOUNT_PER_DAY, window_seconds=rate_limit.DAY, detail=_TOO_MANY_ADDS
    )
    await rate_limit.enforce(
        db,
        "students.add.connection",
        rate_limit.connection_key(client_ip(request)),
        limit=ADDS_PER_CONNECTION_PER_DAY,
        window_seconds=rate_limit.DAY,
        detail=_TOO_MANY_ADDS,
    )

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
        # match is automatic (no approval gate), but never silent. The query
        # autoflushes the new link, so leave the adder out by id.
        other_links = await db.execute(
            select(GuardianStudentLink).where(
                GuardianStudentLink.student_id == existing.id,
                GuardianStudentLink.guardian_user_id != user.id,
            )
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


@router.patch("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: str, payload: StudentUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Any linked guardian can set/correct grad_year - the Student row is
    shared, same as everything else about it (name, school). Typed on My
    Children, or left null (the class pages still work reached directly by
    URL, just with no default class to land a guardian on)."""
    link = await _get_own_link(db, user.id, student_id)
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    fields = payload.model_dump(exclude_unset=True)
    if "grad_year" in fields:
        student.grad_year = fields["grad_year"]
    await db.commit()
    await db.refresh(student)
    return await _student_out(db, student, link)


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_student(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Removes only the calling guardian's own link. Never touches the
    canonical Student row or any other guardian's link to it."""
    link = await _get_own_link(db, user.id, student_id)
    await db.delete(link)
    # Removing the child ends this guardian's sharing of them too.
    await db.execute(
        update(GuardianInvite)
        .where(GuardianInvite.inviter_user_id == user.id, GuardianInvite.student_id == student_id, GuardianInvite.status == "pending")
        .values(status="revoked")
    )
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
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_EXPIRY_DAYS),
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
