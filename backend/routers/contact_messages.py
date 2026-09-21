from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_user, require_admin
from database import get_db
from models import ContactMessage, User
from schemas import ContactMessageCreate, ContactMessageOut

router = APIRouter(prefix="/contact-messages", tags=["contact-messages"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def send_message(
    body: ContactMessageCreate, user: User | None = Depends(get_optional_user), db: AsyncSession = Depends(get_db)
) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message is empty")
    # A filled honeypot gets the same 201 a person would, so a bot learns
    # nothing - it just never reaches the inbox.
    if body.website:
        return {"ok": True}
    db.add(
        ContactMessage(
            name=(body.name or "").strip() or None,
            email=(body.email or "").strip() or None,
            message=message,
            user_id=user.id if user else None,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("", response_model=list[ContactMessageOut])
async def list_messages(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContactMessage).order_by(ContactMessage.created_at.desc()))
    return result.scalars().all()


@router.get("/unread-count")
async def unread_count(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    count = await db.scalar(select(func.count()).select_from(ContactMessage).where(ContactMessage.read_at.is_(None)))
    return {"count": count or 0}


@router.post("/read-all")
async def mark_all_read(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        update(ContactMessage)
        .where(ContactMessage.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc), read_by_user_id=admin.id)
    )
    await db.commit()
    return {"marked": result.rowcount}


async def _get(db: AsyncSession, message_id: str) -> ContactMessage:
    row = await db.get(ContactMessage, message_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return row


@router.post("/{message_id}/unread", response_model=ContactMessageOut)
async def mark_unread(message_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await _get(db, message_id)
    row.read_at = None
    row.read_by_user_id = None
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(message_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await db.delete(await _get(db, message_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
