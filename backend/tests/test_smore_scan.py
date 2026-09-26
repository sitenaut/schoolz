import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest

import database
from models import SmoreNewsletter
from scheduler.jobs import smore_scan
from scheduler.jobs.smore_scan import select_unseen_blocks


def _block(position: int, content_hash: str, text: str) -> dict:
    return {
        "position": position,
        "block_type": "text",
        "text_content": text,
        "image_url": None,
        "link_url": None,
        "content_hash": content_hash,
    }


def test_a_block_repeated_within_one_newsletter_is_stored_once():
    """Regression: Beck's 9-11 issue repeats a block verbatim.

    content_hash is unique per (newsletter, hash), and the dedup check only
    consulted hashes already in the database - so two identical blocks in
    the *same* parse both passed it, and the flush died with a
    UniqueViolationError that failed the whole scan. Nothing was stored,
    including the ~40 blocks that parsed perfectly, and the job recorded
    last_error_code 'db_error'.
    """
    blocks = [
        _block(0, "hash-aaa", "Bobcat Blast #2"),
        _block(1, "hash-bbb", "September 11, 2026"),
        _block(2, "hash-bbb", "September 11, 2026"),  # the repeat
        _block(3, "hash-ccc", "Administrative Contacts"),
    ]

    kept = select_unseen_blocks(blocks, set())

    assert [b["content_hash"] for b in kept] == ["hash-aaa", "hash-bbb", "hash-ccc"]
    # The first occurrence wins, so the stored block keeps the position it
    # first appears at in the newsletter.
    assert kept[1]["position"] == 1


def test_content_already_stored_is_skipped():
    """The hash check's original purpose: Smore pages are edited in place
    week to week, so a re-scan must only insert genuinely new content."""
    blocks = [_block(0, "hash-old", "Unchanged"), _block(1, "hash-new", "Brand new")]

    kept = select_unseen_blocks(blocks, {"hash-old"})

    assert [b["content_hash"] for b in kept] == ["hash-new"]


def test_nothing_new_returns_nothing():
    blocks = [_block(0, "hash-a", "One"), _block(1, "hash-b", "Two")]

    assert select_unseen_blocks(blocks, {"hash-a", "hash-b"}) == []


def test_the_callers_hash_set_is_not_mutated():
    """The job builds existing_hashes from its own query and may reuse it;
    quietly growing the caller's set would be a surprising side effect."""
    existing = {"hash-old"}

    select_unseen_blocks([_block(0, "hash-new", "New")], existing)

    assert existing == {"hash-old"}


@pytest.mark.anyio
async def test_zero_blocks_is_a_warning_not_a_silent_success(monkeypatch):
    """Regression: a Smore link that has expired renders a page with no
    .block-wrapper elements at all rather than 404ing, so fetch_and_parse
    returns []. Confirmed real on prod - several Cherry Hill schools'
    "stable" URLs went stale mid-week while every run still logged
    status=success, because 0 new blocks looks identical to "nothing
    changed this week". Zero blocks *total* is the only signal available
    that the URL itself, not the content, needs attention."""

    async def _empty(url: str) -> list[dict]:
        return []

    monkeypatch.setattr(smore_scan, "fetch_and_parse", _empty)

    newsletter = SmoreNewsletter(url=f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}")
    async with database.SessionLocal() as db:
        db.add(newsletter)
        await db.commit()
        await db.refresh(newsletter)

        result = await smore_scan.run(db, {"newsletter_id": newsletter.id})

        assert result is not None
        assert result.startswith("WARNING[smore_no_blocks]:")
        assert newsletter.url in result
        # last_scanned_at still advances - this isn't "we didn't check",
        # it's "we checked and found the link is dead".
        assert newsletter.last_scanned_at is not None
