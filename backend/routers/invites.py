from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import GuardianInvite, GuardianStudentLink, Notification, Student, User
from schemas import InvitePreviewOut, StudentOut
from routers.students import _student_out

router = APIRouter(prefix="/invites", tags=["invites"])


async def _get_live_invite(db: AsyncSession, token: str) -> GuardianInvite:
    result = await db.execute(select(GuardianInvite).where(GuardianInvite.token == token))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.expires_at < datetime.now(timezone.utc) and invite.status == "pending":
        invite.status = "expired"
        await db.commit()
    return invite


@router.get("/{token}", response_model=InvitePreviewOut)
async def preview_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Unauthenticated preview - deliberately minimal (no full last name or
    student ID) so an invite link alone can't be used to fish for a child's
    identifying info before the invitee has even logged in."""
    invite = await _get_live_invite(db, token)
    student_result = await db.execute(select(Student).where(Student.id == invite.student_id))
    student = student_result.scalar_one()
    inviter_result = await db.execute(select(User).where(User.id == invite.inviter_user_id))
    inviter = inviter_result.scalar_one()

    return InvitePreviewOut(
        student_first_name=student.first_name,
        student_last_initial=student.last_name[:1].upper(),
        inviter_username=inviter.username,
        status=invite.status,
        expires_at=invite.expires_at,
    )


@router.post("/{token}/accept", response_model=StudentOut)
async def accept_invite(token: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    invite = await _get_live_invite(db, token)
    if invite.status != "pending":
        raise HTTPException(status.HTTP_410_GONE, f"This invite is {invite.status}")

    student_result = await db.execute(select(Student).where(Student.id == invite.student_id))
    student = student_result.scalar_one()

    existing_link_result = await db.execute(
        select(GuardianStudentLink).where(
            GuardianStudentLink.guardian_user_id == user.id,
            GuardianStudentLink.student_id == student.id,
        )
    )
    link = existing_link_result.scalar_one_or_none()
    if not link:
        link = GuardianStudentLink(guardian_user_id=user.id, student_id=student.id, linked_via="invite_accepted")
        db.add(link)

    invite.status = "accepted"
    invite.accepted_by_user_id = user.id
    invite.accepted_at = datetime.now(timezone.utc)

    if invite.inviter_user_id != user.id:
        db.add(
            Notification(
                user_id=invite.inviter_user_id,
                type="invite_accepted",
                message=f"{user.username} accepted your invite to {student.first_name} {student.last_name}.",
                student_id=student.id,
            )
        )

    await db.commit()
    await db.refresh(link)
    return await _student_out(db, student, link)
