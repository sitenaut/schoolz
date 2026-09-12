import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy import func, select

import database
from models import SmoreBlock, SmoreNewsletter
from scheduler.jobs import smore_scan


def _block(position: int, content_hash: str, text: str, block_type: str = "text") -> dict:
    return {
        "position": position,
        "block_type": block_type,
        "text_content": text,
        "image_url": None,
        "link_url": None,
        "content_hash": content_hash,
    }


@pytest.mark.anyio
async def test_a_newsletter_repeating_a_block_does_not_fail_the_scan(monkeypatch):
    """Regression: Beck's 9-11 issue repeats a block verbatim.

    content_hash is unique per (newsletter, hash), and the dedup check only
    consulted hashes already in the database - so two identical blocks in
    the *same* parse both passed it, and the flush died with a
    UniqueViolationError that failed the entire scan (last_error_code
    'db_error'). Nothing about the newsletter was stored, including the
    ~40 blocks that were perfectly fine.
    """
    parsed = [
        _block(0, "hash-aaa", "Bobcat Blast #2"),
        _block(1, "hash-bbb", "September 11, 2026"),
        # The same content appearing twice in one issue.
        _block(2, "hash-bbb", "September 11, 2026"),
        _block(3, "hash-ccc", "Administrative Contacts"),
    ]

    async def fake_fetch(url: str):
        return parsed

    monkeypatch.setattr(smore_scan, "fetch_and_parse", fake_fetch)

    async with database.SessionLocal() as db:
        newsletter = SmoreNewsletter(url=f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", label="Beck test")
        db.add(newsletter)
        await db.commit()

        result = await smore_scan.run(db, {"newsletter_id": newsletter.id})
        await db.commit()

        stored = (
            await db.execute(select(func.count()).select_from(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter.id))
        ).scalar_one()

    # The repeat is collapsed, not dropped alongside everything else.
    assert stored == 3, result
    assert "4 block(s), 3 new" in result


@pytest.mark.anyio
async def test_rescanning_an_unchanged_newsletter_adds_nothing(monkeypatch):
    """The original purpose of the hash check: Smore pages get edited in
    place week to week, so a re-scan must only insert genuinely new
    content."""
    parsed = [_block(0, "hash-xyz", "Unchanged"), _block(1, "hash-zzz", "Also unchanged")]

    async def fake_fetch(url: str):
        return parsed

    monkeypatch.setattr(smore_scan, "fetch_and_parse", fake_fetch)

    async with database.SessionLocal() as db:
        newsletter = SmoreNewsletter(url=f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", label="Rescan test")
        db.add(newsletter)
        await db.commit()

        await smore_scan.run(db, {"newsletter_id": newsletter.id})
        await db.commit()
        second = await smore_scan.run(db, {"newsletter_id": newsletter.id})
        await db.commit()

        stored = (
            await db.execute(select(func.count()).select_from(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter.id))
        ).scalar_one()

    assert stored == 2
    assert "0 new" in second
