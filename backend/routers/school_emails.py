from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import SchoolEmailMessage, User
from schemas import SchoolEmailMessageOut

router = APIRouter(prefix="/school-emails", tags=["school-emails"])


@router.get("", response_model=list[SchoolEmailMessageOut])
async def list_school_emails(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SchoolEmailMessage)
        .where(SchoolEmailMessage.owner_user_id == user.id)
        .order_by(SchoolEmailMessage.received_at.desc().nullslast(), SchoolEmailMessage.created_at.desc())
    )
    return result.scalars().all()
