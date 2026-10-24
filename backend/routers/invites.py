from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, mask_email
from database import get_db
from models import GuardianInvite, GuardianStudentLink, Notification, Student, User
from routers.students import _student_out
from schemas import InvitePreviewOut, StudentOut

router = APIRouter(prefix="/invites", tags=["invites"])


async def _get_live_invite(db: AsyncSession, token: str) -> GuardianInvite:
    # An invite speaks for its inviter only while they're still linked to the
    # child: removing the child (students.remove_student revokes these too)
    # used to leave a working link that made its holder a permanent guardian.
    result = await db.execute(select(GuardianInvite).where(GuardianInvite.token == token))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.expires_at < datetime.now(UTC) and invite.status == "pending":
        invite.status = "expired"
        await db.commit()
    if invite.status == "pending" and not await _is_guardian(db, invite.inviter_user_id, invite.student_id):
        invite.status = "revoked"
        await db.commit()
    return invite


async def _is_guardian(db: AsyncSession, user_id: str, student_id: str) -> bool:
    return (
        await db.execute(
            select(GuardianStudentLink.id).where(
                GuardianStudentLink.guardian_user_id == user_id, GuardianStudentLink.student_id == student_id
            )
        )
    ).first() is not None


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
        invitee_email_hint=mask_email(invite.invitee_email) if invite.invitee_email else None,
    )


@router.post("/{token}/accept", response_model=StudentOut)
async def accept_invite(token: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    invite = await _get_live_invite(db, token)
    if invite.status != "pending":
        raise HTTPException(status.HTTP_410_GONE, f"This invite is {invite.status}")

    student_result = await db.execute(select(Student).where(Student.id == invite.student_id))
    student = student_result.scalar_one()

    # The inviter (or anyone already linked) opening the link just to look
    # at it used it up, and the co-parent it was for got "already used".
    if await _is_guardian(db, user.id, student.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{student.first_name} is already on your account - this invite is for someone else"
        )
    link = GuardianStudentLink(guardian_user_id=user.id, student_id=student.id, linked_via="invite_accepted")
    db.add(link)

    invite.status = "accepted"
    invite.accepted_by_user_id = user.id
    invite.accepted_at = datetime.now(UTC)

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
