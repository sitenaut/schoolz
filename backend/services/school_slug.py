"""A new School's slug: derived once at creation and never regenerated
(CLAUDE.md, a permalink, not a label), unique across every school."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, slugify


async def unique_school_slug(db: AsyncSession, base_text: str) -> str:
    base = slugify(base_text)
    slug = base
    suffix = 2
    while (await db.execute(select(School).where(School.slug == slug))).scalar_one_or_none():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug
