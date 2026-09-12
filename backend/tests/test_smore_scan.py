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
